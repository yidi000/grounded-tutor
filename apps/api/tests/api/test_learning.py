from uuid import uuid4

import pytest

from grounded_tutor.adapters.fastgpt import RetrievedChunk
from grounded_tutor.domain.answers import GeneratedAnswer, GeneratedBlock
from grounded_tutor.domain.diagnostics import GeneratedDiagnosticQuestion
from grounded_tutor.domain.models import (
    ActivityState,
    Concept,
    LearningPlan,
    Source,
    SourceStatus,
    SourceType,
)
from grounded_tutor.domain.teaching import GeneratedCheck


@pytest.fixture
def teaching_api(client, seeded_workspace, api_session_factory, fake_fastgpt, fake_generation):
    with api_session_factory() as session:
        source = Source(
            workspace_id=seeded_workspace.id,
            name="Notes",
            source_type=SourceType.TEXT,
            status=SourceStatus.READY,
            collection_id="ready",
            ingestion_config={},
        )
        plan = LearningPlan(workspace_id=seeded_workspace.id, goal="Learn mean")
        session.add_all([source, plan])
        session.flush()
        concepts = [
            Concept(
                workspace_id=seeded_workspace.id,
                plan_id=plan.id,
                order=i + 1,
                title=f"Mean {i}",
                objective="Explain mean",
                evidence_refs=[
                    {"source_id": str(source.id), "source_version": 1, "chunk_id": "chunk"}
                ],
            )
            for i in range(3)
        ]
        session.add_all(
            [
                *concepts,
                ActivityState(
                    workspace_id=seeded_workspace.id,
                    active_mode="PLAN",
                    return_checkpoint=f"plan:{plan.id}",
                ),
            ]
        )
        session.commit()
        ids = [str(c.id) for c in concepts]
    fake_fastgpt.search_results_override = (
        RetrievedChunk("chunk", "ready", "Provider", "Mean", "sum divided by count", 1),
    )
    lesson = GeneratedAnswer(
        blocks=tuple(
            GeneratedBlock(id=kind, kind=kind, text="sum divided by count", chunk_ids=("chunk",))
            for kind in ("definition", "explanation", "example")
        )
    )
    fake_generation.responses = [lesson] * 10
    fake_generation.check_responses = [
        GeneratedCheck(
            question=GeneratedDiagnosticQuestion(
                id="q",
                kind="single_choice",
                prompt="Numerator?",
                options=("sum", "product"),
                answer_key=("sum",),
                explanation="Use the sum.",
                concept_label="Mean",
                chunk_ids=("chunk",),
            )
        )
    ] * 10
    return f"/api/workspaces/{seeded_workspace.id}/learning", ids


def test_lesson_check_loop_wrong_review_then_finish_plan(client, teaching_api):
    url, concepts = teaching_api
    for i, concept in enumerate(concepts):
        lesson = client.post(
            f"{url}/concepts/{concept}/lessons",
            json={"depth": "deeper", "idempotency_key": f"lesson-{i}"},
        )
        assert lesson.status_code == 200
        assert client.get(f"{url}/lessons/{lesson.json()['lesson_id']}").json() == lesson.json()
        checked = client.post(
            f"{url}/concepts/{concept}/checks", json={"idempotency_key": f"check-{i}"}
        )
        assert checked.status_code == 200 and "answer_key" not in checked.text
        resource = f"{url}/checks/{checked.json()['assessment_id']}"
        assert client.get(resource).json() == checked.json()
        if i == 0:
            wrong = client.post(
                resource + "/answers", json={"response": "product", "idempotency_key": "wrong"}
            )
            assert wrong.json()["next_action"] == "review_concept"
            checked = client.post(
                f"{url}/concepts/{concept}/checks", json={"idempotency_key": "retry-check"}
            )
            resource = f"{url}/checks/{checked.json()['assessment_id']}"
        payload = {"response": "sum", "idempotency_key": f"answer-{i}"}
        result = client.post(resource + "/answers", json=payload)
        assert result.status_code == 200 and result.json()["correct"] is True
        assert result.json()["explanation_blocks"] and result.json()["citations"]
        assert client.post(resource + "/answers", json=payload).json() == result.json()
    assert (
        result.json()["next_action"] == "completed" and result.json()["active_concept_id"] is None
    )


def test_check_skip_has_confirmation_and_public_validation(client, teaching_api):
    url, concepts = teaching_api
    client.post(f"{url}/concepts/{concepts[0]}/lessons", json={"idempotency_key": "lesson"})
    check = client.post(
        f"{url}/concepts/{concepts[0]}/checks", json={"idempotency_key": "check"}
    ).json()
    resource = f"{url}/checks/{check['assessment_id']}"
    assert (
        client.post(
            resource + "/answers",
            json={"skip": True, "response": "sum", "idempotency_key": "invalid"},
        ).status_code
        == 422
    )
    result = client.post(resource + "/answers", json={"skip": True, "idempotency_key": "skip"})
    assert result.json()["correct"] is None and result.json()["next_action"] == "confirm_continue"
    assert (
        client.post(
            resource + "/continue", json={"confirm_continue": False, "idempotency_key": "continue"}
        ).status_code
        == 422
    )
    continued = client.post(
        resource + "/continue", json={"confirm_continue": True, "idempotency_key": "continue"}
    )
    assert continued.json()["active_concept_id"] == concepts[1]
    assert (
        client.get(
            f"/api/workspaces/{uuid4()}/learning/checks/{check['assessment_id']}"
        ).status_code
        == 404
    )


def test_demo_blocks_learning_writes(demo_client):
    base = f"/api/workspaces/{uuid4()}/learning"
    for suffix in (
        f"/concepts/{uuid4()}/lessons",
        f"/concepts/{uuid4()}/checks",
        f"/checks/{uuid4()}/answers",
        f"/checks/{uuid4()}/continue",
    ):
        assert demo_client.post(base + suffix, json={}).status_code == 403
