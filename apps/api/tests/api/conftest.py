from collections.abc import Callable, Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import grounded_tutor.main as main_module
from alembic import command
from grounded_tutor.adapters.fakes import FakeFastGPT, FakeGeneration
from grounded_tutor.alembic_config import get_alembic_config
from grounded_tutor.config import Settings, get_settings
from grounded_tutor.db import create_database_engine, create_session_factory, get_session
from grounded_tutor.dependencies import get_fastgpt, get_generation
from grounded_tutor.domain.models import Workspace


@pytest.fixture
def fake_fastgpt() -> FakeFastGPT:
    return FakeFastGPT()


@pytest.fixture
def fake_generation() -> FakeGeneration:
    return FakeGeneration()


@pytest.fixture
def api_engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    database_url = f"sqlite:///{tmp_path / 'api-test.db'}"
    command.upgrade(get_alembic_config(Settings(database_url=database_url)), "head")
    engine = create_database_engine(Settings(database_url=database_url))
    monkeypatch.setattr(main_module, "engine", engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def api_session_factory(api_engine) -> Callable[[], object]:
    return create_session_factory(api_engine)


@pytest.fixture
def client(
    api_session_factory: Callable[[], object],
    fake_fastgpt: FakeFastGPT,
    fake_generation: FakeGeneration,
) -> Generator[TestClient]:
    async def get_test_session():
        session = api_session_factory()
        try:
            yield session
        finally:
            session.close()

    main_module.app.dependency_overrides[get_session] = get_test_session
    main_module.app.dependency_overrides[get_fastgpt] = lambda: fake_fastgpt
    main_module.app.dependency_overrides[get_generation] = lambda: fake_generation
    try:
        with TestClient(main_module.app) as test_client:
            yield test_client
    finally:
        main_module.app.dependency_overrides.clear()
        get_settings.cache_clear()


@pytest.fixture
def demo_client(
    api_engine,
    fake_fastgpt: FakeFastGPT,
    fake_generation: FakeGeneration,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient]:
    monkeypatch.setenv("DEMO_READ_ONLY", "true")
    get_settings.cache_clear()

    async def fail_if_database_is_touched():
        raise AssertionError("demo write reached the database dependency")
        yield

    main_module.app.dependency_overrides[get_session] = fail_if_database_is_touched
    main_module.app.dependency_overrides[get_fastgpt] = lambda: fake_fastgpt
    main_module.app.dependency_overrides[get_generation] = lambda: fake_generation
    try:
        with TestClient(main_module.app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        main_module.app.dependency_overrides.clear()
        get_settings.cache_clear()


@pytest.fixture
def model_capable_client(
    api_session_factory: Callable[[], object],
    fake_fastgpt: FakeFastGPT,
    fake_generation: FakeGeneration,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient]:
    monkeypatch.setenv("SUPPORTS_VECTOR_MODEL", "true")
    monkeypatch.setenv("SUPPORTS_AGENT_MODEL", "true")
    monkeypatch.setenv("SUPPORTS_VLM_MODEL", "true")
    get_settings.cache_clear()

    async def get_test_session():
        session = api_session_factory()
        try:
            yield session
        finally:
            session.close()

    main_module.app.dependency_overrides[get_session] = get_test_session
    main_module.app.dependency_overrides[get_fastgpt] = lambda: fake_fastgpt
    main_module.app.dependency_overrides[get_generation] = lambda: fake_generation
    try:
        with TestClient(main_module.app) as test_client:
            yield test_client
    finally:
        main_module.app.dependency_overrides.clear()
        get_settings.cache_clear()


@pytest.fixture
def seeded_workspace(api_session_factory: Callable[[], object]) -> Workspace:
    with api_session_factory() as session:
        workspace = Workspace(title="Intro Statistics", dataset_id="dataset-seeded")
        session.add(workspace)
        session.commit()
        session.refresh(workspace)
        return workspace
