from functools import partial
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from grounded_tutor.dependencies import get_diagnostic_service
from grounded_tutor.domain.diagnostics import (
    DiagnosticAnswerRequest,
    DiagnosticAnswerResult,
    DiagnosticStartRequest,
    DiagnosticSummary,
    DiagnosticView,
)
from grounded_tutor.domain.schemas import ApiErrorResponse
from grounded_tutor.routers.common import DEMO_WRITE_ERROR_RESPONSE, learning_errors
from grounded_tutor.services.diagnostics import (
    DiagnosticConflictError,
    DiagnosticNotFoundError,
    DiagnosticService,
)

router = APIRouter(
    prefix="/api/workspaces/{workspace_id}/diagnostics",
    tags=["diagnostics"],
    responses={
        **DEMO_WRITE_ERROR_RESPONSE,
        **{code: {"model": ApiErrorResponse} for code in (404, 409, 422, 500, 502)},
    },
)
Service = Annotated[DiagnosticService, Depends(get_diagnostic_service)]


public_errors = partial(
    learning_errors,
    (DiagnosticNotFoundError, "diagnostic_not_found"),
    (DiagnosticConflictError, "diagnostic_conflict"),
)


@router.post("", response_model=DiagnosticView)
async def start(workspace_id: UUID, payload: DiagnosticStartRequest, service: Service):
    with public_errors():
        return await service.start(workspace_id, payload)


@router.get("/{diagnostic_id}", response_model=DiagnosticView)
def get(workspace_id: UUID, diagnostic_id: UUID, service: Service):
    with public_errors():
        return service.get(workspace_id, diagnostic_id)


@router.post("/{diagnostic_id}/answers", response_model=DiagnosticAnswerResult)
async def answer(
    workspace_id: UUID, diagnostic_id: UUID, payload: DiagnosticAnswerRequest, service: Service
):
    with public_errors():
        return await service.answer(workspace_id, diagnostic_id, payload)


@router.get("/{diagnostic_id}/summary", response_model=DiagnosticSummary)
def summary(workspace_id: UUID, diagnostic_id: UUID, service: Service):
    with public_errors():
        return service.summary(workspace_id, diagnostic_id)
