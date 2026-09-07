from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from grounded_tutor.adapters.fakes import FakeFastGPT, FakeGeneration
from grounded_tutor.adapters.fastgpt import RetrievedChunk
from grounded_tutor.config import Settings
from grounded_tutor.db import create_database_engine
from grounded_tutor.domain.diagnostics import (
    DiagnosticAnswerRequest,
    DiagnosticStartRequest,
    GeneratedDiagnostic,
    GeneratedDiagnosticQuestion,
)
from grounded_tutor.domain.models import (
    ActivityState,
    Assessment,
    Attempt,
    Base,
    Source,
    SourceStatus,
    SourceType,
    Workspace,
)
from grounded_tutor.services.diagnostics import (
    DiagnosticConflictError,
    DiagnosticNotFoundError,
    DiagnosticService,
)
from grounded_tutor.services.source_locks import WorkspaceLockRegistry


def generated():
    return GeneratedDiagnostic(
        questions=tuple(
            GeneratedDiagnosticQuestion(
                id=f"q-{i}",
                kind="single_choice",
                prompt=f"Which term appears in the definition? ({i})",
                options=("sum", "product"),
                answer_key=("sum",),
                explanation="The mean is sum divided by count.",
                concept_label=f"Concept {i}",
                chunk_ids=("chunk",),
            )
            for i in range(3)
        )
    )


@pytest.fixture
def tutor(tmp_path):
    engine = create_database_engine(
        Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'diagnostic.db'}")
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        workspace = Workspace(title="Statistics", dataset_id="dataset")
        session.add(workspace)
        session.flush()
        session.add(
            Source(
                workspace_id=workspace.id,
                name="Notes",
                source_type=SourceType.TEXT,
                status=SourceStatus.READY,
                collection_id="ready",
                ingestion_config={},
            )
        )
        session.commit()
        fastgpt = FakeFastGPT()
        fastgpt.search_results_override = (
            RetrievedChunk("foreign", "other", "Secret", "private fact", "private fact", 1),
            RetrievedChunk("chunk", "ready", "provider", "Mean", "sum divided by count", 1),
        )
        generation = FakeGeneration()
        generation.diagnostic_responses = [generated()]
        service = DiagnosticService(session, fastgpt, generation, WorkspaceLockRegistry())
        yield session, workspace, service, fastgpt, generation
    engine.dispose()


def start_request(**updates):
    return DiagnosticStartRequest.model_validate(
        {"consent": True, "goal": "Learn statistics", "idempotency_key": "start", **updates}
    )


@pytest.mark.asyncio
async def test_diagnostic_has_bounded_grounded_questions_and_no_public_keys(tutor):
    session, workspace, service, fastgpt, generation = tutor
    result = await service.start(workspace.id, start_request())
    assert result.status == "active" and len(result.questions) == 3
    assert all(q.evidence_refs and q.citations for q in result.questions)
    assert all(c.source_name == "Notes" for q in result.questions for c in q.citations)
    assert "answer_key" not in result.model_dump_json()
    assert not list(session.scalars(select(Attempt)))
    assert session.get(ActivityState, workspace.id).active_mode == "CHECK"
    assert await service.start(workspace.id, start_request()) == result
    assert len(fastgpt.search_calls) == len(generation.diagnostic_calls) == 1


@pytest.mark.asyncio
async def test_skip_is_not_assessed_answers_are_idempotent_and_summary_has_no_percentage(tutor):
    session, workspace, service, _, _ = tutor
    diagnostic = await service.start(workspace.id, start_request())
    first = DiagnosticAnswerRequest(
        question_id=diagnostic.questions[0].question_id, skip=True, idempotency_key="skip"
    )
    skipped = await service.answer(workspace.id, diagnostic.diagnostic_id, first)
    assert skipped.result == "not_assessed" and not skipped.feedback_blocks
    assert await service.answer(workspace.id, diagnostic.diagnostic_id, first) == skipped
    for i, response in [(1, "sum"), (2, "product")]:
        result = await service.answer(
            workspace.id,
            diagnostic.diagnostic_id,
            DiagnosticAnswerRequest(
                question_id=diagnostic.questions[i].question_id,
                response=response,
                idempotency_key=f"answer-{i}",
            ),
        )
        assert result.result == ("understood" if i == 1 else "needs_review")
        assert result.feedback_blocks and result.citations
    summary = service.summary(workspace.id, diagnostic.diagnostic_id)
    assert summary.status == "completed"
    assert [c.result for c in summary.concepts] == ["not_assessed", "understood", "needs_review"]
    assert "percentage" not in summary.model_dump_json()
    assert len(list(session.scalars(select(Attempt)))) == 3
    assert session.get(ActivityState, workspace.id).active_mode == "ASK"


@pytest.mark.asyncio
async def test_foreign_and_out_of_order_answers_do_not_write(tutor):
    session, workspace, service, _, _ = tutor
    diagnostic = await service.start(workspace.id, start_request())
    answer = DiagnosticAnswerRequest(
        question_id=diagnostic.questions[1].question_id, response="sum", idempotency_key="bad"
    )
    with pytest.raises(DiagnosticConflictError):
        await service.answer(workspace.id, diagnostic.diagnostic_id, answer)
    with pytest.raises(DiagnosticNotFoundError):
        service.get(uuid4(), diagnostic.diagnostic_id)
    assert not list(session.scalars(select(Attempt)))


@pytest.mark.asyncio
async def test_invalid_generation_retries_once_then_refuses_without_progress(tutor):
    session, workspace, service, _, generation = tutor
    generation.diagnostic_responses = [
        generated().model_copy(update={"questions": ()}),
        generated().model_copy(update={"questions": ()}),
    ]
    result = await service.start(workspace.id, start_request())
    assert result.status == "insufficient_material"
    assert not result.questions and result.diagnostic_id is None
    assert len(generation.diagnostic_calls) == 2
    assert not list(session.scalars(select(Assessment)))
    assert session.get(ActivityState, workspace.id) is None


def test_explicit_consent_and_one_answer_shape_are_required():
    for consent in (False, 1, "true"):
        with pytest.raises(ValueError):
            start_request(consent=consent)
    with pytest.raises(ValueError):
        DiagnosticAnswerRequest(question_id=uuid4(), skip=True, response="sum", idempotency_key="x")


@pytest.mark.asyncio
async def test_source_change_during_generation_refuses_stale_evidence(tutor):
    session, workspace, service, _, generation = tutor
    original = generation.generate_diagnostic

    async def change(*args):
        result = await original(*args)
        source = session.scalar(select(Source))
        source.deleted_at = datetime.now(UTC)
        session.commit()
        return result

    generation.generate_diagnostic = change
    result = await service.start(workspace.id, start_request())
    assert result.status == "insufficient_material"
    assert not list(session.scalars(select(Assessment)))


@pytest.mark.asyncio
async def test_provider_failure_releases_request_and_retry_succeeds(tutor):
    from grounded_tutor.adapters.fastgpt import ExternalServiceError
    from grounded_tutor.domain.models import RequestRecord

    session, workspace, service, _, generation = tutor
    generation.diagnostic_responses = [
        ExternalServiceError(service="generation", category="timeout", safe_message="Failed"),
        generated(),
    ]
    with pytest.raises(ExternalServiceError):
        await service.start(workspace.id, start_request())
    assert not list(session.scalars(select(RequestRecord)))
    assert (await service.start(workspace.id, start_request())).status == "active"


@pytest.mark.asyncio
async def test_invitation_is_one_diagnostic_even_with_new_request_keys(tutor):
    from grounded_tutor.domain.models import Diagnostic

    session, workspace, service, _, generation = tutor
    invitation_id = uuid4()
    session.add(
        ActivityState(
            workspace_id=workspace.id,
            diagnostic_invitation={"id": str(invitation_id), "status": "offered"},
        )
    )
    session.commit()
    first = await service.start(workspace.id, start_request(invitation_id=invitation_id))
    second = await service.start(
        workspace.id, start_request(invitation_id=invitation_id, idempotency_key="new-key")
    )
    assert first == second
    assert len(list(session.scalars(select(Diagnostic)))) == len(generation.diagnostic_calls) == 1
    assert session.get(ActivityState, workspace.id).diagnostic_invitation["status"] == "accepted"


@pytest.mark.asyncio
async def test_unresolved_or_unsupported_keys_cannot_create_assessments(tutor):
    session, workspace, service, _, generation = tutor
    bad = generated().model_dump()
    bad["questions"][0]["chunk_ids"] = ("foreign",)
    other = generated().model_dump()
    other["questions"][0]["answer_key"] = ("product",)
    generation.diagnostic_responses = [
        GeneratedDiagnostic.model_validate(bad),
        GeneratedDiagnostic.model_validate(other),
    ]
    assert (await service.start(workspace.id, start_request())).status == "insufficient_material"
    assert not list(session.scalars(select(Assessment)))


@pytest.mark.asyncio
async def test_exact_short_answers_do_not_match_substrings_or_negations(tutor):
    _session, workspace, service, _, generation = tutor
    data = generated().model_dump()
    for question in data["questions"]:
        question.update(kind="structured_short", options=(), answer_key=("count",))
    generation.diagnostic_responses = [GeneratedDiagnostic.model_validate(data)]
    diagnostic = await service.start(workspace.id, start_request())
    for index, response in enumerate(("COUNT", "discount", "not count")):
        result = await service.answer(
            workspace.id,
            diagnostic.diagnostic_id,
            DiagnosticAnswerRequest(
                question_id=diagnostic.questions[index].question_id,
                response=response,
                idempotency_key=str(index),
            ),
        )
        assert result.result == ("understood" if index == 0 else "needs_review")


@pytest.mark.asyncio
async def test_answer_commit_failure_does_not_advance_and_can_retry(tutor, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    from grounded_tutor.repositories.chat import ChatPersistenceError

    session, workspace, service, _, _ = tutor
    diagnostic = await service.start(workspace.id, start_request())
    request = DiagnosticAnswerRequest(
        question_id=diagnostic.questions[0].question_id, skip=True, idempotency_key="skip"
    )
    commit = session.commit
    calls = 0

    def fail_completion():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise SQLAlchemyError("private database details")
        commit()

    monkeypatch.setattr(session, "commit", fail_completion)
    with pytest.raises(ChatPersistenceError, match="Chat persistence failed"):
        await service.answer(workspace.id, diagnostic.diagnostic_id, request)
    assert not list(session.scalars(select(Attempt)))
    assert (
        service.get(workspace.id, diagnostic.diagnostic_id).next_question_id == request.question_id
    )
    assert (
        await service.answer(workspace.id, diagnostic.diagnostic_id, request)
    ).result == "not_assessed"


@pytest.mark.asyncio
async def test_omitted_background_preserves_confirmed_profile(tutor):
    from grounded_tutor.domain.models import LearnerProfile

    session, workspace, service, _, _ = tutor
    session.add(
        LearnerProfile(workspace_id=workspace.id, confirmed_fields={"background": "Beginner"})
    )
    session.commit()
    await service.start(workspace.id, start_request())
    assert session.get(LearnerProfile, workspace.id).confirmed_fields["background"] == "Beginner"


@pytest.mark.asyncio
async def test_single_choice_uses_exact_option_identity(tutor):
    _session, workspace, service, _, generation = tutor
    data = generated().model_dump()
    data["questions"][0]["options"] = ("sum", "SUM")
    generation.diagnostic_responses = [GeneratedDiagnostic.model_validate(data)]
    diagnostic = await service.start(workspace.id, start_request())
    result = await service.answer(
        workspace.id,
        diagnostic.diagnostic_id,
        DiagnosticAnswerRequest(
            question_id=diagnostic.questions[0].question_id, response="SUM", idempotency_key="case"
        ),
    )
    assert result.result == "needs_review"
