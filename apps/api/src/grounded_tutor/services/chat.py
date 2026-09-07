from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from time import perf_counter
from uuid import UUID, uuid4

from grounded_tutor.adapters.fastgpt import FastGPTPort, RetrievedChunk, SearchRequest
from grounded_tutor.adapters.generation import (
    GenerationPort,
    GenerationRequest,
    InvalidGenerationOutput,
)
from grounded_tutor.domain.answers import GeneratedAnswer, GroundedAnswer, SuggestedAction
from grounded_tutor.domain.schemas import ChatHistoryResponse
from grounded_tutor.repositories.chat import (
    ChatConversationNotFoundError,
    ChatPersistenceError,
    ChatRepository,
)
from grounded_tutor.repositories.sources import SourcePersistenceError, SourceRepository
from grounded_tutor.services.diagnostic_invites import (
    DiagnosticInviteService,
    InvitePersistenceError,
)
from grounded_tutor.services.grounding import ReadyChunk, ground_generated_answer
from grounded_tutor.services.idempotency import request_hash
from grounded_tutor.services.routing import RoutePolicy
from grounded_tutor.services.tracing import TracePersistenceError, TraceRecorder

logger = logging.getLogger(__name__)

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
    suggested_actions: tuple[SuggestedAction, ...] = ()


class ChatService:
    def __init__(
        self,
        sources: SourceRepository,
        chats: ChatRepository,
        fastgpt: FastGPTPort,
        generation: GenerationPort,
        tracing: TraceRecorder | None = None,
        invites: DiagnosticInviteService | None = None,
    ) -> None:
        self._sources = sources
        self._chats = chats
        self._fastgpt = fastgpt
        self._generation = generation
        self._tracing = tracing
        self._invites = invites

    def history(self, workspace_id: UUID) -> ChatHistoryResponse:
        if self._sources.get_workspace_dataset_id(workspace_id) is None:
            raise ChatWorkspaceNotFoundError
        history = self._chats.history(workspace_id)
        if self._invites is None:
            return history
        try:
            card = self._invites.current(workspace_id)
        except (InvitePersistenceError, ValueError):
            return history
        if card and card.status == "offered":
            from grounded_tutor.domain.answers import SimpleSuggestedAction

            return history.model_copy(
                update={
                    "exchanges": tuple(
                        exchange.model_copy(
                            update={
                                "response": exchange.response.model_copy(
                                    update={
                                        "suggested_actions": (
                                            SimpleSuggestedAction(type="start_diagnostic"),
                                        )
                                    }
                                )
                            }
                        )
                        if exchange.response.message_id == card.message_id
                        else exchange
                        for exchange in history.exchanges
                    )
                }
            )
        return history

    def _with_invitation(self, workspace_id: UUID, result: ChatResult) -> ChatResult:
        if self._invites is None:
            return result
        try:
            actions = self._invites.suggest(workspace_id, result.conversation_id, result.message_id)
        except (InvitePersistenceError, ValueError):
            logger.warning("Unable to update optional diagnostic invitation")
            return result
        return replace(result, suggested_actions=actions)

    async def ask(
        self,
        workspace_id: UUID,
        message: str,
        conversation_id: UUID | None,
        idempotency_key: str,
        *,
        before_persist: Callable[[], None] | None = None,
    ) -> ChatResult:
        failed = False
        try:
            dataset_id = self._sources.get_workspace_dataset_id(workspace_id)
        except SourcePersistenceError:
            failed = True
        if failed:
            raise ChatPersistenceError()
        if dataset_id is None:
            raise ChatWorkspaceNotFoundError
        saved = self._chats.claim_request(
            workspace_id, idempotency_key, request_hash(message, conversation_id)
        )
        if saved is not None:
            invalid = False
            try:
                result = ChatResult(
                    UUID(saved["conversation_id"]),
                    UUID(saved["message_id"]),
                    GroundedAnswer.model_validate(saved["answer"]),
                )
            except (KeyError, TypeError, ValueError):
                invalid = True
            if invalid:
                raise ChatPersistenceError()
            return self._with_invitation(workspace_id, result)
        started = perf_counter()
        trace = {
            "workspace_id": workspace_id,
            "request_id": str(uuid4()),
            "route": RoutePolicy().choose(
                event="ASK_QUESTION", active_mode=None, classified_intent=None
            ),
            "retrieval": {"chunk_ids": [], "scores": [], "chunks": []},
            "generation": {
                "instruction": message,
                "conversation_id": str(conversation_id) if conversation_id else None,
                "prompt_version": "source-material-v1",
                "attempts": [],
            },
            "validation": {"valid": True},
            "timing": {},
        }
        error = None
        try:
            result = await self._ask(
                workspace_id, message, conversation_id, idempotency_key, dataset_id, trace, before_persist
            )
        except BaseException as caught:  # noqa: BLE001 - release the claim on cancellation too.
            error = caught
        if error is not None:
            # Includes cancellation. Completed responses survive uncertain commit errors.
            self._chats.release_request(workspace_id, idempotency_key)
            if not isinstance(error, ChatConversationNotFoundError):
                trace["validation"] = {
                    "valid": False,
                    "error_code": "external_failure"
                    if isinstance(error, ExternalChatServiceError)
                    else "cancelled"
                    if isinstance(error, asyncio.CancelledError)
                    else "unexpected_exception",
                }
                self._record_trace(trace, started)
            raise error
        trace["validation"].update(
            {
                "status": result.answer.status,
                "conversation_id": str(result.conversation_id),
                "message_id": str(result.message_id),
            }
        )
        trace["generation"]["answer"] = result.answer.model_dump(mode="json")
        self._record_trace(trace, started)
        return self._with_invitation(workspace_id, result)

    def _record_trace(self, trace: dict, started: float) -> None:
        trace["timing"]["total_ms"] = (perf_counter() - started) * 1000
        if self._tracing is not None:
            try:
                self._tracing.record(**trace)
            except TracePersistenceError:
                # Diagnostics must not replace the primary result or trigger duplicate work.
                logger.warning("Unable to persist execution trace %s", trace["request_id"])

    async def _generate(self, request: GenerationRequest, trace: dict) -> GeneratedAnswer:
        attempt = {"instruction": request.instruction}
        trace["generation"]["attempts"].append(attempt)
        started = perf_counter()
        try:
            generated = await self._generation.generate_content(request)
        except InvalidGenerationOutput:
            attempt["outcome"] = "invalid_output"
            raise
        except asyncio.CancelledError:
            attempt["outcome"] = "cancelled"
            raise
        except Exception:
            attempt["outcome"] = "external_failure"
            raise
        finally:
            attempt["elapsed_ms"] = (perf_counter() - started) * 1000
        attempt.update({"outcome": "generated", "output": generated.model_dump(mode="json")})
        return generated

    @staticmethod
    def _validate(
        generated: GeneratedAnswer, ready_chunks: dict[str, ReadyChunk], trace: dict
    ) -> GroundedAnswer:
        answer = ground_generated_answer(generated, ready_chunks, allowed_kinds={"answer"})
        valid = not generated.blocks or len(answer.answer_blocks) == len(generated.blocks)
        trace["generation"]["attempts"][-1]["valid"] = valid
        trace["validation"] = {"valid": valid}
        if not valid:
            trace["validation"]["error_code"] = "citation_failure"
        return answer

    async def _ask(
        self,
        workspace_id: UUID,
        message: str,
        conversation_id: UUID | None,
        idempotency_key: str,
        dataset_id: str,
        trace: dict,
        before_persist: Callable[[], None] | None = None,
    ) -> ChatResult:
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
                workspace_id, conversation_id, message, idempotency_key, _insufficient(), before_persist
            )

        external_failure = False
        search_started = perf_counter()
        try:
            raw_chunks = await self._fastgpt.search(SearchRequest(dataset_id, message))
        except Exception:  # noqa: BLE001 - redact every adapter failure.
            external_failure = True
        finally:
            trace["timing"]["retrieval_ms"] = (perf_counter() - search_started) * 1000
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
        trace["retrieval"] = {
            "received_count": len(raw_chunks),
            "chunk_ids": list(ready_chunks),
            "scores": [ready.chunk.score for ready in ready_chunks.values()],
            "chunks": [
                {
                    "chunk_id": ready.chunk.chunk_id,
                    "q": ready.chunk.q,
                    "a": ready.chunk.a,
                    "source_id": str(ready.source.id),
                    "source_name": ready.source.name,
                    "source_version": ready.source.version,
                    "source_type": ready.source.source_type.value,
                    "position": ready.retrieval_position,
                }
                for ready in ready_chunks.values()
            ],
        }
        if not filtered_chunks:
            return self._persist(
                workspace_id, conversation_id, message, idempotency_key, _insufficient(), before_persist
            )

        request = GenerationRequest("ASK", message, tuple(filtered_chunks))
        invalid_output = False
        external_failure = False
        try:
            generated = await self._generate(request, trace)
        except InvalidGenerationOutput:
            invalid_output = True
        except Exception:  # noqa: BLE001 - redact every adapter failure.
            external_failure = True
        if external_failure:
            raise ExternalChatServiceError()
        if invalid_output:
            answer = await self._retry_generation(
                message, tuple(filtered_chunks), ready_chunks, trace
            )
        else:
            answer = self._validate(generated, ready_chunks, trace)
            if not generated.blocks or len(answer.answer_blocks) != len(generated.blocks):
                answer = await self._retry_generation(
                    message, tuple(filtered_chunks), ready_chunks, trace
                )

        return self._persist(workspace_id, conversation_id, message, idempotency_key, answer, before_persist)

    async def _retry_generation(
        self,
        message: str,
        chunks: tuple[RetrievedChunk, ...],
        ready_chunks: dict[str, ReadyChunk],
        trace: dict,
    ) -> GroundedAnswer:
        request = GenerationRequest("ASK", f"{message}\n\n{RETRY_INSTRUCTION}", chunks)
        invalid_output = False
        external_failure = False
        try:
            generated = await self._generate(request, trace)
        except InvalidGenerationOutput:
            invalid_output = True
        except Exception:  # noqa: BLE001 - redact every adapter failure.
            external_failure = True
        if external_failure:
            raise ExternalChatServiceError()
        if invalid_output:
            trace["validation"] = {
                "valid": False,
                "error_code": "citation_failure",
                "reason": "invalid_output",
            }
            return _insufficient()
        return self._validate(generated, ready_chunks, trace)

    def _persist(
        self,
        workspace_id: UUID,
        conversation_id: UUID | None,
        message: str,
        idempotency_key: str,
        answer: GroundedAnswer,
        before_persist: Callable[[], None] | None = None,
    ) -> ChatResult:
        # The orchestration callback only stages ORM changes in this same transaction.
        if before_persist is not None:
            before_persist()
        persisted = self._chats.persist_exchange(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            user_content=message,
            answer=answer,
            idempotency_key=idempotency_key,
        )
        return ChatResult(persisted.conversation_id, persisted.message_id, answer)


def _insufficient() -> GroundedAnswer:
    return GroundedAnswer(status="insufficient_material", answer_blocks=(), citations=())
