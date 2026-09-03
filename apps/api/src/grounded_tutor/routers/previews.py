from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from grounded_tutor.config import Settings, get_settings
from grounded_tutor.dependencies import get_preview_service
from grounded_tutor.domain.ingestion import (
    PreviewResponse,
    TextPreviewRequest,
)
from grounded_tutor.domain.schemas import ApiErrorResponse
from grounded_tutor.repositories.workspaces import WorkspacePersistenceError
from grounded_tutor.routers.common import (
    DEMO_WRITE_ERROR_RESPONSE,
    api_error,
    parse_chunk_settings,
    parse_uuid,
    require_chunk_capability,
)
from grounded_tutor.services.previews import (
    PreviewError,
    PreviewService,
    PreviewWorkspaceNotFoundError,
)

router = APIRouter(
    prefix="/api/workspaces/{workspace_id}/source-previews",
    tags=["source previews"],
)

COMMON_ERROR_RESPONSES = {
    **DEMO_WRITE_ERROR_RESPONSE,
    404: {"model": ApiErrorResponse, "description": "Workspace not found."},
    413: {"model": ApiErrorResponse, "description": "Preview resource limit exceeded."},
    422: {"model": ApiErrorResponse, "description": "Preview input is invalid."},
    500: {"model": ApiErrorResponse, "description": "Local persistence failed."},
}
FILE_ERROR_RESPONSES = {
    **COMMON_ERROR_RESPONSES,
    415: {"model": ApiErrorResponse, "description": "File type is unsupported."},
}


@router.post(
    "/text",
    response_model=PreviewResponse,
    responses=COMMON_ERROR_RESPONSES,
)
def create_text_preview(
    workspace_id: str,
    payload: TextPreviewRequest,
    service: Annotated[PreviewService, Depends(get_preview_service)],
    runtime_settings: Annotated[Settings, Depends(get_settings)],
) -> PreviewResponse:
    require_chunk_capability(payload.settings, runtime_settings)
    try:
        return service.from_text(
            parse_uuid(workspace_id, "workspace_not_found"),
            source_name=payload.source_name,
            text=payload.text,
            settings=payload.settings,
        )
    except PreviewWorkspaceNotFoundError:
        api_error(status.HTTP_404_NOT_FOUND, "workspace_not_found")
    except PreviewError as error:
        _preview_error(error)
    except WorkspacePersistenceError:
        api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "persistence_error")


@router.post(
    "/file",
    response_model=PreviewResponse,
    responses=FILE_ERROR_RESPONSES,
)
def create_file_preview(
    workspace_id: str,
    service: Annotated[PreviewService, Depends(get_preview_service)],
    file: Annotated[UploadFile, File()],
    runtime_settings: Annotated[Settings, Depends(get_settings)],
    settings: Annotated[str, Form()] = "{}",
) -> PreviewResponse:
    chunk_settings = parse_chunk_settings(settings)
    require_chunk_capability(chunk_settings, runtime_settings)
    content = file.file.read(service.max_upload_bytes + 1)
    try:
        return service.from_file(
            parse_uuid(workspace_id, "workspace_not_found"),
            filename=file.filename or "",
            content=content,
            settings=chunk_settings,
        )
    except PreviewWorkspaceNotFoundError:
        api_error(status.HTTP_404_NOT_FOUND, "workspace_not_found")
    except PreviewError as error:
        _preview_error(error)
    except WorkspacePersistenceError:
        api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "persistence_error")


def _preview_error(error: PreviewError) -> NoReturn:
    status_code = {
        "file_too_large": status.HTTP_413_CONTENT_TOO_LARGE,
        "text_too_large": status.HTTP_413_CONTENT_TOO_LARGE,
        "source_too_large": status.HTTP_413_CONTENT_TOO_LARGE,
        "source_work_limit_exceeded": status.HTTP_413_CONTENT_TOO_LARGE,
        "unsafe_archive": status.HTTP_413_CONTENT_TOO_LARGE,
        "unsupported_file_type": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    }.get(error.code, status.HTTP_422_UNPROCESSABLE_CONTENT)
    api_error(status_code, error.code)
