from __future__ import annotations

import json
from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import ValidationError

from grounded_tutor.dependencies import get_source_service
from grounded_tutor.domain.ingestion import ChunkSettings, validate_public_chunk_settings
from grounded_tutor.domain.schemas import (
    ApiErrorResponse,
    ProcessedPreviewResponse,
    SourceIngestionResponse,
    SourceResponse,
    TextSourceCreate,
)
from grounded_tutor.repositories.sources import SourcePersistenceError, SourceSummary
from grounded_tutor.services.previews import PreviewError
from grounded_tutor.services.source_locks import WorkspaceIngestionBusyError
from grounded_tutor.services.sources import (
    ExternalSourceServiceError,
    SourceIngestionResult,
    SourceNotFoundError,
    SourcePreviewUnavailableError,
    SourceService,
    SourceWorkspaceNotFoundError,
)

router = APIRouter(
    prefix="/api/workspaces/{workspace_id}/sources",
    tags=["sources"],
)

COMMON_ERROR_RESPONSES = {
    404: {"model": ApiErrorResponse, "description": "Workspace or Source not found."},
    409: {"model": ApiErrorResponse, "description": "Source operation conflicts."},
    422: {"model": ApiErrorResponse, "description": "Source input is invalid."},
    500: {"model": ApiErrorResponse, "description": "Local persistence failed."},
    502: {"model": ApiErrorResponse, "description": "External service failed."},
}
FILE_ERROR_RESPONSES = {
    **COMMON_ERROR_RESPONSES,
    413: {"model": ApiErrorResponse, "description": "Source resource limit exceeded."},
    415: {"model": ApiErrorResponse, "description": "File type is unsupported."},
}


@router.post(
    "/text",
    response_model=SourceIngestionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=COMMON_ERROR_RESPONSES,
)
async def ingest_text_source(
    workspace_id: str,
    payload: TextSourceCreate,
    service: Annotated[SourceService, Depends(get_source_service)],
) -> SourceIngestionResponse:
    try:
        result = await service.ingest_text(
            workspace_id=_parse_uuid(workspace_id, "workspace_not_found"),
            name=payload.source_name,
            text=payload.text,
            settings=payload.settings,
        )
        return _ingestion_response(result)
    except SourceWorkspaceNotFoundError:
        _api_error(status.HTTP_404_NOT_FOUND, "workspace_not_found")
    except WorkspaceIngestionBusyError:
        _api_error(status.HTTP_409_CONFLICT, "workspace_ingestion_busy")
    except PreviewError as error:
        _input_error(error)
    except ExternalSourceServiceError:
        _api_error(status.HTTP_502_BAD_GATEWAY, "external_service_error")
    except SourcePersistenceError:
        _api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "persistence_error")


@router.post(
    "/file",
    response_model=SourceIngestionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=FILE_ERROR_RESPONSES,
)
async def ingest_file_source(
    workspace_id: str,
    service: Annotated[SourceService, Depends(get_source_service)],
    file: Annotated[UploadFile, File()],
    settings: Annotated[str, Form()] = "{}",
) -> SourceIngestionResponse:
    chunk_settings = _parse_settings(settings)
    content = await file.read(service.max_upload_bytes + 1)
    try:
        result = await service.ingest_file(
            workspace_id=_parse_uuid(workspace_id, "workspace_not_found"),
            filename=file.filename or "",
            content=content,
            settings=chunk_settings,
        )
        return _ingestion_response(result)
    except SourceWorkspaceNotFoundError:
        _api_error(status.HTTP_404_NOT_FOUND, "workspace_not_found")
    except WorkspaceIngestionBusyError:
        _api_error(status.HTTP_409_CONFLICT, "workspace_ingestion_busy")
    except PreviewError as error:
        _input_error(error)
    except ExternalSourceServiceError:
        _api_error(status.HTTP_502_BAD_GATEWAY, "external_service_error")
    except SourcePersistenceError:
        _api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "persistence_error")


@router.get(
    "",
    response_model=list[SourceResponse],
    responses=COMMON_ERROR_RESPONSES,
)
def list_sources(
    workspace_id: str,
    service: Annotated[SourceService, Depends(get_source_service)],
) -> list[SourceResponse]:
    try:
        return [
            _source_response(source)
            for source in service.list(_parse_uuid(workspace_id, "workspace_not_found"))
        ]
    except SourceWorkspaceNotFoundError:
        _api_error(status.HTTP_404_NOT_FOUND, "workspace_not_found")
    except SourcePersistenceError:
        _api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "persistence_error")


@router.get(
    "/{source_id}/processed-preview",
    response_model=ProcessedPreviewResponse,
    responses=COMMON_ERROR_RESPONSES,
)
async def get_processed_preview(
    workspace_id: str,
    source_id: str,
    service: Annotated[SourceService, Depends(get_source_service)],
) -> ProcessedPreviewResponse:
    try:
        return await service.processed_preview(
            _parse_uuid(workspace_id, "workspace_not_found"),
            _parse_uuid(source_id, "source_not_found"),
        )
    except SourceNotFoundError:
        _api_error(status.HTTP_404_NOT_FOUND, "source_not_found")
    except SourcePreviewUnavailableError:
        _api_error(status.HTTP_409_CONFLICT, "processed_preview_unavailable")
    except ExternalSourceServiceError:
        _api_error(status.HTTP_502_BAD_GATEWAY, "external_service_error")
    except SourcePersistenceError:
        _api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "persistence_error")


def _parse_settings(value: str) -> ChunkSettings:
    try:
        return validate_public_chunk_settings(json.loads(value))
    except (json.JSONDecodeError, ValidationError, ValueError):
        _api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_chunk_settings")


def _parse_uuid(value: str, error_code: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        _api_error(status.HTTP_404_NOT_FOUND, error_code)


def _ingestion_response(result: SourceIngestionResult) -> SourceIngestionResponse:
    return SourceIngestionResponse(
        source=_source_response(result.source),
        processed_preview=result.processed_preview,
    )


def _source_response(source: SourceSummary) -> SourceResponse:
    return SourceResponse(
        id=source.id,
        workspace_id=source.workspace_id,
        name=source.name,
        source_type=source.source_type,
        origin_uri=source.origin_uri,
        status=source.status,
        version=source.version,
        ingestion_config=source.ingestion_config,
        error_message=source.error_message,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def _input_error(error: PreviewError) -> NoReturn:
    status_code = {
        "file_too_large": status.HTTP_413_CONTENT_TOO_LARGE,
        "text_too_large": status.HTTP_413_CONTENT_TOO_LARGE,
        "unsupported_file_type": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    }.get(error.code, status.HTTP_422_UNPROCESSABLE_CONTENT)
    _api_error(status_code, error.code)


def _api_error(status_code: int, code: str) -> NoReturn:
    raise HTTPException(status_code=status_code, detail={"code": code})
