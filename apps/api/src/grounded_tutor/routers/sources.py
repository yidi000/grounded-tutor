from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from grounded_tutor.dependencies import get_source_service
from grounded_tutor.domain.schemas import (
    ApiErrorResponse,
    ProcessedPreviewResponse,
    SourceIngestionResponse,
    SourceResponse,
    TextSourceCreate,
)
from grounded_tutor.repositories.sources import SourcePersistenceError
from grounded_tutor.routers.common import api_error, parse_chunk_settings, parse_uuid
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
            workspace_id=parse_uuid(workspace_id, "workspace_not_found"),
            name=payload.source_name,
            text=payload.text,
            settings=payload.settings,
        )
        return _ingestion_response(result)
    except SourceWorkspaceNotFoundError:
        api_error(status.HTTP_404_NOT_FOUND, "workspace_not_found")
    except WorkspaceIngestionBusyError:
        api_error(status.HTTP_409_CONFLICT, "workspace_ingestion_busy")
    except PreviewError as error:
        _input_error(error)
    except ExternalSourceServiceError:
        api_error(status.HTTP_502_BAD_GATEWAY, "external_service_error")
    except SourcePersistenceError:
        api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "persistence_error")


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
    chunk_settings = parse_chunk_settings(settings)
    content = await file.read(service.max_upload_bytes + 1)
    try:
        result = await service.ingest_file(
            workspace_id=parse_uuid(workspace_id, "workspace_not_found"),
            filename=file.filename or "",
            content=content,
            settings=chunk_settings,
        )
        return _ingestion_response(result)
    except SourceWorkspaceNotFoundError:
        api_error(status.HTTP_404_NOT_FOUND, "workspace_not_found")
    except WorkspaceIngestionBusyError:
        api_error(status.HTTP_409_CONFLICT, "workspace_ingestion_busy")
    except PreviewError as error:
        _input_error(error)
    except ExternalSourceServiceError:
        api_error(status.HTTP_502_BAD_GATEWAY, "external_service_error")
    except SourcePersistenceError:
        api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "persistence_error")


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
            SourceResponse.model_validate(source)
            for source in service.list(parse_uuid(workspace_id, "workspace_not_found"))
        ]
    except SourceWorkspaceNotFoundError:
        api_error(status.HTTP_404_NOT_FOUND, "workspace_not_found")
    except SourcePersistenceError:
        api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "persistence_error")


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
            parse_uuid(workspace_id, "workspace_not_found"),
            parse_uuid(source_id, "source_not_found"),
        )
    except SourceNotFoundError:
        api_error(status.HTTP_404_NOT_FOUND, "source_not_found")
    except SourcePreviewUnavailableError:
        api_error(status.HTTP_409_CONFLICT, "processed_preview_unavailable")
    except ExternalSourceServiceError:
        api_error(status.HTTP_502_BAD_GATEWAY, "external_service_error")
    except SourcePersistenceError:
        api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "persistence_error")


def _ingestion_response(result: SourceIngestionResult) -> SourceIngestionResponse:
    return SourceIngestionResponse(
        source=SourceResponse.model_validate(result.source),
        processed_preview=result.processed_preview,
    )


def _input_error(error: PreviewError) -> NoReturn:
    status_code = {
        "file_too_large": status.HTTP_413_CONTENT_TOO_LARGE,
        "text_too_large": status.HTTP_413_CONTENT_TOO_LARGE,
        "unsupported_file_type": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    }.get(error.code, status.HTTP_422_UNPROCESSABLE_CONTENT)
    api_error(status_code, error.code)
