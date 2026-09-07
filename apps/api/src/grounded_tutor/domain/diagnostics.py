"""Strict generation and public diagnostic contracts; keys stay server-side."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, model_validator

from grounded_tutor.domain.answers import Citation, GroundedContentBlock

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Key = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Result = Literal["understood", "needs_review", "not_assessed"]


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DiagnosticStartRequest(Contract):
    consent: StrictBool
    goal: Text
    background: Text | None = None
    invitation_id: UUID | None = None
    idempotency_key: Key

    @model_validator(mode="after")
    def consent_required(self) -> Self:
        if not self.consent:
            raise ValueError("Explicit consent required")
        return self


class DiagnosticAnswerRequest(Contract):
    question_id: UUID
    response: Text | None = None
    skip: StrictBool = False
    idempotency_key: Key

    @model_validator(mode="after")
    def one_response(self) -> Self:
        if self.skip == (self.response is not None):
            raise ValueError("Provide an answer or skip, exclusively")
        return self


class GeneratedDiagnosticQuestion(Contract):
    id: Label
    kind: Literal["single_choice", "structured_short"]
    prompt: Text
    options: tuple[Text, ...] = Field(default=(), max_length=6)
    answer_key: tuple[Text, ...] = Field(min_length=1, max_length=4)
    explanation: Text
    concept_label: Label
    chunk_ids: tuple[Key, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def scorable(self) -> Self:
        if self.kind == "single_choice":
            if len(self.options) < 2 or len(set(self.options)) != len(self.options):
                raise ValueError("Unique choices required")
            if len(self.answer_key) != 1 or self.answer_key[0] not in self.options:
                raise ValueError("One correct choice required")
        elif self.options:
            raise ValueError("Short answers have no choices")
        return self


class GeneratedDiagnostic(Contract):
    questions: tuple[GeneratedDiagnosticQuestion, ...] = Field(min_length=3, max_length=5)

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        if len({q.id for q in self.questions}) != len(self.questions):
            raise ValueError("Question IDs must be unique")
        return self


class DiagnosticQuestionView(Contract):
    question_id: UUID
    kind: Literal["single_choice", "structured_short"]
    prompt: str
    options: tuple[str, ...]
    concept_label: str
    evidence_refs: tuple[dict, ...]
    citations: tuple[Citation, ...]


class DiagnosticView(Contract):
    status: Literal["active", "completed", "insufficient_material"]
    diagnostic_id: UUID | None = None
    questions: tuple[DiagnosticQuestionView, ...] = ()
    next_question_id: UUID | None = None


class DiagnosticAnswerResult(Contract):
    attempt_id: UUID
    result: Result
    feedback_blocks: tuple[GroundedContentBlock, ...] = ()
    citations: tuple[Citation, ...] = ()
    next_question_id: UUID | None = None
    completed: bool


class DiagnosticConceptResult(Contract):
    concept_label: str
    result: Result


class DiagnosticSummary(Contract):
    status: Literal["active", "completed"]
    concepts: tuple[DiagnosticConceptResult, ...]
