from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from grounded_tutor.adapters.fastgpt import FastGPTPort, ProcessedChunk
from grounded_tutor.domain.ingestion import ChunkSettings
from grounded_tutor.domain.models import SourceType
from grounded_tutor.domain.schemas import (
    ProcessedPreviewItemResponse,
    ProcessedPreviewResponse,
)
from grounded_tutor.repositories.sources import (
    SourcePersistenceError,
    SourcePersistenceOutcome,
    SourceRepository,
    SourceSummary,
)
from grounded_tutor.services.previews import SUPPORTED_EXTENSIONS, PreviewError
from grounded_tutor.services.source_locks import WorkspaceLockRegistry

SAFE_INGESTION_ERROR = "Source ingestion failed."
PROCESSED_PREVIEW_LIMIT = 30


class SourceWorkspaceNotFoundError(LookupError):
    pass


class SourceNotFoundError(LookupError):
    pass


class SourcePreviewUnavailableError(RuntimeError):
    pass


class ExternalSourceServiceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SourceIngestionResult:
    source: SourceSummary
    processed_preview: ProcessedPreviewResponse


class SourceService:
    def __init__(
        self,
        repository: SourceRepository,
        fastgpt: FastGPTPort,
        locks: WorkspaceLockRegistry,
        *,
        max_upload_bytes: int = 20_000_000,
        max_text_bytes: int = 20_000_000,
    ) -> None:
        self._repository = repository
        self._fastgpt = fastgpt
        self._locks = locks
        self.max_upload_bytes = max_upload_bytes
        self.max_text_bytes = max_text_bytes

    async def ingest_text(
        self,
        *,
        workspace_id: UUID,
        name: str,
        text: str,
        settings: ChunkSettings,
    ) -> SourceIngestionResult:
        _validate_text(name, text, self.max_text_bytes)
        return await self._ingest(
            workspace_id=workspace_id,
            name=name,
            source_type=SourceType.TEXT,
            settings=settings,
            create_collection=lambda dataset_id, config: self._fastgpt.create_text_collection(
                dataset_id, name, text, config
            ),
        )

    async def ingest_file(
        self,
        *,
        workspace_id: UUID,
        filename: str,
        content: bytes,
        settings: ChunkSettings,
    ) -> SourceIngestionResult:
        safe_name = _validate_file(filename, content, self.max_upload_bytes)
        return await self._ingest(
            workspace_id=workspace_id,
            name=safe_name,
            source_type=SourceType.FILE,
            settings=settings,
            create_collection=lambda dataset_id, config: self._fastgpt.create_file_collection(
                dataset_id, safe_name, content, config
            ),
        )

    async def _ingest(
        self,
        *,
        workspace_id: UUID,
        name: str,
        source_type: SourceType,
        settings: ChunkSettings,
        create_collection: Callable[[str, dict[str, object]], Awaitable[object]],
    ) -> SourceIngestionResult:
        config = settings.model_dump(by_alias=True)
        source_id = uuid4()
        async with self._locks.acquire(workspace_id):
            dataset_id = self._repository.get_workspace_dataset_id(workspace_id)
            if dataset_id is None:
                raise SourceWorkspaceNotFoundError
            collection_id: str | None = None
            try:
                source = self._repository.create_indexing(
                    source_id=source_id,
                    workspace_id=workspace_id,
                    name=name,
                    source_type=source_type,
                    origin_uri=None,
                    ingestion_config=config,
                )
                collection = await create_collection(dataset_id, config)
                collection_id = _collection_id(collection)
                await self._fastgpt.set_collection_forbidden(collection_id, True)
                self._repository.set_collection_id(source.id, collection_id=collection_id)
                chunks = await self._fastgpt.list_collection_data(
                    collection_id, page_size=PROCESSED_PREVIEW_LIMIT
                )
                source = self._repository.transition_review(source.id)
            except asyncio.CancelledError:
                await self._recover_failed_ingestion(source_id, collection_id, strict=False)
                raise
            except SourcePersistenceError:
                await self._recover_failed_ingestion(source_id, collection_id, strict=False)
                raise
            except Exception as error:
                await self._recover_failed_ingestion(source_id, collection_id, strict=True)
                raise ExternalSourceServiceError("Source ingestion failed.") from error
            return SourceIngestionResult(
                source=source,
                processed_preview=_processed_preview(source, chunks),
            )

    async def _recover_failed_ingestion(
        self,
        source_id: UUID,
        collection_id: str | None,
        *,
        strict: bool,
    ) -> None:
        if collection_id is not None:
            await _best_effort_forbid(self._fastgpt, collection_id)
        try:
            failed = self._repository.transition_failed(
                source_id,
                collection_id=collection_id,
                safe_error_message=SAFE_INGESTION_ERROR,
            )
            if failed is None and strict:
                raise SourcePersistenceError(
                    outcome=SourcePersistenceOutcome.DEFINITELY_UNCOMMITTED
                )
        except SourcePersistenceError:
            if strict:
                raise

    def list(self, workspace_id: UUID) -> list[SourceSummary]:
        exists, sources = self._repository.list_for_workspace(workspace_id)
        if not exists:
            raise SourceWorkspaceNotFoundError
        return sources

    async def processed_preview(
        self, workspace_id: UUID, source_id: UUID
    ) -> ProcessedPreviewResponse:
        source = self._repository.get_for_workspace(workspace_id, source_id)
        if source is None:
            raise SourceNotFoundError
        if source.collection_id is None:
            raise SourcePreviewUnavailableError
        try:
            chunks = await self._fastgpt.list_collection_data(
                source.collection_id, page_size=PROCESSED_PREVIEW_LIMIT
            )
        except Exception as error:
            raise ExternalSourceServiceError("Processed preview failed.") from error
        return _processed_preview(source.summary, chunks)


def _collection_id(collection: object) -> str:
    collection_id = getattr(collection, "collection_id", None)
    if not isinstance(collection_id, str) or not collection_id:
        raise ExternalSourceServiceError("Source ingestion failed.")
    return collection_id


async def _best_effort_forbid(fastgpt: FastGPTPort, collection_id: str) -> None:
    task = asyncio.create_task(fastgpt.set_collection_forbidden(collection_id, True))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        except Exception:  # noqa: BLE001 - cleanup cannot expose remote details.
            return
    except Exception:  # noqa: BLE001 - cleanup remains best effort.
        return


def _processed_preview(
    source: SourceSummary, chunks: list[ProcessedChunk]
) -> ProcessedPreviewResponse:
    return ProcessedPreviewResponse(
        source_id=source.id,
        source_name=source.name,
        items=[
            ProcessedPreviewItemResponse(position=index, q=chunk.q, a=chunk.a)
            for index, chunk in enumerate(chunks[:PROCESSED_PREVIEW_LIMIT], start=1)
        ],
        limit=PROCESSED_PREVIEW_LIMIT,
    )


def _validate_text(name: str, text: str, max_text_bytes: int) -> None:
    if not name or len(name) > 255:
        raise PreviewError("invalid_source_name")
    if len(text.encode("utf-8")) > max_text_bytes:
        raise PreviewError("text_too_large")
    if not text.strip():
        raise PreviewError("empty_source")


def _validate_file(filename: str, content: bytes, max_upload_bytes: int) -> str:
    if len(content) > max_upload_bytes:
        raise PreviewError("file_too_large")
    safe_name = filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    if not 1 <= len(safe_name) <= 255:
        raise PreviewError("invalid_source_name")
    path = Path(safe_name)
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS or not path.stem:
        raise PreviewError("unsupported_file_type")
    if not content:
        raise PreviewError("empty_source")
    return safe_name
