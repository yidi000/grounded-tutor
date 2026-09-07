from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from grounded_tutor.adapters.fakes import FakeFastGPT, FakeGeneration
from grounded_tutor.adapters.fastgpt import RetrievedChunk
from grounded_tutor.config import Settings
from grounded_tutor.db import create_database_engine
from grounded_tutor.domain.models import (
    ActivityState,
    Assessment,
    Attempt,
    Base,
    LearnerProfile,
    Source,
    SourceStatus,
    SourceType,
    Workspace,
)
from grounded_tutor.repositories.chat import ChatRepository
from grounded_tutor.repositories.sources import SourceRepository
from grounded_tutor.services.chat import ChatService
from grounded_tutor.services.diagnostic_invites import DiagnosticInviteService
from grounded_tutor.services.routing import ClassifierObservation


@pytest.fixture
def tutor(tmp_path):
    engine = create_database_engine(
        Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'invites.db'}")
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        workspace = Workspace(title="Statistics", dataset_id="dataset")
        session.add(workspace)
        session.flush()
        session.add(
            Source(
                workspace_id=workspace.id,
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
            RetrievedChunk("chunk", "collection", "Notes", "Mean", "sum / count", 1),
        )
        generation = FakeGeneration()
        invites = DiagnosticInviteService(session)
        chat = ChatService(
            SourceRepository(session), ChatRepository(session), fastgpt, generation, invites=invites
        )
        yield session, workspace, chat, invites, generation
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "我是新手，应该怎么学？",
        "我不理解这个概念",
        "请给我一个测验",
        "How should I learn this?",
        "I'm new to statistics",
    ],
)
async def test_explicit_learning_signal_invites_after_answer_without_starting(tutor, question):
    session, workspace, chat, invites, generation = tutor
    result = await chat.ask(workspace.id, question, None, "key")
    assert [a.type for a in result.suggested_actions] == ["start_diagnostic"]
    card = invites.current(workspace.id)
    assert (card.accept_label, card.dismiss_label) == ("开始诊断", "继续提问")
    assert not list(session.scalars(select(Assessment)))
    assert not list(session.scalars(select(Attempt)))
    assert len(generation.calls) == 1
    assert session.get(ActivityState, workspace.id).active_mode == "ASK"
    assert await chat.ask(workspace.id, question, None, "key") == result
    assert (
        chat.history(workspace.id).exchanges[0].response.suggested_actions
        == result.suggested_actions
    )


@pytest.mark.asyncio
async def test_two_related_foundation_questions_require_same_conversation(tutor):
    _, workspace, chat, invites, _ = tutor
    first = await chat.ask(workspace.id, "What is the mean?", None, "first")
    assert first.suggested_actions == ()
    separate = await chat.ask(workspace.id, "What is the average?", None, "separate")
    assert separate.suggested_actions == ()
    second = await chat.ask(workspace.id, "What is the average?", first.conversation_id, "second")
    assert second.suggested_actions
    assert invites.current(workspace.id).conversation_id == first.conversation_id


@pytest.mark.asyncio
async def test_dismissal_cooldown_and_old_replay_do_not_reinvite(tutor):
    _, workspace, chat, invites, _ = tutor
    first = await chat.ask(workspace.id, "我是新手", None, "first")
    card = invites.current(workspace.id)
    now = datetime.now(UTC)
    invites.dismiss(workspace.id, card.id, now=now)
    assert not (await chat.ask(workspace.id, "我是新手", None, "first")).suggested_actions
    second = await chat.ask(workspace.id, "应该怎么学？", first.conversation_id, "second")
    assert not second.suggested_actions
    assert invites.suggest(
        workspace.id, second.conversation_id, second.message_id, now=now + timedelta(hours=24)
    )
    assert invites.current(workspace.id).id != card.id


@pytest.mark.asyncio
async def test_acceptance_requires_consent_and_is_idempotent(tutor):
    _, workspace, chat, invites, _ = tutor
    await chat.ask(workspace.id, "我是新手", None, "first")
    card = invites.current(workspace.id)
    with pytest.raises(ValueError):
        invites.accept(workspace.id, card.id, consent=False)
    accepted = invites.accept(workspace.id, card.id, consent=True)
    assert invites.accept(workspace.id, card.id, consent=True) == accepted
    assert accepted.id == card.id and accepted.status == "accepted"
    assert not chat.history(workspace.id).exchanges[0].response.suggested_actions
    assert not (await chat.ask(workspace.id, "我是新手", None, "first")).suggested_actions


def test_inferences_do_not_overwrite_confirmed_profile(tutor):
    session, workspace, _, invites, _ = tutor
    invites.confirm_profile(workspace.id, goal="Learn statistics", background="Some experience")
    invites.record_observation(
        workspace.id,
        ClassifierObservation(intent="learning", goal="Learn algebra", background="Beginner"),
    )
    profile = session.get(LearnerProfile, workspace.id)
    assert profile.confirmed_fields == {"goal": "Learn statistics", "background": "Some experience"}
    assert profile.inferred_fields["goal"] == "Learn algebra"
    assert invites.current(workspace.id) is None


@pytest.mark.asyncio
async def test_explicit_text_beats_unrelated_classifier(tutor):
    _, workspace, chat, invites, _ = tutor
    answer = await chat.ask(workspace.id, "我是新手", None, "one")
    actions = invites.suggest(
        workspace.id,
        answer.conversation_id,
        answer.message_id,
        observation=ClassifierObservation(intent="unrelated", proposed_title="Algebra"),
    )
    assert [action.type for action in actions] == ["start_diagnostic"]


@pytest.mark.asyncio
async def test_unrelated_suggestion_does_not_change_workspace_or_activity(tutor):
    session, workspace, chat, invites, _ = tutor
    answer = await chat.ask(workspace.id, "A normal question", None, "one")
    actions = invites.suggest(
        workspace.id,
        answer.conversation_id,
        answer.message_id,
        observation=ClassifierObservation(intent="unrelated", proposed_title="Algebra"),
    )
    assert actions[0].type == "suggest_new_workspace"
    assert session.get(ActivityState, workspace.id) is None
    assert workspace.title == "Statistics"
    assert len(chat.history(workspace.id).exchanges) == 1


@pytest.mark.asyncio
async def test_cross_workspace_cannot_accept_or_dismiss_card(tutor):
    session, workspace, chat, invites, _ = tutor
    await chat.ask(workspace.id, "我是新手", None, "one")
    card = invites.current(workspace.id)
    other = Workspace(title="Other", dataset_id="other")
    session.add(other)
    session.commit()
    with pytest.raises(ValueError):
        invites.accept(other.id, card.id, consent=True)
    with pytest.raises(ValueError):
        invites.dismiss(other.id, card.id)
    assert invites.current(workspace.id) == card


@pytest.mark.asyncio
async def test_history_observes_dismissal_from_another_session(tutor):
    session, workspace, chat, invites, _ = tutor
    await chat.ask(workspace.id, "我是新手", None, "one")
    card = invites.current(workspace.id)
    cached_state = session.get(ActivityState, workspace.id)
    with Session(session.get_bind()) as other:
        DiagnosticInviteService(other).dismiss(workspace.id, card.id)
    assert not chat.history(workspace.id).exchanges[0].response.suggested_actions
    assert cached_state.diagnostic_invitation["status"] == "dismissed"


@pytest.mark.asyncio
async def test_unrelated_evidence_does_not_count_as_related_foundation(tutor):
    _, workspace, chat, _, _ = tutor
    first = await chat.ask(workspace.id, "What is the mean?", None, "one")
    chat._fastgpt.search_results_override = (
        RetrievedChunk("other", "collection", "Notes", "Median", "middle value", 1),
    )
    second = await chat.ask(workspace.id, "What is the median?", first.conversation_id, "two")
    assert not second.suggested_actions


@pytest.mark.asyncio
async def test_continuing_to_ask_ignores_card_and_starts_cooldown(tutor):
    _, workspace, chat, invites, _ = tutor
    first = await chat.ask(workspace.id, "我是新手", None, "one")
    await chat.ask(workspace.id, "What is the mean?", first.conversation_id, "two")
    assert invites.current(workspace.id).status == "dismissed"
    assert not chat.history(workspace.id).exchanges[0].response.suggested_actions


@pytest.mark.asyncio
async def test_active_learning_is_not_interrupted(tutor):
    session, workspace, chat, invites, _ = tutor
    state = ActivityState(
        workspace_id=workspace.id, active_mode="LEARN", return_checkpoint="lesson-1"
    )
    session.add(state)
    session.commit()
    result = await chat.ask(workspace.id, "我不理解这个概念", None, "one")
    assert not result.suggested_actions
    assert invites.current(workspace.id) is None
    assert state.active_mode == "LEARN" and state.return_checkpoint == "lesson-1"


@pytest.mark.asyncio
async def test_optional_invitation_failure_preserves_answer_and_replay(tutor):
    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError

    session, workspace, chat, _invites, generation = tutor
    engine = session.get_bind()

    def fail_invitation(_connection, _cursor, statement, _parameters, _context, _many):
        if statement == "BEGIN IMMEDIATE":
            raise OperationalError("invitation storage", {}, Exception("synthetic failure"))

    event.listen(engine, "before_cursor_execute", fail_invitation)
    try:
        first = await chat.ask(workspace.id, "我是新手", None, "one")
        assert first.answer.status == "ok"
        assert not first.suggested_actions
    finally:
        event.remove(engine, "before_cursor_execute", fail_invitation)
    replay = await chat.ask(workspace.id, "我是新手", None, "one")
    assert replay.message_id == first.message_id and replay.answer == first.answer
    assert replay.suggested_actions
    assert len(generation.calls) == 1
    assert len(chat.history(workspace.id).exchanges) == 1


@pytest.mark.asyncio
async def test_old_conversation_replay_does_not_dismiss_new_invitation(tutor):
    _, workspace, chat, invites, _ = tutor
    await chat.ask(workspace.id, "普通问题", None, "old")
    newer = await chat.ask(workspace.id, "我是新手", None, "new")
    card = invites.current(workspace.id)
    await chat.ask(workspace.id, "普通问题", None, "old")
    assert invites.current(workspace.id) == card
    assert chat.history(workspace.id).exchanges[-1].response.message_id == newer.message_id
    assert chat.history(workspace.id).exchanges[-1].response.suggested_actions


def test_invitation_migration_preserves_existing_learning_checkpoint(tmp_path):
    from sqlalchemy import inspect, text

    from alembic import command
    from grounded_tutor.alembic_config import get_alembic_config

    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'migration.db'}")
    config = get_alembic_config(settings)
    command.upgrade(config, "0007_learning_state")
    engine = create_database_engine(settings)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO workspaces (id,title,dataset_id) VALUES (:id,'Old','old')"),
                {"id": "a" * 32},
            )
            connection.execute(
                text(
                    "INSERT INTO activity_states (workspace_id,active_mode,return_checkpoint) VALUES (:id,'CHECK','question-2')"
                ),
                {"id": "a" * 32},
            )
        command.upgrade(config, "head")
        command.check(config)
        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT active_mode,return_checkpoint,diagnostic_invitation FROM activity_states"
                )
            ).one() == ("CHECK", "question-2", None)
        command.downgrade(config, "0007_learning_state")
        assert "diagnostic_invitation" not in {
            c["name"] for c in inspect(engine).get_columns("activity_states")
        }
        command.upgrade(config, "head")
        command.check(config)
    finally:
        engine.dispose()
