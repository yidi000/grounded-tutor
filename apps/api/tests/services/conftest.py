from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from grounded_tutor.adapters.fakes import FakeFastGPT, FakeGeneration
from grounded_tutor.adapters.fastgpt import RetrievedChunk
from grounded_tutor.config import Settings
from grounded_tutor.db import create_database_engine
from grounded_tutor.domain.answers import GeneratedAnswer, GeneratedBlock
from grounded_tutor.domain.diagnostics import GeneratedDiagnosticQuestion
from grounded_tutor.domain.models import (
    ActivityState,
    Base,
    Concept,
    LearningPlan,
    Source,
    SourceStatus,
    SourceType,
    Workspace,
)
from grounded_tutor.domain.teaching import GeneratedCheck
from grounded_tutor.services.checks import CheckService
from grounded_tutor.services.lessons import LessonService
from grounded_tutor.services.source_locks import WorkspaceLockRegistry


@pytest.fixture
def learning_tutor(tmp_path):
    engine = create_database_engine(
        Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'teaching.db'}")
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        workspace = Workspace(title="Statistics", dataset_id="dataset")
        session.add(workspace)
        session.flush()
        source = Source(
            workspace_id=workspace.id,
            name="Notes",
            source_type=SourceType.TEXT,
            status=SourceStatus.READY,
            collection_id="ready",
            ingestion_config={},
        )
        plan = LearningPlan(workspace_id=workspace.id, goal="Learn the mean")
        session.add_all([source, plan])
        session.flush()
        concepts = [
            Concept(
                workspace_id=workspace.id,
                plan_id=plan.id,
                order=i + 1,
                title=f"Mean {i}",
                objective="Explain the mean",
                check_kind="single_choice",
                evidence_refs=[
                    {"source_id": str(source.id), "source_version": 1, "chunk_id": "chunk"}
                ],
            )
            for i in range(3)
        ]
        state = ActivityState(
            workspace_id=workspace.id, active_mode="PLAN", return_checkpoint=f"plan:{plan.id}"
        )
        session.add_all([*concepts, state])
        session.commit()
        fastgpt = FakeFastGPT()
        fastgpt.search_results_override = (
            RetrievedChunk("foreign", "other", "Private", "Secret", "private fact", 1),
            RetrievedChunk("chunk", "ready", "Provider", "Mean", "sum divided by count", 1),
        )
        lesson = GeneratedAnswer(
            blocks=tuple(
                GeneratedBlock(
                    id=kind,
                    kind=kind,
                    text="The mean is sum divided by count.",
                    chunk_ids=("chunk",),
                )
                for kind in ("definition", "explanation", "example")
            )
        )
        check = GeneratedCheck(
            question=GeneratedDiagnosticQuestion(
                id="q",
                kind="single_choice",
                prompt="Numerator?",
                options=("sum", "product"),
                answer_key=("sum",),
                explanation="Use the sum.",
                concept_label="Mean",
                chunk_ids=("chunk",),
            )
        )
        generation = FakeGeneration(*([lesson] * 10))
        generation.check_responses = [check] * 10
        locks = WorkspaceLockRegistry()
        yield SimpleNamespace(
            session=session,
            workspace=workspace,
            plan=plan,
            concepts=concepts,
            source=source,
            state=state,
            fastgpt=fastgpt,
            generation=generation,
            lesson=lesson,
            check=check,
            lessons=LessonService(session, fastgpt, generation, locks),
            checks=CheckService(session, fastgpt, generation, locks),
        )
    engine.dispose()
