from uuid import uuid4

import pytest
from sqlalchemy import select

from grounded_tutor.adapters.fastgpt import RetrievedChunk
from grounded_tutor.domain.diagnostics import GeneratedDiagnostic, GeneratedDiagnosticQuestion
from grounded_tutor.domain.models import Attempt, Source, SourceStatus, SourceType


@pytest.fixture
def diagnostic_api(client, seeded_workspace, api_session_factory, fake_fastgpt, fake_generation):
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
        RetrievedChunk("chunk", "ready", "provider", "Mean", "sum divided by count", 1),
    )
    fake_generation.diagnostic_responses = [
        GeneratedDiagnostic(
            questions=tuple(
                GeneratedDiagnosticQuestion(
                    id=str(i),
                    kind="single_choice",
                    prompt=f"Choose the numerator {i}",
                    options=("sum", "product"),
                    answer_key=("sum",),
                    explanation="Use the sum.",
                    concept_label=f"Concept {i}",
                    chunk_ids=("chunk",),
                )
                for i in range(3)
            )
        )
    ]
    return f"/api/workspaces/{seeded_workspace.id}/diagnostics"


def test_api_consent_resume_answer_replay_summary(client, diagnostic_api, api_session_factory):
    url = diagnostic_api
    payload = {"goal": "Learn statistics", "idempotency_key": "start"}
    for consent in (None, False, "true", 1):
        assert client.post(url, json={**payload, "consent": consent}).status_code == 422
    response = client.post(url, json={**payload, "consent": True})
    assert response.status_code == 200
    diagnostic = response.json()
    assert "answer_key" not in response.text
    resource = url + "/" + diagnostic["diagnostic_id"]
    assert client.get(resource).json() == diagnostic
    assert (
        client.get(
            f"/api/workspaces/{uuid4()}/diagnostics/{diagnostic['diagnostic_id']}"
        ).status_code
        == 404
    )
    for i, question in enumerate(diagnostic["questions"]):
        answer = {
            "question_id": question["question_id"],
            "idempotency_key": str(i),
            **({"skip": True} if i == 0 else {"response": "sum"}),
        }
        reply = client.post(resource + "/answers", json=answer)
        assert reply.status_code == 200
        assert client.post(resource + "/answers", json=answer).json() == reply.json()
    summary = client.get(resource + "/summary")
    assert summary.status_code == 200
    assert summary.json()["status"] == "completed"
    assert summary.json()["concepts"][0]["result"] == "not_assessed"
    assert "percentage" not in summary.text
    with api_session_factory() as session:
        assert len(list(session.scalars(select(Attempt)))) == 3


def test_api_key_conflicts_and_foreign_question(client, diagnostic_api):
    payload = {"goal": "Learn statistics", "consent": True, "idempotency_key": "start"}
    diagnostic = client.post(diagnostic_api, json=payload).json()
    assert client.post(diagnostic_api, json={**payload, "goal": "Other"}).status_code == 409
    response = client.post(
        diagnostic_api + "/" + diagnostic["diagnostic_id"] + "/answers",
        json={"question_id": str(uuid4()), "response": "sum", "idempotency_key": "answer"},
    )
    assert response.status_code == 409


def test_demo_cannot_start_diagnostics(demo_client):
    response = demo_client.post(f"/api/workspaces/{uuid4()}/diagnostics", json={})
    assert response.status_code == 403
