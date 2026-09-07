"""Explicitly enabled, loopback-only inspection of local evaluation metadata."""

from datetime import datetime
from ipaddress import ip_address
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from grounded_tutor.config import Settings, get_settings
from grounded_tutor.db import get_session
from grounded_tutor.domain.models import BadCase, ExecutionTrace
from grounded_tutor.routers.common import api_error


def require_local_admin(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> None:
    try:
        local = request.client is not None and ip_address(request.client.host).is_loopback
    except ValueError:
        local = False
    if (
        not settings.enable_local_admin
        or settings.demo_read_only
        or not local
        or request.url.hostname not in {"localhost", "127.0.0.1", "::1"}
    ):
        raise HTTPException(status_code=404, detail="Not Found")


router = APIRouter(
    prefix="/api/admin/evals", tags=["local-admin"], dependencies=[Depends(require_local_admin)]
)


class TraceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    request_id: str
    workspace_id: UUID
    route: str
    retrieval_json: dict[str, Any]
    generation_json: dict[str, Any]
    validation_json: dict[str, Any]
    timing_json: dict[str, Any]
    created_at: datetime


class BadCaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    trace_id: UUID
    category: str
    status: str
    note: str
    resolution: str
    created_at: datetime
    updated_at: datetime


@router.get("/traces", response_model=list[TraceResponse])
def traces(
    session: Annotated[Session, Depends(get_session)],
    workspace_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    query = select(ExecutionTrace)
    if workspace_id is not None:
        query = query.where(ExecutionTrace.workspace_id == workspace_id)
    try:
        return list(
            session.scalars(
                query.order_by(ExecutionTrace.created_at.desc(), ExecutionTrace.id.desc()).limit(
                    limit
                )
            )
        )
    except SQLAlchemyError:
        api_error(500, "persistence_error")


@router.get("/traces/{trace_id}", response_model=TraceResponse)
def trace(
    trace_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    workspace_id: UUID | None = None,
):
    query = select(ExecutionTrace).where(ExecutionTrace.id == trace_id)
    if workspace_id is not None:
        query = query.where(ExecutionTrace.workspace_id == workspace_id)
    try:
        result = session.scalar(query)
    except SQLAlchemyError:
        api_error(500, "persistence_error")
    if result is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return result


@router.get("/bad-cases", response_model=list[BadCaseResponse])
def bad_cases(
    session: Annotated[Session, Depends(get_session)],
    workspace_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    query = select(BadCase).join(ExecutionTrace, BadCase.trace_id == ExecutionTrace.id)
    if workspace_id is not None:
        query = query.where(ExecutionTrace.workspace_id == workspace_id)
    try:
        return list(
            session.scalars(
                query.order_by(BadCase.created_at.desc(), BadCase.id.desc()).limit(limit)
            )
        )
    except SQLAlchemyError:
        api_error(500, "persistence_error")


@router.get("/bad-cases/{case_id}", response_model=BadCaseResponse)
def bad_case(
    case_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    workspace_id: UUID | None = None,
):
    query = (
        select(BadCase)
        .join(ExecutionTrace, BadCase.trace_id == ExecutionTrace.id)
        .where(BadCase.id == case_id)
    )
    if workspace_id is not None:
        query = query.where(ExecutionTrace.workspace_id == workspace_id)
    try:
        result = session.scalar(query)
    except SQLAlchemyError:
        api_error(500, "persistence_error")
    if result is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return result
