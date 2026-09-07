"""In-memory implementations of the external-service contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from grounded_tutor.adapters.fastgpt import (
    CollectionListItem,
    CollectionPage,
    CollectionRef,
    DatasetRef,
    FastGPTPort,
    ProcessedChunk,
    RetrievedChunk,
    SearchRequest,
)
from grounded_tutor.adapters.generation import GenerationPort, GenerationRequest
from grounded_tutor.domain.answers import GeneratedAnswer, GeneratedBlock


@dataclass(slots=True)
class FakeCollection:
    dataset_id: str
    name: str
    content: bytes | str
    config: dict[str, Any]
    chunks: list[ProcessedChunk]
    tags: tuple[str, ...] = ()
    forbidden: bool = False


class FakeFastGPT(FastGPTPort):
    """Deterministic, stateful FastGPT substitute for service tests."""

    def __init__(self) -> None:
        self.datasets: dict[str, DatasetRef] = {}
        self.collections: dict[str, FakeCollection] = {}
        # When set, this models raw search results received from FastGPT and bypasses local state.
        self.search_results_override: tuple[RetrievedChunk, ...] | None = None
        self.create_dataset_calls: list[tuple[str, str | None, str | None, str | None]] = []
        self.delete_dataset_calls: list[str] = []
        self.create_file_collection_calls: list[tuple[str, str, bytes, dict[str, Any]]] = []
        self.create_text_collection_calls: list[tuple[str, str, str, dict[str, Any]]] = []
        self.set_collection_forbidden_calls: list[tuple[str, bool]] = []
        self.list_collection_data_calls: list[tuple[str, int]] = []
        self.search_calls: list[SearchRequest] = []
        self.list_collections_calls: list[tuple[str, int, int, str]] = []
        self.call_history: list[tuple[Any, ...]] = []
        self.failures: dict[str, BaseException] = {}
        self._dataset_count = 0
        self._collection_count = 0
        self._chunk_count = 0
        self.supports_tags = True

    async def create_dataset(
        self,
        name: str,
        vector_model: str | None = None,
        agent_model: str | None = None,
        vlm_model: str | None = None,
    ) -> DatasetRef:
        self._record(("create_dataset", name))
        self._dataset_count += 1
        dataset = DatasetRef(f"dataset-{self._dataset_count}")
        self.datasets[dataset.dataset_id] = dataset
        self.create_dataset_calls.append((name, vector_model, agent_model, vlm_model))
        return dataset

    async def delete_dataset(self, dataset_id: str) -> None:
        self._record(("delete_dataset", dataset_id))
        self.datasets.pop(dataset_id, None)
        for collection_id in [
            identifier
            for identifier, collection in self.collections.items()
            if collection.dataset_id == dataset_id
        ]:
            del self.collections[collection_id]
        self.delete_dataset_calls.append(dataset_id)

    async def create_file_collection(
        self, dataset_id: str, filename: str, content: bytes, config: Mapping[str, Any]
    ) -> CollectionRef:
        self._record(("create_file_collection", dataset_id, filename))
        self._require_dataset(dataset_id)
        self.create_file_collection_calls.append((dataset_id, filename, content, dict(config)))
        return self._create_collection(dataset_id, filename, content, config)

    async def create_text_collection(
        self, dataset_id: str, name: str, text: str, config: Mapping[str, Any]
    ) -> CollectionRef:
        self._record(("create_text_collection", dataset_id, name))
        self._require_dataset(dataset_id)
        self.create_text_collection_calls.append((dataset_id, name, text, dict(config)))
        return self._create_collection(dataset_id, name, text, config)

    async def set_collection_forbidden(self, collection_id: str, forbidden: bool) -> None:
        self._record(("set_collection_forbidden", collection_id, forbidden))
        self.collections[collection_id].forbidden = forbidden
        self.set_collection_forbidden_calls.append((collection_id, forbidden))

    async def list_collections(
        self,
        dataset_id: str,
        *,
        offset: int = 0,
        page_size: int = 30,
        search_text: str = "",
    ) -> CollectionPage:
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be non-negative")
        if type(page_size) is not int or not 1 <= page_size <= 30:
            raise ValueError("page_size must be between 1 and 30")
        self._record(("list_collections", dataset_id, offset, page_size, search_text))
        self.list_collections_calls.append((dataset_id, offset, page_size, search_text))
        normalized_search = search_text.casefold()
        matches = [
            CollectionListItem(
                collection_id=collection_id,
                name=collection.name,
                tags=collection.tags,
                forbidden=collection.forbidden,
            )
            for collection_id, collection in self.collections.items()
            if collection.dataset_id == dataset_id
            and (
                not normalized_search
                or normalized_search in collection.name.casefold()
                or any(normalized_search in tag.casefold() for tag in collection.tags)
            )
        ]
        return CollectionPage(tuple(matches[offset : offset + page_size]), len(matches))

    async def list_collection_data(
        self, collection_id: str, page_size: int = 30
    ) -> list[ProcessedChunk]:
        self._record(("list_collection_data", collection_id, page_size))
        if type(page_size) is not int or not 1 <= page_size <= 30:
            raise ValueError("page_size must be between 1 and 30")
        self.list_collection_data_calls.append((collection_id, page_size))
        return self.collections[collection_id].chunks[:page_size]

    async def search(self, request: SearchRequest) -> list[RetrievedChunk]:
        self._record(("search", request.dataset_id))
        self.search_calls.append(request)
        if self.search_results_override is not None:
            return list(self.search_results_override)
        if request.dataset_id not in self.datasets:
            return []
        results: list[RetrievedChunk] = []
        for collection_id, collection in self.collections.items():
            if collection.dataset_id != request.dataset_id or collection.forbidden:
                continue
            for chunk in collection.chunks:
                results.append(
                    RetrievedChunk(
                        chunk_id=chunk.chunk_id,
                        collection_id=collection_id,
                        source_name=collection.name,
                        q=chunk.q,
                        a=chunk.a,
                        score=1.0,
                    )
                )
        return results

    def _create_collection(
        self, dataset_id: str, name: str, content: bytes | str, config: Mapping[str, Any]
    ) -> CollectionRef:
        self._collection_count += 1
        self._chunk_count += 1
        collection_id = f"collection-{self._collection_count}"
        text = content.decode(errors="replace") if isinstance(content, bytes) else content
        chunk = ProcessedChunk(f"chunk-{self._chunk_count}", text, "")
        self.collections[collection_id] = FakeCollection(
            dataset_id=dataset_id,
            name=name,
            content=content,
            config=dict(config),
            chunks=[chunk],
            tags=(
                tuple(tag for tag in config.get("tags", []) if isinstance(tag, str))
                if self.supports_tags
                else ()
            ),
        )
        return CollectionRef(collection_id, inserted_count=1)

    def _require_dataset(self, dataset_id: str) -> None:
        if dataset_id not in self.datasets:
            raise ValueError("dataset_id does not exist")

    def _record(self, call: tuple[Any, ...]) -> None:
        self.call_history.append(call)
        error = self.failures.pop(str(call[0]), None)
        if error is not None:
            raise error


class FakeGeneration(GenerationPort):
    """Configurable generation substitute which records user-visible inputs."""

    def __init__(self, *responses: GeneratedAnswer | BaseException) -> None:
        self.responses = list(responses)
        self.calls: list[GenerationRequest] = []
        self.diagnostic_responses = []
        self.diagnostic_calls = []
        self.plan_responses = []
        self.plan_calls = []

    async def generate_content(self, request: GenerationRequest) -> GeneratedAnswer:
        self.calls.append(request)
        if self.responses:
            response = self.responses.pop(0)
            if isinstance(response, BaseException):
                raise response
            return response
        if not request.chunks:
            return GeneratedAnswer(blocks=())
        chunk = request.chunks[0]
        return GeneratedAnswer(
            blocks=(
                GeneratedBlock(
                    id="block-1",
                    kind="answer" if request.mode == "ASK" else "explanation",
                    text=chunk.a or chunk.q,
                    chunk_ids=(chunk.chunk_id,),
                ),
            )
        )

    async def generate_diagnostic(self, goal, background, chunks):
        from grounded_tutor.adapters.generation import InvalidGenerationOutput
        self.diagnostic_calls.append((goal, background, chunks))
        if self.diagnostic_responses:
            result = self.diagnostic_responses.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result
        # No fabricated educational questions when a test has not supplied evidence.
        raise InvalidGenerationOutput()

    async def generate_plan(self, goal, diagnostic_summary, chunks):
        from grounded_tutor.adapters.generation import InvalidGenerationOutput
        self.plan_calls.append((goal, diagnostic_summary, chunks))
        if self.plan_responses:
            result = self.plan_responses.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result
        raise InvalidGenerationOutput()
