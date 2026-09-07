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


@pytest.mark.asyncio
@pytest.mark.parametrize("commit_succeeds", [False, True])
async def test_initial_claim_commit_failure_releases_only_own_claim(
    scenario, monkeypatch, commit_succeeds
):
    from sqlalchemy.exc import SQLAlchemyError

    from grounded_tutor.domain.models import RequestRecord
    from grounded_tutor.repositories.chat import ChatPersistenceError

    engine, workspace, fastgpt, generation, service = scenario
    commit = Session.commit
    commits = 0

    def fail_initial_commit(session):
        nonlocal commits
        commits += 1
        if commits == 1:
            if commit_succeeds:
                commit(session)
            raise SQLAlchemyError("private initial commit failure")
        commit(session)

    monkeypatch.setattr(Session, "commit", fail_initial_commit)
    with service() as chat, pytest.raises(ChatPersistenceError):
        await chat.ask(workspace, "Question", None, "key")
    assert not fastgpt.search_calls and not generation.calls
    with Session(engine) as session:
        assert session.get(RequestRecord, (workspace, "key")) is None
        assert session.scalar(select(func.count()).select_from(Message)) == 0
    with service() as chat:
        result = await chat.ask(workspace, "Question", None, "key")
        assert await chat.ask(workspace, "Question", None, "key") == result
    assert len(generation.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["pending", "completed"])
async def test_insert_error_does_not_release_another_request(scenario, monkeypatch, state):
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.sql.dml import Insert

    from grounded_tutor.domain.models import RequestRecord
    from grounded_tutor.repositories.chat import ChatPersistenceError
    from grounded_tutor.services.idempotency import request_hash

    engine, workspace, fastgpt, generation, service = scenario
    saved_response = {"marker": "other request"}
    with Session(engine) as session:
        session.add(
            RequestRecord(
                workspace_id=workspace,
                idempotency_key="key",
                request_hash=request_hash("Question", None),
                state=state,
                response_json=saved_response,
            )
        )
        session.commit()
    execute = Session.execute

    def fail_insert(session, statement, *args, **kwargs):
        if isinstance(statement, Insert) and statement.table.name == "request_records":
            raise SQLAlchemyError("uncertain insert execution")
        return execute(session, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "execute", fail_insert)
    with service() as chat, pytest.raises(ChatPersistenceError):
        await chat.ask(workspace, "Question", None, "key")
    with Session(engine) as session:
        record = session.get(RequestRecord, (workspace, "key"))
        assert record.state == state
        assert record.response_json == saved_response
    assert not fastgpt.search_calls and not generation.calls


@pytest.mark.asyncio
async def test_failed_claim_cleanup_preserves_replacement_after_rollback(scenario, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    from grounded_tutor.domain.models import RequestRecord
    from grounded_tutor.repositories.chat import ChatPersistenceError
    from grounded_tutor.services.idempotency import request_hash

    engine, workspace, fastgpt, generation, service = scenario
    commit, rollback = Session.commit, Session.rollback
    failed = replaced = False
    replacement = {"_claim_token": "replacement-worker"}

    def fail_initial_commit(session):
        nonlocal failed
        if not failed:
            failed = True
            raise SQLAlchemyError("initial commit failed before durability")
        commit(session)

    def replace_after_rollback(session):
        nonlocal replaced
        rollback(session)
        if not replaced:
            replaced = True
            with Session(engine) as other:
                other.add(
                    RequestRecord(
                        workspace_id=workspace,
                        idempotency_key="key",
                        request_hash=request_hash("Question", None),
                        state="pending",
                        response_json=replacement,
                    )
                )
                commit(other)

    monkeypatch.setattr(Session, "commit", fail_initial_commit)
    monkeypatch.setattr(Session, "rollback", replace_after_rollback)
    with service() as chat, pytest.raises(ChatPersistenceError):
        await chat.ask(workspace, "Question", None, "key")
    with Session(engine) as session:
        record = session.get(RequestRecord, (workspace, "key"))
        assert record.state == "pending"
        assert record.response_json == replacement
    assert not fastgpt.search_calls and not generation.calls


@pytest.mark.asyncio
async def test_uncertain_insert_acknowledgement_releases_own_durable_claim(scenario, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.sql.dml import Insert

    from grounded_tutor.domain.models import RequestRecord
    from grounded_tutor.repositories.chat import ChatPersistenceError

    engine, workspace, fastgpt, generation, service = scenario
    execute = Session.execute
    failed = False

    def lose_insert_ack(session, statement, *args, **kwargs):
        nonlocal failed
        result = execute(session, statement, *args, **kwargs)
        if (
            not failed
            and isinstance(statement, Insert)
            and statement.table.name == "request_records"
        ):
            failed = True
            session.commit()
            raise SQLAlchemyError("insert succeeded but acknowledgement was lost")
        return result

    monkeypatch.setattr(Session, "execute", lose_insert_ack)
    with service() as chat, pytest.raises(ChatPersistenceError):
        await chat.ask(workspace, "Question", None, "key")
    assert not fastgpt.search_calls and not generation.calls
    with Session(engine) as session:
        assert session.get(RequestRecord, (workspace, "key")) is None
    with service() as chat:
        assert (await chat.ask(workspace, "Question", None, "key")).answer.status == "ok"
