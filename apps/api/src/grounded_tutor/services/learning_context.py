"""Shared concept ownership, activity guards, and plan-scoped READY evidence."""

from sqlalchemy import select

from grounded_tutor.adapters.fastgpt import SearchRequest
from grounded_tutor.domain.models import ActivityState, Concept, LearningPlan, Workspace
from grounded_tutor.repositories.sources import SourceRepository
from grounded_tutor.services.grounding import ReadyChunk


class LearningNotFoundError(RuntimeError):
    pass


class LearningConflictError(RuntimeError):
    pass


class LearningContext:
    def __init__(self, session, fastgpt):
        self.session = session
        self.fastgpt = fastgpt
        self.sources = SourceRepository(session)

    def concept(self, workspace_id, concept_id):
        concept = self.session.get(Concept, concept_id)
        if concept is None or concept.workspace_id != workspace_id:
            raise LearningNotFoundError()
        return concept

    def concepts(self, plan_id):
        return list(
            self.session.scalars(
                select(Concept).where(Concept.plan_id == plan_id).order_by(Concept.order)
            )
        )

    def require(self, workspace_id, concept_id, modes, *, from_plan=False, skipped=False):
        concept = self.concept(workspace_id, concept_id)
        plan = self.session.get(LearningPlan, concept.plan_id)
        state = self.session.get(ActivityState, workspace_id)
        if plan.status in {"completed", "superseded"} or not state or state.suspended_activity:
            raise LearningConflictError()
        if concept.status == "completed" or (concept.status == "not_assessed" and not skipped):
            raise LearningConflictError()
        if (
            from_plan
            and state.active_mode == "PLAN"
            and state.return_checkpoint == f"plan:{plan.id}"
        ):
            first = next(
                (
                    c
                    for c in self.concepts(plan.id)
                    if c.status not in {"completed", "not_assessed"}
                ),
                None,
            )
            if first and first.id == concept_id:
                return concept, state
        if state.active_mode not in modes or state.active_concept_id != concept_id:
            raise LearningConflictError()
        return concept, state

    def citations_current(self, workspace_id, citations):
        sources = {str(s.id): s for s in self.sources.ready_collection_ids(workspace_id).values()}
        return bool(citations) and all(
            str(c["source_id"]) in sources
            and sources[str(c["source_id"])].version == c["source_version"]
            for c in citations
        )

    async def retrieve(self, concept):
        sources = self.sources.ready_collection_ids(concept.workspace_id)
        refs = {
            (str(ref["source_id"]), ref["source_version"], ref["chunk_id"])
            for ref in concept.evidence_refs
        }
        if not refs or not any(
            (str(s.id), s.version) == ref[:2] for s in sources.values() for ref in refs
        ):
            return {}
        dataset = self.session.get(Workspace, concept.workspace_id).dataset_id
        query = f"{concept.title}: {concept.objective}"
        self.session.rollback()
        chunks = await self.fastgpt.search(SearchRequest(dataset, query))
        ready = {}
        for position, chunk in enumerate(chunks, 1):
            source = sources.get(chunk.collection_id)
            if (
                source
                and (str(source.id), source.version, chunk.chunk_id) in refs
                and chunk.chunk_id not in ready
            ):
                ready[chunk.chunk_id] = ReadyChunk(chunk, source, position)
        return ready

    def fresh(self, workspace_id, ready):
        self.session.expire_all()
        current = self.sources.ready_collection_ids(workspace_id)
        return bool(ready) and all(
            current.get(r.chunk.collection_id) == r.source for r in ready.values()
        )

    def advance(self, concept, state):
        next_concept = next(
            (
                c
                for c in self.concepts(concept.plan_id)
                if c.status not in {"completed", "not_assessed"}
            ),
            None,
        )
        if next_concept:
            next_concept.status = "active"
            state.active_mode = "LEARN"
            state.active_concept_id = next_concept.id
            state.return_checkpoint = f"concept:{next_concept.id}:ready"
            return "next_concept"
        self.session.get(LearningPlan, concept.plan_id).status = "completed"
        state.active_mode = "ASK"
        state.active_concept_id = None
        state.return_checkpoint = f"plan:{concept.plan_id}:completed"
        return "completed"
