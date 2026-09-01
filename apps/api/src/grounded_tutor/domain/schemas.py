from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from grounded_tutor.domain.models import SourceStatus, SourceType


class WorkspaceCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class WorkspaceUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    created_at: datetime


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
