"""FastGPT HTTP adapter and its service boundary contract."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, Self

import httpx


@dataclass(frozen=True, slots=True)
class DatasetRef:
    dataset_id: str


@dataclass(frozen=True, slots=True)
class CollectionRef:
    collection_id: str
    inserted_count: int


@dataclass(frozen=True, slots=True)
class ProcessedChunk:
    chunk_id: str
    q: str
    a: str


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: str
    collection_id: str
    source_name: str
    q: str
    a: str
    score: float


@dataclass(frozen=True, slots=True)
class SearchRequest:
    dataset_id: str
    text: str
    limit: int = 5000
    similarity: float = 0.0
    search_mode: str = "mixedRecall"
    using_rerank: bool = False
    extension_query: bool = False
    extension_model: str | None = None
    extension_background: str = ""


class FastGPTPort(Protocol):
    async def create_dataset(
        self,
        name: str,
        vector_model: str | None = None,
        agent_model: str | None = None,
        vlm_model: str | None = None,
    ) -> DatasetRef: ...

    async def delete_dataset(self, dataset_id: str) -> None: ...

    async def create_file_collection(
        self, dataset_id: str, filename: str, content: bytes, config: Mapping[str, Any]
    ) -> CollectionRef: ...

    async def create_text_collection(
        self, dataset_id: str, name: str, text: str, config: Mapping[str, Any]
    ) -> CollectionRef: ...

    async def set_collection_forbidden(self, collection_id: str, forbidden: bool) -> None: ...

    async def list_collection_data(
        self, collection_id: str, page_size: int = 30
    ) -> list[ProcessedChunk]: ...

    async def search(self, request: SearchRequest) -> list[RetrievedChunk]: ...


class ExternalServiceError(RuntimeError):
    """A deliberately redacted error at an outbound service boundary."""

    def __init__(self, *, service: str, safe_message: str) -> None:
        self.service = service
        self.safe_message = safe_message
        super().__init__(f"{service}: {safe_message}")


class FastGPTClient:
    """Async FastGPT adapter which owns its default HTTP client."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(base_url=self._base_url)
        self._owns_client = client is None

    def __repr__(self) -> str:
        return f"FastGPTClient(base_url={self._base_url!r}, closed={self.is_closed})"

    @property
    def is_closed(self) -> bool:
        return self._client.is_closed

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client and not self._client.is_closed:
            await self._client.aclose()

    async def create_dataset(
        self,
        name: str,
        vector_model: str | None = None,
        agent_model: str | None = None,
        vlm_model: str | None = None,
    ) -> DatasetRef:
        payload: dict[str, Any] = {"type": "dataset", "name": name}
        for field, value in (
            ("vectorModel", vector_model),
            ("agentModel", agent_model),
            ("vlmModel", vlm_model),
        ):
            if value is not None and value.strip():
                payload[field] = value
        data = await self._request("POST", "/api/core/dataset/create", json=payload)
        data_object = _object(data)
        return DatasetRef(_required_string(data_object, "id", "datasetId", "_id"))

    async def delete_dataset(self, dataset_id: str) -> None:
        await self._request("DELETE", "/api/core/dataset/delete", params={"id": dataset_id})

    async def create_file_collection(
        self, dataset_id: str, filename: str, content: bytes, config: Mapping[str, Any]
    ) -> CollectionRef:
        data = _protected_config(config, datasetId=dataset_id, name=filename)
        response_data = await self._request(
            "POST",
            "/api/core/dataset/collection/create/localFile",
            data={"data": json.dumps(data)},
            files={"file": (filename, content)},
        )
        return _collection_ref(response_data)

    async def create_text_collection(
        self, dataset_id: str, name: str, text: str, config: Mapping[str, Any]
    ) -> CollectionRef:
        payload = _protected_config(config, datasetId=dataset_id, name=name, text=text)
        response_data = await self._request(
            "POST", "/api/core/dataset/collection/create/text", json=payload
        )
        return _collection_ref(response_data)

    async def set_collection_forbidden(self, collection_id: str, forbidden: bool) -> None:
        await self._request(
            "POST",
            "/api/core/dataset/collection/update",
            json={"id": collection_id, "forbid": forbidden},
        )

    async def list_collection_data(
        self, collection_id: str, page_size: int = 30
    ) -> list[ProcessedChunk]:
        if not 1 <= page_size <= 30:
            raise ValueError("page_size must be between 1 and 30")
        data = await self._request(
            "POST",
            "/api/core/dataset/data/v2/list",
            json={"collectionId": collection_id, "pageNum": 1, "pageSize": page_size},
        )
        items = _list(_object(data).get("list"))
        return [
            ProcessedChunk(
                chunk_id=_required_string(_object(item), "id", "_id"),
                q=_required_string(_object(item), "q"),
                a=_required_string(_object(item), "a"),
            )
            for item in items
        ]

    async def search(self, request: SearchRequest) -> list[RetrievedChunk]:
        payload: dict[str, Any] = {
            "datasetId": request.dataset_id,
            "text": request.text,
            "limit": request.limit,
            "similarity": request.similarity,
            "searchMode": request.search_mode,
            "usingReRank": request.using_rerank,
            "datasetSearchUsingExtensionQuery": request.extension_query,
        }
        if request.extension_query:
            if request.extension_model is not None and request.extension_model.strip():
                payload["datasetSearchExtensionModel"] = request.extension_model
            if request.extension_background:
                payload["datasetSearchExtensionModelBackground"] = request.extension_background
        data = _list(await self._request("POST", "/api/core/dataset/searchTest", json=payload))
        return [
            RetrievedChunk(
                chunk_id=_required_string(_object(item), "id", "_id"),
                collection_id=_required_string(_object(item), "collectionId"),
                source_name=_required_string(_object(item), "sourceName"),
                q=_required_string(_object(item), "q"),
                a=_required_string(_object(item), "a"),
                score=_required_number(_object(item), "score"),
            )
            for item in data
        ]

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self._client.request(
                method,
                path if self._owns_client else f"{self._base_url}{path}",
                headers={"Authorization": f"Bearer {self._api_key}"},
                **kwargs,
            )
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise ExternalServiceError(
                service="fastgpt", safe_message="FastGPT request failed."
            ) from exc
        if not response.is_success:
            raise ExternalServiceError(
                service="fastgpt", safe_message="FastGPT returned an unsuccessful HTTP status."
            )
        try:
            payload = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ExternalServiceError(
                service="fastgpt", safe_message="FastGPT returned invalid JSON."
            ) from exc
        if not isinstance(payload, dict):
            raise ExternalServiceError(
                service="fastgpt", safe_message="FastGPT returned a malformed response."
            )
        if payload.get("code") != 200:
            raise ExternalServiceError(
                service="fastgpt", safe_message="FastGPT reported an unsuccessful result."
            )
        return payload.get("data")


def _protected_config(config: Mapping[str, Any], **required_fields: Any) -> dict[str, Any]:
    payload = dict(config)
    payload.update(required_fields)
    return payload


def _collection_ref(data: Any) -> CollectionRef:
    data_object = _object(data)
    inserted_count = data_object.get("insertLen", data_object.get("insertedCount", 0))
    if isinstance(inserted_count, bool) or not isinstance(inserted_count, int):
        _malformed()
    return CollectionRef(
        collection_id=_required_string(data_object, "collectionId", "id", "_id"),
        inserted_count=inserted_count,
    )


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        _malformed()
    return value


def _list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        _malformed()
    return value


def _required_string(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str):
            return value
    _malformed()


def _required_number(data: dict[str, Any], key: str) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        _malformed()
    return float(value)


def _malformed() -> None:
    raise ExternalServiceError(service="fastgpt", safe_message="FastGPT returned a malformed response.")
