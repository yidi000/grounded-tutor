import json

import pytest
from sqlalchemy import select

from grounded_tutor.adapters.fastgpt import RetrievedChunk
from grounded_tutor.domain.answers import GeneratedAnswer, GeneratedBlock
from grounded_tutor.domain.models import Source, SourceStatus, SourceType


@pytest.fixture
def grounded_chat(seeded_workspace, api_session_factory, fake_fastgpt):
    with api_session_factory() as session:
        session.add(
            Source(
                workspace_id=seeded_workspace.id,
                name="Notes",
                source_type=SourceType.TEXT,
                status=SourceStatus.READY,
                collection_id="ready",
                ingestion_config={},
            )
        )
        session.commit()
    fake_fastgpt.search_results_override = (
        RetrievedChunk("chunk-1", "ready", "provider", "Question", "Evidence", 0.9),
        RetrievedChunk(
            "foreign", "foreign-collection", "private foreign name", "Foreign secret", "", 1
        ),
    )
    return f"/api/workspaces/{seeded_workspace.id}/chat"


def records(api_session_factory):
    from grounded_tutor.domain.models import BadCase, ExecutionTrace

    with api_session_factory() as session:
        return list(session.scalars(select(ExecutionTrace))), list(session.scalars(select(BadCase)))


def test_chat_trace_is_replayable_scoped_and_not_duplicated(
    client, grounded_chat, api_session_factory
):
    payload = {"message": "Explain", "idempotency_key": "private-request-key"}
    response = client.post(grounded_chat, json=payload)
    assert response.status_code == 200
    assert client.post(grounded_chat, json=payload).json() == response.json()
    traces, cases = records(api_session_factory)
    assert len(traces) == 1
    trace = traces[0]
    assert trace.route == "ASK"
    assert trace.retrieval_json["chunk_ids"] == ["chunk-1"]
    assert trace.retrieval_json["scores"] == [0.9]
    assert trace.retrieval_json["chunks"][0]["a"] == "Evidence"
    assert trace.generation_json["instruction"] == "Explain"
    assert len(trace.generation_json["attempts"]) == 1
    assert trace.validation_json["valid"] is True
    assert trace.validation_json["message_id"] == response.json()["message_id"]
    assert trace.timing_json["total_ms"] >= 0
    serialized = json.dumps([trace.retrieval_json, trace.generation_json, trace.validation_json])
    assert "Foreign secret" not in serialized and "private-request-key" not in serialized
    assert cases == []


@pytest.mark.parametrize(
    "failure", ["external_failure", "citation_failure", "unexpected_exception"]
)
def test_chat_failures_automatically_create_safe_bad_cases(
    client, grounded_chat, api_session_factory, fake_generation, monkeypatch, failure
):
    if failure == "external_failure":
        fake_generation.responses = [RuntimeError("api_key=private-failure-secret")]
    elif failure == "citation_failure":
        bad = GeneratedAnswer(
            blocks=(GeneratedBlock(id="b", kind="answer", text="Wrong", chunk_ids=("missing",)),)
        )
        fake_generation.responses = [bad, bad]
    else:
        from grounded_tutor.repositories.chat import ChatRepository

        def unexpected(*args, **kwargs):
            raise RuntimeError("api_key=private-failure-secret")

        monkeypatch.setattr(ChatRepository, "persist_exchange", unexpected)
    if failure == "unexpected_exception":
        with pytest.raises(RuntimeError):
            client.post(grounded_chat, json={"message": "Explain", "idempotency_key": "failed"})
    else:
        response = client.post(
            grounded_chat, json={"message": "Explain", "idempotency_key": "failed"}
        )
        assert response.status_code == (502 if failure == "external_failure" else 200)
    traces, cases = records(api_session_factory)
    assert len(traces) == len(cases) == 1
    assert cases[0].trace_id == traces[0].id
    assert cases[0].category == failure
    assert cases[0].status == "open"
    assert traces[0].validation_json["valid"] is False
    assert "private-failure-secret" not in json.dumps(traces[0].generation_json)
    assert "private-failure-secret" not in json.dumps(traces[0].validation_json)


def test_ordinary_abstention_is_not_a_bad_case(
    client, grounded_chat, fake_generation, api_session_factory
):
    fake_generation.responses = [GeneratedAnswer(blocks=()), GeneratedAnswer(blocks=())]
    response = client.post(
        grounded_chat, json={"message": "Unsupported", "idempotency_key": "empty"}
    )
    assert response.json()["status"] == "insufficient_material"
    traces, cases = records(api_session_factory)
    assert len(traces) == 1
    assert traces[0].validation_json["valid"] is True
    assert cases == []


@pytest.mark.parametrize("external_failure", [False, True])
def test_trace_storage_failure_preserves_primary_result_and_replay(
    client, grounded_chat, fake_generation, monkeypatch, caplog, external_failure
):
    from grounded_tutor.services.tracing import TracePersistenceError, TraceRecorder

    def unavailable(*args, **kwargs):
        raise TracePersistenceError()

    monkeypatch.setattr(TraceRecorder, "record", unavailable)
    if external_failure:
        fake_generation.responses = [RuntimeError("private-upstream-secret")]
    payload = {"message": "Explain", "idempotency_key": "trace-storage-failure"}
    response = client.post(grounded_chat, json=payload)
    assert response.status_code == (502 if external_failure else 200)
    if not external_failure:
        assert client.post(grounded_chat, json=payload).json() == response.json()
        assert len(fake_generation.calls) == 1
    assert "Unable to persist execution trace" in caplog.text
    assert "private-upstream-secret" not in caplog.text


def test_corrected_generation_records_both_attempts_without_bad_case(
    client, grounded_chat, fake_generation, api_session_factory
):
    fake_generation.responses = [
        GeneratedAnswer(
            blocks=(
                GeneratedBlock(
                    id="b",
                    kind="answer",
                    text="Wrong",
                    chunk_ids=("missing",),
                ),
            )
        )
    ]
    response = client.post(
        grounded_chat, json={"message": "Explain", "idempotency_key": "corrected"}
    )
    assert response.status_code == 200
    traces, cases = records(api_session_factory)
    attempts = traces[0].generation_json["attempts"]
    assert len(attempts) == 2
    assert attempts[0]["valid"] is False and attempts[1]["valid"] is True
    assert all(attempt["elapsed_ms"] >= 0 for attempt in attempts)
    assert traces[0].validation_json["valid"] is True
    assert cases == []


def test_trace_retains_source_type_for_office_locator_replay(
    client, grounded_chat, api_session_factory
):
    with api_session_factory() as session:
        source = session.scalar(select(Source))
        source.source_type = SourceType.FILE
        source.name = "slides.pptx"
        session.commit()
    response = client.post(grounded_chat, json={"message": "Explain", "idempotency_key": "office"})
    assert response.status_code == 200
    traces, _ = records(api_session_factory)
    assert traces[0].retrieval_json["chunks"][0]["source_type"] == "file"
