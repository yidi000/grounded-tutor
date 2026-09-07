"""Pure routing decisions. Classifier observations never execute operations."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from grounded_tutor.domain.answers import WorkspaceSuggestionAction
from grounded_tutor.domain.learning import ActivityMode


class ClassifierObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    intent: Literal["unknown", "learning", "foundation", "unrelated"] = "unknown"
    proposed_title: str | None = Field(default=None, max_length=120)
    goal: str | None = Field(default=None, max_length=2000)
    background: str | None = Field(default=None, max_length=2000)

    @field_validator("proposed_title")
    @classmethod
    def bounded_title(cls, value):
        if value is not None and (not value.strip() or "\n" in value or "\r" in value):
            raise ValueError("Topic title must be a nonblank single line")
        return value.strip() if value is not None else None


class RoutePolicy:
    def choose(
        self,
        *,
        event: str | None,
        active_mode: ActivityMode | None,
        classified_intent: str | None,
        explicit_intent: str | None = None,
    ) -> ActivityMode:
        events = {
            "START_DIAGNOSTIC": "CHECK",
            "CONTINUE_CHECK": "CHECK",
            "ASK_QUESTION": "ASK",
            "CONTINUE_LEARNING": "LEARN",
            "CONFIRM_PLAN": "PLAN",
        }
        if event is not None:
            return events.get(event, "ASK")
        if active_mode in {"PLAN", "LEARN", "CHECK"}:
            return active_mode
        # Text and classification are not consent. Learning requests remain ASK
        # until an explicit event; invitation eligibility is decided separately.
        return "ASK"

    @staticmethod
    def workspace_suggestion(
        observation: ClassifierObservation,
    ) -> WorkspaceSuggestionAction | None:
        if observation.intent == "unrelated" and observation.proposed_title:
            return WorkspaceSuggestionAction(proposed_title=observation.proposed_title)
        return None
