"""One suspended activity; ASK persistence and suspension commit together."""

from dataclasses import replace
from uuid import UUID

from grounded_tutor.domain.answers import ResumeActivityAction
from grounded_tutor.domain.learning import ActivitySnapshot
from grounded_tutor.domain.models import (
    ActivityState,
    Attempt,
    ImmediateCheck,
    LearningPlan,
    Workspace,
)
from grounded_tutor.domain.orchestration import ActivityView, ConceptActivity
from grounded_tutor.services.checks import CheckService
from grounded_tutor.services.diagnostics import DiagnosticNotFoundError, DiagnosticService
from grounded_tutor.services.learning_context import (
    LearningConflictError,
    LearningContext,
    LearningNotFoundError,
)
from grounded_tutor.services.learning_requests import LearningRequests
from grounded_tutor.services.lessons import LessonService
from grounded_tutor.services.plans import PlanNotFoundError, PlanService


class Orchestrator:
    def __init__(self, session, chat, fastgpt, generation, locks):
        self.session = session
        self.chat = chat
        self.locks = locks
        self.context = LearningContext(session, fastgpt)
        self.diagnostics = DiagnosticService(session, fastgpt, generation, locks)
        self.plans = PlanService(session, fastgpt, generation, locks)
        self.lessons = LessonService(session, fastgpt, generation, locks)
        self.checks = CheckService(session, fastgpt, generation, locks)
        self.writes = LearningRequests(session, locks, "activity", LearningNotFoundError)

    def _snapshot(self, workspace_id):
        if self.session.get(Workspace, workspace_id) is None:
            raise LearningNotFoundError()
        state = self.session.get(ActivityState, workspace_id)
        if not state:
            return ActivitySnapshot()
        return ActivitySnapshot(
            active_mode=state.active_mode,
            active_concept_id=str(state.active_concept_id) if state.active_concept_id else None,
            checkpoint=state.return_checkpoint,
            suspended_activity=state.suspended_activity,
        )

    def _apply(self, workspace_id, snapshot):
        state = self.session.get(ActivityState, workspace_id)
        if state is None:
            raise LearningConflictError()
        state.active_mode = snapshot.active_mode
        state.active_concept_id = (
            UUID(snapshot.active_concept_id) if snapshot.active_concept_id else None
        )
        state.return_checkpoint = snapshot.checkpoint
        state.suspended_activity = (
            snapshot.suspended_activity.model_dump(mode="json")
            if snapshot.suspended_activity
            else None
        )

    def _concept(self, workspace_id, concept_id):
        concept = self.context.concept(workspace_id, concept_id)
        plan = self.session.get(LearningPlan, concept.plan_id)
        if plan.status in {"completed", "superseded"} or concept.status == "completed":
            raise LearningConflictError()
        return concept

    def view(self, workspace_id, *, require_ready=False):
        try:
            return self._view(workspace_id, require_ready=require_ready)
        except (DiagnosticNotFoundError, PlanNotFoundError, ValueError):
            raise LearningConflictError() from None

    def _view(self, workspace_id, *, require_ready=False):
        snapshot = self._snapshot(workspace_id)
        active = snapshot.resume()
        if active.active_mode == "ASK":
            return ActivityView(snapshot=snapshot, checkpoint=active.checkpoint)
        checkpoint = active.checkpoint
        parts = checkpoint.split(":") if checkpoint else []
        if len(parts) < 2:
            raise LearningConflictError()
        try:
            target = UUID(parts[1])
            concept_id = UUID(active.active_concept_id) if active.active_concept_id else None
        except ValueError:
            raise LearningConflictError() from None
        payload = {}
        citations = []
        concept = None
        kind = parts[0]
        if kind == "diagnostic" and len(parts) == 4 and parts[2] == "question":
            if active.active_mode != "CHECK" or concept_id is not None:
                raise LearningConflictError()
            diagnostic = self.diagnostics.get(workspace_id, target)
            if diagnostic.status != "active":
                raise LearningConflictError()
            question = next(
                (
                    q
                    for i, q in enumerate(diagnostic.questions, 1)
                    if str(i) == parts[3] and q.question_id == diagnostic.next_question_id
                ),
                None,
            )
            if question is None:
                raise LearningConflictError()
            payload["diagnostic"] = diagnostic
            citations = [c.model_dump(mode="json") for c in question.citations]
            label = f"继续第 {parts[3]} 题"
        elif kind == "plan" and len(parts) == 2:
            if active.active_mode != "PLAN" or concept_id is not None:
                raise LearningConflictError()
            plan = self.plans.get(workspace_id, target)
            if plan.status in {"completed", "superseded"}:
                raise LearningConflictError()
            payload["plan"] = plan
            citations = [
                ref.model_dump(mode="json") for c in plan.concepts for ref in c.evidence_refs
            ]
            label = "继续学习计划"
        elif kind == "lesson" and len(parts) == 2:
            lesson = self.lessons.get(workspace_id, target)
            if active.active_mode != "LEARN" or lesson.concept_id != concept_id:
                raise LearningConflictError()
            concept = self._concept(workspace_id, concept_id)
            if concept.status == "not_assessed":
                raise LearningConflictError()
            payload["lesson"] = lesson
            citations = [c.model_dump(mode="json") for c in lesson.citations]
            label = f"继续学习「{concept.title}」"
        elif kind == "concept" and len(parts) == 3 and parts[2] == "ready":
            if active.active_mode != "LEARN" or target != concept_id:
                raise LearningConflictError()
            concept = self._concept(workspace_id, target)
            if concept.status != "active":
                raise LearningConflictError()
            citations = concept.evidence_refs
            label = f"开始学习「{concept.title}」"
        elif kind == "check" and (len(parts) == 2 or (len(parts) == 3 and parts[2] == "skipped")):
            check = self.checks.get(workspace_id, target)
            if active.active_mode != "CHECK" or check.concept_id != concept_id:
                raise LearningConflictError()
            concept = self._concept(workspace_id, concept_id)
            link = self.session.get(ImmediateCheck, target)
            if len(parts) == 3:
                attempt = self.session.get(Attempt, link.attempt_id) if link.attempt_id else None
                if (
                    not attempt
                    or attempt.status != "not_assessed"
                    or concept.status != "not_assessed"
                ):
                    raise LearningConflictError()
                kind, label = "check_skip", "继续跳过后的确认"
            else:
                if link.attempt_id or concept.status == "not_assessed":
                    raise LearningConflictError()
                label = f"继续检查「{concept.title}」"
            payload["check"] = check
            citations = [c.model_dump(mode="json") for c in check.citations]
        else:
            raise LearningConflictError()
        if require_ready and not self.context.citations_current(workspace_id, citations):
            raise LearningConflictError()
        if concept:
            payload["concept"] = ConceptActivity(
                id=concept.id,
                plan_id=concept.plan_id,
                title=concept.title,
                objective=concept.objective,
                status=concept.status,
            )
        action = (
            ResumeActivityAction(type="resume_activity", label=label, checkpoint=checkpoint)
            if snapshot.suspended_activity
            else None
        )
        return ActivityView(
            snapshot=snapshot, checkpoint=checkpoint, kind=kind, resume_action=action, **payload
        )

    def _suspend(self, workspace_id):
        view = self.view(workspace_id)
        if view.snapshot.active_mode != "ASK":
            self._apply(workspace_id, view.snapshot.suspend_for("ASK"))

    async def handle_message(self, workspace_id, message, conversation_id, idempotency_key):
        async with self.locks.acquire(workspace_id):
            result = await self.chat.ask(
                workspace_id,
                message,
                conversation_id,
                idempotency_key,
                before_persist=lambda: self._suspend(workspace_id),
            )
            action = self.view(workspace_id).resume_action
            return (
                replace(result, suggested_actions=(*result.suggested_actions, action))
                if action
                else result
            )

    def history(self, workspace_id):
        history = self.chat.history(workspace_id)
        if not history.exchanges:
            return history
        try:
            action = self.view(workspace_id).resume_action
        except (LearningConflictError, LearningNotFoundError):
            # A stale activity must not hide successfully saved ASK history.
            return history
        if not action:
            return history
        last = history.exchanges[-1]
        last = last.model_copy(
            update={
                "response": last.response.model_copy(
                    update={"suggested_actions": (*last.response.suggested_actions, action)}
                )
            }
        )
        return history.model_copy(update={"exchanges": (*history.exchanges[:-1], last)})

    async def pause(self, workspace_id, request):
        async def suspend():
            view = self.view(workspace_id)
            if view.checkpoint != request.checkpoint or view.kind == "idle":
                raise LearningConflictError()
            self._suspend(workspace_id)
            return self.view(workspace_id)

        return await self.writes.run(workspace_id, "pause:", request, ActivityView, suspend)

    async def resume(self, workspace_id, request):
        async def restore():
            view = self.view(workspace_id, require_ready=True)
            if view.checkpoint != request.checkpoint or view.kind == "idle":
                raise LearningConflictError()
            self._apply(workspace_id, view.snapshot.resume())
            return self.view(workspace_id)

        return await self.writes.run(workspace_id, "resume:", request, ActivityView, restore)
