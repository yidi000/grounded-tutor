from contextlib import contextmanager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.exc import SQLAlchemyError

from grounded_tutor.adapters.fastgpt import ExternalServiceError
from grounded_tutor.dependencies import get_diagnostic_service
from grounded_tutor.domain.diagnostics import (
    DiagnosticAnswerRequest,
    DiagnosticAnswerResult,
    DiagnosticStartRequest,
    DiagnosticSummary,
    DiagnosticView,
)
from grounded_tutor.domain.schemas import ApiErrorResponse
from grounded_tutor.repositories.chat import ChatPersistenceError
from grounded_tutor.repositories.sources import SourcePersistenceError
from grounded_tutor.routers.common import DEMO_WRITE_ERROR_RESPONSE, api_error
from grounded_tutor.services.diagnostics import (
    DiagnosticConflictError,
    DiagnosticNotFoundError,
    DiagnosticService,
)
from grounded_tutor.services.idempotency import IdempotencyInProgress, IdempotencyKeyReused
from grounded_tutor.services.source_locks import WorkspaceIngestionBusyError

router = APIRouter(
    prefix="/api/workspaces/{workspace_id}/diagnostics",
    tags=["diagnostics"],
    responses={
        **DEMO_WRITE_ERROR_RESPONSE,
        **{code: {"model": ApiErrorResponse} for code in (404, 409, 422, 500, 502)},
    },
)
Service = Annotated[DiagnosticService, Depends(get_diagnostic_service)]


@contextmanager
def public_errors():
    try:
        yield
    except DiagnosticNotFoundError:
        api_error(404, "diagnostic_not_found")
    except DiagnosticConflictError:
        api_error(409, "diagnostic_conflict")
    except IdempotencyKeyReused:
        api_error(409, "idempotency_key_reused")
    except IdempotencyInProgress:
        api_error(409, "idempotency_in_progress")
    except WorkspaceIngestionBusyError:
        api_error(409, "workspace_ingestion_busy")
    except (ChatPersistenceError, SourcePersistenceError, SQLAlchemyError):
        api_error(500, "persistence_error")
    except ExternalServiceError:
        api_error(502, "external_service_error")


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
