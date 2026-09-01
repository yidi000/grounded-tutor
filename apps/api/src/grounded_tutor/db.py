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

ALEMBIC_DATABASE_URL_ATTRIBUTE = "grounded_tutor.database_url"


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


def configure_alembic_database_url(config: Config, database_url: str) -> None:
    """Preserve the raw URL while giving ConfigParser an escaped representation."""

    config.attributes[ALEMBIC_DATABASE_URL_ATTRIBUTE] = database_url
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))


def resolve_alembic_database_url(config: Config) -> str:
    configured_url = config.attributes.get(ALEMBIC_DATABASE_URL_ATTRIBUTE)
    if isinstance(configured_url, str):
        return configured_url
    return get_settings().database_url


def get_alembic_config(settings: Settings | None = None) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    configure_alembic_database_url(config, (settings or get_settings()).database_url)
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
