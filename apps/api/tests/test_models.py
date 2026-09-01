from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import grounded_tutor.main as main_module
from alembic import command
from grounded_tutor.config import API_ROOT, Settings, get_settings
from grounded_tutor.db import (
    create_database_engine,
    ensure_database_is_current,
    get_alembic_config,
)
from grounded_tutor.domain.models import (
    Base,
    Conversation,
    Message,
    Source,
    SourceStatus,
    SourceType,
    Workspace,
)


def _database_url(path: Path) -> str:
    return f"sqlite:///{path}"


@pytest.fixture
def temporary_database_url(tmp_path: Path) -> str:
    return _database_url(tmp_path / "grounded-tutor-test.db")


@pytest.fixture
def migrated_database_url(monkeypatch: pytest.MonkeyPatch, temporary_database_url: str) -> str:
    monkeypatch.setenv("DATABASE_URL", temporary_database_url)
    get_settings.cache_clear()
    command.upgrade(Config(str(API_ROOT / "alembic.ini")), "head")
    yield temporary_database_url
    get_settings.cache_clear()


def test_workspace_and_source_are_isolated(temporary_database_url: str) -> None:
    engine = create_database_engine(Settings(database_url=temporary_database_url))
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        workspace = Workspace(title="Statistics", dataset_id="dataset-1")
        session.add(workspace)
        session.flush()
        session.add(
            Source(
                workspace_id=workspace.id,
                name="week-1.pdf",
                source_type=SourceType.FILE,
                status=SourceStatus.REVIEW,
                collection_id="collection-1",
                ingestion_config={"trainingType": "chunk"},
            )
        )
        session.commit()
        stored = session.scalar(select(Source).where(Source.workspace_id == workspace.id))

    assert stored is not None
    assert stored.collection_id == "collection-1"
    assert stored.status is SourceStatus.REVIEW


def test_application_sqlite_engine_enforces_foreign_keys(temporary_database_url: str) -> None:
    engine = create_database_engine(Settings(database_url=temporary_database_url))
    Base.metadata.create_all(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


def test_settings_default_database_url_is_api_local_and_stable_across_cwds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    first = Settings()
    monkeypatch.chdir(tmp_path)
    second = Settings()

    assert first.database_url == second.database_url
    assert first.database_url == _database_url(API_ROOT / "grounded_tutor.db")
    assert Config(str(API_ROOT / "alembic.ini")).get_main_option("sqlalchemy.url") == first.database_url
    assert get_alembic_config(first).get_main_option("sqlalchemy.url") == first.database_url


def test_migration_guard_rejects_unmigrated_database(temporary_database_url: str) -> None:
    engine = create_database_engine(Settings(database_url=temporary_database_url))

    with pytest.raises(RuntimeError, match=r"Run `alembic upgrade head`"):
        ensure_database_is_current(engine)


def test_migration_guard_allows_current_database(migrated_database_url: str) -> None:
    engine = create_database_engine(Settings(database_url=migrated_database_url))

    ensure_database_is_current(engine)


def test_lifespan_requires_a_current_database(
    monkeypatch: pytest.MonkeyPatch, temporary_database_url: str
) -> None:
    engine = create_database_engine(Settings(database_url=temporary_database_url))
    monkeypatch.setattr(main_module, "engine", engine)

    with pytest.raises(RuntimeError, match=r"Run `alembic upgrade head`"), TestClient(main_module.app):
        pass


def test_persistence_defaults_and_constraints(temporary_database_url: str) -> None:
    engine = create_database_engine(Settings(database_url=temporary_database_url))
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        workspace = Workspace(title="Statistics", dataset_id="dataset-1")
        session.add(workspace)
        session.flush()
        source = Source(
            workspace_id=workspace.id,
            name="week-1.pdf",
            source_type=SourceType.FILE,
            ingestion_config={},
        )
        session.add(source)
        session.flush()
        conversation = Conversation(workspace_id=workspace.id)
        session.add(conversation)
        session.flush()
        message = Message(
            conversation_id=conversation.id,
            role="user",
            mode="ask",
            content="What is a distribution?",
            idempotency_key="request-1",
        )
        session.add(message)
        session.commit()

        assert workspace.id is not None
        assert workspace.created_at is not None
        assert source.status is SourceStatus.UPLOADING
        assert source.version == 1
        assert source.ingestion_config == {}
        assert conversation.id is not None
        assert message.id is not None
        assert message.citations == []

        session.add(Workspace(title="Duplicate", dataset_id="dataset-1"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(
            Source(
                workspace_id=workspace.id,
                name="duplicate-collection.pdf",
                source_type=SourceType.FILE,
                collection_id="collection-1",
                ingestion_config={},
            )
        )
        session.commit()
        session.add(
            Source(
                workspace_id=workspace.id,
                name="duplicate-collection-2.pdf",
                source_type=SourceType.FILE,
                collection_id="collection-1",
                ingestion_config={},
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(
            Source(
                workspace_id=workspace.id,
                name="invalid-version.pdf",
                source_type=SourceType.FILE,
                version=0,
                ingestion_config={},
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        with pytest.raises(IntegrityError):
            session.execute(
                Source.__table__.insert().values(
                    workspace_id=workspace.id,
                    name="invalid-enum.pdf",
                    source_type="invalid",
                    ingestion_config={},
                )
            )
        session.rollback()

        session.add(
            Message(
                conversation_id=conversation.id,
                role="assistant",
                mode="ask",
                content="A distribution describes possible values.",
                citations=[],
                idempotency_key="request-1",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        other_conversation = Conversation(workspace_id=workspace.id)
        session.add(other_conversation)
        session.flush()
        session.add(
            Message(
                conversation_id=other_conversation.id,
                role="user",
                mode="ask",
                content="What is a mean?",
                citations=[],
                idempotency_key="request-1",
            )
        )
        session.commit()

        with pytest.raises(IntegrityError):
            session.delete(workspace)
            session.commit()
        session.rollback()


def test_alembic_upgrade_current_check_downgrade_and_reupgrade(
    monkeypatch: pytest.MonkeyPatch, temporary_database_url: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", temporary_database_url)
    get_settings.cache_clear()
    config = Config(str(API_ROOT / "alembic.ini"))

    command.upgrade(config, "head")
    command.current(config)
    command.check(config)
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    ensure_database_is_current(create_database_engine(Settings()))
    command.check(config)
