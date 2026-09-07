from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from grounded_tutor.config import Settings, get_settings
from grounded_tutor.db import get_session
from grounded_tutor.main import app


def test_local_admin_is_disabled_by_default():
    assert Settings(_env_file=None).enable_local_admin is False


@pytest.mark.parametrize(
    "enabled,demo,peer",
    [
        (False, False, "127.0.0.1"),
        (True, True, "127.0.0.1"),
        (True, False, "203.0.113.4"),
        (True, False, "testclient"),
    ],
)
@pytest.mark.parametrize(
    "path",
    [
        "traces",
        "traces/00000000-0000-4000-8000-000000000001",
        "bad-cases",
        "bad-cases/00000000-0000-4000-8000-000000000001",
    ],
)
def test_admin_gate_returns_404_before_database_access(enabled, demo, peer, path):
    settings = Settings(_env_file=None, enable_local_admin=enabled, demo_read_only=demo)

    def no_database():
        pytest.fail("denied admin request touched database")

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = no_database
    try:
        client = TestClient(app, base_url="http://127.0.0.1", client=(peer, 50000))
        try:
            response = client.get(
                f"/api/admin/evals/{path}", headers={"X-Forwarded-For": "127.0.0.1"}
            )
        finally:
            client.close()
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_enabled_admin_lists_empty_records(api_session_factory):
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, enable_local_admin=True
    )

    def session_dependency():
        with api_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_dependency
    try:
        with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
            assert client.get("/api/admin/evals/traces").json() == []
            assert client.get("/api/admin/evals/bad-cases").json() == []
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def local_admin(api_session_factory):
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, enable_local_admin=True
    )

    def session_dependency():
        with api_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_dependency
    try:
        with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def records(api_session_factory):
    from grounded_tutor.domain.models import BadCase, ExecutionTrace, Workspace

    with api_session_factory() as session:
        result = []
        for index in range(2):
            workspace = Workspace(title=f"Topic {index}", dataset_id=f"dataset-{index}")
            session.add(workspace)
            session.flush()
            trace = ExecutionTrace(
                workspace_id=workspace.id,
                request_id=f"request-{index}",
                route="ASK",
                retrieval_json={"returned_count": index},
                generation_json={"attempts": 1},
                validation_json={"status": "ok"},
                timing_json={"total_ms": 12},
            )
            session.add(trace)
            session.flush()
            case = BadCase(
                trace_id=trace.id,
                category="grounding",
                status="open",
                note="Review citation",
                resolution="",
            )
            session.add(case)
            session.flush()
            result.append((str(workspace.id), str(trace.id), str(case.id)))
        session.commit()
        return result


def test_admin_lists_and_details_are_workspace_scoped_and_explicit(local_admin, records):
    workspace_id, trace_id, case_id = records[0]
    other_workspace = records[1][0]
    trace = local_admin.get(f"/api/admin/evals/traces/{trace_id}").json()
    assert set(trace) == {
        "id",
        "request_id",
        "workspace_id",
        "route",
        "retrieval_json",
        "generation_json",
        "validation_json",
        "timing_json",
        "created_at",
    }
    assert trace["retrieval_json"] == {"returned_count": 0}
    assert trace["generation_json"] == {"attempts": 1}
    assert trace["workspace_id"] == workspace_id
    case = local_admin.get(f"/api/admin/evals/bad-cases/{case_id}").json()
    assert set(case) == {
        "id",
        "trace_id",
        "category",
        "status",
        "note",
        "resolution",
        "created_at",
        "updated_at",
    }
    assert case["trace_id"] == trace_id
    for path, record_id in [("traces", trace_id), ("bad-cases", case_id)]:
        assert len(local_admin.get(f"/api/admin/evals/{path}").json()) == 2
        assert len(local_admin.get(f"/api/admin/evals/{path}?limit=1").json()) == 1
        scoped = local_admin.get(f"/api/admin/evals/{path}?workspace_id={workspace_id}").json()
        assert [item["id"] for item in scoped] == [record_id]
        assert (
            local_admin.get(
                f"/api/admin/evals/{path}/{record_id}?workspace_id={other_workspace}"
            ).status_code
            == 404
        )
        assert local_admin.get(f"/api/admin/evals/{path}/{uuid4()}").status_code == 404
        for limit in [0, 101]:
            assert local_admin.get(f"/api/admin/evals/{path}?limit={limit}").status_code == 422
        assert local_admin.get(f"/api/admin/evals/{path}?workspace_id=invalid").status_code == 422
        assert local_admin.post(f"/api/admin/evals/{path}", json={}).status_code == 405


@pytest.mark.parametrize("forwarded_host", [None, "127.0.0.1"])
def test_admin_rejects_rebinding_host_before_database_access(forwarded_host):
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, enable_local_admin=True
    )

    def no_database():
        pytest.fail("untrusted Host reached database")

    app.dependency_overrides[get_session] = no_database
    client = TestClient(app, base_url="http://evil.test", client=("127.0.0.1", 50000))
    try:
        headers = {"X-Forwarded-Host": forwarded_host} if forwarded_host else {}
        assert client.get("/api/admin/evals/traces", headers=headers).status_code == 404
    finally:
        client.close()
        app.dependency_overrides.clear()


@pytest.mark.parametrize("hostname", ["localhost", "127.0.0.1", "[::1]"])
def test_admin_accepts_only_explicit_local_hosts(local_admin, hostname):
    assert local_admin.get("/api/admin/evals/traces", headers={"Host": hostname}).status_code == 200
