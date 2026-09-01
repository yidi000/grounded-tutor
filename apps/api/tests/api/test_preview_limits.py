import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi.testclient import TestClient

import grounded_tutor.main as main_module
from grounded_tutor.config import Settings, get_settings
from grounded_tutor.domain.models import Workspace
from grounded_tutor.middleware import (
    MAX_PREVIEW_REQUEST_MESSAGES,
    PREVIEW_REQUEST_OVERHEAD_BYTES,
    PreviewRequestBodyLimitMiddleware,
)


async def _call_asgi(
    *,
    body_messages: list[dict[str, object]],
    headers: list[tuple[bytes, bytes]],
    endpoint: str = "text",
) -> tuple[list[dict[str, object]], int]:
    sent: list[dict[str, object]] = []
    receive_calls = 0

    async def receive() -> dict[str, object]:
        nonlocal receive_calls
        receive_calls += 1
        if body_messages:
            return body_messages.pop(0)
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    await main_module.app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": (
                "/api/workspaces/00000000-0000-0000-0000-000000000000/"
                f"source-previews/{endpoint}"
            ),
            "raw_path": b"/api/workspaces/id/source-previews/text",
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 1234),
            "server": ("test", 80),
        },
        receive,
        send,
    )
    return sent, receive_calls


def _response_status(messages: list[dict[str, object]]) -> int:
    return next(
        message["status"]
        for message in messages
        if message["type"] == "http.response.start"
    )


@pytest.mark.asyncio
async def test_oversized_content_length_is_rejected_before_receive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_PREVIEW_TEXT_BYTES", "8")
    get_settings.cache_clear()

    sent, receive_calls = await _call_asgi(
        body_messages=[{"type": "http.request", "body": b"", "more_body": False}],
        headers=[
            (b"content-type", b"application/json"),
            (b"content-length", str(PREVIEW_REQUEST_OVERHEAD_BYTES + 9).encode()),
        ],
    )

    assert _response_status(sent) == 413
    assert receive_calls == 0
    assert json.loads(sent[-1]["body"]) == {
        "detail": {"code": "request_body_too_large"}
    }


@pytest.mark.asyncio
async def test_oversized_multipart_content_length_is_rejected_before_receive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "8")
    get_settings.cache_clear()

    sent, receive_calls = await _call_asgi(
        body_messages=[{"type": "http.request", "body": b"", "more_body": False}],
        headers=[
            (b"content-type", b"multipart/form-data; boundary=test"),
            (b"content-length", str(PREVIEW_REQUEST_OVERHEAD_BYTES + 9).encode()),
        ],
        endpoint="file",
    )

    assert _response_status(sent) == 413
    assert receive_calls == 0


class ChunkedBody(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.sent_count = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            self.sent_count += 1
            yield chunk


@pytest.mark.asyncio
async def test_streaming_body_is_stopped_when_cumulative_limit_is_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_PREVIEW_TEXT_BYTES", "8")
    get_settings.cache_clear()
    chunks = [b"x" * 4096 for _ in range(300)]
    stream = ChunkedBody(chunks)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main_module.app), base_url="http://test"
    ) as async_client:
        response = await async_client.post(
            "/api/workspaces/00000000-0000-0000-0000-000000000000/source-previews/text",
            headers={"content-type": "application/json"},
            content=stream,
        )

    assert response.status_code == 413
    assert response.json() == {"detail": {"code": "request_body_too_large"}}
    assert stream.sent_count < len(chunks)


@pytest.mark.asyncio
async def test_fragmented_stream_is_bounded_by_message_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_PREVIEW_TEXT_BYTES", "20000")
    get_settings.cache_clear()
    body_messages = [
        {"type": "http.request", "body": b"x", "more_body": True}
        for _ in range(MAX_PREVIEW_REQUEST_MESSAGES + 1)
    ]

    sent, receive_calls = await _call_asgi(body_messages=body_messages, headers=[])

    assert _response_status(sent) == 413
    assert receive_calls == MAX_PREVIEW_REQUEST_MESSAGES + 1


@pytest.mark.asyncio
async def test_replay_delegates_to_real_disconnect_after_buffered_body() -> None:
    observed: list[dict[str, object]] = []

    async def downstream(scope, receive, send) -> None:
        del scope, send
        observed.append(await receive())
        observed.append(await receive())

    events = [
        {"type": "http.request", "body": b"{}", "more_body": False},
        {"type": "http.disconnect", "reason": "real-client-disconnect"},
    ]

    async def receive() -> dict[str, object]:
        return events.pop(0)

    async def send(message: dict[str, object]) -> None:
        del message

    middleware = PreviewRequestBodyLimitMiddleware(
        downstream,
        settings_provider=lambda: Settings(max_preview_text_bytes=100),
    )
    await asyncio.wait_for(
        middleware(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/workspaces/id/source-previews/text",
                "headers": [],
            },
            receive,
            send,
        ),
        timeout=1,
    )

    assert observed == [
        {"type": "http.request", "body": b"{}", "more_body": False},
        {"type": "http.disconnect", "reason": "real-client-disconnect"},
    ]


def test_text_service_limit_returns_stable_413(
    client: TestClient,
    seeded_workspace: Workspace,
) -> None:
    main_module.app.dependency_overrides[get_settings] = lambda: Settings(
        max_preview_text_bytes=4
    )

    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/source-previews/text",
        json={"source_name": "notes", "text": "界界", "settings": {}},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": {"code": "text_too_large"}}


def test_preview_error_responses_match_runtime_schema_in_openapi(
    client: TestClient,
) -> None:
    openapi = client.get("/openapi.json").json()
    for suffix in ["text", "file"]:
        responses = openapi["paths"][
            f"/api/workspaces/{{workspace_id}}/source-previews/{suffix}"
        ]["post"]["responses"]
        for status_code in ["413", "422"]:
            assert responses[status_code]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ApiErrorResponse"
            }


def test_workspace_validation_errors_share_the_runtime_error_schema(
    client: TestClient,
) -> None:
    openapi = client.get("/openapi.json").json()
    for method, path in [
        ("post", "/api/workspaces"),
        ("patch", "/api/workspaces/{workspace_id}"),
    ]:
        schema = openapi["paths"][path][method]["responses"]["422"]["content"][
            "application/json"
        ]["schema"]
        assert schema == {"$ref": "#/components/schemas/ApiErrorResponse"}
