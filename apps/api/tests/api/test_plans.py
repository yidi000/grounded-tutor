from uuid import uuid4

import pytest

from grounded_tutor.adapters.fastgpt import RetrievedChunk
from grounded_tutor.domain.diagnostics import GeneratedDiagnostic, GeneratedDiagnosticQuestion
from grounded_tutor.domain.models import Source, SourceStatus, SourceType
from grounded_tutor.domain.plans import GeneratedLearningPlan, GeneratedPlanConcept


@pytest.fixture
def plans_api(client, seeded_workspace, api_session_factory, fake_fastgpt, fake_generation):
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
                    prompt=f"Numerator {i}?",
                    options=("sum", "count"),
                    answer_key=("sum",),
                    explanation="Use sum.",
                    concept_label=f"Concept {i}",
                    chunk_ids=("chunk",),
                )
                for i in range(3)
            )
        )
    ]
    base = f"/api/workspaces/{seeded_workspace.id}"
    diagnostic = client.post(
        base + "/diagnostics",
        json={"consent": True, "goal": "Learn mean", "idempotency_key": "diagnostic"},
    ).json()
    for i, question in enumerate(diagnostic["questions"]):
        response = client.post(
            base + "/diagnostics/" + diagnostic["diagnostic_id"] + "/answers",
            json={"question_id": question["question_id"], "skip": True, "idempotency_key": str(i)},
        )
        assert response.status_code == 200
    generated = GeneratedLearningPlan(
        concepts=tuple(
            GeneratedPlanConcept(
                title=f"Concept {i}",
                objective=f"Explain mean {i}",
                check_kind="single_choice",
                chunk_ids=("chunk",),
            )
            for i in range(3)
        )
    )
    fake_generation.plan_responses = [generated, generated]
    return base + "/plans", {
        "diagnostic_id": diagnostic["diagnostic_id"],
        "idempotency_key": "plan",
    }


def test_diagnostic_to_plan_skip_rebuild_history(client, plans_api):
    url, payload = plans_api
    response = client.post(url, json=payload)
    assert response.status_code == 200
    plan = response.json()
    resource = url + "/" + plan["plan_id"]
    assert client.get(resource).json() == plan
    assert "answer_key" not in response.text
    skipped = client.post(
        resource + "/concepts/" + plan["concepts"][0]["id"] + "/skip",
        json={"idempotency_key": "skip"},
    )
    assert skipped.status_code == 200 and skipped.json()["concepts"][0]["status"] == "not_assessed"
    for consent in (False, 1, "true", None):
        assert (
            client.post(
                resource + "/rebuild", json={**payload, "confirm_rebuild": consent}
            ).status_code
            == 422
        )
    rebuilt = client.post(resource + "/rebuild", json={**payload, "confirm_rebuild": True})
    assert rebuilt.status_code == 200 and rebuilt.json()["plan_id"] != plan["plan_id"]
    assert client.get(resource).json()["status"] == "superseded"
    assert len(client.get(url).json()["plans"]) == 2
    assert client.get(f"/api/workspaces/{uuid4()}/plans/{plan['plan_id']}").status_code == 404
    assert not any("reorder" in path for path in client.get("/openapi.json").json()["paths"])


def test_plan_input_and_conflict_contracts(client, plans_api):
    url, payload = plans_api
    assert client.post(url, json={**payload, "goal": "Unconfirmed"}).status_code == 422
    plan = client.post(url, json=payload).json()
    wrong = client.post(url, json={**payload, "diagnostic_id": str(uuid4())})
    assert wrong.status_code == 409 and wrong.json()["detail"]["code"] == "idempotency_key_reused"
    missing = client.post(
        url + "/" + plan["plan_id"] + "/concepts/" + str(uuid4()) + "/skip",
        json={"idempotency_key": "skip"},
    )
    assert missing.status_code == 404


def test_demo_plan_writes_are_blocked(demo_client):
    url = f"/api/workspaces/{uuid4()}/plans"
    for suffix in ("", f"/{uuid4()}/rebuild", f"/{uuid4()}/concepts/{uuid4()}/skip"):
        assert demo_client.post(url + suffix, json={}).status_code == 403
