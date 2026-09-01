from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from grounded_tutor.domain.models import SourceStatus, SourceType


class ApiErrorDetail(BaseModel):
    code: str


class ApiErrorResponse(BaseModel):
    detail: ApiErrorDetail


class WorkspaceCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    vector_model: str | None = None
    agent_model: str | None = None
    vlm_model: str | None = None

    @field_validator("title", mode="before")
    @classmethod
    def trim_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("vector_model", "agent_model", "vlm_model", mode="before")
    @classmethod
    def trim_optional_model(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        value = value.strip()
        return value or None


class WorkspaceUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=120)

    @field_validator("title", mode="before")
    @classmethod
    def trim_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    source_count: int
    ready_source_count: int
    created_at: datetime
    updated_at: datetime


class SourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    name: str
    source_type: SourceType
    origin_uri: str | None
    status: SourceStatus
    version: int
    ingestion_config: dict[str, Any]
    error_message: str | None
    created_at: datetime
    updated_at: datetime
