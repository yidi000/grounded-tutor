from __future__ import annotations

from collections.abc import Generator
from typing import Any

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from grounded_tutor.config import API_ROOT, Settings, get_settings


def create_database_engine(settings: Settings) -> Engine:
    """Create an application database engine without opening a connection."""

    is_sqlite = settings.database_url.startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    database_engine = create_engine(settings.database_url, connect_args=connect_args)

    if is_sqlite:

        @event.listens_for(database_engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: object) -> None:
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return database_engine


def create_session_factory(database_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=database_engine, class_=Session, expire_on_commit=False)


def get_alembic_config(settings: Settings | None = None) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", (settings or get_settings()).database_url)
    return config


def ensure_database_is_current(database_engine: Engine) -> None:
    """Refuse startup unless the database matches this application's Alembic head."""

    script = ScriptDirectory.from_config(get_alembic_config())
    expected_revisions = set(script.get_heads())
    with database_engine.connect() as connection:
        current_revisions = set(MigrationContext.configure(connection).get_current_heads())

    if current_revisions != expected_revisions:
        raise RuntimeError("Database migrations are missing or stale. Run `alembic upgrade head`.")


settings = get_settings()
engine = create_database_engine(settings)
SessionLocal = create_session_factory(engine)


def get_session() -> Generator[Session, None, None]:
    """Yield a transaction-safe session for FastAPI dependencies."""

    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
