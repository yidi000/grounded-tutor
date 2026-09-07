from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from grounded_tutor.adapters.fastgpt import FastGPTPort
from grounded_tutor.adapters.generation import GenerationPort
from grounded_tutor.config import Settings, get_settings
from grounded_tutor.db import get_session
from grounded_tutor.repositories.chat import ChatRepository
from grounded_tutor.repositories.sources import SourceRepository
from grounded_tutor.repositories.workspaces import WorkspaceRepository
from grounded_tutor.services.chat import ChatService
from grounded_tutor.services.previews import PreviewService
from grounded_tutor.services.source_locks import WorkspaceLockRegistry
from grounded_tutor.services.sources import SourceService
from grounded_tutor.services.tracing import TraceRecorder
from grounded_tutor.services.workspaces import WorkspaceService


def get_fastgpt(request: Request) -> FastGPTPort:
    return request.app.state.fastgpt


def get_generation(request: Request) -> GenerationPort:
    return request.app.state.generation


def get_source_locks(request: Request) -> WorkspaceLockRegistry:
    return request.app.state.source_locks


def get_workspace_service(
    session: Annotated[Session, Depends(get_session)],
    fastgpt: Annotated[FastGPTPort, Depends(get_fastgpt)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> WorkspaceService:
    return WorkspaceService(WorkspaceRepository(session), fastgpt, settings)


def get_preview_service(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PreviewService:
    return PreviewService(
        WorkspaceRepository(session),
        max_upload_bytes=settings.max_upload_bytes,
        max_preview_text_bytes=settings.max_preview_text_bytes,
        max_extracted_characters=settings.max_extracted_characters,
        supports_image_files=settings.supports_image_files,
    )


def get_source_service(
    session: Annotated[Session, Depends(get_session)],
    fastgpt: Annotated[FastGPTPort, Depends(get_fastgpt)],
    locks: Annotated[WorkspaceLockRegistry, Depends(get_source_locks)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SourceService:
    return SourceService(
        SourceRepository(session),
        fastgpt,
        locks,
        max_upload_bytes=settings.max_upload_bytes,
        max_text_bytes=settings.max_preview_text_bytes,
        max_extracted_characters=settings.max_extracted_characters,
        supports_image_files=settings.supports_image_files,
    )


def get_chat_service(
    session: Annotated[Session, Depends(get_session)],
    fastgpt: Annotated[FastGPTPort, Depends(get_fastgpt)],
    generation: Annotated[GenerationPort, Depends(get_generation)],
) -> ChatService:
    return ChatService(
        SourceRepository(session),
        ChatRepository(session),
        fastgpt,
        generation,
        tracing=TraceRecorder(session),
    )
