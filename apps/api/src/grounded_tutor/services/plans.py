"""Finite plans; explicit rebuilds preserve the previous learning history."""

from uuid import UUID

from sqlalchemy import literal_column, select
from sqlalchemy.orm import Session

from grounded_tutor.adapters.fastgpt import FastGPTPort, SearchRequest
from grounded_tutor.adapters.generation import GenerationPort, InvalidGenerationOutput
from grounded_tutor.domain.answers import GeneratedAnswer, GeneratedBlock
from grounded_tutor.domain.models import (
    ActivityState,
    Concept,
    Diagnostic,
    DiagnosticQuestion,
    LearningPlan,
    PlanOrigin,
    Workspace,
)
from grounded_tutor.domain.plans import (
    GeneratedLearningPlan,
    PlanConceptView,
    PlanCreateRequest,
    PlanHistory,
    PlanRebuildRequest,
    PlanSkipRequest,
    PlanView,
)
from grounded_tutor.repositories.sources import SourceRepository
from grounded_tutor.services.diagnostics import DiagnosticService
from grounded_tutor.services.grounding import ReadyChunk, ground_generated_answer
from grounded_tutor.services.learning_requests import LearningRequests
from grounded_tutor.services.source_locks import WorkspaceLockRegistry


class PlanNotFoundError(RuntimeError):
    pass


class PlanConflictError(RuntimeError):
    pass


class PlanService:
    def __init__(
        self,
        session: Session,
        fastgpt: FastGPTPort,
        generation: GenerationPort,
        locks: WorkspaceLockRegistry,
    ):
        self.session = session
        self.fastgpt = fastgpt
        self.generation = generation
        self.sources = SourceRepository(session)
        self.diagnostics = DiagnosticService(session, fastgpt, generation, locks)
        self.writes = LearningRequests(session, locks, "plan", PlanNotFoundError)

    def _record(self, workspace_id: UUID, plan_id: UUID) -> LearningPlan:
        plan = self.session.get(LearningPlan, plan_id)
        if plan is None or plan.workspace_id != workspace_id:
            raise PlanNotFoundError()
        return plan

    def _current(self, workspace_id: UUID) -> LearningPlan | None:
        plans = list(
            self.session.scalars(
                select(LearningPlan).where(
                    LearningPlan.workspace_id == workspace_id, LearningPlan.status != "superseded"
                )
            )
        )
        if len(plans) > 1:
            raise PlanConflictError()
        return plans[0] if plans else None

    def _concepts(self, plan_id: UUID) -> list[Concept]:
        return list(
            self.session.scalars(
                select(Concept).where(Concept.plan_id == plan_id).order_by(Concept.order)
            )
        )

    def _diagnostic(self, workspace_id: UUID, diagnostic_id: UUID) -> Diagnostic:
        diagnostic = self.session.get(Diagnostic, diagnostic_id)
        if diagnostic is None or diagnostic.workspace_id != workspace_id:
            raise PlanNotFoundError()
        questions = list(
            self.session.scalars(
                select(DiagnosticQuestion).where(DiagnosticQuestion.diagnostic_id == diagnostic_id)
            )
        )
        if (
            diagnostic.status != "completed"
            or not 3 <= len(questions) <= 5
            or any(q.attempt_id is None for q in questions)
        ):
            raise PlanConflictError()
        return diagnostic

    def _allow_change(self, workspace_id: UUID, plan: LearningPlan | None) -> None:
        state = self.session.get(ActivityState, workspace_id)
        if state is None:
            return
        if state.suspended_activity:
            raise PlanConflictError()
        if state.active_mode == "ASK":
            return
        if plan is not None:
            if state.active_mode == "PLAN" and state.return_checkpoint == f"plan:{plan.id}":
                return
            if state.active_mode in {"LEARN", "CHECK"} and state.active_concept_id in {
                c.id for c in self._concepts(plan.id)
            }:
                return
        raise PlanConflictError()

    def get(self, workspace_id: UUID, plan_id: UUID) -> PlanView:
        plan = self._record(workspace_id, plan_id)
        origin = self.session.get(PlanOrigin, plan.id)
        return PlanView(
            plan_id=plan.id,
            diagnostic_id=origin.diagnostic_id if origin else None,
            goal=plan.goal,
            status=plan.status,
            concepts=tuple(
                PlanConceptView(
                    id=c.id,
                    title=c.title,
                    objective=c.objective,
                    order=c.order,
                    status=c.status,
                    check_kind=c.check_kind,
                    evidence_refs=c.evidence_refs,
                )
                for c in self._concepts(plan.id)
            ),
        )

    def history(self, workspace_id: UUID) -> PlanHistory:
        if self.session.get(Workspace, workspace_id) is None:
            raise PlanNotFoundError()
        # ponytail: SQLite rowid preserves creation order when timestamps tie, as in chat history.
        ids = list(
            self.session.scalars(
                select(LearningPlan.id)
                .where(LearningPlan.workspace_id == workspace_id)
                .order_by(literal_column("learning_plans.rowid"))
            )
        )
        return PlanHistory(plans=tuple(self.get(workspace_id, plan_id) for plan_id in ids))

    async def create_from_diagnostic(
        self, workspace_id: UUID, request: PlanCreateRequest
    ) -> PlanView:
        async def create():
            self._diagnostic(workspace_id, request.diagnostic_id)
            current = self._current(workspace_id)
            if current is not None:
                origin = self.session.get(PlanOrigin, current.id)
                if origin and origin.diagnostic_id == request.diagnostic_id:
                    return self.get(workspace_id, current.id)
                raise PlanConflictError()
            return await self._generate(workspace_id, request.diagnostic_id, None)

        return await self.writes.run(workspace_id, "create:", request, PlanView, create)

    async def rebuild(
        self, workspace_id: UUID, plan_id: UUID, request: PlanRebuildRequest
    ) -> PlanView:
        async def regenerate():
            old = self._record(workspace_id, plan_id)
            if old.status == "superseded" or self._current(workspace_id).id != plan_id:
                raise PlanConflictError()
            return await self._generate(workspace_id, request.diagnostic_id, plan_id)

        return await self.writes.run(
            workspace_id, f"rebuild:{plan_id}:", request, PlanView, regenerate
        )

    async def _generate(
        self, workspace_id: UUID, diagnostic_id: UUID, old_id: UUID | None
    ) -> PlanView:
        diagnostic = self._diagnostic(workspace_id, diagnostic_id)
        old = self._record(workspace_id, old_id) if old_id else None
        self._allow_change(workspace_id, old)
        goal = diagnostic.goal  # The goal explicitly confirmed for this diagnostic.
        summary = {
            c.concept_label: c.result
            for c in self.diagnostics.summary(workspace_id, diagnostic_id).concepts
        }
        sources = self.sources.ready_collection_ids(workspace_id)
        if not sources:
            return PlanView(status="insufficient_material")
        dataset = self.session.get(Workspace, workspace_id).dataset_id
        self.session.rollback()  # Never hold a SQLite transaction during model calls.
        retrieved = await self.fastgpt.search(SearchRequest(dataset, goal))
        ready = {}
        for position, chunk in enumerate(retrieved, 1):
            if chunk.collection_id in sources and chunk.chunk_id not in ready:
                ready[chunk.chunk_id] = ReadyChunk(chunk, sources[chunk.collection_id], position)
        if not ready:
            return PlanView(status="insufficient_material")
        generated = None
        evidence = []
        for _ in range(2):
            try:
                candidate = await self.generation.generate_plan(
                    goal, summary, tuple(r.chunk for r in ready.values())
                )
                candidate = GeneratedLearningPlan.model_validate(candidate.model_dump())
                evidence = []
                for i, concept in enumerate(candidate.concepts, 1):
                    answer = ground_generated_answer(
                        GeneratedAnswer(
                            blocks=(
                                GeneratedBlock(
                                    id=str(i),
                                    kind="explanation",
                                    text=concept.objective,
                                    chunk_ids=concept.chunk_ids,
                                ),
                            )
                        ),
                        ready,
                        allowed_kinds={"explanation"},
                    )
                    if answer.status != "ok":
                        raise ValueError("Unresolved plan evidence")
                    evidence.append([c.model_dump(mode="json") for c in answer.citations])
                generated = candidate
                break
            except (InvalidGenerationOutput, ValueError):
                continue
        if generated is None:
            return PlanView(status="insufficient_material")
        self.session.expire_all()
        current_sources = self.sources.ready_collection_ids(workspace_id)
        if any(current_sources.get(r.chunk.collection_id) != r.source for r in ready.values()):
            return PlanView(status="insufficient_material")
        if self._diagnostic(workspace_id, diagnostic_id).goal != goal:
            raise PlanConflictError()
        current = self._current(workspace_id)
        if (current.id if current else None) != old_id:
            raise PlanConflictError()
        self._allow_change(workspace_id, current)
        plan = LearningPlan(workspace_id=workspace_id, goal=goal)
        self.session.add(plan)
        self.session.flush()
        self.session.add(
            PlanOrigin(plan_id=plan.id, workspace_id=workspace_id, diagnostic_id=diagnostic_id)
        )
        for order, (concept, refs) in enumerate(zip(generated.concepts, evidence), 1):
            self.session.add(
                Concept(
                    plan_id=plan.id,
                    workspace_id=workspace_id,
                    order=order,
                    title=concept.title,
                    objective=concept.objective,
                    check_kind=concept.check_kind,
                    evidence_refs=refs,
                )
            )
        if current is not None:
            current.status = "superseded"
        state = self.session.get(ActivityState, workspace_id)
        if state is None:
            state = ActivityState(workspace_id=workspace_id)
            self.session.add(state)
        state.active_mode = "PLAN"
        state.active_concept_id = None
        state.return_checkpoint = f"plan:{plan.id}"
        self.session.flush()
        return self.get(workspace_id, plan.id)

    async def skip(
        self, workspace_id: UUID, plan_id: UUID, concept_id: UUID, request: PlanSkipRequest
    ) -> PlanView:
        async def skip_concept():
            plan = self._record(workspace_id, plan_id)
            if plan.status == "superseded":
                raise PlanConflictError()
            concepts = self._concepts(plan_id)
            concept = next((c for c in concepts if c.id == concept_id), None)
            if concept is None:
                raise PlanNotFoundError()
            if concept.status in {"completed", "not_assessed"}:
                return self.get(workspace_id, plan_id)
            self._allow_change(workspace_id, plan)
            concept.status = "not_assessed"
            state = self.session.get(ActivityState, workspace_id)
            if all(c.status in {"completed", "not_assessed"} for c in concepts):
                plan.status = "completed"
                if state:
                    state.active_mode = "ASK"
                    state.active_concept_id = None
                    state.return_checkpoint = f"plan:{plan_id}:completed"
            elif state and state.active_concept_id == concept_id:
                # Return to the existing plan; Task 5 owns lesson/check activation.
                state.active_mode = "PLAN"
                state.active_concept_id = None
                state.return_checkpoint = f"plan:{plan_id}"
            self.session.flush()
            return self.get(workspace_id, plan_id)

        return await self.writes.run(
            workspace_id, f"skip:{plan_id}:{concept_id}:", request, PlanView, skip_concept
        )
