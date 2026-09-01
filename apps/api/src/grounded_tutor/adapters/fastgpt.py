"""FastGPT HTTP adapter and its service boundary contract."""

from __future__ import annotations

import json
import math
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

    def __post_init__(self) -> None:
        _validate_nonempty_string(self.dataset_id, "dataset_id")
        _validate_nonempty_string(self.text, "text")
        if type(self.limit) is not int or not 1 <= self.limit <= 20_000:
            raise ValueError("limit must be an integer between 1 and 20000")
        if (
            isinstance(self.similarity, bool)
            or not isinstance(self.similarity, int | float)
            or not math.isfinite(self.similarity)
            or not 0 <= self.similarity <= 1
        ):
            raise ValueError("similarity must be a finite number between 0 and 1")
        if self.search_mode not in {"embedding", "fullTextRecall", "mixedRecall"}:
            raise ValueError("search_mode must be embedding, fullTextRecall, or mixedRecall")
        if type(self.using_rerank) is not bool:
            raise TypeError("using_rerank must be a bool")
        if type(self.extension_query) is not bool:
            raise TypeError("extension_query must be a bool")
        if self.extension_model is not None:
            _validate_nonempty_string(self.extension_model, "extension_model")
        if type(self.extension_background) is not str:
            raise TypeError("extension_background must be a str")
        if self.extension_query and self.extension_model is None:
            raise ValueError("extension_model is required when extension_query is enabled")


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

    def __init__(self, *, service: str, category: str, safe_message: str) -> None:
        self.service = service
        self.category = category
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
        self._client = client or httpx.AsyncClient()
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
        return DatasetRef(_required_nonempty_string(data))

    async def delete_dataset(self, dataset_id: str) -> None:
        await self._request("DELETE", "/api/core/dataset/delete", params={"id": dataset_id})

    async def create_file_collection(
        self, dataset_id: str, filename: str, content: bytes, config: Mapping[str, Any]
    ) -> CollectionRef:
        data = _protected_config(config, datasetId=dataset_id)
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
        if type(page_size) is not int or not 1 <= page_size <= 30:
            raise ValueError("page_size must be between 1 and 30")
        data = await self._request(
            "POST",
            "/api/core/dataset/data/v2/list",
            json={"collectionId": collection_id, "offset": 0, "pageSize": page_size, "searchText": ""},
        )
        items = _list(_object(data).get("list"))
        return [
            ProcessedChunk(
                chunk_id=_required_string(_object(item), "id", "_id"),
                q=_required_text(_object(item), "q"),
                a=_required_text(_object(item), "a"),
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
                payload["datasetSearchExtensionBg"] = request.extension_background
        data = _list(await self._request("POST", "/api/core/dataset/searchTest", json=payload))
        return [
            RetrievedChunk(
                chunk_id=_required_string(_object(item), "id", "_id"),
                collection_id=_required_string(_object(item), "collectionId"),
                source_name=_required_string(_object(item), "sourceName"),
                q=_required_text(_object(item), "q"),
                a=_required_text(_object(item), "a"),
                score=_required_number(_object(item), "score"),
            )
            for item in data
        ]

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if self._client.is_closed:
            raise _failure("client_closed", "FastGPT client is closed.")
        failure_category: str | None = None
        try:
            response = await self._client.request(
                method,
                f"{self._base_url}{path}",
                headers={"Authorization": f"Bearer {self._api_key}"},
                **kwargs,
            )
        except httpx.TimeoutException:
            failure_category = "timeout"
        except httpx.RequestError:
            failure_category = "network"
        if failure_category is not None:
            raise _failure(failure_category, "FastGPT request failed.")
        if not response.is_success:
            raise _failure("http_status", "FastGPT returned an unsuccessful HTTP status.")
        invalid_json = False
        try:
            payload = response.json()
        except (ValueError, UnicodeDecodeError):
            invalid_json = True
        if invalid_json:
            raise _failure("invalid_json", "FastGPT returned invalid JSON.")
        if not isinstance(payload, dict):
            raise _failure("malformed_response", "FastGPT returned a malformed response.")
        if type(payload.get("code")) is not int or payload["code"] != 200:
            raise _failure("service_rejected", "FastGPT reported an unsuccessful result.")
        return payload.get("data")


def _protected_config(config: Mapping[str, Any], **required_fields: Any) -> dict[str, Any]:
    payload = dict(config)
    payload.update(required_fields)
    return payload


def _collection_ref(data: Any) -> CollectionRef:
    data_object = _object(data)
    results = _object(data_object.get("results"))
    inserted_count = results.get("insertLen")
    if type(inserted_count) is not int or inserted_count < 0:
        _malformed()
    return CollectionRef(
        collection_id=_required_string(data_object, "collectionId"),
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
        if isinstance(value, str) and value.strip():
            return value
    _malformed()


def _required_nonempty_string(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value
    _malformed()


def _required_text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if isinstance(value, str):
        return value
    _malformed()


def _required_number(data: dict[str, Any], key: str) -> float:
    value = data.get(key)
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
    ):
        _malformed()
    return float(value)


def _malformed() -> None:
    raise _failure("malformed_response", "FastGPT returned a malformed response.")


def _failure(category: str, safe_message: str) -> ExternalServiceError:
    return ExternalServiceError(service="fastgpt", category=category, safe_message=safe_message)


def _validate_nonempty_string(value: object, name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{name} must be a str")
    if not value.strip():
        raise ValueError(f"{name} must not be blank")
