from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError

from grounded_tutor.adapters.fastgpt import RetrievedChunk
from grounded_tutor.domain.answers import (
    ChunkLocator,
    Citation,
    GeneratedAnswer,
    GeneratedBlock,
    GroundedContentBlock,
    ImageLocator,
    PdfLocator,
    SourceLocator,
)
from grounded_tutor.domain.models import SourceStatus, SourceType
from grounded_tutor.repositories.sources import SourceSummary
from grounded_tutor.services.grounding import ReadyChunk, ground_generated_answer


def _source(identifier: int, name: str, version: int = 1) -> SourceSummary:
    return SourceSummary(
        id=UUID(int=identifier),
        workspace_id=UUID(int=100),
        name=name,
        source_type=SourceType.TEXT,
        origin_uri=None,
        status=SourceStatus.READY,
        version=version,
        lineage_id=UUID(int=identifier),
        replaces_source_id=None,
        superseded_at=None,
        deleted_at=None,
        ingestion_config={},
        error_message=None,
        created_at=None,  # type: ignore[arg-type]
        updated_at=None,  # type: ignore[arg-type]
    )


@pytest.fixture
def ready_chunks() -> dict[str, ReadyChunk]:
    return {
        "chunk-1": ReadyChunk(
            chunk=RetrievedChunk(
                "chunk-1", "collection-1", "provider-name", "什么是均值？", "均值是平均数。", 0.9
            ),
            source=_source(1, "本地统计讲义", 3),
            retrieval_position=1,
        ),
        "chunk-2": ReadyChunk(
            chunk=RetrievedChunk(
                "chunk-2", "collection-2", "wrong-provider-name", "Median", "Middle value.", 0.8
            ),
            source=_source(2, "Local medians"),
            retrieval_position=2,
        ),
    }


def test_valid_blocks_use_local_sources_and_deterministic_reused_citations(
    ready_chunks: dict[str, ReadyChunk],
) -> None:
    generated = GeneratedAnswer(
        blocks=(
            GeneratedBlock(
                id="block-1",
                kind="answer",
                text="先解释中位数。",
                chunk_ids=("chunk-2", "chunk-1"),
            ),
            GeneratedBlock(
                id="block-2",
                kind="answer",
                text="再补充均值。",
                chunk_ids=("chunk-1",),
            ),
        )
    )

    result = ground_generated_answer(generated, ready_chunks, allowed_kinds={"answer"})

    assert result.status == "ok"
    assert [citation.id for citation in result.citations] == ["citation-1", "citation-2"]
    assert [citation.chunk_id for citation in result.citations] == ["chunk-1", "chunk-2"]
    assert result.citations[0].source_name == "本地统计讲义"
    assert result.citations[0].source_version == 3
    assert result.citations[0].excerpt == "什么是均值？\n均值是平均数。"
    assert result.citations[0].locator == ChunkLocator(label="匹配片段 1")
    assert result.citations[1].locator == ChunkLocator(label="匹配片段 2")
    assert result.answer_blocks[0].citation_ids == ("citation-1", "citation-2")
    assert result.answer_blocks[1].citation_ids == ("citation-1",)


@pytest.mark.parametrize(
    "block",
    [
        GeneratedBlock(id="block-1", kind="answer", text="Unknown", chunk_ids=("missing",)),
        GeneratedBlock(id="block-1", kind="answer", text="Dangling", chunk_ids=("chunk-1", "missing")),
        GeneratedBlock(id="block-1", kind="answer", text="No citation", chunk_ids=()),
        GeneratedBlock(id="block-1", kind="definition", text="Wrong kind", chunk_ids=("chunk-1",)),
        GeneratedBlock(id=" ", kind="answer", text="Blank id", chunk_ids=("chunk-1",)),
        GeneratedBlock(id="block-1", kind="answer", text=" \n ", chunk_ids=("chunk-1",)),
    ],
)
def test_invalid_block_becomes_insufficient_material(
    block: GeneratedBlock, ready_chunks: dict[str, ReadyChunk]
) -> None:
    result = ground_generated_answer(
        GeneratedAnswer(blocks=(block,)), ready_chunks, allowed_kinds={"answer"}
    )

    assert result.status == "insufficient_material"
    assert result.answer_blocks == ()
    assert result.citations == ()


def test_partial_invalid_output_keeps_only_valid_blocks(
    ready_chunks: dict[str, ReadyChunk],
) -> None:
    result = ground_generated_answer(
        GeneratedAnswer(
            blocks=(
                GeneratedBlock(
                    id="block-1", kind="answer", text="Supported", chunk_ids=("chunk-1",)
                ),
                GeneratedBlock(
                    id="block-2", kind="answer", text="Unsupported", chunk_ids=("missing",)
                ),
            )
        ),
        ready_chunks,
        allowed_kinds={"answer"},
    )

    assert [block.text for block in result.answer_blocks] == ["Supported"]
    assert result.answer_blocks[0].citation_ids == ("citation-1",)


def test_duplicate_block_ids_are_all_removed(ready_chunks: dict[str, ReadyChunk]) -> None:
    result = ground_generated_answer(
        GeneratedAnswer(
            blocks=(
                GeneratedBlock(id="same", kind="answer", text="One", chunk_ids=("chunk-1",)),
                GeneratedBlock(id="same", kind="answer", text="Two", chunk_ids=("chunk-2",)),
            )
        ),
        ready_chunks,
        allowed_kinds={"answer"},
    )

    assert result.status == "insufficient_material"
    assert result.answer_blocks == ()


def test_public_contract_rejects_blank_text_empty_citations_and_invalid_locators() -> None:
    with pytest.raises(ValidationError):
        GroundedContentBlock(id="b", kind="answer", text=" ", citation_ids=("c",))
    with pytest.raises(ValidationError):
        GroundedContentBlock(id="b", kind="answer", text="answer", citation_ids=())
    with pytest.raises(ValidationError):
        PdfLocator(page=0)
    with pytest.raises(ValidationError):
        ImageLocator(filename=" ")

    parsed = TypeAdapter(SourceLocator).validate_python({"kind": "pdf", "page": 4})
    assert parsed == PdfLocator(page=4)


def test_provider_contract_rejects_browser_citation_ids() -> None:
    with pytest.raises(ValidationError):
        GeneratedBlock.model_validate(
            {
                "id": "block-1",
                "kind": "answer",
                "text": "Answer",
                "chunk_ids": ["chunk-1"],
                "citation_ids": ["citation-provider"],
            }
        )


def test_citation_locator_is_a_discriminated_union() -> None:
    citation = Citation.model_validate(
        {
            "id": "citation-1",
            "source_id": str(UUID(int=1)),
            "source_name": "notes.png",
            "source_version": 1,
            "chunk_id": "chunk-1",
            "excerpt": "evidence",
            "locator": {"kind": "image", "filename": "notes.png", "region": "top-left"},
        }
    )

    assert citation.locator == ImageLocator(filename="notes.png", region="top-left")
