from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

import grounded_tutor.main as main_module
from grounded_tutor.adapters.fakes import FakeFastGPT
from grounded_tutor.adapters.fastgpt import ExternalServiceError, FastGPTClient
from grounded_tutor.config import Settings
from grounded_tutor.db import get_session
from grounded_tutor.dependencies import get_fastgpt
from grounded_tutor.domain.models import Source, SourceStatus, SourceType, Workspace
from grounded_tutor.repositories.workspaces import (
    WorkspacePersistenceError,
    WorkspacePersistenceOutcome,
    WorkspaceRepository,
)
from grounded_tutor.services.workspaces import WorkspaceService


def test_create_workspace_creates_fastgpt_dataset(client: TestClient, fake_fastgpt: FakeFastGPT) -> None:
    response = client.post("/api/workspaces", json={"title": "Intro Statistics"})

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "id",
        "title",
        "source_count",
        "ready_source_count",
        "model_choices",
        "created_at",
        "updated_at",
    }
    assert body["title"] == "Intro Statistics"
    assert body["source_count"] == 0
    assert fake_fastgpt.create_dataset_calls == [("Intro Statistics", None, None, None)]


def test_create_workspace_round_trips_all_model_choices(
    model_capable_client: TestClient, fake_fastgpt: FakeFastGPT
) -> None:
    response = model_capable_client.post(
        "/api/workspaces",
        json={
            "title": "  Intro Statistics  ",
            "vector_model": " embedding-3 ",
            "agent_model": " agent-1 ",
            "vlm_model": " vision-1 ",
        },
    )

    assert response.status_code == 201
    assert response.json()["title"] == "Intro Statistics"
    assert response.json()["model_choices"] == {
        "vector_model": "embedding-3",
        "agent_model": "agent-1",
        "vlm_model": "vision-1",
    }
    assert fake_fastgpt.create_dataset_calls == [
        ("Intro Statistics", "embedding-3", "agent-1", "vision-1")
    ]

    listed = model_capable_client.get("/api/workspaces")
    detail = model_capable_client.get(f"/api/workspaces/{response.json()['id']}")
    assert listed.json()[0]["model_choices"] == response.json()["model_choices"]
    assert detail.json()["model_choices"] == response.json()["model_choices"]


def test_workspace_model_choices_cannot_be_patched(
    client: TestClient, seeded_workspace: Workspace
) -> None:
    response = client.patch(
        f"/api/workspaces/{seeded_workspace.id}",
        json={"title": "Renamed", "vector_model": "replacement"},
    )

    assert response.status_code == 422


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


def test_workspace_counts_exclude_deleted_and_superseded_sources(
    client: TestClient,
    api_session_factory: Callable[[], object],
    seeded_workspace: Workspace,
) -> None:
    now = datetime.now(UTC)
    with api_session_factory() as session:
        session.add_all(
            [
                Source(
                    workspace_id=seeded_workspace.id,
                    name="current.txt",
                    source_type=SourceType.TEXT,
                    status=SourceStatus.READY,
                    ingestion_config={},
                ),
                Source(
                    workspace_id=seeded_workspace.id,
                    name="old.txt",
                    source_type=SourceType.TEXT,
                    status=SourceStatus.READY,
                    superseded_at=now,
                    ingestion_config={},
                ),
                Source(
                    workspace_id=seeded_workspace.id,
                    name="deleted.txt",
                    source_type=SourceType.TEXT,
                    status=SourceStatus.REVIEW,
                    deleted_at=now,
                    ingestion_config={},
                ),
            ]
        )
        session.commit()

    detail = client.get(f"/api/workspaces/{seeded_workspace.id}")

    assert detail.status_code == 200
    assert detail.json()["source_count"] == 1
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
    def fail_create(
        self: WorkspaceRepository,
        *,
        title: str,
        dataset_id: str,
        vector_model: str | None,
        agent_model: str | None,
        vlm_model: str | None,
    ) -> None:
        del self, title, dataset_id, vector_model, agent_model, vlm_model
        raise WorkspacePersistenceError(
            "not public", outcome=WorkspacePersistenceOutcome.DEFINITELY_UNCOMMITTED
        )

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
        lambda self, **kwargs: (_ for _ in ()).throw(
            WorkspacePersistenceError(
                "internal", outcome=WorkspacePersistenceOutcome.DEFINITELY_UNCOMMITTED
            )
        ),
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


def test_lifespan_closes_generation_when_fastgpt_close_fails(
    api_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    close_order: list[str] = []

    class FailingCloseFastGPT:
        def __init__(self, *_args: object) -> None:
            pass

        async def aclose(self) -> None:
            close_order.append("fastgpt")
            raise RuntimeError("fastgpt close failed")

    class RecordingCloseGeneration:
        def __init__(self, *_args: object) -> None:
            pass

        async def aclose(self) -> None:
            close_order.append("generation")

    monkeypatch.setattr(main_module, "FastGPTClient", FailingCloseFastGPT)
    monkeypatch.setattr(
        main_module, "OpenAICompatibleGenerationClient", RecordingCloseGeneration
    )
    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: Settings(database_url=str(api_engine.url), external_mode="live"),
    )

    with pytest.raises(RuntimeError, match="fastgpt close failed"), TestClient(
        main_module.app
    ):
        pass

    assert close_order == ["fastgpt", "generation"]


@pytest.mark.asyncio
async def test_add_failure_rolls_back_and_compensates_exact_dataset(api_engine) -> None:
    class AddFailingSession(Session):
        def add(self, instance, _warn: bool = True) -> None:
            raise SQLAlchemyError("database connection detail")

    fake_fastgpt = FakeFastGPT()
    session = AddFailingSession(bind=api_engine, expire_on_commit=False)
    service = WorkspaceService(WorkspaceRepository(session), fake_fastgpt)
    try:
        with pytest.raises(WorkspacePersistenceError) as caught:
            await service.create(
                title="Statistics", vector_model=None, agent_model=None, vlm_model=None
            )
    finally:
        session.close()

    assert caught.value.outcome is WorkspacePersistenceOutcome.DEFINITELY_UNCOMMITTED
    assert fake_fastgpt.delete_dataset_calls == ["dataset-1"]
    assert _workspace_count(api_engine) == 0


@pytest.mark.asyncio
async def test_flush_failure_rolls_back_and_compensates_exact_dataset(api_engine) -> None:
    class FlushFailingSession(Session):
        def flush(self, objects=None) -> None:
            super().flush(objects)
            raise SQLAlchemyError("flush failed")

    session = FlushFailingSession(bind=api_engine, expire_on_commit=False)
    fake_fastgpt = FakeFastGPT()
    service = WorkspaceService(WorkspaceRepository(session), fake_fastgpt)
    try:
        with pytest.raises(WorkspacePersistenceError) as caught:
            await service.create(
                title="Statistics", vector_model=None, agent_model=None, vlm_model=None
            )
    finally:
        session.close()

    assert caught.value.outcome is WorkspacePersistenceOutcome.DEFINITELY_UNCOMMITTED
    assert fake_fastgpt.delete_dataset_calls == ["dataset-1"]
    assert _workspace_count(api_engine) == 0


@pytest.mark.asyncio
async def test_commit_failure_is_ambiguous_and_does_not_compensate(api_engine) -> None:
    class CommitFailingSession(Session):
        def commit(self) -> None:
            raise SQLAlchemyError("commit failed")

    session = CommitFailingSession(bind=api_engine, expire_on_commit=False)
    fake_fastgpt = FakeFastGPT()
    service = WorkspaceService(WorkspaceRepository(session), fake_fastgpt)
    try:
        with pytest.raises(WorkspacePersistenceError) as caught:
            await service.create(
                title="Statistics", vector_model=None, agent_model=None, vlm_model=None
            )
    finally:
        session.close()

    assert caught.value.outcome is WorkspacePersistenceOutcome.UNKNOWN_OR_COMMITTED
    assert fake_fastgpt.delete_dataset_calls == []
    assert _workspace_count(api_engine) == 0


@pytest.mark.asyncio
async def test_post_commit_refresh_failure_does_not_compensate_committed_workspace(api_engine) -> None:
    class PostCommitRefreshFailingSession(Session):
        def refresh(self, instance, attribute_names=None, with_for_update=None) -> None:
            raise SQLAlchemyError("post-commit read failed")

    fake_fastgpt = FakeFastGPT()
    session = PostCommitRefreshFailingSession(bind=api_engine, expire_on_commit=False)
    service = WorkspaceService(WorkspaceRepository(session), fake_fastgpt)
    try:
        workspace = await service.create(
            title="Statistics", vector_model=None, agent_model=None, vlm_model=None
        )
    finally:
        session.close()

    assert workspace.title == "Statistics"
    assert fake_fastgpt.delete_dataset_calls == []
    with Session(api_engine) as check_session:
        persisted = check_session.scalar(select(Workspace).where(Workspace.id == workspace.id))
    assert persisted is not None
    assert persisted.dataset_id == "dataset-1"


def test_after_commit_failure_preserves_durable_workspace_and_dataset(api_engine) -> None:
    class AfterCommitFailingSession(Session):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            event.listen(self, "after_commit", self._raise_after_commit)

        def _raise_after_commit(self, session) -> None:
            raise SQLAlchemyError("after commit failed")

    fake_fastgpt = FakeFastGPT()

    with _client_with_session(api_engine, fake_fastgpt, AfterCommitFailingSession) as client:
        response = client.post("/api/workspaces", json={"title": "Statistics"})

    assert response.status_code == 500
    assert response.json() == {"detail": {"code": "persistence_error"}}
    assert fake_fastgpt.delete_dataset_calls == []
    with Session(api_engine) as check_session:
        persisted = check_session.scalar(select(Workspace).where(Workspace.dataset_id == "dataset-1"))
    assert persisted is not None
    assert persisted.title == "Statistics"


def test_add_failure_with_compensation_failure_returns_safe_api_error(api_engine) -> None:
    class AddFailingSession(Session):
        def add(self, instance, _warn: bool = True) -> None:
            raise SQLAlchemyError("database connection detail")

    fake_fastgpt = FakeFastGPT()
    fake_fastgpt.delete_dataset = AsyncMock(side_effect=RuntimeError("dataset-1 secret"))

    with _client_with_session(api_engine, fake_fastgpt, AddFailingSession) as client:
        response = client.post("/api/workspaces", json={"title": "Statistics"})

    assert response.status_code == 500
    assert response.json() == {"detail": {"code": "persistence_error"}}
    fake_fastgpt.delete_dataset.assert_awaited_once_with("dataset-1")
    assert "dataset-1" not in response.text
    assert "secret" not in response.text
    assert _workspace_count(api_engine) == 0


@contextmanager
def _client_with_session(
    api_engine, fastgpt: FakeFastGPT, session_class: type[Session]
) -> Generator[TestClient, None, None]:
    session_factory = sessionmaker(bind=api_engine, class_=session_class, expire_on_commit=False)

    def get_test_session() -> Generator[Session, None, None]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    main_module.app.dependency_overrides[get_session] = get_test_session
    main_module.app.dependency_overrides[get_fastgpt] = lambda: fastgpt
    try:
        with TestClient(main_module.app) as client:
            yield client
    finally:
        main_module.app.dependency_overrides.clear()


def _workspace_count(api_engine) -> int:
    with Session(api_engine) as session:
        return len(session.scalars(select(Workspace)).all())


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
