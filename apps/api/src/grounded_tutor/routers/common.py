from __future__ import annotations

import json
from typing import NoReturn
from uuid import UUID

from fastapi import HTTPException, status
from pydantic import ValidationError

from grounded_tutor.domain.ingestion import ChunkSettings, validate_public_chunk_settings


def api_error(status_code: int, code: str) -> NoReturn:
    raise HTTPException(status_code=status_code, detail={"code": code})


def parse_uuid(value: str, error_code: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        api_error(status.HTTP_404_NOT_FOUND, error_code)


def parse_chunk_settings(value: str) -> ChunkSettings:
    try:
        return validate_public_chunk_settings(json.loads(value))
    except (json.JSONDecodeError, ValidationError, ValueError):
        api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_chunk_settings")
