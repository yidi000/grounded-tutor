"""Opt-in cloud learning contracts using synthetic evidence only."""

import os

import pytest

from grounded_tutor.adapters.fastgpt import RetrievedChunk
from grounded_tutor.adapters.generation import GenerationRequest, OpenAICompatibleGenerationClient
from grounded_tutor.config import Settings
from grounded_tutor.services.assessment_scoring import normalize

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_INTEGRATION") != "1",
    reason="set RUN_LIVE_INTEGRATION=1 with local credentials",
)


@pytest.mark.asyncio
async def test_live_learning_generation_contracts():
    settings = Settings()
    chunks = (
        RetrievedChunk(
            "learning-probe",
            "probe",
            "Statistics",
            "Measures of center",
            "Mean is sum divided by count. For 2, 4, 6 the mean is 4. "
            "Median is the middle value. Mode is the most frequent value.",
            1,
        ),
    )
    async with OpenAICompatibleGenerationClient(
        settings.llm_base_url,
        settings.llm_api_key.get_secret_value(),
        settings.llm_model,
    ) as generation:
        result = await generation.generate_diagnostic(
            "Learn mean, median and mode", "Beginner", chunks
        )
        assert 3 <= len(result.questions) <= 5
        assert all(q.chunk_ids == ("learning-probe",) for q in result.questions)
        plan = await generation.generate_plan(
            "Learn mean, median and mode", {"mean": "not_assessed"}, chunks
        )
        assert 3 <= len(plan.concepts) <= 5
        assert all(c.chunk_ids == ("learning-probe",) for c in plan.concepts)
        lesson = await generation.generate_content(
            GenerationRequest(
                "LEARN",
                "Explain mean with a definition, explanation and example using only the evidence.",
                chunks,
            )
        )
        assert {b.kind for b in lesson.blocks} == {"definition", "explanation", "example"}
        for kind in ("single_choice", "structured_short"):
            checked = await generation.generate_check("Define mean", kind, chunks)
            assert checked.question.kind == kind
            assert all(
                normalize(key) in normalize(chunks[0].a) for key in checked.question.answer_key
            )
        answer = await generation.generate_content(
            GenerationRequest("ASK", "What is mean?", chunks)
        )
        assert answer.blocks and all(b.kind == "answer" for b in answer.blocks)
        unsupported = await generation.generate_content(
            GenerationRequest("ASK", "What is the mass of the Moon?", chunks)
        )
        assert not unsupported.blocks


@pytest.mark.asyncio
async def test_live_learning_from_import_to_completed_plan(tmp_path):
    from uuid import uuid4

    from sqlalchemy.orm import Session

    from grounded_tutor.adapters.fastgpt import FastGPTClient
    from grounded_tutor.db import create_database_engine
    from grounded_tutor.domain.diagnostics import DiagnosticAnswerRequest, DiagnosticStartRequest
    from grounded_tutor.domain.ingestion import ChunkSettings
    from grounded_tutor.domain.models import Assessment, Base, Workspace
    from grounded_tutor.domain.orchestration import ActivityCommand
    from grounded_tutor.domain.plans import PlanCreateRequest
    from grounded_tutor.domain.teaching import CheckAnswerRequest, CheckStartRequest, LessonRequest
    from grounded_tutor.repositories.chat import ChatRepository
    from grounded_tutor.repositories.sources import SourceRepository
    from grounded_tutor.services.chat import ChatService
    from grounded_tutor.services.orchestrator import Orchestrator
    from grounded_tutor.services.source_locks import WorkspaceLockRegistry
    from grounded_tutor.services.sources import SourceService

    settings = Settings()
    engine = create_database_engine(Settings(database_url=f"sqlite:///{tmp_path / 'learning.db'}"))
    Base.metadata.create_all(engine)
    dataset = None
    async with (
        FastGPTClient(
            settings.fastgpt_base_url, settings.fastgpt_api_key.get_secret_value()
        ) as fastgpt,
        OpenAICompatibleGenerationClient(
            settings.llm_base_url,
            settings.llm_api_key.get_secret_value(),
            settings.llm_model,
        ) as generation,
    ):
        try:
            dataset = await fastgpt.create_dataset(f"Grounded Tutor learning probe {uuid4()}")
            with Session(engine, expire_on_commit=False) as session:
                workspace = Workspace(
                    title="Statistics learning probe", dataset_id=dataset.dataset_id
                )
                session.add(workspace)
                session.commit()
                wid = workspace.id
                sources = SourceRepository(session)
                locks = WorkspaceLockRegistry()
                ingestion = SourceService(sources, fastgpt, locks, supports_image_files=False)
                imported = await ingestion.ingest_text(
                    workspace_id=wid,
                    name="Synthetic statistics notes",
                    text="Mean is sum divided by count. For 2, 4, 6 the mean is 4 because the sum is 12 and the count is 3. Median is the middle value in sorted data. For 2, 4, 6 the median is 4. Mode is the most frequent value. For 2, 2, 6 the mode is 2. Mean uses every value. Median describes the middle position. Mode describes frequency.",
                    settings=ChunkSettings(),
                )
                await ingestion.accept(wid, imported.source.id)
                chat = ChatService(sources, ChatRepository(session), fastgpt, generation)
                tutor = Orchestrator(session, chat, fastgpt, generation, locks)
                diagnostic = await tutor.diagnostics.start(
                    wid,
                    DiagnosticStartRequest(
                        consent=True,
                        goal="Learn mean, median and mode",
                        background="Beginner",
                        idempotency_key="diagnostic",
                    ),
                )
                assert diagnostic.status == "active"
                for question in diagnostic.questions:
                    await tutor.diagnostics.answer(
                        wid,
                        diagnostic.diagnostic_id,
                        DiagnosticAnswerRequest(
                            question_id=question.question_id,
                            skip=True,
                            idempotency_key=str(question.question_id),
                        ),
                    )
                plan = await tutor.plans.create_from_diagnostic(
                    wid,
                    PlanCreateRequest(
                        diagnostic_id=diagnostic.diagnostic_id, idempotency_key="plan"
                    ),
                )
                assert 3 <= len(plan.concepts) <= 5
                for index, concept in enumerate(plan.concepts):
                    lesson = await tutor.lessons.start(
                        wid, concept.id, LessonRequest(idempotency_key=f"lesson-{index}")
                    )
                    assert lesson.status == "ok" and lesson.citations
                    check = await tutor.checks.start(
                        wid, concept.id, CheckStartRequest(idempotency_key=f"check-{index}")
                    )
                    assert check.status == "ok" and check.assessment_id
                    if index == 0:
                        checkpoint = tutor.view(wid).checkpoint
                        asked = await tutor.handle_message(wid, "What is mean?", None, "ask-detour")
                        assert asked.answer.status == "ok" and asked.answer.citations
                        session.expire_all()
                        assert tutor.view(wid).resume_action.checkpoint == checkpoint
                        restored = await tutor.resume(
                            wid, ActivityCommand(checkpoint=checkpoint, idempotency_key="resume")
                        )
                        assert restored.check == check
                    # Test driver reads the server-only key to simulate a correct learner.
                    assessment = session.get(Assessment, check.assessment_id)
                    result = await tutor.checks.submit(
                        wid,
                        check.assessment_id,
                        CheckAnswerRequest(
                            response=assessment.answer_key[0], idempotency_key=f"answer-{index}"
                        ),
                    )
                    assert result.result == "understood" and result.citations
                    assert (
                        tutor.view(wid).check_feedback.explanation_blocks
                        == result.explanation_blocks
                    )
                assert result.next_action == "completed"
                assert tutor.plans.get(wid, plan.plan_id).status == "completed"
                assert tutor.view(wid).snapshot.active_mode == "ASK"
        finally:
            try:
                if dataset is not None:
                    await fastgpt.delete_dataset(dataset.dataset_id)
            finally:
                engine.dispose()
