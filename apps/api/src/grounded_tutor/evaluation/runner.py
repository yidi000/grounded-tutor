"""Run real ASK services with fake providers and a fresh SQLite DB per case."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from grounded_tutor.adapters.fakes import FakeFastGPT, FakeGeneration
from grounded_tutor.adapters.fastgpt import RetrievedChunk
from grounded_tutor.adapters.generation import InvalidGenerationOutput
from grounded_tutor.domain.models import Base, Conversation, Message, Source, SourceType, Workspace
from grounded_tutor.evaluation.metrics import check_targets, summarize
from grounded_tutor.evaluation.schema import TARGETS, EvaluationCase
from grounded_tutor.repositories.chat import ChatConversationNotFoundError, ChatRepository
from grounded_tutor.repositories.sources import SourceRepository
from grounded_tutor.services.chat import ChatService, ExternalChatServiceError
from grounded_tutor.services.idempotency import (
    IdempotencyInProgress,
    IdempotencyKeyReused,
    request_hash,
)
from grounded_tutor.services.tracing import TraceRecorder


def load_cases(path: Path | str) -> list[EvaluationCase]:
    cases = [
        EvaluationCase.model_validate_json(line)
        for line in Path(path).read_text().splitlines()
        if line.strip()
    ]
    if not cases:
        raise ValueError("Case file is empty")
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("Duplicate case IDs")
    return cases


async def observe(case: EvaluationCase) -> dict:
    with TemporaryDirectory(prefix="grounded-eval-") as directory:
        engine = create_engine(f"sqlite:///{directory}/eval.db")

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        try:
            Base.metadata.create_all(engine)
            with Session(engine) as session:
                return await _journey(case, session)
        finally:
            engine.dispose()


async def _journey(case: EvaluationCase, session: Session) -> dict:
    workspaces = {name: Workspace(title=name, dataset_id=name) for name in ("current", "other")}
    session.add_all(workspaces.values())
    session.commit()
    sources = []
    for fixture in case.workspace_fixture:
        source = Source(
            workspace_id=workspaces[fixture.workspace].id,
            name=fixture.name,
            collection_id=fixture.collection_id,
            source_type=SourceType.TEXT,
            status=fixture.status,
            version=fixture.version,
            ingestion_config={},
            deleted_at=datetime.now(UTC) if fixture.deleted else None,
            superseded_at=datetime.now(UTC) if fixture.superseded else None,
        )
        sources.append(source)
        session.add(source)
    session.commit()
    fastgpt = FakeFastGPT()
    fastgpt.search_results_override = tuple(
        RetrievedChunk(**c.model_dump()) for c in case.input.chunks
    )
    if case.input.search_failure:
        fastgpt.failures["search"] = RuntimeError("Simulated search outage")
    generation = FakeGeneration(
        *[
            InvalidGenerationOutput()
            if response == "invalid"
            else RuntimeError("Simulated generation outage")
            if response == "failure"
            else response
            for response in case.input.responses
        ]
    )
    chats = ChatRepository(session)
    service = ChatService(
        SourceRepository(session), chats, fastgpt, generation, TraceRecorder(session)
    )
    workspace_id = workspaces["current"].id
    conversation_id = None
    journey = case.input.journey
    if journey == "foreign_conversation":
        conversation = Conversation(workspace_id=workspaces["other"].id)
        session.add(conversation)
        session.commit()
        conversation_id = conversation.id
    if journey == "pending":
        chats.claim_request(workspace_id, "key", request_hash(case.input.message, None))

    async def ask(message=case.input.message):
        return await service.ask(workspace_id, message, conversation_id, "key")

    result = None
    replay_valid = False
    recovered = False
    try:
        if journey == "recover":
            try:
                await ask()
            except ExternalChatServiceError:
                recovered = True
            else:
                raise AssertionError("Recovery fixture did not trigger a failure")
        result = await ask()
        status = result.answer.status
        if journey == "replay":
            before = (len(fastgpt.call_history), len(generation.calls))
            replay = await ask()
            replay_valid = result == replay and before == (
                len(fastgpt.call_history),
                len(generation.calls),
            )
        elif journey == "conflict":
            await ask(case.input.message + " changed")
    except IdempotencyKeyReused:
        status = "conflict"
    except IdempotencyInProgress:
        status = "pending"
    except ChatConversationNotFoundError:
        status = "not_found"

    answer = result.answer if result else None
    citations = {c.id: c for c in answer.citations} if answer else {}
    ready = {
        s.collection_id: s
        for s in sources
        if s.workspace_id == workspace_id
        and s.status.value == "ready"
        and not s.deleted_at
        and not s.superseded_at
    }
    chunks = {c.chunk_id: c for c in case.input.chunks if c.collection_id in ready}
    valid_citations = set()
    for identifier, citation in citations.items():
        chunk = chunks.get(citation.chunk_id)
        source = ready.get(chunk.collection_id) if chunk else None
        if (
            source
            and (citation.source_id, citation.source_name, citation.source_version)
            == (source.id, source.name, source.version)
            and citation.excerpt == "\n".join(t.strip() for t in (chunk.q, chunk.a) if t.strip())
        ):
            valid_citations.add(identifier)
    blocks = answer.answer_blocks if answer else ()
    grounded_blocks = sum(
        bool(b.citation_ids) and set(b.citation_ids) <= valid_citations for b in blocks
    )
    names = sorted({c.source_name for c in citations.values()})
    history = service.history(workspace_id)
    other_history = service.history(workspaces["other"].id)
    # Inspect provider inputs as well as user-visible output/history for foreign evidence.
    foreign = [
        c
        for c in case.input.chunks
        if any(
            s.collection_id == c.collection_id and s.workspace_id != workspace_id for s in sources
        )
    ]
    surface = json.dumps(
        {
            "answer": answer.model_dump(mode="json") if answer else None,
            "history": history.model_dump(mode="json"),
        },
        ensure_ascii=False,
    )
    leaked_chunks = {
        c.chunk_id
        for request in generation.calls
        for c in request.chunks
        if c.collection_id not in ready
    }
    leaked_text = {
        c.chunk_id for c in foreign if any(text and text in surface for text in (c.q, c.a))
    }
    leakage = len(leaked_chunks | leaked_text)
    calls = {
        "search": sum(call[0] == "search" for call in fastgpt.call_history),
        "generate": len(generation.calls),
    }
    unauthorized = sum(
        max(0, count - case.expected_external_calls[name]) for name, count in calls.items()
    )
    unauthorized += sum(call[0] != "search" for call in fastgpt.call_history)
    expected_messages = 2 if result else 0
    history_valid = (
        len(list(session.scalars(select(Message)))) == expected_messages
        and len(history.exchanges) == (1 if result else 0)
        and not other_history.exchanges
    )
    if result and history.exchanges:
        saved = history.exchanges[0]
        history_valid = history_valid and (
            saved.question == case.input.message
            and saved.response.message_id == result.message_id
            and saved.response.conversation_id == result.conversation_id
            and saved.response.status == answer.status
            and saved.response.answer_blocks == answer.answer_blocks
            and saved.response.citations == answer.citations
        )
    return {
        "status": status,
        "source_names": names,
        "external_calls": calls,
        "block_count": len(blocks),
        "grounded_blocks": grounded_blocks,
        "citations_valid": len(valid_citations) == len(citations)
        and (not answer or len(citations) == len(answer.citations))
        and len({block.id for block in blocks}) == len(blocks),
        "leakage_count": leakage,
        "unauthorized_calls": unauthorized,
        "replay_valid": replay_valid,
        "recovered": recovered,
        "history_valid": history_valid,
    }


async def run_suite(cases: list[EvaluationCase]) -> dict:
    results = []
    for case in cases:
        result = {
            "id": case.id,
            "category": case.category,
            "journey": case.input.journey,
            "expected_status": case.expected_status,
            "expected_source_names": case.expected_source_names,
            "forbidden_source_names": case.forbidden_source_names,
            "expected_external_calls": case.expected_external_calls,
            "passed": False,
            "error": None,
        }
        try:
            observed = await observe(case)
            checks = {
                "status": observed["status"] == case.expected_status,
                "sources": observed["source_names"] == sorted(set(case.expected_source_names)),
                "forbidden_sources": not set(observed["source_names"])
                & set(case.forbidden_source_names),
                "calls": observed["external_calls"] == case.expected_external_calls,
                "citations": observed["citations_valid"]
                and observed["block_count"] == observed["grounded_blocks"],
                "isolation": observed["leakage_count"] == 0,
                "history": observed["history_valid"],
                "replay": case.input.journey != "replay" or observed["replay_valid"],
                "recovery": case.input.journey != "recover" or observed["recovered"],
            }
            result.update(observed=observed, checks=checks, passed=all(checks.values()))
        except Exception as error:  # noqa: BLE001 - report per-case errors and keep running.
            # No raw exception text: diagnostics must never expose configuration credentials.
            result["error"] = type(error).__name__
        results.append(result)
    return {
        "total": len(cases),
        "executed": sum(r["error"] is None for r in results),
        "execution_errors": sum(r["error"] is not None for r in results),
        "results": results,
        "metrics": summarize(results),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--targets", type=Path, default=Path("evals/targets.json"))
    args = parser.parse_args()
    try:
        cases = load_cases(args.cases)
        targets = TARGETS.validate_json(args.targets.read_text())
        report = asyncio.run(run_suite(cases))
        config = {
            "cases": [case.model_dump(mode="json") for case in cases],
            "targets": targets,
            "adapter": "fake",
            "database": "isolated-sqlite",
            "schema_version": 1,
            "source_hash": hashlib.sha256(
                b"".join(
                    path.relative_to(Path(__file__).parents[1]).as_posix().encode()
                    + path.read_bytes()
                    for path in sorted(Path(__file__).parents[1].rglob("*.py"))
                )
            ).hexdigest(),
        }
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
        )
        report.update(
            timestamp=datetime.now(UTC).isoformat(),
            configuration_hash=hashlib.sha256(
                json.dumps(config, sort_keys=True).encode()
            ).hexdigest(),
            git_commit=commit.stdout.strip() if commit.returncode == 0 else None,
            configuration=config,
            target_checks=check_targets(report["metrics"], targets),
            targets=targets,
        )
        exit_code = (
            2
            if report["execution_errors"]
            else 0
            if (
                all(r["passed"] for r in report["results"])
                and all(report["target_checks"].values())
            )
            else 1
        )
        report["exit_code"] = exit_code
    except (OSError, ValueError) as error:
        report = {"exit_code": 2, "error": type(error).__name__}
        exit_code = 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"{report.get('executed', 0)}/{report.get('total', 0)} executed; exit={exit_code}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
