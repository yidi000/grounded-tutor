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

    assert set(operation["responses"]) == {"200", "403", "404", "422", "500", "502"}
    assert "ApiErrorResponse" in json.dumps(operation)
