import asyncio
from contextlib import contextmanager

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from grounded_tutor.adapters.fakes import FakeFastGPT, FakeGeneration
from grounded_tutor.adapters.fastgpt import RetrievedChunk
from grounded_tutor.config import Settings
from grounded_tutor.db import create_database_engine
from grounded_tutor.domain.models import Base, Message, Source, SourceStatus, SourceType, Workspace
from grounded_tutor.repositories.chat import ChatRepository
from grounded_tutor.repositories.sources import SourceRepository
from grounded_tutor.services.chat import ChatService, ExternalChatServiceError
from grounded_tutor.services.idempotency import IdempotencyInProgress, IdempotencyKeyReused


@pytest.fixture
def scenario(tmp_path):
    engine = create_database_engine(Settings(database_url=f"sqlite:///{tmp_path / 'requests.db'}"))
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        workspace = Workspace(title="Notes", dataset_id="dataset")
        session.add(workspace)
        session.flush()
        workspace_id = workspace.id
        session.add(
            Source(
                workspace_id=workspace_id,
                name="Notes",
                source_type=SourceType.TEXT,
                status=SourceStatus.READY,
                collection_id="collection",
                ingestion_config={},
            )
        )
        session.commit()
    fastgpt = FakeFastGPT()
    fastgpt.search_results_override = (
        RetrievedChunk("chunk", "collection", "provider", "q", "Evidence", 1),
    )
    generation = FakeGeneration()

    @contextmanager
    def service():
        with Session(engine) as session:
            yield ChatService(
                SourceRepository(session), ChatRepository(session), fastgpt, generation
            )

    yield engine, workspace_id, fastgpt, generation, service
    engine.dispose()


@pytest.mark.asyncio
async def test_same_key_replays_across_sessions_without_generation(scenario):
    engine, workspace, fastgpt, generation, service = scenario
    with service() as chat:
        first = await chat.ask(workspace, "Question", None, "key")
    with service() as chat:
        second = await chat.ask(workspace, "Question", None, "key")
    assert second == first
    assert len(generation.calls) == len(fastgpt.search_calls) == 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 2


@pytest.mark.asyncio
async def test_changed_payload_conflicts_before_provider_call(scenario):
    _, workspace, _, generation, service = scenario
    with service() as chat:
        await chat.ask(workspace, "Question", None, "key")
        with pytest.raises(IdempotencyKeyReused):
            await chat.ask(workspace, "Different", None, "key")
    assert len(generation.calls) == 1


@pytest.mark.asyncio
async def test_concurrent_key_is_claimed_before_generation(scenario, monkeypatch):
    _, workspace, _, generation, service = scenario
    started, release = asyncio.Event(), asyncio.Event()
    generate = generation.generate_content

    async def slow(request):
        started.set()
        await release.wait()
        return await generate(request)

    monkeypatch.setattr(generation, "generate_content", slow)
    with service() as first, service() as second:
        task = asyncio.create_task(first.ask(workspace, "Question", None, "key"))
        await started.wait()
        try:
            with pytest.raises(IdempotencyInProgress):
                await asyncio.wait_for(second.ask(workspace, "Question", None, "key"), 1)
        finally:
            release.set()
            result = await task
        replay = await second.ask(workspace, "Question", None, "key")
        assert replay == result
    assert len(generation.calls) == 1


@pytest.mark.asyncio
async def test_generation_failure_releases_key_for_retry(scenario):
    engine, workspace, _, generation, service = scenario
    generation.responses = [RuntimeError("private-provider-error")]
    with service() as chat, pytest.raises(ExternalChatServiceError):
        await chat.ask(workspace, "Question", None, "key")
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 0
    with service() as chat:
        result = await chat.ask(workspace, "Question", None, "key")
        assert await chat.ask(workspace, "Question", None, "key") == result
    assert len(generation.calls) == 2


@pytest.mark.asyncio
async def test_final_transaction_failure_rolls_back_messages_and_releases_key(scenario):
    from sqlalchemy import event
    from sqlalchemy.exc import SQLAlchemyError

    from grounded_tutor.domain.models import RequestRecord
    from grounded_tutor.repositories.chat import ChatPersistenceError

    engine, workspace, _, _, service = scenario

    def fail_completed_commit(session):
        if any(
            isinstance(row, RequestRecord) and row.state == "completed" for row in session.dirty
        ):
            raise SQLAlchemyError("private transaction data")

    event.listen(Session, "before_commit", fail_completed_commit)
    try:
        with service() as chat, pytest.raises(ChatPersistenceError):
            await chat.ask(workspace, "Question", None, "key")
    finally:
        event.remove(Session, "before_commit", fail_completed_commit)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 0
        assert session.scalar(select(func.count()).select_from(RequestRecord)) == 0
    with service() as chat:
        result = await chat.ask(workspace, "Question", None, "key")
        assert await chat.ask(workspace, "Question", None, "key") == result


@pytest.mark.asyncio
async def test_cancellation_releases_claim(scenario, monkeypatch):
    from grounded_tutor.domain.models import RequestRecord

    engine, workspace, _, generation, service = scenario
    started = asyncio.Event()
    generate = generation.generate_content

    async def wait_forever(request):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(generation, "generate_content", wait_forever)
    with service() as chat:
        task = asyncio.create_task(chat.ask(workspace, "Question", None, "key"))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(RequestRecord)) == 0
    monkeypatch.setattr(generation, "generate_content", generate)
    with service() as chat:
        assert (await chat.ask(workspace, "Question", None, "key")).answer.status == "ok"


@pytest.mark.asyncio
async def test_key_is_workspace_scoped_and_conversation_is_part_of_hash(scenario):
    engine, workspace, _, _, service = scenario
    with Session(engine) as session:
        other = Workspace(title="Other", dataset_id="other")
        session.add(other)
        session.commit()
        other_id = other.id
    with service() as chat:
        first = await chat.ask(workspace, "Question", None, "key")
        other = await chat.ask(other_id, "Question", None, "key")
        assert first.message_id != other.message_id
        assert other.answer.status == "insufficient_material"
        assert await chat.ask(other_id, "Question", None, "key") == other
        with pytest.raises(IdempotencyKeyReused):
            await chat.ask(workspace, "Question", first.conversation_id, "key")


@pytest.mark.asyncio
async def test_committed_answer_survives_lost_commit_acknowledgement(scenario, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    from grounded_tutor.repositories.chat import ChatPersistenceError

    _, workspace, _, generation, service = scenario
    commit = Session.commit
    commits = 0

    def lost_ack(session):
        nonlocal commits
        commit(session)
        commits += 1
        if commits == 2:
            raise SQLAlchemyError("Commit succeeded but acknowledgement was lost")

    monkeypatch.setattr(Session, "commit", lost_ack)
    with service() as chat, pytest.raises(ChatPersistenceError):
        await chat.ask(workspace, "Question", None, "key")
    monkeypatch.setattr(Session, "commit", commit)
    with service() as chat:
        result = await chat.ask(workspace, "Question", None, "key")
        assert result.answer.status == "ok"
    assert len(generation.calls) == 1
