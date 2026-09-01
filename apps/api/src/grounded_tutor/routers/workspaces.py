from __future__ import annotations

from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from grounded_tutor.dependencies import get_workspace_service
from grounded_tutor.domain.schemas import WorkspaceCreate, WorkspaceResponse, WorkspaceUpdate
from grounded_tutor.repositories.workspaces import WorkspacePersistenceError, WorkspaceSummary
from grounded_tutor.services.workspaces import (
    ExternalWorkspaceServiceError,
    WorkspaceNotFoundError,
    WorkspaceService,
)

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
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
        _api_error(status.HTTP_502_BAD_GATEWAY, "external_service_error")
    except WorkspacePersistenceError:
        _api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "persistence_error")
    return _response(workspace)


@router.get("", response_model=list[WorkspaceResponse])
def list_workspaces(
    service: Annotated[WorkspaceService, Depends(get_workspace_service)]
) -> list[WorkspaceResponse]:
    return [_response(workspace) for workspace in service.list()]


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
def get_workspace(
    workspace_id: str,
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceResponse:
    return _read_workspace(_parse_workspace_id(workspace_id), service)


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
def rename_workspace(
    workspace_id: str,
    payload: WorkspaceUpdate,
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceResponse:
    try:
        return _response(service.rename(_parse_workspace_id(workspace_id), title=payload.title))
    except WorkspaceNotFoundError:
        _api_error(status.HTTP_404_NOT_FOUND, "workspace_not_found")
    except WorkspacePersistenceError:
        _api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "persistence_error")


def _read_workspace(workspace_id: UUID, service: WorkspaceService) -> WorkspaceResponse:
    try:
        return _response(service.get(workspace_id))
    except WorkspaceNotFoundError:
        _api_error(status.HTTP_404_NOT_FOUND, "workspace_not_found")


def _parse_workspace_id(workspace_id: str) -> UUID:
    try:
        return UUID(workspace_id)
    except ValueError:
        _api_error(status.HTTP_404_NOT_FOUND, "workspace_not_found")


def _response(workspace: WorkspaceSummary) -> WorkspaceResponse:
    return WorkspaceResponse(
        id=workspace.id,
        title=workspace.title,
        source_count=workspace.source_count,
        ready_source_count=workspace.ready_source_count,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
    )


def _api_error(status_code: int, code: str) -> NoReturn:
    raise HTTPException(status_code=status_code, detail={"code": code})
