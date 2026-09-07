from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from grounded_tutor.adapters.fakes import FakeFastGPT, FakeGeneration
from grounded_tutor.adapters.fastgpt import RetrievedChunk
from grounded_tutor.config import Settings
from grounded_tutor.db import create_database_engine
from grounded_tutor.domain.models import (
    ActivityState,
    Assessment,
    Attempt,
    Base,
    Concept,
    Diagnostic,
    DiagnosticQuestion,
    LearningPlan,
    Source,
    SourceStatus,
    SourceType,
    Workspace,
)
from grounded_tutor.domain.plans import (
    GeneratedLearningPlan,
    GeneratedPlanConcept,
    PlanCreateRequest,
    PlanRebuildRequest,
    PlanSkipRequest,
)
from grounded_tutor.services.plans import PlanConflictError, PlanNotFoundError, PlanService
from grounded_tutor.services.source_locks import WorkspaceLockRegistry


def generated():
    return GeneratedLearningPlan(
        concepts=tuple(
            GeneratedPlanConcept(
                title=f"Concept {i}",
                objective=f"Explain part {i} of the mean",
                chunk_ids=("chunk",),
                check_kind="single_choice",
            )
            for i in range(3)
        )
    )


@pytest.fixture
def tutor(tmp_path):
    engine = create_database_engine(
        Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'plan.db'}")
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        workspace = Workspace(title="Statistics", dataset_id="dataset")
        session.add(workspace)
        session.flush()
        diagnostic = Diagnostic(
            workspace_id=workspace.id, goal="Learn the mean", status="completed"
        )
        session.add(diagnostic)
        session.flush()
        for i in range(3):
            assessment = Assessment(
                workspace_id=workspace.id,
                kind="single_choice",
                prompt="Numerator?",
                options=["sum", "count"],
                answer_key=["sum"],
            )
            session.add(assessment)
            session.flush()
            attempt = Attempt(assessment_id=assessment.id, status="not_assessed")
            session.add(attempt)
            session.flush()
            session.add(
                DiagnosticQuestion(
                    assessment_id=assessment.id,
                    diagnostic_id=diagnostic.id,
                    workspace_id=workspace.id,
                    order=i + 1,
                    concept_label=f"Concept {i}",
                    attempt_id=attempt.id,
                )
            )
        session.add_all(
            [
                ActivityState(workspace_id=workspace.id),
                Source(
                    workspace_id=workspace.id,
                    name="Notes",
                    source_type=SourceType.TEXT,
                    status=SourceStatus.READY,
                    collection_id="ready",
                    ingestion_config={},
                ),
            ]
        )
        session.commit()
        fastgpt = FakeFastGPT()
        fastgpt.search_results_override = (
            RetrievedChunk("foreign", "other", "Private", "Secret", "secret text", 1),
            RetrievedChunk("chunk", "ready", "provider", "Mean", "sum divided by count", 1),
        )
        generation = FakeGeneration()
        generation.plan_responses = [generated()]
        service = PlanService(session, fastgpt, generation, WorkspaceLockRegistry())
        yield session, workspace, diagnostic, service, fastgpt, generation
    engine.dispose()


def request(diagnostic, key="create"):
    return PlanCreateRequest(diagnostic_id=diagnostic.id, idempotency_key=key)


@pytest.mark.asyncio
async def test_three_to_five_grounded_concepts_and_replay_without_regeneration(tutor):
    session, workspace, diagnostic, service, fastgpt, generation = tutor
    plan = await service.create_from_diagnostic(workspace.id, request(diagnostic))
    assert plan.status == "not_started"
    assert [c.order for c in plan.concepts] == [1, 2, 3]
    assert all(
        c.objective and c.check_kind == "single_choice" and c.evidence_refs for c in plan.concepts
    )
    assert all(ref.source_name == "Notes" for c in plan.concepts for ref in c.evidence_refs)
    assert await service.create_from_diagnostic(workspace.id, request(diagnostic)) == plan
    assert (
        await service.create_from_diagnostic(workspace.id, request(diagnostic, "new-key")) == plan
    )
    assert len(fastgpt.search_calls) == len(generation.plan_calls) == 1
    goal, summary, chunks = generation.plan_calls[0]
    assert goal == diagnostic.goal
    assert summary == {f"Concept {i}": "not_assessed" for i in range(3)}
    assert [c.chunk_id for c in chunks] == ["chunk"]
    assert session.get(ActivityState, workspace.id).active_mode == "PLAN"
    assert service.get(workspace.id, plan.plan_id) == plan


@pytest.mark.asyncio
async def test_skip_preserves_completed_concepts_and_replays(tutor):
    session, workspace, diagnostic, service, _, _ = tutor
    plan = await service.create_from_diagnostic(workspace.id, request(diagnostic))
    first = session.get(Concept, plan.concepts[0].id)
    first.status = "completed"
    session.commit()
    skip = PlanSkipRequest(idempotency_key="skip")
    result = await service.skip(workspace.id, plan.plan_id, plan.concepts[1].id, skip)
    assert [c.status for c in result.concepts] == ["completed", "not_assessed", "not_started"]
    assert await service.skip(workspace.id, plan.plan_id, plan.concepts[1].id, skip) == result
    assert (
        await service.skip(
            workspace.id, plan.plan_id, first.id, PlanSkipRequest(idempotency_key="completed")
        )
    ).concepts[0].status == "completed"


@pytest.mark.asyncio
async def test_rebuild_requires_confirmation_and_preserves_old_plan_history(tutor):
    session, workspace, diagnostic, service, _, generation = tutor
    old = await service.create_from_diagnostic(workspace.id, request(diagnostic))
    session.get(Concept, old.concepts[0].id).status = "completed"
    session.commit()
    for consent in (False, "true", 1):
        with pytest.raises(ValueError):
            PlanRebuildRequest(
                diagnostic_id=diagnostic.id, confirm_rebuild=consent, idempotency_key="rebuild"
            )
    generation.plan_responses = [generated()]
    rebuild = PlanRebuildRequest(
        diagnostic_id=diagnostic.id, confirm_rebuild=True, idempotency_key="rebuild"
    )
    new = await service.rebuild(workspace.id, old.plan_id, rebuild)
    assert new.plan_id != old.plan_id
    assert service.get(workspace.id, old.plan_id).status == "superseded"
    assert service.get(workspace.id, old.plan_id).concepts[0].status == "completed"
    assert len(service.history(workspace.id).plans) == 2
    assert await service.rebuild(workspace.id, old.plan_id, rebuild) == new
    with pytest.raises(PlanConflictError):
        await service.rebuild(
            workspace.id, old.plan_id, rebuild.model_copy(update={"idempotency_key": "stale"})
        )
    assert len(generation.plan_calls) == 2


@pytest.mark.asyncio
async def test_invalid_evidence_and_count_refuse_rebuild_without_replacing_plan(tutor):
    session, workspace, diagnostic, service, _, generation = tutor
    old = await service.create_from_diagnostic(workspace.id, request(diagnostic))
    bad = generated().model_dump()
    bad["concepts"][0]["chunk_ids"] = ("foreign",)
    generation.plan_responses = [
        GeneratedLearningPlan.model_validate(bad),
        generated().model_copy(update={"concepts": ()}),
    ]
    result = await service.rebuild(
        workspace.id,
        old.plan_id,
        PlanRebuildRequest(
            diagnostic_id=diagnostic.id, confirm_rebuild=True, idempotency_key="bad"
        ),
    )
    assert result.status == "insufficient_material" and result.plan_id is None
    assert service.get(workspace.id, old.plan_id) == old
    assert len(list(session.scalars(select(LearningPlan)))) == 1


@pytest.mark.asyncio
async def test_foreign_or_incomplete_diagnostics_never_call_provider(tutor):
    session, workspace, diagnostic, service, fastgpt, generation = tutor
    with pytest.raises(PlanNotFoundError):
        await service.create_from_diagnostic(uuid4(), request(diagnostic))
    with pytest.raises(PlanNotFoundError):
        await service.create_from_diagnostic(
            workspace.id, PlanCreateRequest(diagnostic_id=uuid4(), idempotency_key="foreign")
        )
    diagnostic.status = "active"
    session.commit()
    with pytest.raises(PlanConflictError):
        await service.create_from_diagnostic(workspace.id, request(diagnostic))
    assert not fastgpt.search_calls and not generation.plan_calls


@pytest.mark.asyncio
async def test_source_change_during_generation_does_not_write_plan(tutor):
    session, workspace, diagnostic, service, _, generation = tutor
    original = generation.generate_plan

    async def change(*args):
        result = await original(*args)
        session.scalar(select(Source)).deleted_at = datetime.now(UTC)
        session.commit()
        return result

    generation.generate_plan = change
    assert (
        await service.create_from_diagnostic(workspace.id, request(diagnostic))
    ).status == "insufficient_material"
    assert not list(session.scalars(select(LearningPlan)))
    assert session.get(ActivityState, workspace.id).active_mode == "ASK"


@pytest.mark.parametrize("count", [0, 2, 6])
def test_generated_plan_rejects_out_of_bounds(count):
    concepts = [
        generated().concepts[0].model_copy(update={"title": f"Concept {i}"}) for i in range(count)
    ]
    with pytest.raises(ValueError):
        GeneratedLearningPlan(concepts=concepts)


@pytest.mark.asyncio
async def test_rebuild_commit_failure_keeps_old_plan_and_releases_claim(tutor, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    from grounded_tutor.repositories.chat import ChatPersistenceError

    session, workspace, diagnostic, service, _, generation = tutor
    old = await service.create_from_diagnostic(workspace.id, request(diagnostic))
    generation.plan_responses = [generated(), generated()]
    rebuild = PlanRebuildRequest(
        diagnostic_id=diagnostic.id, confirm_rebuild=True, idempotency_key="rebuild"
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
    with pytest.raises(ChatPersistenceError):
        await service.rebuild(workspace.id, old.plan_id, rebuild)
    assert service.get(workspace.id, old.plan_id) == old
    assert len(service.history(workspace.id).plans) == 1
    assert (await service.rebuild(workspace.id, old.plan_id, rebuild)).plan_id != old.plan_id


@pytest.mark.asyncio
async def test_lost_commit_ack_replays_without_another_plan(tutor, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    from grounded_tutor.repositories.chat import ChatPersistenceError

    session, workspace, diagnostic, service, _, generation = tutor
    commit = session.commit
    calls = 0

    def lost_ack():
        nonlocal calls
        calls += 1
        commit()
        if calls == 2:
            raise SQLAlchemyError("lost ack")

    monkeypatch.setattr(session, "commit", lost_ack)
    with pytest.raises(ChatPersistenceError):
        await service.create_from_diagnostic(workspace.id, request(diagnostic))
    result = await service.create_from_diagnostic(workspace.id, request(diagnostic))
    assert result.plan_id and len(service.history(workspace.id).plans) == 1
    assert len(generation.plan_calls) == 1


@pytest.mark.asyncio
async def test_concurrent_requests_share_workspace_lock(tutor):
    import asyncio

    from grounded_tutor.services.source_locks import WorkspaceIngestionBusyError

    _, workspace, diagnostic, service, _, generation = tutor
    entered, release = asyncio.Event(), asyncio.Event()
    original = generation.generate_plan

    async def wait(*args):
        entered.set()
        await release.wait()
        return await original(*args)

    generation.generate_plan = wait
    task = asyncio.create_task(service.create_from_diagnostic(workspace.id, request(diagnostic)))
    await entered.wait()
    try:
        with pytest.raises(WorkspaceIngestionBusyError):
            await service.create_from_diagnostic(workspace.id, request(diagnostic, "parallel"))
    finally:
        release.set()
        await task
    assert len(generation.plan_calls) == 1


@pytest.mark.asyncio
async def test_cancellation_releases_claim_and_lock(tutor):
    import asyncio

    from grounded_tutor.domain.models import RequestRecord

    session, workspace, diagnostic, service, _, generation = tutor
    generation.plan_responses = [asyncio.CancelledError(), generated()]
    with pytest.raises(asyncio.CancelledError):
        await service.create_from_diagnostic(workspace.id, request(diagnostic))
    assert not list(session.scalars(select(RequestRecord)))
    assert (await service.create_from_diagnostic(workspace.id, request(diagnostic))).plan_id


@pytest.mark.asyncio
async def test_skip_current_concept_returns_to_plan_and_all_skips_are_not_mastery(tutor):
    session, workspace, diagnostic, service, _, _ = tutor
    plan = await service.create_from_diagnostic(workspace.id, request(diagnostic))
    state = session.get(ActivityState, workspace.id)
    state.active_mode = "LEARN"
    state.active_concept_id = plan.concepts[0].id
    session.get(Concept, plan.concepts[0].id).status = "active"
    session.commit()
    for i, concept in enumerate(plan.concepts):
        result = await service.skip(
            workspace.id, plan.plan_id, concept.id, PlanSkipRequest(idempotency_key=str(i))
        )
        if i == 0:
            assert state.active_mode == "PLAN" and state.active_concept_id is None
    assert result.status == "completed"
    assert all(c.status == "not_assessed" for c in result.concepts)
    assert state.active_mode == "ASK"


@pytest.mark.asyncio
async def test_foreign_concept_and_suspended_learning_cannot_be_modified(tutor):
    session, workspace, diagnostic, service, _, generation = tutor
    plan = await service.create_from_diagnostic(workspace.id, request(diagnostic))
    with pytest.raises(PlanNotFoundError):
        await service.skip(
            workspace.id, plan.plan_id, uuid4(), PlanSkipRequest(idempotency_key="foreign")
        )
    state = session.get(ActivityState, workspace.id)
    state.active_mode = "ASK"
    state.suspended_activity = {"mode": "PLAN", "checkpoint": f"plan:{plan.plan_id}"}
    session.commit()
    with pytest.raises(PlanConflictError):
        await service.rebuild(
            workspace.id,
            plan.plan_id,
            PlanRebuildRequest(
                diagnostic_id=diagnostic.id, confirm_rebuild=True, idempotency_key="suspended"
            ),
        )
    assert len(generation.plan_calls) == 1
    assert state.suspended_activity


def test_plan_history_keeps_creation_order_when_timestamps_tie(tutor):
    from uuid import UUID

    session, workspace, _, service, _, _ = tutor
    for number in (2, 1):
        session.add(
            LearningPlan(
                id=UUID(int=number),
                workspace_id=workspace.id,
                goal=f"Goal {number}",
                status="superseded",
                created_at=datetime(2026, 9, 7, tzinfo=UTC),
            )
        )
        session.commit()
    assert [p.goal for p in service.history(workspace.id).plans] == ["Goal 2", "Goal 1"]
