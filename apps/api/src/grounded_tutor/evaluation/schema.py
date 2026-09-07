from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from grounded_tutor.domain.answers import GeneratedAnswer
from grounded_tutor.domain.models import SourceStatus


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceFixture(StrictModel):
    name: str = "Notes"
    collection_id: str = "local"
    workspace: Literal["current", "other"] = "current"
    status: SourceStatus = SourceStatus.READY
    version: int = Field(default=1, ge=1)
    deleted: bool = False
    superseded: bool = False


class ChunkFixture(StrictModel):
    chunk_id: str = "chunk"
    collection_id: str = "local"
    source_name: str = "Untrusted provider name"
    q: str = "Mean"
    a: str = "The mean is the sum divided by the count."
    score: float = 1


class CaseInput(StrictModel):
    message: str = Field(default="What is the mean?", min_length=1)
    chunks: list[ChunkFixture] = Field(default_factory=lambda: [ChunkFixture()])
    responses: list[GeneratedAnswer | Literal["invalid", "failure"]] = Field(default_factory=list)
    journey: Literal["ask", "replay", "conflict", "pending", "foreign_conversation", "recover"] = (
        "ask"
    )
    search_failure: bool = False


class EvaluationCase(StrictModel):
    id: str = Field(pattern=r"^(GA|IM|WI|CV|SS|ID|RC)-\d{2}$")
    category: Literal[
        "grounded_answer",
        "insufficient_material",
        "workspace_isolation",
        "citation_validation",
        "source_state",
        "idempotency",
        "recovery",
    ]
    workspace_fixture: list[SourceFixture]
    input: CaseInput
    expected_status: Literal["ok", "insufficient_material", "conflict", "pending", "not_found"]
    expected_source_names: list[str]
    forbidden_source_names: list[str]
    expected_external_calls: dict[
        Literal["search", "generate"], Annotated[int, Field(ge=0, strict=True)]
    ] = Field(min_length=2)


TargetName = Literal[
    "grounded_citation_coverage",
    "insufficient_material_refusal_rate",
    "cross_workspace_leakage_count",
    "unauthorized_external_call_count",
    "idempotent_replay_rate",
    "journey_pass_rate",
]
TARGETS = TypeAdapter(
    Annotated[
        dict[TargetName, Annotated[float, Field(ge=0, strict=True, allow_inf_nan=False)]],
        Field(min_length=1),
    ]
)
