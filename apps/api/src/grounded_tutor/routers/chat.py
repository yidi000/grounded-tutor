from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from grounded_tutor.dependencies import get_chat_service
from grounded_tutor.domain.answers import SimpleSuggestedAction
from grounded_tutor.domain.schemas import ApiErrorResponse, ChatRequest, ChatResponse
from grounded_tutor.repositories.chat import ChatConversationNotFoundError, ChatPersistenceError
from grounded_tutor.repositories.sources import SourcePersistenceError
from grounded_tutor.routers.common import DEMO_WRITE_ERROR_RESPONSE, api_error, parse_uuid
from grounded_tutor.services.chat import (
    ChatService,
    ChatWorkspaceNotFoundError,
    ExternalChatServiceError,
)

router = APIRouter(prefix="/api/workspaces/{workspace_id}/chat", tags=["chat"])

ERROR_RESPONSES = {
    **DEMO_WRITE_ERROR_RESPONSE,
    404: {"model": ApiErrorResponse, "description": "Workspace or conversation not found."},
    422: {"model": ApiErrorResponse, "description": "Chat input is invalid."},
    500: {"model": ApiErrorResponse, "description": "Local persistence failed."},
    502: {"model": ApiErrorResponse, "description": "External service failed."},
}


@router.post("", response_model=ChatResponse, responses=ERROR_RESPONSES)
async def ask(
    workspace_id: str,
    payload: ChatRequest,
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatResponse:
    try:
        result = await service.ask(
            parse_uuid(workspace_id, "workspace_not_found"),
            payload.message,
            payload.conversation_id,
            payload.idempotency_key,
        )
    except (ChatWorkspaceNotFoundError, ChatConversationNotFoundError):
        api_error(status.HTTP_404_NOT_FOUND, "workspace_not_found")
    except (ChatPersistenceError, SourcePersistenceError):
        api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "persistence_error")
    except ExternalChatServiceError:
        api_error(status.HTTP_502_BAD_GATEWAY, "external_service_error")

    actions = (
        (
            SimpleSuggestedAction(type="add_material"),
            SimpleSuggestedAction(type="rephrase"),
        )
        if result.answer.status == "insufficient_material"
        else ()
    )
    return ChatResponse(
        conversation_id=result.conversation_id,
        message_id=result.message_id,
        status=result.answer.status,
        answer_blocks=result.answer.answer_blocks,
        citations=result.answer.citations,
        suggested_actions=actions,
    )
