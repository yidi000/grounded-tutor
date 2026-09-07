from dataclasses import replace
from uuid import UUID

import pytest
from pydantic import ValidationError

from grounded_tutor.adapters.fastgpt import RetrievedChunk
from grounded_tutor.domain.answers import (
    Citation,
    GeneratedAnswer,
    GeneratedBlock,
    GroundedContentBlock,
)
from grounded_tutor.domain.models import SourceStatus, SourceType
from grounded_tutor.repositories.sources import SourceSummary
from grounded_tutor.services.grounding import ReadyChunk, ground_generated_answer


def chunks(count=1, excerpt="Evidence"):
    source = SourceSummary(
        id=UUID(int=1),
        workspace_id=UUID(int=2),
        name="Notes",
        source_type=SourceType.TEXT,
        origin_uri=None,
        status=SourceStatus.READY,
        version=1,
        lineage_id=UUID(int=1),
        replaces_source_id=None,
        superseded_at=None,
        deleted_at=None,
        ingestion_config={},
        error_message=None,
        created_at=None,
        updated_at=None,
    )
    return {
        str(i): ReadyChunk(
            RetrievedChunk(str(i), "collection", "provider", excerpt, "", 1), source, i + 1
        )
        for i in range(count)
    }


def block(identifier="b", text="Answer", ids=("0",)):
    return GeneratedBlock(id=identifier, kind="answer", text=text, chunk_ids=ids)


def ground(blocks, evidence=None):
    return ground_generated_answer(
        GeneratedAnswer(blocks=tuple(blocks)),
        chunks() if evidence is None else evidence,
        allowed_kinds={"answer"},
    )


@pytest.mark.parametrize("count,expected", [(32, "ok"), (33, "insufficient_material")])
def test_block_count_bound(count, expected):
    assert ground([block(str(i)) for i in range(count)]).status == expected


@pytest.mark.parametrize("count,expected", [(64, "ok"), (65, "insufficient_material")])
def test_total_citation_bound_across_blocks(count, expected):
    evidence = chunks(count)
    result = ground(
        [block("a", ids=tuple(evidence)[:32]), block("b", ids=tuple(evidence)[32:])], evidence
    )
    assert result.status == expected


@pytest.mark.parametrize("length,expected", [(6000, "ok"), (6001, "insufficient_material")])
def test_block_text_bound(length, expected):
    assert ground([block(text="x" * length)]).status == expected


@pytest.mark.parametrize("length,expected", [(12000, "ok"), (12001, "insufficient_material")])
def test_excerpt_bound_without_silent_truncation(length, expected):
    result = ground([block()], chunks(excerpt="x" * length))
    assert result.status == expected
    if result.citations:
        assert result.citations[0].excerpt == "x" * length


@pytest.mark.parametrize("field", ["context_before", "context_after"])
def test_optional_context_bound(field):
    citation = ground([block()]).citations[0].model_dump()
    Citation.model_validate({**citation, field: "x" * 2000})
    with pytest.raises(ValidationError):
        Citation.model_validate({**citation, field: "x" * 2001})


def test_duplicate_normalized_block_ids_and_blank_text_are_removed():
    result = ground([block("a"), block(" a "), block("blank", text=" \n ")])
    assert result.status == "insufficient_material"


def test_repeated_chunk_references_create_only_one_local_citation():
    result = ground([block(ids=("0", "0")), block("second")])
    assert len(result.citations) == 1
    assert all(b.citation_ids == ("citation-1",) for b in result.answer_blocks)
    with pytest.raises(ValidationError):
        GroundedContentBlock(id="b", kind="answer", text="A", citation_ids=("c", "c"))


def test_non_ready_source_cannot_support_valid_chunk_id():
    evidence = chunks()
    evidence["0"] = replace(
        evidence["0"], source=replace(evidence["0"].source, status=SourceStatus.REVIEW)
    )
    assert ground([block()], evidence).status == "insufficient_material"


def test_provider_bracket_labels_remain_plain_text():
    result = ground([block(text="Claim [1] [999]")])
    assert result.answer_blocks[0].text == "Claim [1] [999]"
    assert result.answer_blocks[0].citation_ids == ("citation-1",)
    assert len(result.citations) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed_first", [False, True])
async def test_retry_shape_changes_never_admit_foreign_or_unready_evidence(
    tmp_path, malformed_first
):
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from grounded_tutor.adapters.fakes import FakeFastGPT, FakeGeneration
    from grounded_tutor.adapters.generation import InvalidGenerationOutput
    from grounded_tutor.config import Settings
    from grounded_tutor.db import create_database_engine
    from grounded_tutor.domain.models import Base, Message, Source, Workspace
    from grounded_tutor.repositories.chat import ChatRepository
    from grounded_tutor.repositories.sources import SourceRepository
    from grounded_tutor.services.chat import ChatService

    engine = create_database_engine(Settings(database_url=f"sqlite:///{tmp_path / 'audit.db'}"))
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            current = Workspace(title="Current", dataset_id="current")
            other = Workspace(title="Other", dataset_id="other")
            session.add_all([current, other])
            session.flush()
            sources = [
                Source(
                    workspace_id=workspace.id,
                    name=name,
                    source_type=SourceType.TEXT,
                    status=status,
                    collection_id=name,
                    ingestion_config={},
                )
                for workspace, name, status in [
                    (current, "ready", SourceStatus.READY),
                    (current, "review", SourceStatus.REVIEW),
                    (other, "foreign", SourceStatus.READY),
                ]
            ]
            session.add_all(sources)
            session.commit()
            fastgpt = FakeFastGPT()
            fastgpt.search_results_override = tuple(
                RetrievedChunk(s.name, s.collection_id, "provider", s.name, "evidence", 1)
                for s in sources
            )
            oversized = GeneratedAnswer(blocks=(block(text="x" * 6001, ids=("ready",)),))
            malformed = InvalidGenerationOutput()
            # A provider can change its JSON shape between the first call and retry.
            generation = FakeGeneration(
                malformed if malformed_first else oversized,
                GeneratedAnswer(blocks=(block(ids=("foreign", "review")),))
                if malformed_first
                else malformed,
            )
            service = ChatService(
                SourceRepository(session), ChatRepository(session), fastgpt, generation
            )
            result = await service.ask(current.id, "Question", None, "audit")
            assert result.answer.status == "insufficient_material"
            assert result.answer.citations == ()
            assert len(generation.calls) == 2
            assert len(fastgpt.search_calls) == 1
            assert all(
                [c.chunk_id for c in request.chunks] == ["ready"] for request in generation.calls
            )
            saved = session.scalar(select(Message).where(Message.role == "assistant"))
            assert saved.content_blocks == []
            assert saved.citations == []
    finally:
        engine.dispose()
