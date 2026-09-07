from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.schema import ForeignKeyConstraint, UniqueConstraint


class SourceType(str, Enum):
    FILE = "file"
    TEXT = "text"
    WEBPAGE = "webpage"


class SourceStatus(str, Enum):
    UPLOADING = "uploading"
    PARSING = "parsing"
    INDEXING = "indexing"
    REVIEW = "review"
    READY = "ready"
    FAILED = "failed"


def _enum_values(enum_class: type[Enum]) -> list[str]:
    return [member.value for member in enum_class]


class Base(DeclarativeBase):
    pass


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    dataset_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    vector_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agent_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vlm_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint("source_type IN ('file', 'text', 'webpage')", name="source_type"),
        CheckConstraint(
            "status IN ('uploading', 'parsing', 'indexing', 'review', 'ready', 'failed')",
            name="source_status",
        ),
        CheckConstraint("version > 0", name="ck_sources_version_positive"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[SourceType] = mapped_column(
        SqlEnum(
            SourceType,
            name="source_type",
            native_enum=False,
            create_constraint=False,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    origin_uri: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    collection_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    status: Mapped[SourceStatus] = mapped_column(
        SqlEnum(
            SourceStatus,
            name="source_status",
            native_enum=False,
            create_constraint=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=SourceStatus.UPLOADING,
    )
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    lineage_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
        default=lambda context: context.get_current_parameters()["id"],
    )
    replaces_source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), nullable=True
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingestion_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "idempotency_key", name="uq_messages_conversation_idempotency_key"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    content_blocks: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RequestRecord(Base):
    __tablename__ = "request_records"
    __table_args__ = (
        CheckConstraint("state IN ('pending', 'completed')", name="ck_request_records_state"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id"), primary_key=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    response_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )


class ExecutionTrace(Base):
    __tablename__ = "execution_traces"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    request_id: Mapped[str] = mapped_column(String(255), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    route: Mapped[str] = mapped_column(String(32), nullable=False)
    retrieval_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    generation_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    validation_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    timing_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )


class BadCase(Base):
    __tablename__ = "bad_cases"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    trace_id: Mapped[UUID] = mapped_column(
        ForeignKey("execution_traces.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open", server_default="open")
    note: Mapped[str] = mapped_column(String, nullable=False, default="", server_default="")
    resolution: Mapped[str] = mapped_column(String, nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )


class LearningPlan(Base):
    __tablename__ = "learning_plans"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id", name="uq_learning_plans_id_workspace"),
        CheckConstraint(
            "status IN ('not_started','active','completed','superseded')",
            name="ck_plan_status",
        ),
    )
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), index=True
    )
    goal: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="not_started", server_default="not_started"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Concept(Base):
    __tablename__ = "concepts"
    __table_args__ = (
        CheckConstraint("check_kind IN ('single_choice','structured_short')", name="ck_concept_check_kind"),
        ForeignKeyConstraint(
            ["plan_id", "workspace_id"],
            ["learning_plans.id", "learning_plans.workspace_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "workspace_id", name="uq_concepts_id_workspace"),
        UniqueConstraint("plan_id", "order", name="uq_concepts_plan_order"),
        CheckConstraint('"order" > 0', name="ck_concept_order_positive"),
        CheckConstraint(
            "status IN ('not_started','active','completed','needs_review','not_assessed')",
            name="ck_concept_status",
        ),
    )
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    plan_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True
    )
    order: Mapped[int] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    objective: Mapped[str] = mapped_column(String, nullable=False)
    check_kind: Mapped[str] = mapped_column(String(32), default="single_choice", server_default="single_choice")
    status: Mapped[str] = mapped_column(
        String(32), default="not_started", server_default="not_started"
    )
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class ActivityState(Base):
    __tablename__ = "activity_states"
    __table_args__ = (
        ForeignKeyConstraint(
            ["active_concept_id", "workspace_id"],
            ["concepts.id", "concepts.workspace_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "active_mode IN ('ASK','PLAN','LEARN','CHECK')", name="ck_activity_mode"
        ),
        CheckConstraint(
            "suspended_activity IS NULL OR active_mode = 'ASK'",
            name="ck_activity_suspended_mode",
        ),
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), primary_key=True
    )
    active_mode: Mapped[str] = mapped_column(
        String(16), default="ASK", server_default="ASK"
    )
    active_concept_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    suspended_activity: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    diagnostic_invitation: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    return_checkpoint: Mapped[str | None] = mapped_column(String, nullable=True)
    nudge_cooldown_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LearnerProfile(Base):
    __tablename__ = "learner_profiles"
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), primary_key=True
    )
    inferred_fields: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confirmed_fields: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Assessment(Base):
    __tablename__ = "assessments"
    __table_args__ = (
        Index("uq_assessments_workspace", "id", "workspace_id", unique=True),
        ForeignKeyConstraint(
            ["concept_id", "workspace_id"],
            ["concepts.id", "concepts.workspace_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "kind IN ('single_choice','structured_short')", name="ck_assessment_kind"
        ),
        CheckConstraint(
            "purpose IN ('diagnostic','immediate_check')", name="ck_assessment_purpose"
        ),
        CheckConstraint(
            "purpose != 'immediate_check' OR concept_id IS NOT NULL",
            name="ck_check_has_concept",
        ),
    )
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), index=True
    )
    concept_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    purpose: Mapped[str] = mapped_column(
        String(32), default="diagnostic", server_default="diagnostic"
    )
    prompt: Mapped[str] = mapped_column(String, nullable=False)
    options: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Server-only; future public question schemas must explicitly omit this field.
    answer_key: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    feedback_blocks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        Index("uq_attempts_assessment", "id", "assessment_id", unique=True),
        CheckConstraint(
            "status IN ('completed','not_assessed')", name="ck_attempt_status"
        ),
        CheckConstraint(
            "(status = 'not_assessed' AND result IS NULL AND response IS NULL) OR (status = 'completed' AND result IS NOT NULL AND result IN ('understood','needs_review') AND response IS NOT NULL)",
            name="ck_attempt_result",
        ),
    )
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    assessment_id: Mapped[UUID] = mapped_column(
        ForeignKey("assessments.id", ondelete="RESTRICT"), index=True
    )
    response: Mapped[str | None] = mapped_column(String, nullable=True)
    result: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Diagnostic(Base):
    __tablename__ = "diagnostics"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id", name="uq_diagnostics_workspace"),
        CheckConstraint("status IN ('active','completed')", name="ck_diagnostic_status"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    goal: Mapped[str] = mapped_column(String)
    background: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DiagnosticQuestion(Base):
    __tablename__ = "diagnostic_questions"
    __table_args__ = (
        ForeignKeyConstraint(["diagnostic_id", "workspace_id"], ["diagnostics.id", "diagnostics.workspace_id"]),
        ForeignKeyConstraint(["assessment_id", "workspace_id"], ["assessments.id", "assessments.workspace_id"]),
        ForeignKeyConstraint(["attempt_id", "assessment_id"], ["attempts.id", "attempts.assessment_id"]),
        UniqueConstraint("diagnostic_id", "order", name="uq_diagnostic_question_order"),
        CheckConstraint('"order" BETWEEN 1 AND 5', name="ck_diagnostic_question_order"),
    )
    assessment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    diagnostic_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    order: Mapped[int] = mapped_column()
    concept_label: Mapped[str] = mapped_column(String(120))
    attempt_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)


class PlanOrigin(Base):
    __tablename__ = "plan_origins"
    __table_args__ = (
        ForeignKeyConstraint(["plan_id", "workspace_id"], ["learning_plans.id", "learning_plans.workspace_id"]),
        ForeignKeyConstraint(["diagnostic_id", "workspace_id"], ["diagnostics.id", "diagnostics.workspace_id"]),
    )
    plan_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    diagnostic_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
