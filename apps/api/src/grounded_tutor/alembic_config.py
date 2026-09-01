from __future__ import annotations

from alembic.config import Config

from grounded_tutor.config import API_ROOT, Settings, get_settings

ALEMBIC_DATABASE_URL_ATTRIBUTE = "grounded_tutor.database_url"


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
