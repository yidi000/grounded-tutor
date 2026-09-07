import pytest
from pydantic import ValidationError

from grounded_tutor.domain.learning import ActivitySnapshot


def test_activity_can_suspend_check_for_ask():
    state = ActivitySnapshot(
        active_mode="CHECK", active_concept_id="concept-1", checkpoint="question-2"
    )
    suspended = state.suspend_for("ASK")
    assert suspended.active_mode == "ASK"
    assert suspended.suspended_activity.mode == "CHECK"
    assert suspended.suspended_activity.checkpoint == "question-2"
    assert suspended.resume() == state
    assert state.active_mode == "CHECK"


@pytest.mark.parametrize("mode", ["CHECK", "LEARN", "PLAN"])
def test_repeated_detours_and_serialization_preserve_checkpoint(mode):
    state = ActivitySnapshot(active_mode=mode, checkpoint="completed-step-1")
    detour = state.suspend_for("ASK").suspend_for("ASK")
    restored = ActivitySnapshot.model_validate_json(detour.model_dump_json()).resume()
    assert restored == state
    assert restored.resume() == state


def test_only_completed_steps_change_checkpoint():
    state = ActivitySnapshot(active_mode="CHECK", checkpoint="completed-question-1")
    completed = state.complete_step("completed-question-2")
    assert state.checkpoint == "completed-question-1"
    assert completed.suspend_for("ASK").resume().checkpoint == "completed-question-2"
    with pytest.raises(ValueError):
        completed.suspend_for("ASK").complete_step("unsubmitted-answer")
    with pytest.raises(ValueError):
        state.complete_step(" ")


def test_rejects_unknown_modes_and_unsupported_nested_activity():
    with pytest.raises(ValidationError):
        ActivitySnapshot(active_mode="DIAGNOSTIC")
    with pytest.raises(ValueError):
        ActivitySnapshot(active_mode="LEARN").suspend_for("CHECK")
    assert ActivitySnapshot().suspend_for("ASK") == ActivitySnapshot()


@pytest.fixture(params=["metadata", "migration"])
def learning_database(tmp_path, request):
    from alembic import command
    from grounded_tutor.alembic_config import get_alembic_config
    from grounded_tutor.config import Settings
    from grounded_tutor.db import create_database_engine
    from grounded_tutor.domain.models import Base

    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'learning.db'}")
    engine = create_database_engine(settings)
    if request.param == "metadata":
        Base.metadata.create_all(engine)
    else:
        command.upgrade(get_alembic_config(settings), "head")
    yield engine
    engine.dispose()


def test_learning_records_round_trip_and_skip_is_not_incorrect(learning_database):
    from sqlalchemy.orm import Session

    from grounded_tutor.domain.models import (
        ActivityState,
        Assessment,
        Attempt,
        Concept,
        LearnerProfile,
        LearningPlan,
        Workspace,
    )

    with Session(learning_database) as session:
        workspace = Workspace(title="Learning", dataset_id="learning")
        session.add(workspace)
        session.flush()
        plan = LearningPlan(workspace_id=workspace.id, goal="Understand means")
        session.add(plan)
        session.flush()
        concept = Concept(
            workspace_id=workspace.id,
            plan_id=plan.id,
            order=1,
            title="Mean",
            objective="Compute a mean",
            evidence_refs=[{"chunk_id": "chunk-1"}],
        )
        session.add(concept)
        session.flush()
        question = Assessment(
            workspace_id=workspace.id,
            concept_id=concept.id,
            kind="single_choice",
            purpose="immediate_check",
            prompt="2+2?",
            options=["3", "4"],
            answer_key=["4"],
        )
        session.add(question)
        session.flush()
        skipped = Attempt(assessment_id=question.id, status="not_assessed")
        snapshot = ActivitySnapshot(
            active_mode="CHECK", active_concept_id=str(concept.id), checkpoint=str(question.id)
        ).suspend_for("ASK")
        activity = ActivityState(
            workspace_id=workspace.id, suspended_activity=snapshot.suspended_activity.model_dump()
        )
        profile = LearnerProfile(
            workspace_id=workspace.id,
            inferred_fields={"background": "new"},
            confirmed_fields={"goal": "means"},
        )
        session.add_all([skipped, activity, profile])
        session.commit()
        session.expire_all()
        saved = session.get(ActivityState, workspace.id)
        restored = ActivitySnapshot(
            active_mode=saved.active_mode, suspended_activity=saved.suspended_activity
        ).resume()
        assert restored.checkpoint == str(question.id)
        assert restored.active_concept_id == str(concept.id)
        assert skipped.result is None and skipped.response is None
        assert concept.status == "not_started"
        assert plan.status == "not_started"
        assert question.answer_key == ["4"]
        assert profile.confirmed_fields == {"goal": "means"}


def test_learning_constraints_prevent_foreign_workspace_links(learning_database):
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    from grounded_tutor.domain.models import (
        ActivityState,
        Assessment,
        Concept,
        LearningPlan,
        Workspace,
    )

    with Session(learning_database) as session:
        first, second = Workspace(title="A", dataset_id="A"), Workspace(title="B", dataset_id="B")
        session.add_all([first, second])
        session.flush()
        plan = LearningPlan(workspace_id=first.id, goal="Learn")
        session.add(plan)
        session.flush()
        concept = Concept(
            workspace_id=first.id, plan_id=plan.id, order=1, title="Mean", objective="Learn"
        )
        session.add(concept)
        session.commit()
        invalid_records = [
            ActivityState(workspace_id=second.id, active_concept_id=concept.id),
            Concept(
                workspace_id=second.id, plan_id=plan.id, order=2, title="Wrong", objective="Wrong"
            ),
            Assessment(
                workspace_id=second.id,
                concept_id=concept.id,
                kind="single_choice",
                prompt="Wrong",
                answer_key=["x"],
            ),
            LearningPlan(workspace_id=first.id, goal="Wrong", status="invented"),
            ActivityState(workspace_id=first.id, active_mode="DIAGNOSTIC"),
            Concept(
                workspace_id=first.id,
                plan_id=plan.id,
                order=1,
                title="Duplicate",
                objective="Wrong",
            ),
        ]
        for record in invalid_records:
            session.add(record)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()


def test_learning_migration_preserves_existing_workspace_and_reverses(tmp_path):
    from sqlalchemy import inspect, text

    from alembic import command
    from grounded_tutor.alembic_config import get_alembic_config
    from grounded_tutor.config import Settings
    from grounded_tutor.db import create_database_engine

    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'upgrade.db'}")
    config = get_alembic_config(settings)
    command.upgrade(config, "0006_traces_bad_cases")
    engine = create_database_engine(settings)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO workspaces (id,title,dataset_id) VALUES (:id,'Legacy','legacy')"),
                {"id": "a" * 32},
            )
        command.upgrade(config, "head")
        assert "activity_states" in inspect(engine).get_table_names()
        command.check(config)
        command.downgrade(config, "0006_traces_bad_cases")
        assert "activity_states" not in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert connection.execute(text("SELECT title FROM workspaces")).scalar_one() == "Legacy"
        command.upgrade(config, "head")
        command.check(config)
    finally:
        engine.dispose()


def test_attempt_constraints_and_workspace_singletons(learning_database):
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    from grounded_tutor.domain.models import (
        ActivityState,
        Assessment,
        Attempt,
        LearnerProfile,
        Workspace,
    )

    with Session(learning_database) as session:
        workspace = Workspace(title="Diagnostic", dataset_id="diagnostic")
        session.add(workspace)
        session.flush()
        assessment = Assessment(
            workspace_id=workspace.id,
            kind="structured_short",
            prompt="Define mean",
            answer_key=["sum", "count"],
        )
        session.add_all(
            [
                assessment,
                ActivityState(workspace_id=workspace.id),
                LearnerProfile(workspace_id=workspace.id),
            ]
        )
        session.commit()
        invalid_records = [
            Attempt(assessment_id=assessment.id, status="not_assessed", result="needs_review"),
            Attempt(assessment_id=assessment.id, status="completed", response="answer"),
            Attempt(assessment_id=assessment.id, status="completed", result="understood"),
            ActivityState(workspace_id=workspace.id),
            LearnerProfile(workspace_id=workspace.id),
        ]
        for record in invalid_records:
            session.add(record)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
        answered = Attempt(
            assessment_id=assessment.id,
            status="completed",
            response="sum divided by count",
            result="understood",
        )
        session.add(answered)
        session.commit()
        assert answered.result == "understood"
