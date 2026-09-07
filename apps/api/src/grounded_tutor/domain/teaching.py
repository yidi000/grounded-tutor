"""Public lesson/check contracts and the server-only generated check."""

from typing import Literal, Self
from uuid import UUID

from pydantic import StrictBool, model_validator

from grounded_tutor.domain.answers import Citation, GroundedContentBlock
from grounded_tutor.domain.diagnostics import (
    Contract,
    GeneratedDiagnosticQuestion,
    Key,
    Result,
    Text,
)
from grounded_tutor.domain.learning import AssessmentKind

Depth = Literal["standard", "simpler", "more_examples", "deeper"]
DEPTHS = ("standard", "simpler", "more_examples", "deeper")


class LessonRequest(Contract):
    depth: Depth = "standard"
    idempotency_key: Key


class LessonView(Contract):
    status: Literal["ok", "insufficient_material"]
    concept_id: UUID
    lesson_id: UUID | None = None
    depth: Depth
    content_blocks: tuple[GroundedContentBlock, ...] = ()
    citations: tuple[Citation, ...] = ()
    available_depths: tuple[Depth, ...] = DEPTHS


class GeneratedCheck(Contract):
    question: GeneratedDiagnosticQuestion


class CheckStartRequest(Contract):
    idempotency_key: Key


class CheckView(Contract):
    status: Literal["ok", "insufficient_material"]
    concept_id: UUID
    assessment_id: UUID | None = None
    kind: AssessmentKind | None = None
    prompt: str | None = None
    options: tuple[str, ...] = ()
    citations: tuple[Citation, ...] = ()


class CheckAnswerRequest(Contract):
    response: Text | None = None
    skip: StrictBool = False
    idempotency_key: Key

    @model_validator(mode="after")
    def one_response(self) -> Self:
        if self.skip == (self.response is not None):
            raise ValueError("Provide an answer or skip, exclusively")
        return self


class CheckContinueRequest(Contract):
    confirm_continue: StrictBool
    idempotency_key: Key

    @model_validator(mode="after")
    def confirmed(self) -> Self:
        if not self.confirm_continue:
            raise ValueError("Explicit continuation required")
        return self


class CheckResult(Contract):
    attempt_id: UUID
    result: Result
    correct: bool | None
    next_action: Literal["next_concept", "review_concept", "confirm_continue", "completed"]
    active_concept_id: UUID | None
    explanation_blocks: tuple[GroundedContentBlock, ...] = ()
    citations: tuple[Citation, ...] = ()
