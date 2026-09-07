"""Finite generated plans and their public request/response contracts."""

from typing import Literal, Self
from uuid import UUID

from pydantic import Field, StrictBool, model_validator

from grounded_tutor.domain.answers import Citation
from grounded_tutor.domain.diagnostics import Contract, Key, Label, Text
from grounded_tutor.domain.learning import AssessmentKind, ConceptStatus, PlanStatus


class GeneratedPlanConcept(Contract):
    title: Label
    objective: Text
    chunk_ids: tuple[Key, ...] = Field(min_length=1, max_length=8)
    check_kind: AssessmentKind


class GeneratedLearningPlan(Contract):
    concepts: tuple[GeneratedPlanConcept, ...] = Field(min_length=3, max_length=5)

    @model_validator(mode="after")
    def unique_concepts(self) -> Self:
        if len({c.title.casefold() for c in self.concepts}) != len(self.concepts):
            raise ValueError("Concept titles must be distinct")
        return self


class PlanCreateRequest(Contract):
    diagnostic_id: UUID
    idempotency_key: Key


class PlanRebuildRequest(PlanCreateRequest):
    confirm_rebuild: StrictBool

    @model_validator(mode="after")
    def confirmed(self) -> Self:
        if not self.confirm_rebuild:
            raise ValueError("Explicit rebuild confirmation required")
        return self


class PlanSkipRequest(Contract):
    idempotency_key: Key


class PlanConceptView(Contract):
    id: UUID
    title: str
    objective: str
    order: int
    status: ConceptStatus
    check_kind: AssessmentKind
    evidence_refs: tuple[Citation, ...]


class PlanView(Contract):
    plan_id: UUID | None = None
    diagnostic_id: UUID | None = None
    goal: str | None = None
    status: PlanStatus | Literal["insufficient_material"]
    concepts: tuple[PlanConceptView, ...] = ()


class PlanHistory(Contract):
    plans: tuple[PlanView, ...]
