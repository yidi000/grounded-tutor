from uuid import uuid4

import pytest
from sqlalchemy import select

from grounded_tutor.domain.answers import GeneratedAnswer, GeneratedBlock
from grounded_tutor.domain.diagnostics import (
    DiagnosticAnswerRequest,
    DiagnosticStartRequest,
    GeneratedDiagnostic,
)
from grounded_tutor.domain.models import (
    Attempt,
    Message,
    Workspace,
)
from grounded_tutor.domain.orchestration import ActivityCommand
from grounded_tutor.domain.teaching import CheckAnswerRequest, CheckStartRequest, LessonRequest
from grounded_tutor.repositories.chat import ChatRepository
from grounded_tutor.repositories.sources import SourceRepository
from grounded_tutor.services.chat import ChatService, ExternalChatServiceError
from grounded_tutor.services.diagnostics import DiagnosticService
from grounded_tutor.services.learning_context import LearningConflictError, LearningNotFoundError
from grounded_tutor.services.orchestrator import Orchestrator


def orchestrator(t):
    locks = t.lessons.writes.locks
    chat = ChatService(
        SourceRepository(t.session), ChatRepository(t.session), t.fastgpt, t.generation
    )
    return Orchestrator(t.session, chat, t.fastgpt, t.generation, locks)


def ask_answer(t):
    t.generation.responses = [
        GeneratedAnswer(
            blocks=(
                GeneratedBlock(
                    id="answer", kind="answer", text="sum divided by count", chunk_ids=("chunk",)
                ),
            )
        )
    ] * 4


@pytest.mark.asyncio
async def test_lesson_detour_and_repeated_ask_resume_exact_saved_depth(learning_tutor):
    t = learning_tutor
    lesson = await t.lessons.start(
        t.workspace.id, t.concepts[0].id, LessonRequest(depth="deeper", idempotency_key="lesson")
    )
    before = t.state.return_checkpoint
    service = orchestrator(t)
    ask_answer(t)
    result = await service.handle_message(t.workspace.id, "Why?", None, "ask")
    assert result.suggested_actions[0].type == "resume_activity"
    assert result.suggested_actions[0].checkpoint == before
    assert t.state.active_mode == "ASK" and t.state.suspended_activity["checkpoint"] == before
    await service.handle_message(t.workspace.id, "Another question?", None, "ask-2")
    assert t.state.suspended_activity["checkpoint"] == before
    calls = len(t.generation.calls), len(t.fastgpt.search_calls)
    current = service.view(t.workspace.id)
    assert current.lesson == lesson and current.snapshot.active_mode == "ASK"
    resumed = await service.resume(
        t.workspace.id, ActivityCommand(checkpoint=before, idempotency_key="resume")
    )
    assert resumed.snapshot.active_mode == "LEARN" and resumed.lesson == lesson
    assert t.state.suspended_activity is None
    assert (len(t.generation.calls), len(t.fastgpt.search_calls)) == calls
    assert not list(t.session.scalars(select(Attempt)))


@pytest.mark.asyncio
async def test_immediate_check_and_skip_confirmation_resume_without_regeneration(learning_tutor):
    t = learning_tutor
    await t.lessons.start(t.workspace.id, t.concepts[0].id, LessonRequest(idempotency_key="lesson"))
    check = await t.checks.start(
        t.workspace.id, t.concepts[0].id, CheckStartRequest(idempotency_key="check")
    )
    service = orchestrator(t)
    for skipped in (False, True):
        if skipped:
            await t.checks.submit(
                t.workspace.id,
                check.assessment_id,
                CheckAnswerRequest(skip=True, idempotency_key="skip"),
            )
        before = t.state.return_checkpoint
        ask_answer(t)
        await service.handle_message(t.workspace.id, "Explain?", None, f"ask-{skipped}")
        result = await service.resume(
            t.workspace.id, ActivityCommand(checkpoint=before, idempotency_key=f"resume-{skipped}")
        )
        assert result.check == check
        assert result.kind == ("check_skip" if skipped else "check")
        assert t.state.active_concept_id == t.concepts[0].id
    assert len(t.generation.check_calls) == 1
    assert t.concepts[0].status == "not_assessed"
    assert len(list(t.session.scalars(select(Attempt)))) == 1


@pytest.mark.asyncio
async def test_diagnostic_question_two_resumes_exactly(learning_tutor):
    t = learning_tutor
    t.state.active_mode = "ASK"
    t.state.return_checkpoint = None
    t.session.commit()
    t.generation.diagnostic_responses = [
        GeneratedDiagnostic(
            questions=tuple(t.check.question.model_copy(update={"id": str(i)}) for i in range(3))
        )
    ]
    diagnostics = DiagnosticService(t.session, t.fastgpt, t.generation, t.lessons.writes.locks)
    diagnostic = await diagnostics.start(
        t.workspace.id, DiagnosticStartRequest(consent=True, goal="Learn", idempotency_key="diag")
    )
    await diagnostics.answer(
        t.workspace.id,
        diagnostic.diagnostic_id,
        DiagnosticAnswerRequest(
            question_id=diagnostic.questions[0].question_id, skip=True, idempotency_key="skip"
        ),
    )
    checkpoint = t.state.return_checkpoint
    service = orchestrator(t)
    ask_answer(t)
    result = await service.handle_message(t.workspace.id, "Why?", None, "ask")
    assert result.suggested_actions[0].label == "继续第 2 题"
    resumed = await service.resume(
        t.workspace.id, ActivityCommand(checkpoint=checkpoint, idempotency_key="resume")
    )
    assert resumed.diagnostic.next_question_id == diagnostic.questions[1].question_id
    assert resumed.kind == "diagnostic" and resumed.snapshot.active_mode == "CHECK"
    assert len(t.generation.diagnostic_calls) == 1
    assert len(list(t.session.scalars(select(Attempt)))) == 1


@pytest.mark.asyncio
async def test_failed_ask_keeps_active_checkpoint_and_no_messages(learning_tutor):
    t = learning_tutor
    await t.lessons.start(t.workspace.id, t.concepts[0].id, LessonRequest(idempotency_key="lesson"))
    checkpoint = t.state.return_checkpoint
    service = orchestrator(t)
    t.generation.responses = [RuntimeError("provider failure")]
    with pytest.raises(ExternalChatServiceError):
        await service.handle_message(t.workspace.id, "Why?", None, "ask")
    assert t.state.active_mode == "LEARN" and t.state.return_checkpoint == checkpoint
    assert t.state.suspended_activity is None
    assert not list(t.session.scalars(select(Message)))


@pytest.mark.asyncio
async def test_pause_read_reload_and_workspace_isolation(learning_tutor):
    t = learning_tutor
    lesson = await t.lessons.start(
        t.workspace.id, t.concepts[0].id, LessonRequest(idempotency_key="lesson")
    )
    service = orchestrator(t)
    checkpoint = t.state.return_checkpoint
    command = ActivityCommand(checkpoint=checkpoint, idempotency_key="pause")
    paused = await service.pause(t.workspace.id, command)
    assert paused.snapshot.active_mode == "ASK" and paused.lesson == lesson
    assert await service.pause(t.workspace.id, command) == paused
    other = Workspace(title="Other", dataset_id="other")
    t.session.add(other)
    t.session.commit()
    assert service.view(other.id).kind == "idle"
    t.session.expire_all()
    assert service.view(t.workspace.id) == paused
    with pytest.raises(LearningNotFoundError):
        service.view(uuid4())
    with pytest.raises(LearningConflictError):
        await service.resume(
            other.id, ActivityCommand(checkpoint=checkpoint, idempotency_key="foreign")
        )
    assert t.state.suspended_activity


@pytest.mark.asyncio
async def test_old_ask_replay_does_not_suspend_resumed_activity(learning_tutor):
    t = learning_tutor
    await t.lessons.start(t.workspace.id, t.concepts[0].id, LessonRequest(idempotency_key="lesson"))
    checkpoint = t.state.return_checkpoint
    service = orchestrator(t)
    ask_answer(t)
    await service.handle_message(t.workspace.id, "Why?", None, "ask")
    await service.resume(
        t.workspace.id, ActivityCommand(checkpoint=checkpoint, idempotency_key="resume")
    )
    replay = await service.handle_message(t.workspace.id, "Why?", None, "ask")
    assert not replay.suggested_actions
    assert t.state.active_mode == "LEARN" and t.state.suspended_activity is None


@pytest.mark.asyncio
@pytest.mark.parametrize("lost_ack", [False, True])
async def test_ask_and_suspension_commit_together_and_retry_once(
    learning_tutor, monkeypatch, lost_ack
):
    from sqlalchemy.exc import SQLAlchemyError

    from grounded_tutor.repositories.chat import ChatPersistenceError

    t = learning_tutor
    await t.lessons.start(t.workspace.id, t.concepts[0].id, LessonRequest(idempotency_key="lesson"))
    checkpoint = t.state.return_checkpoint
    service = orchestrator(t)
    ask_answer(t)
    commit = t.session.commit
    calls = 0

    def fail():
        nonlocal calls
        calls += 1
        if calls == 2:
            if lost_ack:
                commit()
            raise SQLAlchemyError("commit acknowledgement failure")
        commit()

    monkeypatch.setattr(t.session, "commit", fail)
    with pytest.raises(ChatPersistenceError):
        await service.handle_message(t.workspace.id, "Why?", None, "ask")
    if not lost_ack:
        assert t.state.active_mode == "LEARN" and t.state.return_checkpoint == checkpoint
        assert not list(t.session.scalars(select(Message)))
    result = await service.handle_message(t.workspace.id, "Why?", None, "ask")
    assert result.suggested_actions[0].checkpoint == checkpoint
    assert len(list(t.session.scalars(select(Message)))) == 2
    assert t.state.active_mode == "ASK"


@pytest.mark.asyncio
async def test_cancelled_ask_releases_lock_and_leaves_learning_untouched(learning_tutor):
    import asyncio

    t = learning_tutor
    await t.lessons.start(t.workspace.id, t.concepts[0].id, LessonRequest(idempotency_key="lesson"))
    service = orchestrator(t)
    t.generation.responses = [asyncio.CancelledError()]
    with pytest.raises(asyncio.CancelledError):
        await service.handle_message(t.workspace.id, "Why?", None, "ask")
    assert t.state.active_mode == "LEARN" and t.state.suspended_activity is None
    ask_answer(t)
    assert (await service.handle_message(t.workspace.id, "Why?", None, "ask")).suggested_actions


@pytest.mark.asyncio
async def test_inflight_ask_prevents_check_and_pause_races(learning_tutor):
    import asyncio

    from grounded_tutor.services.source_locks import WorkspaceIngestionBusyError

    t = learning_tutor
    await t.lessons.start(t.workspace.id, t.concepts[0].id, LessonRequest(idempotency_key="lesson"))
    service = orchestrator(t)
    ask_answer(t)
    original = t.generation.generate_content
    entered, release = asyncio.Event(), asyncio.Event()

    async def wait(request):
        entered.set()
        await release.wait()
        return await original(request)

    t.generation.generate_content = wait
    task = asyncio.create_task(service.handle_message(t.workspace.id, "Why?", None, "ask"))
    await entered.wait()
    try:
        with pytest.raises(WorkspaceIngestionBusyError):
            await t.checks.start(
                t.workspace.id, t.concepts[0].id, CheckStartRequest(idempotency_key="check")
            )
        with pytest.raises(WorkspaceIngestionBusyError):
            await service.pause(
                t.workspace.id,
                ActivityCommand(checkpoint=t.state.return_checkpoint, idempotency_key="pause"),
            )
    finally:
        release.set()
        await task
    assert not t.generation.check_calls


@pytest.mark.asyncio
async def test_stale_command_and_removed_evidence_do_not_restore_activity(learning_tutor):
    from datetime import UTC, datetime

    t = learning_tutor
    await t.lessons.start(t.workspace.id, t.concepts[0].id, LessonRequest(idempotency_key="lesson"))
    service = orchestrator(t)
    checkpoint = t.state.return_checkpoint
    await service.pause(
        t.workspace.id, ActivityCommand(checkpoint=checkpoint, idempotency_key="pause")
    )
    with pytest.raises(LearningConflictError):
        await service.resume(
            t.workspace.id,
            ActivityCommand(checkpoint="lesson:" + str(uuid4()), idempotency_key="stale"),
        )
    t.source.deleted_at = datetime.now(UTC)
    t.session.commit()
    with pytest.raises(LearningConflictError):
        await service.resume(
            t.workspace.id, ActivityCommand(checkpoint=checkpoint, idempotency_key="removed")
        )
    assert t.state.active_mode == "ASK" and t.state.suspended_activity["checkpoint"] == checkpoint
    assert service.view(t.workspace.id).lesson


@pytest.mark.asyncio
async def test_plan_and_ready_concept_restore_without_generating_content(learning_tutor):
    from grounded_tutor.domain.answers import ChunkLocator, Citation

    t = learning_tutor
    for concept in t.concepts:
        concept.evidence_refs = [
            Citation(
                id="citation-1",
                source_id=t.source.id,
                source_name="Notes",
                source_version=1,
                chunk_id="chunk",
                excerpt="sum divided by count",
                locator=ChunkLocator(label="Fragment"),
            ).model_dump(mode="json")
        ]
    t.session.commit()
    service = orchestrator(t)
    checkpoint = t.state.return_checkpoint
    await service.pause(
        t.workspace.id, ActivityCommand(checkpoint=checkpoint, idempotency_key="pause")
    )
    restored = await service.resume(
        t.workspace.id, ActivityCommand(checkpoint=checkpoint, idempotency_key="resume")
    )
    assert restored.kind == "plan" and len(restored.plan.concepts) == 3
    assert not t.generation.calls
    await t.lessons.start(t.workspace.id, t.concepts[0].id, LessonRequest(idempotency_key="lesson"))
    check = await t.checks.start(
        t.workspace.id, t.concepts[0].id, CheckStartRequest(idempotency_key="check")
    )
    await t.checks.submit(
        t.workspace.id,
        check.assessment_id,
        CheckAnswerRequest(response="sum", idempotency_key="pass"),
    )
    checkpoint = t.state.return_checkpoint
    await service.pause(
        t.workspace.id, ActivityCommand(checkpoint=checkpoint, idempotency_key="pause-ready")
    )
    restored = await service.resume(
        t.workspace.id, ActivityCommand(checkpoint=checkpoint, idempotency_key="resume-ready")
    )
    assert restored.kind == "concept" and restored.concept.id == t.concepts[1].id
    assert restored.lesson is None and len(t.generation.calls) == 1


@pytest.mark.asyncio
async def test_resume_commit_failure_keeps_original_pause(learning_tutor, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    from grounded_tutor.repositories.chat import ChatPersistenceError

    t = learning_tutor
    await t.lessons.start(t.workspace.id, t.concepts[0].id, LessonRequest(idempotency_key="lesson"))
    service = orchestrator(t)
    checkpoint = t.state.return_checkpoint
    await service.pause(
        t.workspace.id, ActivityCommand(checkpoint=checkpoint, idempotency_key="pause")
    )
    commit = t.session.commit
    calls = 0

    def fail():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise SQLAlchemyError("failed")
        commit()

    monkeypatch.setattr(t.session, "commit", fail)
    request = ActivityCommand(checkpoint=checkpoint, idempotency_key="resume")
    with pytest.raises(ChatPersistenceError):
        await service.resume(t.workspace.id, request)
    assert t.state.active_mode == "ASK" and t.state.suspended_activity["checkpoint"] == checkpoint
    assert (await service.resume(t.workspace.id, request)).snapshot.active_mode == "LEARN"
