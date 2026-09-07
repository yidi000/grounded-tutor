from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.schema import UniqueConstraint


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
