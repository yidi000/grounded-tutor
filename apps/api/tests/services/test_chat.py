from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from grounded_tutor.adapters.fakes import FakeFastGPT, FakeGeneration
from grounded_tutor.adapters.fastgpt import ExternalServiceError, RetrievedChunk
from grounded_tutor.adapters.generation import InvalidGenerationOutput
from grounded_tutor.db import create_database_engine
from grounded_tutor.domain.answers import GeneratedAnswer, GeneratedBlock
from grounded_tutor.domain.models import (
    Base,
    Conversation,
    Message,
    Source,
    SourceStatus,
    SourceType,
    Workspace,
)
from grounded_tutor.repositories.chat import (
    ChatConversationNotFoundError,
    ChatPersistenceError,
    ChatRepository,
)
from grounded_tutor.repositories.sources import (
    SourcePersistenceError,
    SourcePersistenceOutcome,
    SourceRepository,
)
from grounded_tutor.services.chat import (
    ChatService,
    ChatWorkspaceNotFoundError,
    ExternalChatServiceError,
)


def _answer(*blocks: GeneratedBlock) -> GeneratedAnswer:
    return GeneratedAnswer(blocks=blocks)


def _block(
    text: str = "均值是平均数。",
    *,
    identifier: str = "block-1",
    kind: str = "answer",
    chunk_ids: tuple[str, ...] = ("chunk-ready",),
) -> GeneratedBlock:
    return GeneratedBlock(id=identifier, kind=kind, text=text, chunk_ids=chunk_ids)  # type: ignore[arg-type]


@pytest.fixture
def session(tmp_path) -> Session:
    engine = create_database_engine(
        type("TestSettings", (), {"database_url": f"sqlite:///{tmp_path / 'chat.db'}"})()
    )
    Base.metadata.create_all(engine)
    database_session = Session(engine)
    try:
        yield database_session
    finally:
        database_session.close()
        engine.dispose()


@pytest.fixture
def workspace(session: Session) -> Workspace:
    workspace = Workspace(title="统计", dataset_id="dataset-current")
    session.add(workspace)
    session.commit()
    return workspace


def _ready_source(
    session: Session,
    workspace: Workspace,
    *,
    collection_id: str = "collection-ready",
    name: str = "本地统计讲义",
) -> Source:
    source = Source(
        workspace_id=workspace.id,
        name=name,
        source_type=SourceType.TEXT,
        status=SourceStatus.READY,
        collection_id=collection_id,
        ingestion_config={},
    )
    session.add(source)
    session.commit()
    return source


def _service(
    session: Session,
    fastgpt: FakeFastGPT,
    generation: FakeGeneration,
) -> ChatService:
    return ChatService(
        SourceRepository(session),
        ChatRepository(session),
        fastgpt,
        generation,
    )


def _exception_surface(error: BaseException, seen: set[int] | None = None) -> str:
    seen = seen or set()
    if id(error) in seen:
        return ""
    seen.add(id(error))
    parts = [repr(error), str(error)]
    for value in (*error.args, error.__cause__, error.__context__):
        if isinstance(value, BaseException):
            parts.append(_exception_surface(value, seen))
        else:
            parts.append(repr(value))
    return " ".join(parts)


@pytest.mark.asyncio
async def test_no_ready_sources_persists_insufficient_without_external_calls(
    session: Session, workspace: Workspace
) -> None:
    fastgpt = FakeFastGPT()
    generation = FakeGeneration(_answer(_block()))

    result = await _service(session, fastgpt, generation).ask(
        workspace.id, "什么是均值？", None, "request-1"
    )

    assert result.answer.status == "insufficient_material"
    assert result.answer.answer_blocks == ()
    assert result.answer.citations == ()
    assert fastgpt.search_calls == []
    assert generation.calls == []
    messages = {message.role: message for message in session.scalars(select(Message))}
    assert messages["user"].idempotency_key is None
    assert messages["assistant"].idempotency_key == "request-1"
    assert messages["user"].content == "什么是均值？"
    assert messages["user"].content_blocks is None
    assert messages["assistant"].content == "insufficient_material"
    assert messages["assistant"].content_blocks == []
    assert messages["assistant"].citations == []


@pytest.mark.asyncio
async def test_searches_once_and_filters_non_ready_and_cross_workspace_hits(
    session: Session, workspace: Workspace
) -> None:
    ready = _ready_source(session, workspace)
    other_workspace = Workspace(title="Other", dataset_id="dataset-other")
    session.add(other_workspace)
    session.commit()
    cross_source = _ready_source(
        session,
        other_workspace,
        collection_id="collection-other-workspace",
        name="Cross workspace secret",
    )
    pending = Source(
        workspace_id=workspace.id,
        name="Pending secret",
        source_type=SourceType.TEXT,
        status=SourceStatus.REVIEW,
        collection_id="collection-review",
        ingestion_config={},
    )
    session.add(pending)
    session.commit()
    fastgpt = FakeFastGPT()
    fastgpt.search_results_override = (
        RetrievedChunk("chunk-ready", ready.collection_id, "provider name", "均值", "本地证据", 0.9),
        RetrievedChunk(
            "chunk-review", pending.collection_id, "pending", "q", "not ready", 0.8
        ),
        RetrievedChunk(
            "chunk-cross", cross_source.collection_id, "cross", "q", "other workspace", 0.7
        ),
    )
    generation = FakeGeneration(_answer(_block()))

    result = await _service(session, fastgpt, generation).ask(
        workspace.id, "解释均值", None, "request-2"
    )

    assert len(fastgpt.search_calls) == 1
    search = fastgpt.search_calls[0]
    assert (
        search.dataset_id,
        search.text,
        search.search_mode,
        search.limit,
        search.using_rerank,
        search.extension_query,
    ) == ("dataset-current", "解释均值", "mixedRecall", 5000, False, False)
    assert len(generation.calls) == 1
    assert [chunk.chunk_id for chunk in generation.calls[0].chunks] == ["chunk-ready"]
    assert result.answer.citations[0].source_id == ready.id
    assert result.answer.citations[0].source_name == "本地统计讲义"


@pytest.mark.asyncio
async def test_no_ready_search_hit_skips_generation_and_persists_insufficient(
    session: Session, workspace: Workspace
) -> None:
    _ready_source(session, workspace)
    fastgpt = FakeFastGPT()
    fastgpt.search_results_override = (
        RetrievedChunk("chunk-remote", "remote-only", "remote", "q", "a", 0.9),
    )
    generation = FakeGeneration(_answer(_block()))

    result = await _service(session, fastgpt, generation).ask(
        workspace.id, "question", None, "request-3"
    )

    assert result.answer.status == "insufficient_material"
    assert len(fastgpt.search_calls) == 1
    assert generation.calls == []


@pytest.mark.asyncio
async def test_invalid_json_retries_once_then_uses_valid_language_preserving_answer(
    session: Session, workspace: Workspace
) -> None:
    ready = _ready_source(session, workspace)
    fastgpt = FakeFastGPT()
    fastgpt.search_results_override = (
        RetrievedChunk("chunk-ready", ready.collection_id, "provider", "q", "SOURCE-TEXT", 0.9),
    )
    generation = FakeGeneration(
        InvalidGenerationOutput(),
        _answer(_block("均值就是所有数值之和除以数量。")),
    )

    result = await _service(session, fastgpt, generation).ask(
        workspace.id, "请用中文回答", None, "request-4"
    )

    assert len(generation.calls) == 2
    assert generation.calls[0].instruction == "请用中文回答"
    assert "validation" in generation.calls[1].instruction.lower()
    assert "SOURCE-TEXT" not in generation.calls[1].instruction
    assert len(generation.calls[1].instruction) <= 8_500
    assert result.answer.answer_blocks[0].text == "均值就是所有数值之和除以数量。"


@pytest.mark.asyncio
async def test_grounding_invalid_first_response_retries_and_drops_second_pass_invalid_blocks(
    session: Session, workspace: Workspace
) -> None:
    ready = _ready_source(session, workspace)
    fastgpt = FakeFastGPT()
    fastgpt.search_results_override = (
        RetrievedChunk("chunk-ready", ready.collection_id, "provider", "q", "evidence", 0.9),
    )
    generation = FakeGeneration(
        _answer(_block("unsupported first", chunk_ids=("missing",))),
        _answer(
            _block("supported second"),
            _block("still unsupported", identifier="block-2", chunk_ids=("missing",)),
        ),
    )

    result = await _service(session, fastgpt, generation).ask(
        workspace.id, "question", None, "request-5"
    )

    assert len(generation.calls) == 2
    assert [block.text for block in result.answer.answer_blocks] == ["supported second"]
    assert len(fastgpt.search_calls) == 1


@pytest.mark.asyncio
async def test_second_invalid_response_becomes_insufficient_after_exactly_one_retry(
    session: Session, workspace: Workspace
) -> None:
    ready = _ready_source(session, workspace)
    fastgpt = FakeFastGPT()
    fastgpt.search_results_override = (
        RetrievedChunk("chunk-ready", ready.collection_id, "provider", "q", "evidence", 0.9),
    )
    generation = FakeGeneration(
        _answer(_block("first", chunk_ids=())),
        _answer(_block("second", kind="definition")),
    )

    result = await _service(session, fastgpt, generation).ask(
        workspace.id, "question", None, "request-6"
    )

    assert len(generation.calls) == 2
    assert result.answer.status == "insufficient_material"
    assert result.answer.answer_blocks == ()


@pytest.mark.asyncio
async def test_external_failure_is_not_retried_or_persisted(
    session: Session, workspace: Workspace
) -> None:
    ready = _ready_source(session, workspace)
    fastgpt = FakeFastGPT()
    fastgpt.search_results_override = (
        RetrievedChunk("chunk-ready", ready.collection_id, "provider", "q", "evidence", 0.9),
    )
    generation = FakeGeneration(
        ExternalServiceError(
            service="generation",
            category="network",
            safe_message="private-prompt private-header private-body",
        )
    )

    with pytest.raises(ExternalChatServiceError) as captured:
        await _service(session, fastgpt, generation).ask(
            workspace.id, "question", None, "request-7"
        )

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert "private" not in str(captured.value)
    assert len(generation.calls) == 1
    assert list(session.scalars(select(Message))) == []


@pytest.mark.asyncio
async def test_search_failure_detaches_private_provider_context(
    session: Session, workspace: Workspace
) -> None:
    _ready_source(session, workspace)
    fastgpt = FakeFastGPT()
    fastgpt.failures["search"] = RuntimeError(
        "private-prompt private-header private-provider-body"
    )

    with pytest.raises(ExternalChatServiceError) as captured:
        await _service(session, fastgpt, FakeGeneration()).ask(
            workspace.id, "question", None, "request-search-error"
        )

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert "private" not in str(captured.value)


@pytest.mark.asyncio
async def test_retry_failure_detaches_private_provider_context(
    session: Session, workspace: Workspace
) -> None:
    ready = _ready_source(session, workspace)
    fastgpt = FakeFastGPT()
    fastgpt.search_results_override = (
        RetrievedChunk("chunk-ready", ready.collection_id, "provider", "q", "evidence", 0.9),
    )
    generation = FakeGeneration(
        InvalidGenerationOutput(),
        ExternalServiceError(
            service="generation",
            category="network",
            safe_message="private-retry-prompt private-retry-body",
        ),
    )

    with pytest.raises(ExternalChatServiceError) as captured:
        await _service(session, fastgpt, generation).ask(
            workspace.id, "question", None, "request-retry-error"
        )

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert "private" not in str(captured.value)
    assert len(generation.calls) == 2


@pytest.mark.asyncio
async def test_missing_workspace_uses_stable_not_found_path(session: Session) -> None:
    fastgpt = FakeFastGPT()
    generation = FakeGeneration(_answer(_block()))

    with pytest.raises(ChatWorkspaceNotFoundError):
        await _service(session, fastgpt, generation).ask(
            UUID(int=999), "question", None, "request-8"
        )

    assert fastgpt.search_calls == []
    assert generation.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_name", ["get_workspace_dataset_id", "ready_collection_ids"]
)
async def test_source_read_failure_detaches_private_sql_context_before_public_error(
    session: Session,
    workspace: Workspace,
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
) -> None:
    sources = SourceRepository(session)

    def fail_read(_workspace_id: UUID):
        try:
            raise SQLAlchemyError(
                "params=(private-user-text, private-idempotency-key), SELECT secret"
            )
        except SQLAlchemyError as error:
            raise SourcePersistenceError(
                outcome=SourcePersistenceOutcome.DEFINITELY_UNCOMMITTED
            ) from error

    monkeypatch.setattr(sources, method_name, fail_read)
    fastgpt = FakeFastGPT()
    generation = FakeGeneration()
    service = ChatService(sources, ChatRepository(session), fastgpt, generation)

    with pytest.raises(ChatPersistenceError) as captured:
        await service.ask(workspace.id, "private-user-text", None, "private-idempotency-key")

    surface = _exception_surface(captured.value)
    assert "private-user-text" not in surface
    assert "private-idempotency-key" not in surface
    assert "SELECT secret" not in surface
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert fastgpt.search_calls == []
    assert generation.calls == []


@pytest.mark.asyncio
async def test_provided_conversation_must_belong_to_workspace(
    session: Session, workspace: Workspace
) -> None:
    other = Workspace(title="Other", dataset_id="dataset-other-conversation")
    session.add(other)
    session.flush()
    conversation = Conversation(workspace_id=other.id)
    session.add(conversation)
    session.commit()
    ready = _ready_source(session, workspace)
    fastgpt = FakeFastGPT()
    fastgpt.search_results_override = (
        RetrievedChunk("chunk-ready", ready.collection_id, "provider", "q", "evidence", 0.9),
    )
    generation = FakeGeneration(_answer(_block()))

    with pytest.raises(ChatConversationNotFoundError):
        await _service(session, fastgpt, generation).ask(
            workspace.id, "question", conversation.id, "request-9"
        )

    assert fastgpt.search_calls == []
    assert generation.calls == []
    assert list(session.scalars(select(Message))) == []


@pytest.mark.asyncio
async def test_persistence_failure_rolls_back_both_messages(
    session: Session, workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    generation = FakeGeneration(_answer(_block()))

    def fail_commit() -> None:
        raise SQLAlchemyError(
            "params=(user-secret, idempotency-secret), private database detail"
        )

    monkeypatch.setattr(session, "commit", fail_commit)

    with pytest.raises(ChatPersistenceError, match="Chat persistence failed") as captured:
        await _service(session, FakeFastGPT(), generation).ask(
            workspace.id, "question", None, "request-10"
        )

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert "secret" not in str(captured.value)
    assert list(session.scalars(select(Message))) == []
