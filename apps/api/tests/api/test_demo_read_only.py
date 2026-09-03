import json

import pytest
from fastapi.testclient import TestClient

import grounded_tutor.main as main_module
from grounded_tutor.config import get_settings


def test_demo_mode_rejects_every_write_before_parsing_or_dependencies(
    demo_client: TestClient,
    fake_fastgpt,
) -> None:
    workspace = "00000000-0000-0000-0000-000000000000"
    source = "10000000-0000-0000-0000-000000000000"
    attempts = [
        demo_client.post("/api/workspaces", content=b"not json"),
        demo_client.patch(f"/api/workspaces/{workspace}", content=b"not json"),
        demo_client.post(f"/api/workspaces/{workspace}/source-previews/text", content=b"not json"),
        demo_client.post(f"/api/workspaces/{workspace}/source-previews/file", content=b"not multipart"),
        demo_client.post(f"/api/workspaces/{workspace}/sources/text", content=b"not json"),
        demo_client.post(f"/api/workspaces/{workspace}/sources/file", content=b"not multipart"),
        demo_client.post(f"/api/workspaces/{workspace}/sources/{source}/accept", content=b"ignored"),
        demo_client.post(f"/api/workspaces/{workspace}/sources/{source}/reprocess/text", content=b"not json"),
        demo_client.post(f"/api/workspaces/{workspace}/sources/{source}/reprocess/file", content=b"not multipart"),
        demo_client.delete(f"/api/workspaces/{workspace}/sources/{source}"),
    ]

    assert {(response.status_code, response.json()["detail"]["code"]) for response in attempts} == {
        (403, "demo_read_only")
    }
    assert fake_fastgpt.create_dataset_calls == []
    assert fake_fastgpt.call_history == []


def test_demo_mode_keeps_read_methods_available(demo_client: TestClient) -> None:
    assert demo_client.get("/api/health").status_code == 200
    capabilities = demo_client.get("/api/capabilities/source-ingestion")
    assert capabilities.status_code == 200
    assert capabilities.json()["read_only_demo"] is True
    assert {
        item["disabled_reason"]
        for item in capabilities.json()["settings"] + capabilities.json()["workspace_models"]
    } == {"demo_read_only"}
    assert demo_client.head("/api/health").status_code != 403
    assert demo_client.options("/api/health").status_code != 403


def test_demo_mode_rejects_unknown_non_read_route(demo_client: TestClient) -> None:
    response = demo_client.post("/api/not-a-route", content=b"not json")

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "demo_read_only"}}


@pytest.mark.asyncio
async def test_full_app_demo_rejects_oversized_write_without_reading_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEMO_READ_ONLY", "true")
    get_settings.cache_clear()
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        raise AssertionError("demo middleware read the request body")

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
                "source-previews/text"
            ),
            "raw_path": b"/api/workspaces/id/source-previews/text",
            "query_string": b"",
            "headers": [(b"content-length", b"999999999")],
            "client": ("127.0.0.1", 1234),
            "server": ("test", 80),
        },
        receive,
        send,
    )

    assert next(
        message["status"]
        for message in sent
        if message["type"] == "http.response.start"
    ) == 403
    assert json.loads(sent[-1]["body"]) == {"detail": {"code": "demo_read_only"}}
