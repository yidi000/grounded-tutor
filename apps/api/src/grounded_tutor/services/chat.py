from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from grounded_tutor.adapters.fastgpt import FastGPTPort, RetrievedChunk, SearchRequest
from grounded_tutor.adapters.generation import (
    GenerationPort,
    GenerationRequest,
    InvalidGenerationOutput,
)
from grounded_tutor.domain.answers import GroundedAnswer
from grounded_tutor.domain.schemas import ChatHistoryResponse
from grounded_tutor.repositories.chat import (
    ChatConversationNotFoundError,
    ChatPersistenceError,
    ChatRepository,
)
from grounded_tutor.repositories.sources import SourcePersistenceError, SourceRepository
from grounded_tutor.services.grounding import ReadyChunk, ground_generated_answer

RETRY_INSTRUCTION = (
    "Validation correction: return only unique nonblank answer blocks, and give every block "
    "one or more chunk_ids copied exactly from the supplied chunks. Return JSON only."
)


class ChatWorkspaceNotFoundError(RuntimeError):
    pass


class ExternalChatServiceError(RuntimeError):
    """A redacted external-service failure."""

    def __init__(self) -> None:
        super().__init__("Chat external service failed.")


@dataclass(frozen=True, slots=True)
class ChatResult:
    conversation_id: UUID
    message_id: UUID
    answer: GroundedAnswer


class ChatService:
    def __init__(
        self,
        sources: SourceRepository,
        chats: ChatRepository,
        fastgpt: FastGPTPort,
        generation: GenerationPort,
    ) -> None:
        self._sources = sources
        self._chats = chats
        self._fastgpt = fastgpt
        self._generation = generation

    def history(self, workspace_id: UUID) -> ChatHistoryResponse:
        if self._sources.get_workspace_dataset_id(workspace_id) is None:
            raise ChatWorkspaceNotFoundError
        return self._chats.history(workspace_id)

    async def ask(
        self,
        workspace_id: UUID,
        message: str,
        conversation_id: UUID | None,
        idempotency_key: str,
    ) -> ChatResult:
        persistence_failure = False
        try:
            dataset_id = self._sources.get_workspace_dataset_id(workspace_id)
        except SourcePersistenceError:
            persistence_failure = True
        if persistence_failure:
            raise ChatPersistenceError()
        if dataset_id is None:
            raise ChatWorkspaceNotFoundError
        if conversation_id is not None and not self._chats.conversation_belongs_to_workspace(
            workspace_id, conversation_id
        ):
            raise ChatConversationNotFoundError
        persistence_failure = False
        try:
            ready_sources = self._sources.ready_collection_ids(workspace_id)
        except SourcePersistenceError:
            persistence_failure = True
        if persistence_failure:
            raise ChatPersistenceError()
        if not ready_sources:
            return self._persist(
                workspace_id, conversation_id, message, idempotency_key, _insufficient()
            )

        external_failure = False
        try:
            raw_chunks = await self._fastgpt.search(SearchRequest(dataset_id, message))
        except Exception:  # noqa: BLE001 - redact every adapter failure.
            external_failure = True
        if external_failure:
            raise ExternalChatServiceError()

        ready_chunks: dict[str, ReadyChunk] = {}
        filtered_chunks = []
        for chunk in raw_chunks:
            source = ready_sources.get(chunk.collection_id)
            if source is None or chunk.chunk_id in ready_chunks:
                continue
            filtered_chunks.append(chunk)
            ready_chunks[chunk.chunk_id] = ReadyChunk(
                chunk=chunk,
                source=source,
                retrieval_position=len(filtered_chunks),
            )
        if not filtered_chunks:
            return self._persist(
                workspace_id, conversation_id, message, idempotency_key, _insufficient()
            )

        request = GenerationRequest("ASK", message, tuple(filtered_chunks))
        invalid_output = False
        external_failure = False
        try:
            generated = await self._generation.generate_content(request)
        except InvalidGenerationOutput:
            invalid_output = True
        except Exception:  # noqa: BLE001 - redact every adapter failure.
            external_failure = True
        if external_failure:
            raise ExternalChatServiceError()
        if invalid_output:
            answer = await self._retry_generation(message, tuple(filtered_chunks), ready_chunks)
        else:
            answer = ground_generated_answer(
                generated, ready_chunks, allowed_kinds={"answer"}
            )
            if not generated.blocks or len(answer.answer_blocks) != len(generated.blocks):
                answer = await self._retry_generation(
                    message, tuple(filtered_chunks), ready_chunks
                )

        return self._persist(
            workspace_id, conversation_id, message, idempotency_key, answer
        )

    async def _retry_generation(
        self,
        message: str,
        chunks: tuple[RetrievedChunk, ...],
        ready_chunks: dict[str, ReadyChunk],
    ) -> GroundedAnswer:
        request = GenerationRequest(
            "ASK", f"{message}\n\n{RETRY_INSTRUCTION}", chunks
        )
        invalid_output = False
        external_failure = False
        try:
            generated = await self._generation.generate_content(request)
        except InvalidGenerationOutput:
            invalid_output = True
        except Exception:  # noqa: BLE001 - redact every adapter failure.
            external_failure = True
        if external_failure:
            raise ExternalChatServiceError()
        if invalid_output:
            return _insufficient()
        return ground_generated_answer(generated, ready_chunks, allowed_kinds={"answer"})

    def _persist(
        self,
        workspace_id: UUID,
        conversation_id: UUID | None,
        message: str,
        idempotency_key: str,
        answer: GroundedAnswer,
    ) -> ChatResult:
        persisted = self._chats.persist_exchange(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            user_content=message,
            answer=answer,
            idempotency_key=idempotency_key,
        )
        return ChatResult(persisted.conversation_id, persisted.message_id, answer)


def _insufficient() -> GroundedAnswer:
    return GroundedAnswer(
        status="insufficient_material", answer_blocks=(), citations=()
    )
