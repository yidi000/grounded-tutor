"""Public persisted activity snapshots; never carry drafts or answer keys."""

from typing import Literal
from uuid import UUID

from grounded_tutor.domain.answers import ResumeActivityAction
from grounded_tutor.domain.diagnostics import Contract, DiagnosticView, Key
from grounded_tutor.domain.learning import ActivitySnapshot, ConceptStatus
from grounded_tutor.domain.plans import PlanView
from grounded_tutor.domain.teaching import CheckView, LessonView


class ActivityCommand(Contract):
    checkpoint: Key
    idempotency_key: Key


class ConceptActivity(Contract):
    id: UUID
    plan_id: UUID
    title: str
    objective: str
    status: ConceptStatus


class ActivityView(Contract):
    snapshot: ActivitySnapshot
    checkpoint: str | None = None
    kind: Literal["idle", "plan", "diagnostic", "lesson", "concept", "check", "check_skip"] = "idle"
    resume_action: ResumeActivityAction | None = None
    concept: ConceptActivity | None = None
    plan: PlanView | None = None
    diagnostic: DiagnosticView | None = None
    lesson: LessonView | None = None
    check: CheckView | None = None
