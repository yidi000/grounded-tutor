"""Learning state values; answer keys belong only in persistence, never public schemas."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

ActivityMode = Literal["ASK", "PLAN", "LEARN", "CHECK"]
PlanStatus = Literal["not_started", "active", "completed", "superseded"]
ConceptStatus = Literal["not_started", "active", "completed", "needs_review", "not_assessed"]
AssessmentKind = Literal["single_choice", "structured_short"]
AttemptStatus = Literal["completed", "not_assessed"]
Checkpoint = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class SuspendedActivity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: Literal["PLAN", "LEARN", "CHECK"]
    active_concept_id: str | None = None
    checkpoint: Checkpoint | None = None


class ActivitySnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    active_mode: ActivityMode = "ASK"
    active_concept_id: str | None = None
    checkpoint: Checkpoint | None = None
    suspended_activity: SuspendedActivity | None = None

    @model_validator(mode="after")
    def require_ask_detour(self) -> Self:
        if self.suspended_activity is not None and self.active_mode != "ASK":
            raise ValueError("Only ASK can hold a suspended activity")
        return self

    def suspend_for(self, mode: ActivityMode) -> Self:
        # ponytail: one suspended activity; add a stack only for an approved nested flow.
        if mode != "ASK":
            raise ValueError("Only ASK detours are supported")
        if self.active_mode == "ASK":
            return self
        return type(self)(
            suspended_activity=SuspendedActivity(
                mode=self.active_mode,
                active_concept_id=self.active_concept_id,
                checkpoint=self.checkpoint,
            )
        )

    def resume(self) -> Self:
        if self.suspended_activity is None:
            return self
        saved = self.suspended_activity
        return type(self)(
            active_mode=saved.mode,
            active_concept_id=saved.active_concept_id,
            checkpoint=saved.checkpoint,
        )

    def complete_step(self, checkpoint: str) -> Self:
        if self.active_mode == "ASK":
            raise ValueError("ASK must not advance learning progress")
        return type(self).model_validate({**self.model_dump(), "checkpoint": checkpoint})
