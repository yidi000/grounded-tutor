import json

import httpx
import pytest
import respx

from grounded_tutor.adapters.fastgpt import (
    ExternalServiceError,
    FastGPTClient,
    SearchRequest,
)


@pytest.mark.asyncio
@respx.mock
async def test_search_maps_fastgpt_results() -> None:
    route = respx.post("https://fastgpt.test/api/core/dataset/searchTest").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": 200,
                "data": [
                    {
                        "id": "chunk-1",
                        "q": "Mean is an average.",
                        "a": "",
                        "datasetId": "dataset-1",
                        "collectionId": "collection-1",
                        "sourceName": "notes.pdf",
                        "sourceId": "source-remote-1",
                        "score": 0.91,
                    }
                ],
            },
        )
    )
    client = FastGPTClient("https://fastgpt.test", "secret")
    results = await client.search(SearchRequest(dataset_id="dataset-1", text="mean"))

    assert route.called
    assert results[0].chunk_id == "chunk-1"
    assert results[0].score == 0.91
    assert _request_json(route.calls.last.request) == {
        "datasetId": "dataset-1",
        "text": "mean",
        "limit": 5000,
        "similarity": 0.0,
        "searchMode": "mixedRecall",
        "usingReRank": False,
        "datasetSearchUsingExtensionQuery": False,
    }

    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_create_dataset_maps_optional_models_and_omits_blank_models() -> None:
    route = respx.post("https://fastgpt.test/api/core/dataset/create").mock(
        return_value=httpx.Response(200, json={"code": 200, "data": {"id": "dataset-1"}})
    )
    client = FastGPTClient("https://fastgpt.test/", "secret")

    dataset = await client.create_dataset(
        "Statistics", vector_model="embedding-3", agent_model="", vlm_model="vision-1"
    )

    assert dataset.dataset_id == "dataset-1"
    request = route.calls.last.request
    assert request.method == "POST"
    assert request.url.path == "/api/core/dataset/create"
    assert request.headers["authorization"] == "Bearer secret"
    assert _request_json(request) == {
        "type": "dataset",
        "name": "Statistics",
        "vectorModel": "embedding-3",
        "vlmModel": "vision-1",
    }
    assert "secret" not in repr(client)
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_delete_dataset_uses_encoded_query_parameter() -> None:
    route = respx.delete("https://fastgpt.test/api/core/dataset/delete?id=dataset+one").mock(
        return_value=httpx.Response(200, json={"code": 200, "data": None})
    )
    client = FastGPTClient("https://fastgpt.test", "secret")

    await client.delete_dataset("dataset one")

    assert route.called
    assert route.calls.last.request.url.params["id"] == "dataset one"
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_create_file_collection_sends_file_and_protected_data_fields() -> None:
    route = respx.post("https://fastgpt.test/api/core/dataset/collection/create/localFile").mock(
        return_value=httpx.Response(
            200, json={"code": 200, "data": {"collectionId": "collection-1", "insertLen": 2}}
        )
    )
    client = FastGPTClient("https://fastgpt.test", "secret")

    collection = await client.create_file_collection(
        "dataset-1",
        "notes.pdf",
        b"document bytes",
        {"chunkSize": 256, "datasetId": "wrong", "name": "wrong"},
    )

    assert collection.collection_id == "collection-1"
    assert collection.inserted_count == 2
    request = route.calls.last.request
    assert request.headers["content-type"].startswith("multipart/form-data;")
    assert b'name="file"; filename="notes.pdf"' in request.content
    assert b"document bytes" in request.content
    assert b'"datasetId": "dataset-1"' in request.content
    assert b'"name": "notes.pdf"' in request.content
    assert b'"chunkSize": 256' in request.content
    assert b'"wrong"' not in request.content
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_create_text_collection_preserves_config_but_protects_required_fields() -> None:
    route = respx.post("https://fastgpt.test/api/core/dataset/collection/create/text").mock(
        return_value=httpx.Response(
            200, json={"code": 200, "data": {"id": "collection-1", "insertLen": 1}}
        )
    )
    client = FastGPTClient("https://fastgpt.test", "secret")

    collection = await client.create_text_collection(
        "dataset-1",
        "notes",
        "Mean is an average.",
        {"chunkSize": 256, "datasetId": "wrong", "name": "wrong", "text": "wrong"},
    )

    assert collection.collection_id == "collection-1"
    assert collection.inserted_count == 1
    assert _request_json(route.calls.last.request) == {
        "chunkSize": 256,
        "datasetId": "dataset-1",
        "name": "notes",
        "text": "Mean is an average.",
    }
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_set_collection_forbidden_uses_fastgpt_field_name() -> None:
    route = respx.post("https://fastgpt.test/api/core/dataset/collection/update").mock(
        return_value=httpx.Response(200, json={"code": 200, "data": {}})
    )
    client = FastGPTClient("https://fastgpt.test", "secret")

    await client.set_collection_forbidden("collection-1", True)

    assert _request_json(route.calls.last.request) == {"id": "collection-1", "forbid": True}
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_list_collection_data_maps_processed_chunks() -> None:
    route = respx.post("https://fastgpt.test/api/core/dataset/data/v2/list").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": 200,
                "data": {"list": [{"id": "chunk-1", "q": "Question", "a": "Answer"}]},
            },
        )
    )
    client = FastGPTClient("https://fastgpt.test", "secret")

    chunks = await client.list_collection_data("collection-1", page_size=12)

    assert chunks[0].chunk_id == "chunk-1"
    assert chunks[0].q == "Question"
    assert chunks[0].a == "Answer"
    assert _request_json(route.calls.last.request) == {
        "collectionId": "collection-1",
        "pageNum": 1,
        "pageSize": 12,
    }
    await client.aclose()


@pytest.mark.asyncio
async def test_list_collection_data_rejects_page_size_outside_fastgpt_limit() -> None:
    client = FastGPTClient("https://fastgpt.test", "secret")

    with pytest.raises(ValueError, match="page_size"):
        await client.list_collection_data("collection-1", page_size=0)
    with pytest.raises(ValueError, match="page_size"):
        await client.list_collection_data("collection-1", page_size=31)

    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_search_maps_all_fastgpt_request_fields_when_extension_is_enabled() -> None:
    route = respx.post("https://fastgpt.test/api/core/dataset/searchTest").mock(
        return_value=httpx.Response(200, json={"code": 200, "data": []})
    )
    client = FastGPTClient("https://fastgpt.test", "secret")

    await client.search(
        SearchRequest(
            dataset_id="dataset-1",
            text="mean",
            limit=10,
            similarity=0.4,
            search_mode="fullTextRecall",
            using_rerank=True,
            extension_query=True,
            extension_model="gpt-4o-mini",
            extension_background="statistics",
        )
    )

    assert _request_json(route.calls.last.request) == {
        "datasetId": "dataset-1",
        "text": "mean",
        "limit": 10,
        "similarity": 0.4,
        "searchMode": "fullTextRecall",
        "usingReRank": True,
        "datasetSearchUsingExtensionQuery": True,
        "datasetSearchExtensionModel": "gpt-4o-mini",
        "datasetSearchExtensionModelBackground": "statistics",
    }
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, json={"code": 200, "data": {}}),
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"code": 500, "data": {}}),
        httpx.Response(200, json={"code": 200, "data": {}}),
    ],
)
async def test_fastgpt_bad_responses_raise_redacted_external_service_error(
    response: httpx.Response,
) -> None:
    respx.post("https://fastgpt.test/api/core/dataset/create").mock(return_value=response)
    client = FastGPTClient("https://fastgpt.test", "super-secret")

    with pytest.raises(ExternalServiceError) as caught:
        await client.create_dataset("private source content")

    public = f"{caught.value!r} {caught.value}"
    assert caught.value.service == "fastgpt"
    assert "super-secret" not in public
    assert "private source content" not in public
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [httpx.ConnectError("secret"), httpx.ReadTimeout("secret")])
async def test_fastgpt_network_errors_are_redacted(error: httpx.RequestError) -> None:
    transport = httpx.MockTransport(lambda request: (_ for _ in ()).throw(error))
    injected = httpx.AsyncClient(transport=transport)
    client = FastGPTClient("https://fastgpt.test", "super-secret", client=injected)

    with pytest.raises(ExternalServiceError) as caught:
        await client.create_dataset("private source content")

    assert "super-secret" not in str(caught.value)
    assert "private source content" not in repr(caught.value)
    await client.aclose()
    assert not injected.is_closed
    await injected.aclose()


@pytest.mark.asyncio
async def test_network_error_does_not_retain_api_key_or_uploaded_content() -> None:
    api_key = "API-KEY-MARKER"
    upload = b"UPLOADED-CONTENT-MARKER"

    def fail_with_request(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("NETWORK-ERROR-MARKER", request=request)

    injected = httpx.AsyncClient(transport=httpx.MockTransport(fail_with_request))
    client = FastGPTClient("https://fastgpt.test", api_key, client=injected)

    with pytest.raises(ExternalServiceError) as caught:
        await client.create_file_collection("dataset-1", "private.pdf", upload, {})

    assert caught.value.service == "fastgpt"
    assert caught.value.category == "network"
    _assert_exception_surface_redacted(
        caught.value,
        api_key,
        "Bearer",
        upload.decode(),
        "NETWORK-ERROR-MARKER",
    )
    await injected.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_invalid_json_error_does_not_retain_sensitive_response_or_json_request() -> None:
    api_key = "API-KEY-MARKER"
    request_content = "JSON-REQUEST-CONTENT-MARKER"
    response_header = "RESPONSE-HEADER-MARKER"
    response_body = "INVALID-RESPONSE-BODY-MARKER"
    respx.post("https://fastgpt.test/api/core/dataset/collection/create/text").mock(
        return_value=httpx.Response(
            200,
            headers={"X-Private": response_header},
            content=response_body.encode(),
        )
    )
    client = FastGPTClient("https://fastgpt.test", api_key)

    with pytest.raises(ExternalServiceError) as caught:
        await client.create_text_collection("dataset-1", "private", request_content, {})

    assert caught.value.category == "invalid_json"
    _assert_exception_surface_redacted(
        caught.value,
        api_key,
        "Bearer",
        request_content,
        response_header,
        response_body,
    )
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "status, data, category",
    [
        (503, {"code": 200, "data": {}}, "http_status"),
        (200, {"code": 200, "data": {}}, "malformed_response"),
    ],
)
async def test_response_errors_do_not_expose_sensitive_response_state(
    status: int, data: dict[str, object], category: str
) -> None:
    api_key = "API-KEY-MARKER"
    request_content = "JSON-REQUEST-CONTENT-MARKER"
    response_header = "RESPONSE-HEADER-MARKER"
    response_body = "RESPONSE-BODY-MARKER"
    respx.post("https://fastgpt.test/api/core/dataset/create").mock(
        return_value=httpx.Response(
            status,
            headers={"X-Private": response_header},
            content=json.dumps(data).replace("{}", f'{{"private":"{response_body}"}}').encode(),
        )
    )
    client = FastGPTClient("https://fastgpt.test", api_key)

    with pytest.raises(ExternalServiceError) as caught:
        await client.create_dataset(request_content)

    assert caught.value.category == category
    _assert_exception_surface_redacted(
        caught.value,
        api_key,
        "Bearer",
        request_content,
        response_header,
        response_body,
    )
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("kind", ["file", "text"])
@pytest.mark.parametrize(
    "data",
    [
        {"collectionId": "collection-1"},
        {"collectionId": "collection-1", "insertLen": "1"},
        {"collectionId": "collection-1", "insertLen": -1},
        {"collectionId": "collection-1", "insertedCount": True},
    ],
)
async def test_collection_result_requires_non_negative_integer_insert_count(
    kind: str, data: dict[str, object]
) -> None:
    endpoint = (
        "/api/core/dataset/collection/create/localFile"
        if kind == "file"
        else "/api/core/dataset/collection/create/text"
    )
    respx.post(f"https://fastgpt.test{endpoint}").mock(
        return_value=httpx.Response(200, json={"code": 200, "data": data})
    )
    client = FastGPTClient("https://fastgpt.test", "secret")

    with pytest.raises(ExternalServiceError) as caught:
        if kind == "file":
            await client.create_file_collection("dataset-1", "notes.pdf", b"content", {})
        else:
            await client.create_text_collection("dataset-1", "notes", "content", {})

    assert caught.value.category == "malformed_response"
    assert caught.value.service == "fastgpt"
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_collection_result_accepts_inserted_count_alias() -> None:
    respx.post("https://fastgpt.test/api/core/dataset/collection/create/text").mock(
        return_value=httpx.Response(
            200, json={"code": 200, "data": {"collectionId": "collection-1", "insertedCount": 3}}
        )
    )
    client = FastGPTClient("https://fastgpt.test", "secret")

    collection = await client.create_text_collection("dataset-1", "notes", "content", {})

    assert collection.inserted_count == 3
    await client.aclose()


def _request_json(request: httpx.Request) -> object:
    return json.loads(request.content)


def _assert_exception_surface_redacted(error: BaseException, *markers: str) -> None:
    surface = _exception_surface(error)
    for marker in markers:
        assert marker not in surface


def _exception_surface(value: object, seen: set[int] | None = None) -> str:
    seen = seen or set()
    if id(value) in seen:
        return ""
    seen.add(id(value))
    if isinstance(value, (str, bytes, bytearray, int, float, bool, type(None))):
        return repr(value)
    parts = [repr(value), str(value)]
    if isinstance(value, BaseException):
        parts.extend(
            [
                _exception_surface(value.args, seen),
                _exception_surface(value.__cause__, seen),
                _exception_surface(value.__context__, seen),
            ]
        )
    if isinstance(value, dict):
        for key, item in value.items():
            parts.extend([_exception_surface(key, seen), _exception_surface(item, seen)])
    elif isinstance(value, (list, tuple, set, frozenset)):
        parts.extend(_exception_surface(item, seen) for item in value)
    else:
        parts.extend(_exception_surface(item, seen) for item in vars(value).values())
    return " ".join(parts)


@pytest.mark.asyncio
async def test_client_closes_only_client_it_owns() -> None:
    owned = FastGPTClient("https://fastgpt.test", "secret")
    await owned.aclose()
    assert owned.is_closed

    injected = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    borrowed = FastGPTClient("https://fastgpt.test", "secret", client=injected)
    await borrowed.aclose()
    assert not injected.is_closed
    await injected.aclose()
