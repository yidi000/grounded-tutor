from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

import grounded_tutor.main as main_module
from grounded_tutor.adapters.fakes import FakeFastGPT
from grounded_tutor.adapters.fastgpt import DatasetRef, ExternalServiceError, ProcessedChunk
from grounded_tutor.config import Settings, get_settings
from grounded_tutor.domain.models import Source, SourceStatus, SourceType, Workspace


def _register_dataset(fake: FakeFastGPT, workspace: Workspace) -> None:
    fake.datasets[workspace.dataset_id] = DatasetRef(workspace.dataset_id)


def test_text_source_enters_review_and_returns_actual_processed_preview(
    client: TestClient,
    seeded_workspace: Workspace,
    fake_fastgpt: FakeFastGPT,
    api_session_factory: Callable[[], object],
) -> None:
    _register_dataset(fake_fastgpt, seeded_workspace)

    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/text",
        json={
            "source_name": "  Week 1  ",
            "text": "Mean is an average.",
            "settings": {"trainingType": "chunk", "chunkSize": 1000, "indexSize": 256},
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"source", "processed_preview"}
    assert set(body["source"]) == {
        "id",
        "workspace_id",
        "name",
        "source_type",
        "origin_uri",
        "status",
        "version",
        "ingestion_config",
        "error_message",
        "created_at",
        "updated_at",
    }
    assert body["source"]["name"] == "Week 1"
    assert body["source"]["status"] == "review"
    assert body["processed_preview"] == {
        "authority": "actual",
        "source_id": body["source"]["id"],
        "source_name": "Week 1",
        "items": [
            {
                "position": 1,
                "q": "Mean is an average.",
                "a": "",
                "q_truncated": False,
                "a_truncated": False,
            }
        ],
        "limit": 30,
    }
    assert "collection" not in response.text.lower()
    assert seeded_workspace.dataset_id not in response.text
    assert "gt-src-" not in response.text
    with api_session_factory() as session:
        stored = session.scalar(select(Source))
    assert stored is not None
    assert stored.status is SourceStatus.REVIEW
    assert stored.collection_id == "collection-1"


def test_file_source_accepts_exact_upload_limit_without_local_reparse(
    client: TestClient,
    seeded_workspace: Workspace,
    fake_fastgpt: FakeFastGPT,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register_dataset(fake_fastgpt, seeded_workspace)
    monkeypatch.setattr(
        "grounded_tutor.main.get_settings",
        lambda: Settings(max_upload_bytes=8, max_preview_text_bytes=8),
    )
    client.app.dependency_overrides[get_settings] = lambda: Settings(
        max_upload_bytes=8, max_preview_text_bytes=8
    )
    content = b"\x00\x01\x02\x03\x04\x05\x06\x07"

    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/file",
        files={"file": ("binary.pdf", content, "application/pdf")},
        data={"settings": json.dumps({"trainingType": "chunk"})},
    )

    assert response.status_code == 201
    assert fake_fastgpt.create_file_collection_calls[0][2] == content


def test_file_source_rejects_one_byte_over_limit_and_unsupported_extension(
    client: TestClient,
    seeded_workspace: Workspace,
    fake_fastgpt: FakeFastGPT,
) -> None:
    _register_dataset(fake_fastgpt, seeded_workspace)
    client.app.dependency_overrides[get_settings] = lambda: Settings(max_upload_bytes=8)

    too_large = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/file",
        files={"file": ("notes.txt", b"123456789", "text/plain")},
        data={"settings": "{}"},
    )
    unsupported = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/file",
        files={"file": ("private.exe", b"x")},
        data={"settings": "{}"},
    )

    assert too_large.status_code == 413
    assert too_large.json() == {"detail": {"code": "file_too_large"}}
    assert unsupported.status_code == 415
    assert unsupported.json() == {"detail": {"code": "unsupported_file_type"}}
    assert "private.exe" not in unsupported.text
    assert fake_fastgpt.create_file_collection_calls == []


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("text", {"source_name": "notes", "text": " ", "settings": {}}),
        (
            "text",
            {
                "source_name": "notes",
                "text": "Mean.",
                "settings": {"chunkSize": 99},
            },
        ),
    ],
)
def test_text_source_rejects_invalid_inputs(
    client: TestClient, seeded_workspace: Workspace, path: str, payload: dict[str, object]
) -> None:
    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/{path}", json=payload
    )

    assert response.status_code == 422


def test_missing_workspace_is_checked_before_external_call(
    client: TestClient, fake_fastgpt: FakeFastGPT
) -> None:
    response = client.post(
        f"/api/workspaces/{uuid4()}/sources/text",
        json={"source_name": "notes", "text": "Mean.", "settings": {}},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "workspace_not_found"}}
    assert fake_fastgpt.call_history == []


def test_same_workspace_concurrent_api_ingestion_returns_immediate_409(
    client: TestClient,
    seeded_workspace: Workspace,
    fake_fastgpt: FakeFastGPT,
) -> None:
    _register_dataset(fake_fastgpt, seeded_workspace)
    entered = Event()
    release = Event()
    original_create = fake_fastgpt.create_text_collection

    async def blocking_create(dataset_id, name, text, config):
        entered.set()
        await asyncio.to_thread(release.wait)
        return await original_create(dataset_id, name, text, config)

    fake_fastgpt.create_text_collection = blocking_create
    path = f"/api/workspaces/{seeded_workspace.id}/sources/text"
    with ThreadPoolExecutor(max_workers=1) as executor:
        active = executor.submit(
            client.post,
            path,
            json={"source_name": "first", "text": "Mean.", "settings": {}},
        )
        assert entered.wait(timeout=1)
        conflict = client.post(
            path,
            json={"source_name": "second", "text": "Median.", "settings": {}},
        )
        release.set()
        first = active.result(timeout=2)

    assert conflict.status_code == 409
    assert conflict.json() == {"detail": {"code": "workspace_ingestion_busy"}}
    assert first.status_code == 201
    assert len(fake_fastgpt.create_text_collection_calls) == 1


def test_different_workspaces_ingest_concurrently_through_api(
    client: TestClient,
    seeded_workspace: Workspace,
    fake_fastgpt: FakeFastGPT,
    api_session_factory: Callable[[], object],
) -> None:
    with api_session_factory() as session:
        other = Workspace(title="Calculus", dataset_id="dataset-calculus")
        session.add(other)
        session.commit()
        session.refresh(other)
    _register_dataset(fake_fastgpt, seeded_workspace)
    _register_dataset(fake_fastgpt, other)
    entered: set[str] = set()
    entered_lock = Lock()
    both_entered = Event()
    original_create = fake_fastgpt.create_text_collection

    async def rendezvous_create(dataset_id, name, text, config):
        with entered_lock:
            entered.add(dataset_id)
            if len(entered) == 2:
                both_entered.set()
        await asyncio.to_thread(both_entered.wait)
        return await original_create(dataset_id, name, text, config)

    fake_fastgpt.create_text_collection = rendezvous_create
    requests = [
        (
            f"/api/workspaces/{workspace.id}/sources/text",
            {"source_name": workspace.title, "text": "Content.", "settings": {}},
        )
        for workspace in (seeded_workspace, other)
    ]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(client.post, path, json=payload) for path, payload in requests]
        responses = [future.result(timeout=2) for future in futures]

    assert [response.status_code for response in responses] == [201, 201]
    assert entered == {"dataset-seeded", "dataset-calculus"}


def test_external_failure_returns_safe_error_and_lists_failed_source(
    client: TestClient,
    seeded_workspace: Workspace,
    fake_fastgpt: FakeFastGPT,
) -> None:
    _register_dataset(fake_fastgpt, seeded_workspace)
    fake_fastgpt.failures["create_text_collection"] = ExternalServiceError(
        service="fastgpt",
        category="timeout",
        safe_message="private material dataset-secret api-key",
    )

    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/text",
        json={"source_name": "private notes", "text": "private material", "settings": {}},
    )
    listed = client.get(f"/api/workspaces/{seeded_workspace.id}/sources")

    assert response.status_code == 502
    assert response.json() == {"detail": {"code": "external_service_error"}}
    assert "private material" not in response.text
    assert "dataset-secret" not in response.text
    assert listed.status_code == 200
    assert listed.json()[0]["status"] == "failed"
    assert listed.json()[0]["error_message"] == "Source ingestion failed."


def test_uncertain_create_reconciliation_marker_never_leaks_to_browser(
    client: TestClient,
    seeded_workspace: Workspace,
    fake_fastgpt: FakeFastGPT,
) -> None:
    _register_dataset(fake_fastgpt, seeded_workspace)
    original_create = fake_fastgpt.create_text_collection

    async def commit_then_timeout(dataset_id, name, text, config):
        await original_create(dataset_id, name, text, config)
        raise ExternalServiceError(
            service="fastgpt",
            category="timeout",
            safe_message="FastGPT request failed.",
        )

    fake_fastgpt.create_text_collection = commit_then_timeout
    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/text",
        json={"source_name": "Local notes", "text": "Mean.", "settings": {}},
    )
    listed = client.get(f"/api/workspaces/{seeded_workspace.id}/sources")

    assert response.status_code == 502
    assert listed.status_code == 200
    assert listed.json()[0]["name"] == "Local notes"
    assert listed.json()[0]["status"] == "failed"
    assert "gt-src-" not in response.text
    assert "gt-src-" not in listed.text
    assert next(iter(fake_fastgpt.collections.values())).name.startswith("gt-src-")


@pytest.mark.parametrize("operation", ["set_collection_forbidden", "list_collection_data"])
def test_post_creation_external_failures_are_safe_and_persist_failed_collection(
    client: TestClient,
    seeded_workspace: Workspace,
    fake_fastgpt: FakeFastGPT,
    api_session_factory: Callable[[], object],
    operation: str,
) -> None:
    _register_dataset(fake_fastgpt, seeded_workspace)
    fake_fastgpt.failures[operation] = RuntimeError("private-content collection-secret api-key")

    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/text",
        json={"source_name": "notes", "text": "Mean.", "settings": {}},
    )

    assert response.status_code == 502
    assert response.json() == {"detail": {"code": "external_service_error"}}
    assert "private-content" not in response.text
    assert "collection-secret" not in response.text
    with api_session_factory() as session:
        source = session.scalar(select(Source))
    assert source is not None
    assert source.status is SourceStatus.FAILED
    assert source.collection_id == "collection-1"
    assert fake_fastgpt.collections["collection-1"].forbidden is True


def test_list_and_processed_preview_are_workspace_scoped(
    client: TestClient,
    seeded_workspace: Workspace,
    fake_fastgpt: FakeFastGPT,
    api_session_factory: Callable[[], object],
) -> None:
    _register_dataset(fake_fastgpt, seeded_workspace)
    created = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/text",
        json={"source_name": "notes", "text": "Mean.", "settings": {}},
    ).json()
    source_id = created["source"]["id"]
    with api_session_factory() as session:
        other = Workspace(title="Other", dataset_id="dataset-other")
        session.add(other)
        session.commit()
        session.refresh(other)

    own = client.get(
        f"/api/workspaces/{seeded_workspace.id}/sources/{source_id}/processed-preview"
    )
    cross = client.get(f"/api/workspaces/{other.id}/sources/{source_id}/processed-preview")
    invalid = client.get(
        f"/api/workspaces/{seeded_workspace.id}/sources/not-a-uuid/processed-preview"
    )

    assert own.status_code == 200
    assert own.json()["authority"] == "actual"
    assert cross.status_code == 404
    assert cross.json() == {"detail": {"code": "source_not_found"}}
    assert invalid.status_code == 404


def test_processed_preview_external_failure_is_safe(
    client: TestClient,
    seeded_workspace: Workspace,
    fake_fastgpt: FakeFastGPT,
) -> None:
    _register_dataset(fake_fastgpt, seeded_workspace)
    source_id = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/text",
        json={"source_name": "notes", "text": "Mean.", "settings": {}},
    ).json()["source"]["id"]
    fake_fastgpt.list_collection_data = AsyncMock(
        side_effect=RuntimeError("collection-1 private-content api-key")
    )

    response = client.get(
        f"/api/workspaces/{seeded_workspace.id}/sources/{source_id}/processed-preview"
    )

    assert response.status_code == 502
    assert response.json() == {"detail": {"code": "external_service_error"}}
    assert "private-content" not in response.text
    assert "collection-1" not in response.text


def test_processed_preview_is_bounded_to_30_and_omits_external_chunk_ids(
    client: TestClient,
    seeded_workspace: Workspace,
    fake_fastgpt: FakeFastGPT,
) -> None:
    _register_dataset(fake_fastgpt, seeded_workspace)
    source_id = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/text",
        json={"source_name": "notes", "text": "Mean.", "settings": {}},
    ).json()["source"]["id"]
    fake_fastgpt.collections["collection-1"].chunks = [
        ProcessedChunk(f"external-private-{index}", f"Question {index}", f"Answer {index}")
        for index in range(35)
    ]

    response = client.get(
        f"/api/workspaces/{seeded_workspace.id}/sources/{source_id}/processed-preview"
    )

    assert response.status_code == 200
    assert response.json()["limit"] == 30
    assert len(response.json()["items"]) == 30
    assert "external-private" not in response.text


def test_processed_preview_sanitizes_controls_and_caps_public_fields(
    client: TestClient,
    seeded_workspace: Workspace,
    fake_fastgpt: FakeFastGPT,
) -> None:
    _register_dataset(fake_fastgpt, seeded_workspace)
    source_id = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/text",
        json={"source_name": "notes", "text": "Mean.", "settings": {}},
    ).json()["source"]["id"]
    fake_fastgpt.collections["collection-1"].chunks = [
        ProcessedChunk("external-1", "Q" * 4_001 + "\x00private", "A\x00B")
    ]

    response = client.get(
        f"/api/workspaces/{seeded_workspace.id}/sources/{source_id}/processed-preview"
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["q"] == "Q" * 4_000
    assert item["a"] == "AB"
    assert item["q_truncated"] is True
    assert item["a_truncated"] is False
    assert "private" not in response.text
    assert "\\u0000" not in response.text


def test_failed_source_without_collection_has_stable_unavailable_preview(
    client: TestClient,
    seeded_workspace: Workspace,
    api_session_factory: Callable[[], object],
) -> None:
    with api_session_factory() as session:
        source = Source(
            workspace_id=seeded_workspace.id,
            name="failed",
            source_type=SourceType.TEXT,
            status=SourceStatus.FAILED,
            ingestion_config={},
            error_message="Source ingestion failed.",
        )
        session.add(source)
        session.commit()
        session.refresh(source)

    response = client.get(
        f"/api/workspaces/{seeded_workspace.id}/sources/{source.id}/processed-preview"
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "processed_preview_unavailable"}}


def test_source_list_uses_one_query_and_exposes_no_private_identifiers(
    client: TestClient,
    seeded_workspace: Workspace,
    api_engine,
    api_session_factory: Callable[[], object],
) -> None:
    with api_session_factory() as session:
        session.add_all(
            [
                Source(
                    workspace_id=seeded_workspace.id,
                    name=f"notes-{index}",
                    source_type=SourceType.TEXT,
                    status=SourceStatus.REVIEW,
                    collection_id=f"collection-private-{index}",
                    ingestion_config={},
                )
                for index in range(3)
            ]
        )
        session.commit()
    selects: list[str] = []

    def record_select(conn, cursor, statement, parameters, context, executemany) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    event.listen(api_engine, "before_cursor_execute", record_select)
    try:
        response = client.get(f"/api/workspaces/{seeded_workspace.id}/sources")
    finally:
        event.remove(api_engine, "before_cursor_execute", record_select)

    assert response.status_code == 200
    assert len(response.json()) == 3
    assert len(selects) == 1
    assert "collection-private" not in response.text
    assert "dataset" not in response.text


def test_source_routes_do_not_accidentally_add_task7_actions(
    client: TestClient, seeded_workspace: Workspace
) -> None:
    source_id = uuid4()

    assert (
        client.post(
            f"/api/workspaces/{seeded_workspace.id}/sources/{source_id}/accept"
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/workspaces/{seeded_workspace.id}/sources/{source_id}/reprocess"
        ).status_code
        == 404
    )
    assert client.delete(
        f"/api/workspaces/{seeded_workspace.id}/sources/{source_id}"
    ).status_code == 404


def test_source_openapi_and_runtime_never_expose_external_identifiers(
    client: TestClient,
) -> None:
    openapi = client.get("/openapi.json").json()
    schemas = openapi["components"]["schemas"]

    assert "collection_id" not in json.dumps(schemas)
    assert "dataset_id" not in json.dumps(schemas)
    assert "api_key" not in json.dumps(schemas)
    source_config_schema = schemas["SourceResponse"]["properties"]["ingestion_config"]
    assert source_config_schema == {"$ref": "#/components/schemas/ChunkSettings"}


def test_source_lock_registry_is_recreated_for_each_app_lifespan(api_engine) -> None:
    with TestClient(main_module.app):
        first = main_module.app.state.source_locks
    with TestClient(main_module.app):
        second = main_module.app.state.source_locks

    assert first is not second
    assert first.active_count == 0
    assert second.active_count == 0
