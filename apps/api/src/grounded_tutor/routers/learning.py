from functools import partial
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from grounded_tutor.dependencies import get_check_service, get_lesson_service
from grounded_tutor.domain.schemas import ApiErrorResponse
from grounded_tutor.domain.teaching import (
    CheckAnswerRequest,
    CheckContinueRequest,
    CheckResult,
    CheckStartRequest,
    CheckView,
    LessonRequest,
    LessonView,
)
from grounded_tutor.routers.common import DEMO_WRITE_ERROR_RESPONSE, learning_errors
from grounded_tutor.services.checks import CheckService
from grounded_tutor.services.learning_context import LearningConflictError, LearningNotFoundError
from grounded_tutor.services.lessons import LessonService

router = APIRouter(
    prefix="/api/workspaces/{workspace_id}/learning",
    tags=["learning"],
    responses={
        **DEMO_WRITE_ERROR_RESPONSE,
        **{code: {"model": ApiErrorResponse} for code in (404, 409, 422, 500, 502)},
    },
)
Lessons = Annotated[LessonService, Depends(get_lesson_service)]
Checks = Annotated[CheckService, Depends(get_check_service)]
public_errors = partial(
    learning_errors,
    (LearningNotFoundError, "learning_not_found"),
    (LearningConflictError, "learning_conflict"),
)


@router.post("/concepts/{concept_id}/lessons", response_model=LessonView)
async def lesson(workspace_id: UUID, concept_id: UUID, payload: LessonRequest, service: Lessons):
    with public_errors():
        return await service.start(workspace_id, concept_id, payload)


@router.get("/lessons/{lesson_id}", response_model=LessonView)
def get_lesson(workspace_id: UUID, lesson_id: UUID, service: Lessons):
    with public_errors():
        return service.get(workspace_id, lesson_id)


@router.post("/concepts/{concept_id}/checks", response_model=CheckView)
async def check(workspace_id: UUID, concept_id: UUID, payload: CheckStartRequest, service: Checks):
    with public_errors():
        return await service.start(workspace_id, concept_id, payload)


@router.get("/checks/{assessment_id}", response_model=CheckView)
def get_check(workspace_id: UUID, assessment_id: UUID, service: Checks):
    with public_errors():
        return service.get(workspace_id, assessment_id)


@router.post("/checks/{assessment_id}/answers", response_model=CheckResult)
async def answer(
    workspace_id: UUID, assessment_id: UUID, payload: CheckAnswerRequest, service: Checks
):
    with public_errors():
        return await service.submit(workspace_id, assessment_id, payload)


@router.post("/checks/{assessment_id}/continue", response_model=CheckResult)
async def continue_check(
    workspace_id: UUID, assessment_id: UUID, payload: CheckContinueRequest, service: Checks
):
    with public_errors():
        return await service.continue_after_skip(workspace_id, assessment_id, payload)
