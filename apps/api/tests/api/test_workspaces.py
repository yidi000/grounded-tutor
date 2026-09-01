from collections.abc import Callable
from unittest.mock import AsyncMock

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import event

import grounded_tutor.main as main_module
from grounded_tutor.adapters.fakes import FakeFastGPT
from grounded_tutor.adapters.fastgpt import ExternalServiceError, FastGPTClient
from grounded_tutor.config import Settings
from grounded_tutor.dependencies import get_fastgpt
from grounded_tutor.domain.models import Source, SourceStatus, SourceType, Workspace
from grounded_tutor.repositories.workspaces import WorkspacePersistenceError, WorkspaceRepository


def test_create_workspace_creates_fastgpt_dataset(client: TestClient, fake_fastgpt: FakeFastGPT) -> None:
    response = client.post("/api/workspaces", json={"title": "Intro Statistics"})

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "id",
        "title",
        "source_count",
        "ready_source_count",
        "created_at",
        "updated_at",
    }
    assert body["title"] == "Intro Statistics"
    assert body["source_count"] == 0
    assert fake_fastgpt.create_dataset_calls == [("Intro Statistics", None, None, None)]


def test_create_workspace_trims_title_and_optional_models(
    client: TestClient, fake_fastgpt: FakeFastGPT
) -> None:
    response = client.post(
        "/api/workspaces",
        json={
            "title": "  Intro Statistics  ",
            "vector_model": " embedding-3 ",
            "agent_model": "   ",
            "vlm_model": " vision-1 ",
        },
    )

    assert response.status_code == 201
    assert response.json()["title"] == "Intro Statistics"
    assert fake_fastgpt.create_dataset_calls == [
        ("Intro Statistics", "embedding-3", None, "vision-1")
    ]


@pytest.mark.parametrize("title", ["", "   ", "x" * 121])
def test_create_workspace_rejects_invalid_trimmed_title(client: TestClient, title: str) -> None:
    response = client.post("/api/workspaces", json={"title": title})

    assert response.status_code == 422


def test_create_workspace_accepts_one_and_120_unicode_characters(client: TestClient) -> None:
    assert client.post("/api/workspaces", json={"title": "学"}).status_code == 201
    assert client.post("/api/workspaces", json={"title": "学" * 120}).status_code == 201


def test_create_workspace_measures_title_bounds_after_trimming(client: TestClient) -> None:
    response = client.post("/api/workspaces", json={"title": f"  {'学' * 120}  "})

    assert response.status_code == 201
    assert response.json()["title"] == "学" * 120


def test_list_and_detail_workspace_include_aggregated_source_counts(
    client: TestClient,
    api_session_factory: Callable[[], object],
    seeded_workspace: Workspace,
) -> None:
    with api_session_factory() as session:
        session.add_all(
            [
                Source(
                    workspace_id=seeded_workspace.id,
                    name="ready.pdf",
                    source_type=SourceType.FILE,
                    status=SourceStatus.READY,
                    ingestion_config={},
                ),
                Source(
                    workspace_id=seeded_workspace.id,
                    name="review.txt",
                    source_type=SourceType.TEXT,
                    status=SourceStatus.REVIEW,
                    ingestion_config={},
                ),
            ]
        )
        session.commit()

    listed = client.get("/api/workspaces")
    detail = client.get(f"/api/workspaces/{seeded_workspace.id}")

    assert listed.status_code == 200
    assert listed.json()[0]["source_count"] == 2
    assert listed.json()[0]["ready_source_count"] == 1
    assert detail.status_code == 200
    assert detail.json()["source_count"] == 2
    assert detail.json()["ready_source_count"] == 1


def test_rename_workspace_does_not_recreate_dataset(
    client: TestClient, seeded_workspace: Workspace, fake_fastgpt: FakeFastGPT
) -> None:
    response = client.patch(
        f"/api/workspaces/{seeded_workspace.id}", json={"title": "Statistics Review"}
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Statistics Review"
    assert fake_fastgpt.create_dataset_calls == []
    assert fake_fastgpt.delete_dataset_calls == []


@pytest.mark.parametrize("workspace_id", ["not-a-uuid", "00000000-0000-0000-0000-000000000000"])
def test_unknown_or_invalid_workspace_returns_not_found(client: TestClient, workspace_id: str) -> None:
    response = client.get(f"/api/workspaces/{workspace_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "workspace_not_found"}}


def test_external_creation_failure_returns_safe_gateway_and_does_not_persist(
    client: TestClient, fake_fastgpt: FakeFastGPT
) -> None:
    fake_fastgpt.create_dataset = AsyncMock(
        side_effect=ExternalServiceError(
            service="fastgpt", category="network", safe_message="temporary unavailable"
        )
    )

    response = client.post("/api/workspaces", json={"title": "secret-title"})

    assert response.status_code == 502
    assert response.json() == {"detail": {"code": "external_service_error"}}
    assert client.get("/api/workspaces").json() == []
    assert "secret-title" not in response.text


def test_db_failure_compensates_exact_created_dataset_and_remains_safe(
    client: TestClient, fake_fastgpt: FakeFastGPT, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_create(self: WorkspaceRepository, *, title: str, dataset_id: str):
        raise WorkspacePersistenceError("not public")

    monkeypatch.setattr(WorkspaceRepository, "create", fail_create)

    response = client.post("/api/workspaces", json={"title": "Statistics"})

    assert response.status_code == 500
    assert response.json() == {"detail": {"code": "persistence_error"}}
    assert fake_fastgpt.delete_dataset_calls == ["dataset-1"]
    assert "dataset-1" not in response.text


def test_db_failure_stays_safe_when_compensation_fails(
    client: TestClient, fake_fastgpt: FakeFastGPT, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        WorkspaceRepository,
        "create",
        lambda self, **kwargs: (_ for _ in ()).throw(WorkspacePersistenceError("internal")),
    )
    fake_fastgpt.delete_dataset = AsyncMock(side_effect=RuntimeError("dataset-1 secret"))

    response = client.post("/api/workspaces", json={"title": "Statistics"})

    assert response.status_code == 500
    assert response.json() == {"detail": {"code": "persistence_error"}}
    assert "dataset-1" not in response.text
    assert "secret" not in response.text


def test_workspace_response_excludes_private_fields(client: TestClient) -> None:
    response = client.post("/api/workspaces", json={"title": "Statistics"})

    assert response.status_code == 201
    assert not _contains_private_key(response.json())


def test_list_workspace_query_does_not_grow_per_workspace(
    client: TestClient, api_engine, api_session_factory: Callable[[], object]
) -> None:
    with api_session_factory() as session:
        session.add_all(
            [Workspace(title=f"Workspace {index}", dataset_id=f"dataset-{index}") for index in range(3)]
        )
        session.commit()

    selects: list[str] = []

    def record_select(conn, cursor, statement, parameters, context, executemany) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    event.listen(api_engine, "before_cursor_execute", record_select)
    try:
        response = client.get("/api/workspaces")
    finally:
        event.remove(api_engine, "before_cursor_execute", record_select)

    assert response.status_code == 200
    assert len(response.json()) == 3
    assert len(selects) == 1


def test_live_fastgpt_is_shared_for_lifespan_and_closed_without_network(
    api_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: Settings(
            database_url=str(api_engine.url),
            external_mode="live",
            fastgpt_base_url="https://fastgpt.test",
            fastgpt_api_key="not-a-real-key",
        ),
    )

    with TestClient(main_module.app):
        fastgpt = main_module.app.state.fastgpt
        request = Request({"type": "http", "app": main_module.app})
        assert isinstance(fastgpt, FastGPTClient)
        assert get_fastgpt(request) is fastgpt
        assert not fastgpt.is_closed

    assert fastgpt.is_closed


def _contains_private_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            key in {"dataset_id", "collection_id", "api_key", "fastgpt_api_key", "provider"}
            or _contains_private_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_private_key(item) for item in value)
    return False
