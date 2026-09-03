from __future__ import annotations

import json
from typing import Literal, NoReturn
from uuid import UUID

from fastapi import HTTPException, status
from pydantic import ValidationError

from grounded_tutor.config import Settings, capability_request_is_supported
from grounded_tutor.domain.errors import PublicErrorCode
from grounded_tutor.domain.ingestion import ChunkSettings, validate_public_chunk_settings
from grounded_tutor.domain.schemas import ApiErrorResponse

DEMO_WRITE_ERROR_RESPONSE = {
    403: {"model": ApiErrorResponse, "description": "Demo mode is read-only."}
}


def api_error(status_code: int, code: PublicErrorCode) -> NoReturn:
    raise HTTPException(status_code=status_code, detail={"code": code})


def parse_uuid(
    value: str, error_code: Literal["source_not_found", "workspace_not_found"]
) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        api_error(status.HTTP_404_NOT_FOUND, error_code)


def parse_chunk_settings(value: str) -> ChunkSettings:
    try:
        return validate_public_chunk_settings(json.loads(value))
    except (json.JSONDecodeError, ValidationError, ValueError):
        api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_chunk_settings")


def require_chunk_capability(
    settings: ChunkSettings, runtime_settings: Settings
) -> None:
    if not capability_request_is_supported(
        requested=settings.custom_pdf_parse,
        supported=runtime_settings.supports_custom_pdf_parse,
    ):
        api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_chunk_settings")
