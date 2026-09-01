from __future__ import annotations

import json
from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import ValidationError

from grounded_tutor.dependencies import get_preview_service
from grounded_tutor.domain.ingestion import (
    ChunkSettings,
    PreviewResponse,
    TextPreviewRequest,
    validate_public_chunk_settings,
)
from grounded_tutor.repositories.workspaces import WorkspacePersistenceError
from grounded_tutor.services.previews import (
    PreviewError,
    PreviewService,
    PreviewWorkspaceNotFoundError,
)

router = APIRouter(
    prefix="/api/workspaces/{workspace_id}/source-previews",
    tags=["source previews"],
)


@router.post("/text", response_model=PreviewResponse)
def create_text_preview(
    workspace_id: str,
    payload: TextPreviewRequest,
    service: Annotated[PreviewService, Depends(get_preview_service)],
) -> PreviewResponse:
    try:
        return service.from_text(
            _parse_workspace_id(workspace_id),
            source_name=payload.source_name,
            text=payload.text,
            settings=payload.settings,
        )
    except PreviewWorkspaceNotFoundError:
        _api_error(status.HTTP_404_NOT_FOUND, "workspace_not_found")
    except PreviewError as error:
        _preview_error(error)
    except WorkspacePersistenceError:
        _api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "persistence_error")


@router.post("/file", response_model=PreviewResponse)
def create_file_preview(
    workspace_id: str,
    service: Annotated[PreviewService, Depends(get_preview_service)],
    file: Annotated[UploadFile, File()],
    settings: Annotated[str, Form()] = "{}",
) -> PreviewResponse:
    chunk_settings = _parse_settings(settings)
    content = file.file.read(service.max_upload_bytes + 1)
    try:
        return service.from_file(
            _parse_workspace_id(workspace_id),
            filename=file.filename or "",
            content=content,
            settings=chunk_settings,
        )
    except PreviewWorkspaceNotFoundError:
        _api_error(status.HTTP_404_NOT_FOUND, "workspace_not_found")
    except PreviewError as error:
        _preview_error(error)
    except WorkspacePersistenceError:
        _api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "persistence_error")


def _parse_settings(value: str) -> ChunkSettings:
    try:
        return validate_public_chunk_settings(json.loads(value))
    except (json.JSONDecodeError, ValidationError, ValueError):
        _api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_chunk_settings")


def _parse_workspace_id(workspace_id: str) -> UUID:
    try:
        return UUID(workspace_id)
    except ValueError:
        _api_error(status.HTTP_404_NOT_FOUND, "workspace_not_found")


def _preview_error(error: PreviewError) -> NoReturn:
    status_code = {
        "file_too_large": status.HTTP_413_CONTENT_TOO_LARGE,
        "unsupported_file_type": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    }.get(error.code, status.HTTP_422_UNPROCESSABLE_CONTENT)
    _api_error(status_code, error.code)


def _api_error(status_code: int, code: str) -> NoReturn:
    raise HTTPException(status_code=status_code, detail={"code": code})
