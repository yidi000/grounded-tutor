from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from grounded_tutor.dependencies import get_workspace_service
from grounded_tutor.domain.schemas import (
    ApiErrorResponse,
    WorkspaceCreate,
    WorkspaceResponse,
    WorkspaceUpdate,
)
from grounded_tutor.repositories.workspaces import WorkspacePersistenceError
from grounded_tutor.routers.common import DEMO_WRITE_ERROR_RESPONSE, api_error, parse_uuid
from grounded_tutor.services.workspaces import (
    ExternalWorkspaceServiceError,
    UnsupportedWorkspaceModelError,
    WorkspaceNotFoundError,
    WorkspaceService,
)

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])

VALIDATION_ERROR_RESPONSE = {
    **DEMO_WRITE_ERROR_RESPONSE,
    422: {"model": ApiErrorResponse, "description": "Workspace input is invalid."}
}
CREATE_ERROR_RESPONSES = {
    **VALIDATION_ERROR_RESPONSE,
    500: {"model": ApiErrorResponse, "description": "Local persistence failed."},
    502: {"model": ApiErrorResponse, "description": "External service failed."},
}
LIST_ERROR_RESPONSES = {
    500: {"model": ApiErrorResponse, "description": "Local persistence failed."}
}
DETAIL_ERROR_RESPONSES = {
    404: {"model": ApiErrorResponse, "description": "Workspace not found."},
    500: {"model": ApiErrorResponse, "description": "Local persistence failed."},
}
UPDATE_ERROR_RESPONSES = {**DETAIL_ERROR_RESPONSES, **VALIDATION_ERROR_RESPONSE}


@router.post(
    "",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
    responses=CREATE_ERROR_RESPONSES,
)
async def create_workspace(
    payload: WorkspaceCreate,
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceResponse:
    try:
        workspace = await service.create(
            title=payload.title,
            vector_model=payload.vector_model,
            agent_model=payload.agent_model,
            vlm_model=payload.vlm_model,
        )
    except ExternalWorkspaceServiceError:
        api_error(status.HTTP_502_BAD_GATEWAY, "external_service_error")
    except UnsupportedWorkspaceModelError:
        api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "unsupported_workspace_model")
    except WorkspacePersistenceError:
        api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "persistence_error")
    return WorkspaceResponse.model_validate(workspace)


@router.get("", response_model=list[WorkspaceResponse], responses=LIST_ERROR_RESPONSES)
def list_workspaces(
    service: Annotated[WorkspaceService, Depends(get_workspace_service)]
) -> list[WorkspaceResponse]:
    try:
        return [WorkspaceResponse.model_validate(workspace) for workspace in service.list()]
    except WorkspacePersistenceError:
        api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "persistence_error")


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
    responses=DETAIL_ERROR_RESPONSES,
)
def get_workspace(
    workspace_id: str,
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceResponse:
    try:
        return WorkspaceResponse.model_validate(
            service.get(parse_uuid(workspace_id, "workspace_not_found"))
        )
    except WorkspaceNotFoundError:
        api_error(status.HTTP_404_NOT_FOUND, "workspace_not_found")
    except WorkspacePersistenceError:
        api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "persistence_error")


@router.patch(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
    responses=UPDATE_ERROR_RESPONSES,
)
def rename_workspace(
    workspace_id: str,
    payload: WorkspaceUpdate,
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceResponse:
    try:
        return WorkspaceResponse.model_validate(
            service.rename(parse_uuid(workspace_id, "workspace_not_found"), title=payload.title)
        )
    except WorkspaceNotFoundError:
        api_error(status.HTTP_404_NOT_FOUND, "workspace_not_found")
    except WorkspacePersistenceError:
        api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "persistence_error")
