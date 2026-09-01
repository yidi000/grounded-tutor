from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from grounded_tutor.adapters.fastgpt import FastGPTPort
from grounded_tutor.db import get_session
from grounded_tutor.repositories.workspaces import WorkspaceRepository
from grounded_tutor.services.workspaces import WorkspaceService


def get_fastgpt(request: Request) -> FastGPTPort:
    return request.app.state.fastgpt


def get_workspace_service(
    session: Annotated[Session, Depends(get_session)],
    fastgpt: Annotated[FastGPTPort, Depends(get_fastgpt)],
) -> WorkspaceService:
    return WorkspaceService(WorkspaceRepository(session), fastgpt)
