from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import literal_column, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from grounded_tutor.domain.answers import GroundedAnswer, SimpleSuggestedAction
from grounded_tutor.domain.models import Conversation, Message
from grounded_tutor.domain.schemas import ChatHistoryExchange, ChatHistoryResponse, ChatResponse


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

    def history(self, workspace_id: UUID) -> ChatHistoryResponse:
        failed = False
        try:
            # ponytail: P0 is SQLite; rowid preserves insertion order when timestamps
            # tie. Add an explicit sequence and pagination before PostgreSQL/large histories.
            messages = self._session.scalars(
                select(Message)
                .join(Conversation)
                .where(Conversation.workspace_id == workspace_id, Message.mode == "ask")
                .order_by(literal_column("messages.rowid"))
            )
            questions: dict[UUID, str] = {}
            exchanges = []
            for message in messages:
                if message.role == "user":
                    questions[message.conversation_id] = message.content
                elif message.role == "assistant":
                    insufficient = (
                        message.content == "insufficient_material" and not message.content_blocks
                    )
                    exchanges.append(
                        ChatHistoryExchange(
                            question=questions.pop(message.conversation_id),
                            response=ChatResponse(
                                conversation_id=message.conversation_id,
                                message_id=message.id,
                                status="insufficient_material" if insufficient else "ok",
                                answer_blocks=message.content_blocks or [],
                                citations=message.citations if message.content_blocks else [],
                                suggested_actions=(
                                    SimpleSuggestedAction(type="add_material"),
                                    SimpleSuggestedAction(type="rephrase"),
                                )
                                if insufficient
                                else (),
                            ),
                            legacy_content=message.content
                            if message.content_blocks is None and not insufficient
                            else None,
                        )
                    )
            return ChatHistoryResponse(exchanges=tuple(exchanges))
        except (SQLAlchemyError, ValueError, KeyError):
            self._rollback()
            failed = True
        if failed:
            raise ChatPersistenceError()

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
                content_blocks=[block.model_dump(mode="json") for block in answer.answer_blocks],
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

    def conversation_belongs_to_workspace(self, workspace_id: UUID, conversation_id: UUID) -> bool:
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

    def _conversation(self, workspace_id: UUID, conversation_id: UUID | None) -> Conversation:
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
