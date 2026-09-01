from pathlib import Path

from alembic.config import Config
from fastapi.testclient import TestClient

import grounded_tutor.main as main_module
from alembic import command
from grounded_tutor.config import Settings, get_settings
from grounded_tutor.db import create_database_engine


def test_health(monkeypatch, tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'health.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    engine = create_database_engine(Settings(database_url=database_url))
    monkeypatch.setattr(main_module, "engine", engine)

    try:
        with TestClient(main_module.app) as client:
            response = client.get("/api/health")
    finally:
        engine.dispose()

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
