from uuid import uuid4

import pytest
from sqlalchemy import select

from grounded_tutor.domain.models import Attempt
from grounded_tutor.domain.teaching import (
    CheckAnswerRequest,
    CheckContinueRequest,
    CheckStartRequest,
    LessonRequest,
)
from grounded_tutor.services.learning_context import LearningConflictError, LearningNotFoundError


async def start(t):
    await t.lessons.start(t.workspace.id, t.concepts[0].id, LessonRequest(idempotency_key="lesson"))
    return await t.checks.start(
        t.workspace.id, t.concepts[0].id, CheckStartRequest(idempotency_key="check")
    )


@pytest.mark.asyncio
async def test_failed_check_returns_to_same_concept(learning_tutor):
    t = learning_tutor
    question = await start(t)
    assert "answer_key" not in question.model_dump_json()
    result = await t.checks.submit(
        t.workspace.id,
        question.assessment_id,
        CheckAnswerRequest(response="product", idempotency_key="answer"),
    )
    assert result.correct is False and result.next_action == "review_concept"
    assert result.active_concept_id == t.concepts[0].id
    assert t.concepts[0].status == "needs_review" and t.state.active_mode == "LEARN"
    assert result.explanation_blocks and result.citations


@pytest.mark.asyncio
async def test_correct_advances_once_and_duplicate_is_replayed(learning_tutor):
    t = learning_tutor
    question = await start(t)
    request = CheckAnswerRequest(response="sum", idempotency_key="answer")
    result = await t.checks.submit(t.workspace.id, question.assessment_id, request)
    assert result.correct is True and result.next_action == "next_concept"
    assert result.active_concept_id == t.concepts[1].id
    assert t.concepts[0].status == "completed"
    assert await t.checks.submit(t.workspace.id, question.assessment_id, request) == result
    with pytest.raises(LearningConflictError):
        await t.checks.submit(
            t.workspace.id,
            question.assessment_id,
            request.model_copy(update={"idempotency_key": "other"}),
        )
    assert len(list(t.session.scalars(select(Attempt)))) == 1


@pytest.mark.asyncio
async def test_skip_requires_explicit_continue_and_is_not_incorrect(learning_tutor):
    t = learning_tutor
    question = await start(t)
    result = await t.checks.submit(
        t.workspace.id,
        question.assessment_id,
        CheckAnswerRequest(skip=True, idempotency_key="skip"),
    )
    assert result.correct is None and result.next_action == "confirm_continue"
    assert result.active_concept_id == t.concepts[0].id
    assert t.concepts[0].status == "not_assessed"
    attempt = t.session.scalar(select(Attempt))
    assert attempt.status == "not_assessed" and attempt.result is None and attempt.response is None
    for confirm in (False, 1, "true"):
        with pytest.raises(ValueError):
            CheckContinueRequest(confirm_continue=confirm, idempotency_key="continue")
    request = CheckContinueRequest(confirm_continue=True, idempotency_key="continue")
    next_result = await t.checks.continue_after_skip(
        t.workspace.id, question.assessment_id, request
    )
    assert next_result.active_concept_id == t.concepts[1].id
    assert (
        await t.checks.continue_after_skip(t.workspace.id, question.assessment_id, request)
        == next_result
    )


@pytest.mark.asyncio
async def test_pending_check_reuses_question_and_rejects_unrelated_writes(learning_tutor):
    t = learning_tutor
    question = await start(t)
    assert (
        await t.checks.start(
            t.workspace.id, t.concepts[0].id, CheckStartRequest(idempotency_key="new")
        )
        == question
    )
    assert t.checks.get(t.workspace.id, question.assessment_id) == question
    assert len(t.generation.check_calls) == 1
    with pytest.raises(LearningNotFoundError):
        t.checks.get(uuid4(), question.assessment_id)
    with pytest.raises(LearningConflictError):
        await t.lessons.start(
            t.workspace.id, t.concepts[0].id, LessonRequest(depth="deeper", idempotency_key="depth")
        )


@pytest.mark.asyncio
async def test_wrong_answer_returns_to_the_exact_lesson_depth(learning_tutor):
    t = learning_tutor
    lesson = await t.lessons.start(
        t.workspace.id, t.concepts[0].id, LessonRequest(depth="deeper", idempotency_key="deeper")
    )
    check = await t.checks.start(
        t.workspace.id, t.concepts[0].id, CheckStartRequest(idempotency_key="check")
    )
    await t.checks.submit(
        t.workspace.id,
        check.assessment_id,
        CheckAnswerRequest(response="product", idempotency_key="wrong"),
    )
    assert t.state.return_checkpoint == f"lesson:{lesson.lesson_id}"
    assert t.lessons.get(t.workspace.id, lesson.lesson_id).depth == "deeper"


@pytest.mark.asyncio
async def test_check_requires_a_lesson_and_refuses_unsupported_keys(learning_tutor):
    from grounded_tutor.domain.models import Assessment
    from grounded_tutor.domain.teaching import GeneratedCheck

    t = learning_tutor
    with pytest.raises(LearningConflictError):
        await t.checks.start(
            t.workspace.id, t.concepts[0].id, CheckStartRequest(idempotency_key="early")
        )
    await t.lessons.start(t.workspace.id, t.concepts[0].id, LessonRequest(idempotency_key="lesson"))
    checkpoint = t.state.return_checkpoint
    bad = t.check.model_dump()
    bad["question"]["answer_key"] = ["product"]
    t.generation.check_responses = [GeneratedCheck.model_validate(bad)] * 2
    result = await t.checks.start(
        t.workspace.id, t.concepts[0].id, CheckStartRequest(idempotency_key="bad")
    )
    assert result.status == "insufficient_material"
    assert t.state.return_checkpoint == checkpoint
    assert not list(t.session.scalars(select(Assessment)))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response,correct", [("COUNT", True), ("discount", False), ("not count", False)]
)
async def test_structured_short_uses_exact_normalized_alternatives(
    learning_tutor, response, correct
):
    from grounded_tutor.domain.teaching import GeneratedCheck

    t = learning_tutor
    t.concepts[0].check_kind = "structured_short"
    t.session.commit()
    bad = t.check.model_dump()
    bad["question"].update(kind="structured_short", options=[], answer_key=["count"])
    t.generation.check_responses = [GeneratedCheck.model_validate(bad)]
    question = await start(t)
    result = await t.checks.submit(
        t.workspace.id,
        question.assessment_id,
        CheckAnswerRequest(response=response, idempotency_key="answer"),
    )
    assert result.correct is correct


@pytest.mark.asyncio
@pytest.mark.parametrize("lost_ack", [False, True])
async def test_attempt_and_progress_commit_together_and_retry_safely(
    learning_tutor, monkeypatch, lost_ack
):
    from sqlalchemy.exc import SQLAlchemyError

    from grounded_tutor.repositories.chat import ChatPersistenceError

    t = learning_tutor
    question = await start(t)
    request = CheckAnswerRequest(response="sum", idempotency_key="answer")
    commit = t.session.commit
    calls = 0

    def fail_completion():
        nonlocal calls
        calls += 1
        if calls == 2:
            if lost_ack:
                commit()
            raise SQLAlchemyError("private database failure")
        commit()

    monkeypatch.setattr(t.session, "commit", fail_completion)
    with pytest.raises(ChatPersistenceError):
        await t.checks.submit(t.workspace.id, question.assessment_id, request)
    if not lost_ack:
        assert t.state.active_concept_id == t.concepts[0].id
        assert not list(t.session.scalars(select(Attempt)))
    result = await t.checks.submit(t.workspace.id, question.assessment_id, request)
    assert result.active_concept_id == t.concepts[1].id
    assert len(list(t.session.scalars(select(Attempt)))) == 1


@pytest.mark.asyncio
async def test_skip_last_concept_does_not_finish_until_confirmed(learning_tutor):
    t = learning_tutor
    for concept in t.concepts[1:]:
        concept.status = "completed"
    t.session.commit()
    question = await start(t)
    await t.checks.submit(
        t.workspace.id,
        question.assessment_id,
        CheckAnswerRequest(skip=True, idempotency_key="skip"),
    )
    assert t.plan.status == "active" and t.state.active_concept_id == t.concepts[0].id
    result = await t.checks.continue_after_skip(
        t.workspace.id,
        question.assessment_id,
        CheckContinueRequest(confirm_continue=True, idempotency_key="continue"),
    )
    assert result.next_action == "completed" and t.plan.status == "completed"
    assert t.concepts[0].status == "not_assessed"


@pytest.mark.asyncio
async def test_suspended_or_superseded_learning_cannot_be_advanced(learning_tutor):
    t = learning_tutor
    question = await start(t)
    t.state.suspended_activity = {
        "mode": "CHECK",
        "checkpoint": t.state.return_checkpoint,
        "active_concept_id": str(t.concepts[0].id),
    }
    t.state.active_mode = "ASK"
    t.session.commit()
    request = CheckAnswerRequest(response="sum", idempotency_key="answer")
    with pytest.raises(LearningConflictError):
        await t.checks.submit(t.workspace.id, question.assessment_id, request)
    t.state.active_mode = "CHECK"
    t.state.suspended_activity = None
    t.plan.status = "superseded"
    t.session.commit()
    with pytest.raises(LearningConflictError):
        await t.checks.submit(t.workspace.id, question.assessment_id, request)
    assert not list(t.session.scalars(select(Attempt)))


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["delete", "replace"])
async def test_stale_check_evidence_cannot_resume_or_advance_with_new_requests(
    learning_tutor, change
):
    from datetime import UTC, datetime

    t = learning_tutor
    question = await start(t)
    if change == "delete":
        t.source.deleted_at = datetime.now(UTC)
    else:
        t.source.superseded_at = datetime.now(UTC)
    t.session.commit()
    restored = await t.checks.start(
        t.workspace.id, t.concepts[0].id, CheckStartRequest(idempotency_key="restore")
    )
    assert restored.status == "insufficient_material"
    with pytest.raises(LearningConflictError):
        await t.checks.submit(
            t.workspace.id,
            question.assessment_id,
            CheckAnswerRequest(response="sum", idempotency_key="answer"),
        )
    assert t.state.active_concept_id == t.concepts[0].id and t.concepts[0].status == "active"
    assert not list(t.session.scalars(select(Attempt)))
    assert t.checks.get(t.workspace.id, question.assessment_id) == question
    assert (
        await t.checks.start(
            t.workspace.id, t.concepts[0].id, CheckStartRequest(idempotency_key="check")
        )
        == question
    )


@pytest.mark.asyncio
async def test_source_deleted_after_skip_does_not_allow_continuation(learning_tutor):
    from datetime import UTC, datetime

    t = learning_tutor
    question = await start(t)
    await t.checks.submit(
        t.workspace.id,
        question.assessment_id,
        CheckAnswerRequest(skip=True, idempotency_key="skip"),
    )
    t.source.deleted_at = datetime.now(UTC)
    t.session.commit()
    with pytest.raises(LearningConflictError):
        await t.checks.continue_after_skip(
            t.workspace.id,
            question.assessment_id,
            CheckContinueRequest(confirm_continue=True, idempotency_key="continue"),
        )
    assert t.state.active_concept_id == t.concepts[0].id
    assert len(list(t.session.scalars(select(Attempt)))) == 1
