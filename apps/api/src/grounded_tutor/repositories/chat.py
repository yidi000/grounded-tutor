from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from grounded_tutor.domain.answers import GroundedAnswer
from grounded_tutor.domain.models import Conversation, Message


class ChatPersistenceError(RuntimeError):
    """A deliberately redacted chat transaction failure."""

    def __init__(self) -> None:
        super().__init__("Chat persistence failed.")


class ChatConversationNotFoundError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PersistedChat:
    conversation_id: UUID
    message_id: UUID


class ChatRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def persist_exchange(
        self,
        *,
        workspace_id: UUID,
        conversation_id: UUID | None,
        user_content: str,
        answer: GroundedAnswer,
        idempotency_key: str,
    ) -> PersistedChat:
        persistence_failed = False
        try:
            conversation = self._conversation(workspace_id, conversation_id)
            user_message = Message(
                conversation_id=conversation.id,
                role="user",
                mode="ask",
                content=user_content,
                content_blocks=None,
                citations=[],
                idempotency_key=None,
            )
            assistant_message = Message(
                conversation_id=conversation.id,
                role="assistant",
                mode="ask",
                content=(
                    "\n\n".join(block.text for block in answer.answer_blocks)
                    if answer.status == "ok"
                    else answer.status
                ),
                content_blocks=[
                    block.model_dump(mode="json") for block in answer.answer_blocks
                ],
                citations=[citation.model_dump(mode="json") for citation in answer.citations],
                idempotency_key=idempotency_key,
            )
            self._session.add_all((user_message, assistant_message))
            self._session.flush()
            result = PersistedChat(conversation.id, assistant_message.id)
            self._session.commit()
        except ChatConversationNotFoundError:
            self._rollback()
            raise
        except SQLAlchemyError:
            self._rollback()
            persistence_failed = True
        if persistence_failed:
            raise ChatPersistenceError()
        return result

    def conversation_belongs_to_workspace(
        self, workspace_id: UUID, conversation_id: UUID
    ) -> bool:
        persistence_failed = False
        try:
            belongs = self._session.scalar(
                select(Conversation.id).where(
                    Conversation.id == conversation_id,
                    Conversation.workspace_id == workspace_id,
                )
            )
        except SQLAlchemyError:
            self._rollback()
            persistence_failed = True
        if persistence_failed:
            raise ChatPersistenceError()
        return belongs is not None

    def _conversation(
        self, workspace_id: UUID, conversation_id: UUID | None
    ) -> Conversation:
        if conversation_id is None:
            conversation = Conversation(workspace_id=workspace_id)
            self._session.add(conversation)
            self._session.flush()
            return conversation
        conversation = self._session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.workspace_id == workspace_id,
            )
        )
        if conversation is None:
            raise ChatConversationNotFoundError
        return conversation

    def _rollback(self) -> None:
        try:
            self._session.rollback()
        except SQLAlchemyError:
            self._session.close()
