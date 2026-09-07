import json

import pytest
from sqlalchemy import event, func, inspect, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from alembic import command
from grounded_tutor.alembic_config import get_alembic_config
from grounded_tutor.config import Settings
from grounded_tutor.db import create_database_engine
from grounded_tutor.domain.models import BadCase, ExecutionTrace, Workspace
from grounded_tutor.services.tracing import TracePersistenceError, TraceRecorder


@pytest.fixture
def trace_database(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'traces.db'}")
    command.upgrade(get_alembic_config(settings), "head")
    engine = create_database_engine(settings)
    with Session(engine) as session:
        workspace = Workspace(title="Trace workspace", dataset_id="synthetic-trace-dataset")
        session.add(workspace)
        session.commit()
        workspace_id = workspace.id
    yield engine, workspace_id, settings
    engine.dispose()


def test_trace_persists_replay_fields_and_recursively_omits_credentials(trace_database):
    engine, workspace_id, _ = trace_database
    retrieval = {
        "chunk_ids": ["chunk-1"],
        "scores": [0.91],
        "nested": [{"AUTHORIZATION": "private-bearer", "safe": {"api_key": "private-api"}}],
        "access_token": "private-token",
        "clientSECRET": "private-secret",
        "Cookie": "private-cookie",
    }
    with Session(engine) as session:
        trace = TraceRecorder(session).record(
            workspace_id=workspace_id,
            request_id="request-1",
            route="ASK",
            retrieval=retrieval,
            generation={"blocks": [{"text": "Evidence", "secret": "private"}]},
            validation={"valid": True},
            timing={"total_ms": 12.5},
        )
        trace_id = trace.id
    with Session(engine) as session:
        saved = session.get(ExecutionTrace, trace_id)
        assert saved.workspace_id == workspace_id
        assert saved.request_id == "request-1" and saved.route == "ASK"
        assert saved.retrieval_json == {
            "chunk_ids": ["chunk-1"],
            "scores": [0.91],
            "nested": [{"safe": {}}],
        }
        assert saved.generation_json == {"blocks": [{"text": "Evidence"}]}
        assert saved.validation_json == {"valid": True}
        assert saved.timing_json == {"total_ms": 12.5}
        assert saved.created_at is not None
        assert session.scalar(select(func.count()).select_from(BadCase)) == 0
        assert "private" not in json.dumps([saved.retrieval_json, saved.generation_json])
    assert retrieval["access_token"] == "private-token"


@pytest.mark.parametrize(
    "validation, category",
    [
        ({"outcome": "external_failure"}, "external_failure"),
        ({"error_code": "external_service_error"}, "external_failure"),
        ({"outcome": "citation_failure"}, "citation_failure"),
        ({"error_code": "citation_validation_failed"}, "citation_failure"),
        ({"outcome": "wrong_route"}, "wrong_route"),
        ({"error_code": "unexpected_exception"}, "unexpected_exception"),
    ],
)
def test_failure_outcomes_automatically_create_bad_cases(trace_database, validation, category):
    engine, workspace_id, _ = trace_database
    with Session(engine) as session:
        trace = TraceRecorder(session).record(
            workspace_id=workspace_id,
            request_id="failed-request",
            route="ASK",
            validation=validation,
        )
        bad_case = session.scalar(select(BadCase).where(BadCase.trace_id == trace.id))
        assert bad_case.category == category
        assert bad_case.status == "open"
        assert bad_case.note == bad_case.resolution == ""
        assert bad_case.created_at is not None and bad_case.updated_at is not None


def test_explicit_bad_case_category_and_raw_diagnostics_are_sanitized(trace_database):
    engine, workspace_id, _ = trace_database
    with Session(engine) as session:
        trace = TraceRecorder(session).record(
            workspace_id=workspace_id,
            request_id="request",
            route="ASK",
            generation={
                "headers": {"unusual-header": "private-provider-header"},
                "exception": "private-exception-string",
                "error_message": "private-error-message",
                "unknown": RuntimeError("private-object"),
            },
            category="unexpected_exception",
        )
        assert trace.generation_json == {"unknown": "[REDACTED]"}
        assert (
            session.scalar(select(BadCase).where(BadCase.trace_id == trace.id)).category
            == "unexpected_exception"
        )


def test_trace_and_bad_case_roll_back_together_with_redacted_error(trace_database):
    engine, workspace_id, _ = trace_database

    def fail_bad_case(_mapper, _connection, _target):
        raise SQLAlchemyError("private database parameters")

    event.listen(BadCase, "before_insert", fail_bad_case)
    try:
        with Session(engine) as session, pytest.raises(TracePersistenceError) as error:
            TraceRecorder(session).record(
                workspace_id=workspace_id,
                request_id="request",
                route="ASK",
                category="wrong_route",
            )
    finally:
        event.remove(BadCase, "before_insert", fail_bad_case)
    assert str(error.value) == "Trace persistence failed."
    assert error.value.__context__ is None
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ExecutionTrace)) == 0
        assert session.scalar(select(func.count()).select_from(BadCase)) == 0


def test_trace_migration_downgrades_and_upgrades_without_removing_workspace(trace_database):
    engine, workspace_id, settings = trace_database
    config = get_alembic_config(settings)
    command.downgrade(config, "0005_idempotency")
    assert "execution_traces" not in inspect(engine).get_table_names()
    assert "bad_cases" not in inspect(engine).get_table_names()
    with Session(engine) as session:
        assert session.get(Workspace, workspace_id) is not None
    command.upgrade(config, "head")
    assert {"execution_traces", "bad_cases"} <= set(inspect(engine).get_table_names())
