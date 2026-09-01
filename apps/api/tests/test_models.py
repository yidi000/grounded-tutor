from collections.abc import Generator
from pathlib import Path
from unittest.mock import Mock

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import grounded_tutor.db as db_module
import grounded_tutor.main as main_module
from alembic import command
from grounded_tutor.config import Settings, get_settings
from grounded_tutor.db import (
    ALEMBIC_DATABASE_URL_ATTRIBUTE,
    create_database_engine,
    ensure_database_is_current,
    get_alembic_config,
    resolve_alembic_database_url,
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
def temporary_engine(temporary_database_url: str) -> Generator[Engine]:
    engine = create_database_engine(Settings(database_url=temporary_database_url))
    yield engine
    engine.dispose()


@pytest.fixture
def migrated_database_url(monkeypatch: pytest.MonkeyPatch, temporary_database_url: str) -> str:
    monkeypatch.setenv("DATABASE_URL", temporary_database_url)
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    return temporary_database_url


@pytest.fixture
def migrated_engine(migrated_database_url: str) -> Generator[Engine]:
    engine = create_database_engine(Settings(database_url=migrated_database_url))
    yield engine
    engine.dispose()


def test_workspace_and_source_are_isolated(temporary_engine: Engine) -> None:
    Base.metadata.create_all(temporary_engine)
    with Session(temporary_engine) as session:
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


def test_application_sqlite_engine_enforces_foreign_keys(temporary_engine: Engine) -> None:
    Base.metadata.create_all(temporary_engine)
    with temporary_engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


def test_alembic_command_honors_explicit_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    explicit_path = tmp_path / "explicit.db"
    fallback_path = tmp_path / "fallback.db"
    explicit_settings = Settings(database_url=_database_url(explicit_path))
    monkeypatch.setenv("DATABASE_URL", _database_url(fallback_path))

    command.upgrade(get_alembic_config(explicit_settings), "head")

    assert explicit_path.exists()
    assert not fallback_path.exists()


def test_alembic_url_resolution_uses_explicit_url_and_api_local_fallback() -> None:
    explicit_url = "sqlite:////tmp/explicit.db"
    explicit_config = get_alembic_config(Settings(database_url=explicit_url))

    assert explicit_config.attributes[ALEMBIC_DATABASE_URL_ATTRIBUTE] == explicit_url
    assert resolve_alembic_database_url(explicit_config) == explicit_url
    assert resolve_alembic_database_url(Config(str(Path(__file__).parents[1] / "alembic.ini"))) == Settings().database_url


def test_alembic_config_escapes_percent_encoded_database_url() -> None:
    database_url = "postgresql+psycopg://user:p%40ss@example.test/grounded_tutor"

    config = get_alembic_config(Settings(database_url=database_url))

    assert config.attributes[ALEMBIC_DATABASE_URL_ATTRIBUTE] == database_url
    assert config.get_main_option("sqlalchemy.url") == database_url


def test_settings_cache_does_not_retain_temporary_database_url(
    monkeypatch: pytest.MonkeyPatch, temporary_database_url: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", temporary_database_url)
    get_settings.cache_clear()
    assert get_settings().database_url == temporary_database_url

    monkeypatch.delenv("DATABASE_URL")
    get_settings.cache_clear()
    assert get_settings().database_url == Settings().database_url


def test_migration_guard_rejects_unmigrated_database(temporary_engine: Engine) -> None:
    with pytest.raises(RuntimeError, match=r"Run `alembic upgrade head`"):
        ensure_database_is_current(temporary_engine)


def test_migration_guard_allows_current_database(migrated_engine: Engine) -> None:
    ensure_database_is_current(migrated_engine)


def test_lifespan_requires_a_current_database(
    monkeypatch: pytest.MonkeyPatch, temporary_engine: Engine
) -> None:
    monkeypatch.setattr(main_module, "engine", temporary_engine)

    with pytest.raises(RuntimeError, match=r"Run `alembic upgrade head`"), TestClient(main_module.app):
        pass


def test_get_session_rolls_back_and_closes_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Mock(spec=Session)
    monkeypatch.setattr(db_module, "SessionLocal", Mock(return_value=session))
    sessions = db_module.get_session()

    assert next(sessions) is session
    with pytest.raises(RuntimeError, match="boom"):
        sessions.throw(RuntimeError("boom"))

    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()


def test_settings_mask_secrets_in_repr_and_json_serialization() -> None:
    settings = Settings(fastgpt_api_key="fastgpt-secret", llm_api_key="llm-secret")
    serialized = settings.model_dump(mode="json")

    assert "fastgpt-secret" not in repr(settings)
    assert "llm-secret" not in repr(settings)
    assert "fastgpt-secret" not in str(serialized)
    assert "llm-secret" not in str(serialized)


def test_persistence_defaults_and_constraints(temporary_engine: Engine) -> None:
    Base.metadata.create_all(temporary_engine)

    with Session(temporary_engine) as session:
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
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    command.upgrade(config, "head")
    command.current(config)
    command.check(config)
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_database_engine(Settings())
    try:
        ensure_database_is_current(engine)
    finally:
        engine.dispose()
    command.check(config)
