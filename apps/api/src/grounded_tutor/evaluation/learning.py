"""Eight deterministic learning journeys; real services, isolated SQLite, no network."""

import argparse
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from grounded_tutor.adapters.fakes import FakeFastGPT, FakeGeneration
from grounded_tutor.adapters.fastgpt import RetrievedChunk
from grounded_tutor.domain.answers import GeneratedAnswer, GeneratedBlock
from grounded_tutor.domain.diagnostics import (
    DiagnosticAnswerRequest,
    DiagnosticStartRequest,
    GeneratedDiagnostic,
    GeneratedDiagnosticQuestion,
)
from grounded_tutor.domain.models import ActivityState, Assessment, Attempt, Base, Source, Workspace
from grounded_tutor.domain.orchestration import ActivityCommand
from grounded_tutor.domain.plans import (
    GeneratedLearningPlan,
    GeneratedPlanConcept,
    PlanCreateRequest,
)
from grounded_tutor.domain.teaching import (
    CheckAnswerRequest,
    CheckStartRequest,
    GeneratedCheck,
    LessonRequest,
)
from grounded_tutor.repositories.chat import ChatRepository
from grounded_tutor.repositories.sources import SourceRepository
from grounded_tutor.services.chat import ChatService
from grounded_tutor.services.diagnostic_invites import DiagnosticInviteService
from grounded_tutor.services.orchestrator import Orchestrator
from grounded_tutor.services.source_locks import WorkspaceLockRegistry

JOURNEYS = (
    "invite_consent",
    "dismiss_cooldown",
    "diagnostic_skip",
    "bounded_plan",
    "check_detour",
    "failed_check",
    "passed_check",
    "reload",
)


def load_cases(path):
    cases = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    if not cases or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Empty or duplicate learning cases")
    for case in cases:
        if set(case) != {"id", "journey"} or case["journey"] not in JOURNEYS:
            raise ValueError("Invalid learning case")
    return cases


def _service(session, fastgpt, generation, locks):
    chat = ChatService(
        SourceRepository(session),
        ChatRepository(session),
        fastgpt,
        generation,
        invites=DiagnosticInviteService(session),
    )
    return Orchestrator(session, chat, fastgpt, generation, locks)


async def observe(case):
    with TemporaryDirectory(prefix="grounded-learning-eval-") as directory:
        engine = create_engine(f"sqlite:///{directory}/learning.db")

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        try:
            Base.metadata.create_all(engine)
            with Session(engine) as session:
                await _journey(case["journey"], session, engine)
        finally:
            engine.dispose()
    return {"id": case["id"], "passed": True}


async def _journey(journey, session, engine):
    workspace = Workspace(title="Statistics", dataset_id="eval")
    session.add(workspace)
    session.flush()
    session.add(
        Source(
            workspace_id=workspace.id,
            name="Notes",
            source_type="text",
            status="ready",
            collection_id="ready",
            ingestion_config={},
        )
    )
    session.commit()
    wid = workspace.id
    fastgpt, generation, locks = FakeFastGPT(), FakeGeneration(), WorkspaceLockRegistry()
    fastgpt.search_results_override = (
        RetrievedChunk("chunk", "ready", "Notes", "Mean", "sum divided by count", 1),
    )
    question = GeneratedDiagnosticQuestion(
        id="q",
        kind="single_choice",
        prompt="Numerator?",
        options=("sum", "product"),
        answer_key=("sum",),
        explanation="Use sum divided by count.",
        concept_label="Mean",
        chunk_ids=("chunk",),
    )
    generation.diagnostic_responses = [
        GeneratedDiagnostic(
            questions=tuple(
                question.model_copy(update={"id": f"q{i}", "concept_label": f"Mean {i}"})
                for i in range(3)
            )
        )
    ]
    generation.plan_responses = [
        GeneratedLearningPlan(
            concepts=tuple(
                GeneratedPlanConcept(
                    title=f"Mean {i}",
                    objective="Explain mean",
                    chunk_ids=("chunk",),
                    check_kind="single_choice",
                )
                for i in range(3)
            )
        )
    ]
    generation.check_responses = [GeneratedCheck(question=question)]
    service = _service(session, fastgpt, generation, locks)
    asked = await service.handle_message(wid, "我是新手，应该怎么学？", None, "ask")
    invites = DiagnosticInviteService(session)
    card = invites.current(wid)
    assert card and card.status == "offered"
    assert any(a.type == "start_diagnostic" for a in asked.suggested_actions)
    assert not list(session.scalars(select(Assessment)))
    if journey == "dismiss_cooldown":
        invites.dismiss(wid, card.id)
        asked = await service.handle_message(wid, "怎么学？", asked.conversation_id, "ask-again")
        assert not any(a.type == "start_diagnostic" for a in asked.suggested_actions)
        assert invites.current(wid).status == "dismissed"
        return
    payload = {
        "consent": True,
        "goal": "Learn mean",
        "invitation_id": card.id,
        "idempotency_key": "consent",
    }
    try:
        DiagnosticStartRequest(**{**payload, "consent": False})
    except ValidationError:
        pass
    else:
        raise AssertionError("Missing consent accepted")
    request = DiagnosticStartRequest(**payload)
    diagnostic = await service.diagnostics.start(wid, request)
    assert diagnostic.status == "active"
    if journey == "invite_consent":
        assert await service.diagnostics.start(wid, request) == diagnostic
        assert len(list(session.scalars(select(Assessment)))) == 3
        assert invites.current(wid).status == "accepted"
        return
    for q in diagnostic.questions:
        answer = await service.diagnostics.answer(
            wid,
            diagnostic.diagnostic_id,
            DiagnosticAnswerRequest(
                question_id=q.question_id, skip=True, idempotency_key=str(q.question_id)
            ),
        )
        assert answer.result == "not_assessed"
    if journey == "diagnostic_skip":
        assert answer.completed
        assert all(
            a.result is None and a.response is None for a in session.scalars(select(Attempt))
        )
        assert all(
            c.result == "not_assessed"
            for c in service.diagnostics.summary(wid, diagnostic.diagnostic_id).concepts
        )
        return
    plan = await service.plans.create_from_diagnostic(
        wid, PlanCreateRequest(diagnostic_id=diagnostic.diagnostic_id, idempotency_key="plan")
    )
    assert len(plan.concepts) == 3 and all(c.evidence_refs for c in plan.concepts)
    if journey == "bounded_plan":
        assert service.plans.get(wid, plan.plan_id) == plan
        assert len(service.plans.history(wid).plans) == 1
        return
    generation.responses = [
        GeneratedAnswer(
            blocks=tuple(
                GeneratedBlock(id=k, kind=k, text="sum divided by count", chunk_ids=("chunk",))
                for k in ("definition", "explanation", "example")
            )
        )
    ]
    lesson = await service.lessons.start(
        wid, plan.concepts[0].id, LessonRequest(depth="deeper", idempotency_key="lesson")
    )
    if journey == "reload":
        saved = service.view(wid)
        other = Workspace(title="Other", dataset_id="other")
        session.add(other)
        session.commit()
        other_id = other.id
        session.rollback()
        calls = (len(generation.calls), len(fastgpt.call_history))
        with Session(engine) as restored_session:
            restored = _service(restored_session, fastgpt, generation, locks)
            assert restored.view(wid) == saved
            assert restored.view(wid).lesson == lesson
            assert restored.view(wid).lesson.depth == "deeper"
            assert restored.view(other_id).kind == "idle"
        assert (len(generation.calls), len(fastgpt.call_history)) == calls
        return
    check = await service.checks.start(
        wid, plan.concepts[0].id, CheckStartRequest(idempotency_key="check")
    )
    assert check.assessment_id and "answer_key" not in check.model_dump()
    if journey == "check_detour":
        checkpoint = service.view(wid).checkpoint
        asked = await service.handle_message(wid, "Explain mean?", None, "detour")
        assert asked.suggested_actions[-1].checkpoint == checkpoint
        saved = service.view(wid)
        calls = (len(generation.calls), len(generation.check_calls), len(fastgpt.call_history))
        session.rollback()
        with Session(engine) as restored_session:
            restored = _service(restored_session, fastgpt, generation, locks)
            assert restored.view(wid) == saved
            resumed = await restored.resume(
                wid, ActivityCommand(checkpoint=checkpoint, idempotency_key="resume")
            )
            assert resumed.check == check and resumed.snapshot.active_mode == "CHECK"
        assert (
            len(generation.calls),
            len(generation.check_calls),
            len(fastgpt.call_history),
        ) == calls
        assert len(list(session.scalars(select(Attempt)))) == 3
        return
    answer = await service.checks.submit(
        wid,
        check.assessment_id,
        CheckAnswerRequest(
            response="product" if journey == "failed_check" else "sum", idempotency_key="answer"
        ),
    )
    state = session.get(ActivityState, wid)
    if journey == "failed_check":
        assert answer.next_action == "review_concept"
        assert service.view(wid).lesson == lesson
        assert state.active_concept_id == plan.concepts[0].id
    else:
        assert answer.next_action == "next_concept"
        assert state.active_concept_id == plan.concepts[1].id
        assert service.plans.get(wid, plan.plan_id).concepts[0].status == "completed"


async def run(args):
    results = []
    for case in load_cases(args.cases):
        try:
            results.append(await observe(case))
        except Exception:  # noqa: BLE001 - every failed journey must produce a redacted report
            # Reports contain identifiers and outcomes, never exception/provider text.
            results.append({"id": case["id"], "passed": False})
    report = {
        "total": len(results),
        "executed": len(results),
        "passed": sum(r["passed"] for r in results),
        "cases": results,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    print(f"Learning: {report['passed']}/{report['total']} passed")
    return int(report["passed"] != report["total"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="evals/cases/learning.jsonl")
    parser.add_argument("--output", default="evals/reports/learning-local.json")
    raise SystemExit(asyncio.run(run(parser.parse_args())))
