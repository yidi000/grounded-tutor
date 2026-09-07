import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from grounded_tutor.adapters.fakes import FakeFastGPT, FakeGeneration
from grounded_tutor.adapters.fastgpt import ExternalServiceError, RetrievedChunk
from grounded_tutor.adapters.generation import InvalidGenerationOutput
from grounded_tutor.domain.answers import GeneratedAnswer, GeneratedBlock
from grounded_tutor.domain.models import (
    Conversation,
    Message,
    Source,
    SourceStatus,
    SourceType,
    Workspace,
)
from grounded_tutor.repositories.sources import (
    SourcePersistenceError,
    SourcePersistenceOutcome,
    SourceRepository,
)


def _generated(
    text: str = "均值是平均数。", *, chunk_ids: tuple[str, ...] = ("chunk-ready",)
) -> GeneratedAnswer:
    return GeneratedAnswer(
        blocks=(
            GeneratedBlock(
                id="block-1", kind="answer", text=text, chunk_ids=chunk_ids
            ),
        )
    )


def test_history_restores_ordered_exchanges_and_citations_without_external_calls(
    client, seeded_workspace, api_session_factory, fake_fastgpt, fake_generation
):
    source = _seed_ready_source(api_session_factory, seeded_workspace)
    fake_fastgpt.search_results_override = (
        RetrievedChunk("chunk-ready", source.collection_id, "private", "均值", "均值是平均数。", 0.9),
    )
    fake_generation.responses = [_generated(), _generated(), _generated()]
    url = f"/api/workspaces/{seeded_workspace.id}/chat"
    responses = []
    for index in range(3):
        result = client.post(url, json={
            "message": f"问题 {index}", "idempotency_key": f"history-{index}",
            "conversation_id": responses[0]["conversation_id"] if index == 1 else None,
        })
        assert result.status_code == 200
        responses.append(result.json())
    # SQLite timestamps can tie; message UUIDs must not determine turn order.
    with api_session_factory() as session:
        from datetime import UTC, datetime
        for message in session.scalars(select(Message)):
            message.created_at = datetime(2026, 9, 7, tzinfo=UTC)
        session.commit()
    calls = len(fake_fastgpt.search_calls), len(fake_generation.calls)
    history = client.get(url + "/history")
    assert history.status_code == 200
    assert history.json() == {"exchanges": [
        {"question": f"问题 {i}", "response": response, "legacy_content": None}
        for i, response in enumerate(responses)
    ]}
    assert (len(fake_fastgpt.search_calls), len(fake_generation.calls)) == calls


def test_history_is_workspace_scoped_and_distinguishes_empty_from_missing(client, seeded_workspace):
    other = client.post("/api/workspaces", json={"title": "Other"}).json()["id"]
    client.post(f"/api/workspaces/{seeded_workspace.id}/chat", json={
        "message": "Only in A", "idempotency_key": "history-a",
    })
    assert client.get(f"/api/workspaces/{other}/chat/history").json() == {"exchanges": []}
    history = client.get(f"/api/workspaces/{seeded_workspace.id}/chat/history").json()
    assert history["exchanges"][0]["response"]["status"] == "insufficient_material"
    assert history["exchanges"][0]["response"]["suggested_actions"]
    assert client.get(f"/api/workspaces/{uuid4()}/chat/history").status_code == 404
    assert client.get("/api/workspaces/not-a-uuid/chat/history").status_code == 404


def _seed_ready_source(api_session_factory, workspace: Workspace) -> Source:
    with api_session_factory() as session:
        source = Source(
            workspace_id=workspace.id,
            name="本地讲义",
            source_type=SourceType.TEXT,
            status=SourceStatus.READY,
            collection_id="collection-ready",
            ingestion_config={},
        )
        session.add(source)
        session.commit()
        session.refresh(source)
        return source


def test_chat_success_returns_renderable_locally_grounded_blocks(
    client: TestClient,
    seeded_workspace: Workspace,
    api_session_factory,
    fake_fastgpt: FakeFastGPT,
    fake_generation: FakeGeneration,
) -> None:
    source = _seed_ready_source(api_session_factory, seeded_workspace)
    fake_fastgpt.search_results_override = (
        RetrievedChunk(
            "chunk-ready", source.collection_id, "provider-private-name", "什么是均值？", "均值是平均数。", 0.95
        ),
    )
    fake_generation.responses.append(_generated())

    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/chat",
        json={"message": "什么是均值？", "idempotency_key": "request-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["answer_blocks"] == [
        {
            "id": "block-1",
            "kind": "answer",
            "text": "均值是平均数。",
            "citation_ids": ["citation-1"],
        }
    ]
    assert body["citations"][0]["source_id"] == str(source.id)
    assert body["citations"][0]["source_name"] == "本地讲义"
    assert body["citations"][0]["locator"] == {"kind": "chunk", "label": "匹配片段 1"}
    assert body["suggested_actions"] == []
    serialized = response.text
    for private_value in (
        seeded_workspace.dataset_id,
        source.collection_id,
        "provider-private-name",
        "fastgpt-secret",
        "llm-secret",
    ):
        assert private_value not in serialized

    with api_session_factory() as session:
        messages = {message.role: message for message in session.scalars(select(Message))}
    assert messages["user"].idempotency_key is None
    assert str(messages["assistant"].id) == body["message_id"]
    assert messages["assistant"].content_blocks == body["answer_blocks"]
    assert messages["assistant"].citations == body["citations"]


def test_chat_insufficient_is_http_200_with_contract_valid_actions(
    client: TestClient, seeded_workspace: Workspace, fake_fastgpt: FakeFastGPT, fake_generation: FakeGeneration
) -> None:
    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/chat",
        json={"message": "unknown", "idempotency_key": "request-2"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_material"
    assert response.json()["answer_blocks"] == []
    assert response.json()["citations"] == []
    assert response.json()["suggested_actions"] == [
        {"type": "add_material"},
        {"type": "rephrase"},
    ]
    assert fake_fastgpt.search_calls == []
    assert fake_generation.calls == []


def test_chat_trims_input_and_rejects_blank_or_oversized_values(
    client: TestClient,
    seeded_workspace: Workspace,
    api_session_factory,
) -> None:
    accepted = client.post(
        f"/api/workspaces/{seeded_workspace.id}/chat",
        json={"message": "  trimmed question  ", "idempotency_key": "  key-1  "},
    )
    attempts = [
        client.post(
            f"/api/workspaces/{seeded_workspace.id}/chat",
            json={"message": "   ", "idempotency_key": "key"},
        ),
        client.post(
            f"/api/workspaces/{seeded_workspace.id}/chat",
            json={"message": "x" * 8001, "idempotency_key": "key"},
        ),
        client.post(
            f"/api/workspaces/{seeded_workspace.id}/chat",
            json={"message": "question", "idempotency_key": "   "},
        ),
        client.post(
            f"/api/workspaces/{seeded_workspace.id}/chat",
            json={"message": "question", "idempotency_key": "x" * 256},
        ),
    ]

    assert accepted.status_code == 200
    assert {(response.status_code, response.json()["detail"]["code"]) for response in attempts} == {
        (422, "validation_error")
    }
    with api_session_factory() as session:
        messages = {message.role: message for message in session.scalars(select(Message))}
    assert messages["user"].content == "trimmed question"
    assert messages["assistant"].idempotency_key == "key-1"


def test_conversation_from_another_workspace_is_not_reused(
    client: TestClient,
    seeded_workspace: Workspace,
    api_session_factory,
) -> None:
    with api_session_factory() as session:
        other = Workspace(title="Other", dataset_id="dataset-other")
        session.add(other)
        session.flush()
        conversation = Conversation(workspace_id=other.id)
        session.add(conversation)
        session.commit()
        conversation_id = conversation.id

    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/chat",
        json={
            "conversation_id": str(conversation_id),
            "message": "question",
            "idempotency_key": "request-isolated",
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "workspace_not_found"}}
    with api_session_factory() as session:
        assert list(session.scalars(select(Message))) == []


def test_invalid_generation_output_retries_once_then_refuses_safely(
    client: TestClient,
    seeded_workspace: Workspace,
    api_session_factory,
    fake_fastgpt: FakeFastGPT,
    fake_generation: FakeGeneration,
) -> None:
    source = _seed_ready_source(api_session_factory, seeded_workspace)
    fake_fastgpt.search_results_override = (
        RetrievedChunk("chunk-ready", source.collection_id, "provider", "q", "private evidence", 0.9),
    )
    fake_generation.responses.extend(
        [InvalidGenerationOutput(), _generated("guess", chunk_ids=("missing",))]
    )

    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/chat",
        json={"message": "question", "idempotency_key": "request-invalid"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_material"
    assert len(fake_generation.calls) == 2
    assert "private evidence" not in response.text


def test_provider_failure_is_redacted_as_external_service_error(
    client: TestClient,
    seeded_workspace: Workspace,
    api_session_factory,
    fake_fastgpt: FakeFastGPT,
    fake_generation: FakeGeneration,
) -> None:
    source = _seed_ready_source(api_session_factory, seeded_workspace)
    fake_fastgpt.search_results_override = (
        RetrievedChunk("chunk-ready", source.collection_id, "provider", "q", "a", 0.9),
    )
    fake_generation.responses.append(
        ExternalServiceError(
            service="generation",
            category="network",
            safe_message="private-provider-body super-secret",
        )
    )

    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/chat",
        json={"message": "question", "idempotency_key": "request-provider"},
    )

    assert response.status_code == 502
    assert response.json() == {"detail": {"code": "external_service_error"}}
    assert "private-provider-body" not in response.text
    assert "super-secret" not in response.text


@pytest.mark.parametrize(
    "method_name", ["get_workspace_dataset_id", "ready_collection_ids"]
)
def test_source_read_failure_returns_safe_500_without_provider_calls(
    client: TestClient,
    seeded_workspace: Workspace,
    fake_fastgpt: FakeFastGPT,
    fake_generation: FakeGeneration,
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
) -> None:
    def fail_read(_repository: SourceRepository, _workspace_id):
        try:
            raise SQLAlchemyError("params=(private-value,), SELECT private-table")
        except SQLAlchemyError as error:
            raise SourcePersistenceError(
                outcome=SourcePersistenceOutcome.DEFINITELY_UNCOMMITTED
            ) from error

    monkeypatch.setattr(SourceRepository, method_name, fail_read)

    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/chat",
        json={"message": "question", "idempotency_key": "request-source-db"},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": {"code": "persistence_error"}}
    assert "private" not in response.text
    assert fake_fastgpt.search_calls == []
    assert fake_generation.calls == []


def test_chat_missing_or_malformed_workspace_uses_stable_not_found_response(
    client: TestClient,
) -> None:
    responses = [
        client.post(
            f"/api/workspaces/{uuid4()}/chat",
            json={"message": "question", "idempotency_key": "key"},
        ),
        client.post(
            "/api/workspaces/not-a-uuid/chat",
            json={"message": "question", "idempotency_key": "key"},
        ),
    ]

    assert {(response.status_code, response.json()["detail"]["code"]) for response in responses} == {
        (404, "workspace_not_found")
    }


def test_demo_mode_rejects_chat_before_body_or_dependencies(demo_client: TestClient) -> None:
    response = demo_client.post(
        "/api/workspaces/00000000-0000-0000-0000-000000000000/chat",
        content=b"not-json",
    )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "demo_read_only"}}


def test_chat_openapi_documents_actual_public_error_responses(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"][
        "/api/workspaces/{workspace_id}/chat"
    ]["post"]

    assert set(operation["responses"]) == {"200", "403", "404", "409", "422", "500", "502"}
    assert "ApiErrorResponse" in json.dumps(operation)


def test_history_keeps_legacy_text_and_redacts_broken_pairs(client, seeded_workspace, api_session_factory):
    url = f"/api/workspaces/{seeded_workspace.id}/chat"
    client.post(url, json={"message": "旧问题", "idempotency_key": "legacy-history"})
    with api_session_factory() as session:
        assistant = session.scalar(select(Message).where(Message.role == "assistant"))
        assistant.content = "旧回答"
        assistant.content_blocks = None
        session.commit()
    exchange = client.get(url + "/history").json()["exchanges"][0]
    assert exchange["legacy_content"] == "旧回答"
    assert exchange["response"]["citations"] == []
    with api_session_factory() as session:
        user = session.scalar(select(Message).where(Message.role == "user"))
        session.delete(user)
        session.commit()
    response = client.get(url + "/history")
    assert response.status_code == 500
    assert "旧回答" not in response.text


def test_chat_idempotency_replays_exact_response_and_reports_conflicts(client, seeded_workspace):
    url = f"/api/workspaces/{seeded_workspace.id}/chat"
    payload = {"message": "Question", "idempotency_key": "replay"}
    first = client.post(url, json=payload)
    assert first.status_code == 200
    assert client.post(url, json=payload).json() == first.json()
    changed = client.post(url, json={**payload, "message": "Changed"})
    assert changed.status_code == 409
    assert "idempotency_key_reused" in changed.text


def test_chat_reports_pending_key_without_calling_providers(
    client, seeded_workspace, api_session_factory, fake_fastgpt, fake_generation
):
    from grounded_tutor.domain.models import RequestRecord
    from grounded_tutor.services.idempotency import request_hash

    with api_session_factory() as session:
        session.add(RequestRecord(
            workspace_id=seeded_workspace.id, idempotency_key="pending",
            request_hash=request_hash("Question", None), state="pending",
        ))
        session.commit()
    response = client.post(f"/api/workspaces/{seeded_workspace.id}/chat", json={
        "message": "Question", "idempotency_key": "pending",
    })
    assert response.status_code == 409
    from grounded_tutor.domain.schemas import ApiErrorResponse

    assert ApiErrorResponse.model_validate(response.json()).detail.code == "idempotency_in_progress"
    assert fake_fastgpt.search_calls == []
    assert fake_generation.calls == []


def test_diagnostic_invitation_survives_replay_and_history(
    client, seeded_workspace, api_session_factory, fake_fastgpt, fake_generation
):
    from grounded_tutor.domain.models import Assessment, Attempt

    source = _seed_ready_source(api_session_factory, seeded_workspace)
    fake_fastgpt.search_results_override = (
        RetrievedChunk("chunk-ready", source.collection_id, "provider", "Mean", "sum / count", 1),
    )
    url = f"/api/workspaces/{seeded_workspace.id}/chat"
    payload = {"message": "我是新手，应该怎么学？", "idempotency_key": "invite-test"}
    first = client.post(url, json=payload)
    assert first.status_code == 200
    assert first.json()["suggested_actions"] == [{"type": "start_diagnostic"}]
    assert client.post(url, json=payload).json() == first.json()
    assert client.get(url + "/history").json()["exchanges"][0]["response"] == first.json()
    assert len(fake_generation.calls) == 1
    with api_session_factory() as session:
        assert not list(session.scalars(select(Assessment)))
        assert not list(session.scalars(select(Attempt)))
