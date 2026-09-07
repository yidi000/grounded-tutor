from functools import partial
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from grounded_tutor.dependencies import get_plan_service
from grounded_tutor.domain.plans import (
    PlanCreateRequest,
    PlanHistory,
    PlanRebuildRequest,
    PlanSkipRequest,
    PlanView,
)
from grounded_tutor.domain.schemas import ApiErrorResponse
from grounded_tutor.routers.common import DEMO_WRITE_ERROR_RESPONSE, learning_errors
from grounded_tutor.services.plans import PlanConflictError, PlanNotFoundError, PlanService

router = APIRouter(
    prefix="/api/workspaces/{workspace_id}/plans",
    tags=["plans"],
    responses={
        **DEMO_WRITE_ERROR_RESPONSE,
        **{code: {"model": ApiErrorResponse} for code in (404, 409, 422, 500, 502)},
    },
)
Service = Annotated[PlanService, Depends(get_plan_service)]
public_errors = partial(
    learning_errors, (PlanNotFoundError, "plan_not_found"), (PlanConflictError, "plan_conflict")
)


@router.post("", response_model=PlanView)
async def create(workspace_id: UUID, payload: PlanCreateRequest, service: Service):
    with public_errors():
        return await service.create_from_diagnostic(workspace_id, payload)


@router.get("", response_model=PlanHistory)
def history(workspace_id: UUID, service: Service):
    with public_errors():
        return service.history(workspace_id)


@router.get("/{plan_id}", response_model=PlanView)
def get(workspace_id: UUID, plan_id: UUID, service: Service):
    with public_errors():
        return service.get(workspace_id, plan_id)


@router.post("/{plan_id}/rebuild", response_model=PlanView)
async def rebuild(workspace_id: UUID, plan_id: UUID, payload: PlanRebuildRequest, service: Service):
    with public_errors():
        return await service.rebuild(workspace_id, plan_id, payload)


@router.post("/{plan_id}/concepts/{concept_id}/skip", response_model=PlanView)
async def skip(
    workspace_id: UUID, plan_id: UUID, concept_id: UUID, payload: PlanSkipRequest, service: Service
):
    with public_errors():
        return await service.skip(workspace_id, plan_id, concept_id, payload)
