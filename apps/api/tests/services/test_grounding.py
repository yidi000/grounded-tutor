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
    PptxLocator,
    SourceLocator,
    XlsxLocator,
)
from grounded_tutor.domain.models import SourceStatus, SourceType
from grounded_tutor.repositories.sources import SourceSummary
from grounded_tutor.services.grounding import ReadyChunk, ground_generated_answer
from grounded_tutor.services.sources import serialize_locator_marker


def _source(
    identifier: int,
    name: str,
    version: int = 1,
    source_type: SourceType = SourceType.TEXT,
) -> SourceSummary:
    return SourceSummary(
        id=UUID(int=identifier),
        workspace_id=UUID(int=100),
        name=name,
        source_type=source_type,
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


@pytest.mark.parametrize(
    ("name", "marker", "expected"),
    [
        (
            "slides.pptx",
            '[[GT_LOCATOR {"kind":"pptx","slide":1,"title":"Chunking"}]]',
            PptxLocator(slide=1, title="Chunking"),
        ),
        (
            "scores.xlsx",
            '[[GT_LOCATOR {"cell_range":"A1:B3","kind":"xlsx","sheet":"Week 1"}]]',
            XlsxLocator(sheet="Week 1", cell_range="A1:B3"),
        ),
    ],
)
def test_generated_office_markers_are_stripped_into_typed_locators(
    name: str,
    marker: str,
    expected: PptxLocator | XlsxLocator,
) -> None:
    ready = ReadyChunk(
        chunk=RetrievedChunk(
            "chunk-1",
            "collection-1",
            "provider-name",
            f"{marker}\nEvidence body",
            "",
            0.9,
        ),
        source=_source(1, name, source_type=SourceType.FILE),
        retrieval_position=1,
    )

    result = ground_generated_answer(
        GeneratedAnswer(
            blocks=(
                GeneratedBlock(
                    id="block-1",
                    kind="answer",
                    text="Supported",
                    chunk_ids=("chunk-1",),
                ),
            )
        ),
        {"chunk-1": ready},
        allowed_kinds={"answer"},
    )

    assert result.citations[0].excerpt == "Evidence body"
    assert result.citations[0].locator == expected


def test_generated_qa_answer_marker_is_trusted_and_question_is_retained() -> None:
    marker = '[[GT_LOCATOR {"kind":"pptx","slide":1,"title":"Chunking"}]]'
    ready = ReadyChunk(
        chunk=RetrievedChunk(
            "chunk-1",
            "collection-1",
            "provider",
            "What is chunking?",
            f"{marker}\nEvidence body",
            0.9,
        ),
        source=_source(1, "slides.pptx", source_type=SourceType.FILE),
        retrieval_position=1,
    )

    result = ground_generated_answer(
        GeneratedAnswer(
            blocks=(
                GeneratedBlock(
                    id="block-1", kind="answer", text="Answer", chunk_ids=("chunk-1",)
                ),
            )
        ),
        {"chunk-1": ready},
        allowed_kinds={"answer"},
    )

    assert result.citations[0].locator == PptxLocator(slide=1, title="Chunking")
    assert result.citations[0].excerpt == "What is chunking?\nEvidence body"


@pytest.mark.parametrize(
    ("name", "marker", "expected", "split"),
    [
        (name, marker, expected, split)
        for name, marker, expected in [
            (
                "slides.pptx",
                '[[GT_LOCATOR {"kind":"pptx","slide":1,"title":"Chunking"}]]',
                PptxLocator(slide=1, title="Chunking"),
            ),
            (
                "scores.xlsx",
                '[[GT_LOCATOR {"cell_range":"A1:B3","kind":"xlsx","sheet":"Week 1"}]]',
                XlsxLocator(sheet="Week 1", cell_range="A1:B3"),
            ),
            (
                "slides.pptx",
                serialize_locator_marker(
                    PptxLocator(
                        slide=2,
                        title="Before ]] and [[GT_LOCATOR after",
                    )
                ),
                PptxLocator(
                    slide=2,
                    title="Before ]] and [[GT_LOCATOR after",
                ),
            ),
        ]
        for split in range(1, len(marker))
    ],
)
def test_generated_office_marker_every_qa_boundary_split_is_reconstructed(
    name: str,
    marker: str,
    expected: PptxLocator | XlsxLocator,
    split: int,
) -> None:
    ready = ReadyChunk(
        chunk=RetrievedChunk(
            "chunk-1",
            "collection-1",
            "provider",
            marker[:split],
            f"{marker[split:]}\nEvidence body",
            0.9,
        ),
        source=_source(1, name, source_type=SourceType.FILE),
        retrieval_position=1,
    )

    result = ground_generated_answer(
        GeneratedAnswer(
            blocks=(
                GeneratedBlock(
                    id="block-1", kind="answer", text="Answer", chunk_ids=("chunk-1",)
                ),
            )
        ),
        {"chunk-1": ready},
        allowed_kinds={"answer"},
    )

    assert result.citations[0].locator == expected
    assert result.citations[0].excerpt == "Evidence body"
    assert "GT_LOCATOR" not in result.citations[0].excerpt


@pytest.mark.parametrize(
    "answer",
    [
        '"slide":"one"}]]\nEvidence body',
        '"slide":1\nEvidence body',
    ],
)
def test_invalid_or_incomplete_office_marker_split_does_not_leak(
    answer: str,
) -> None:
    ready = ReadyChunk(
        chunk=RetrievedChunk(
            "chunk-1",
            "collection-1",
            "provider",
            '[[GT_LOCATOR {"kind":"pptx",',
            answer,
            0.9,
        ),
        source=_source(1, "slides.pptx", source_type=SourceType.FILE),
        retrieval_position=3,
    )

    result = ground_generated_answer(
        GeneratedAnswer(
            blocks=(
                GeneratedBlock(
                    id="block-1", kind="answer", text="Answer", chunk_ids=("chunk-1",)
                ),
            )
        ),
        {"chunk-1": ready},
        allowed_kinds={"answer"},
    )

    assert result.citations[0].locator == ChunkLocator(label="匹配片段 3")
    assert result.citations[0].excerpt == "Evidence body"
    assert "GT_LOCATOR" not in result.citations[0].excerpt
    assert '"slide"' not in result.citations[0].excerpt


@pytest.mark.parametrize(
    "chunk_text",
    [
        '[[GT_LOCATOR {"kind":"pptx","slide":"one"}]]\nEvidence body',
        '[[GT_LOCATOR {"kind":"pdf","page":9}]]\nEvidence body',
        (
            '[[GT_LOCATOR {"kind":"pptx","slide":1}]]\n'
            '[[GT_LOCATOR {"kind":"pptx","slide":2}]]\nEvidence body'
        ),
        '[[GT_LOCATOR {"kind":"xlsx","sheet":"Forged"}]]\nEvidence body',
    ],
)
def test_invalid_ambiguous_or_mismatched_markers_fall_back_without_leaking(
    chunk_text: str,
) -> None:
    ready = ReadyChunk(
        chunk=RetrievedChunk(
            "chunk-1", "collection-1", "provider", chunk_text, "", 0.9
        ),
        source=_source(1, "slides.pptx", source_type=SourceType.FILE),
        retrieval_position=4,
    )

    result = ground_generated_answer(
        GeneratedAnswer(
            blocks=(
                GeneratedBlock(
                    id="block-1",
                    kind="answer",
                    text="Supported",
                    chunk_ids=("chunk-1",),
                ),
            )
        ),
        {"chunk-1": ready},
        allowed_kinds={"answer"},
    )

    assert result.citations[0].locator == ChunkLocator(label="匹配片段 4")
    assert "GT_LOCATOR" not in result.citations[0].excerpt
    assert result.citations[0].excerpt == "Evidence body"


@pytest.mark.parametrize(
    "marker_like_text",
    [
        'x[[GT_LOCATOR{"kind":"pptx","slide":5}]]',
        '[[GT_LOCATOR{"kind":"pptx","slide":5}]]',
        '[[GT_LOCATOR\t{"kind":"pptx","slide":6}]]',
    ],
)
def test_marker_like_user_text_requires_the_exact_generated_prefix(
    marker_like_text: str,
) -> None:
    ready = ReadyChunk(
        chunk=RetrievedChunk(
            "chunk-1",
            "collection-1",
            "provider",
            f"{marker_like_text}\nEvidence body",
            "",
            0.9,
        ),
        source=_source(1, "slides.pptx", source_type=SourceType.FILE),
        retrieval_position=5,
    )

    result = ground_generated_answer(
        GeneratedAnswer(
            blocks=(
                GeneratedBlock(
                    id="block-1", kind="answer", text="Answer", chunk_ids=("chunk-1",)
                ),
            )
        ),
        {"chunk-1": ready},
        allowed_kinds={"answer"},
    )

    assert result.citations[0].locator == ChunkLocator(label="匹配片段 5")
    assert result.citations[0].excerpt == "Evidence body"
    assert "GT_LOCATOR" not in result.citations[0].excerpt


def test_semantically_valid_noncanonical_marker_is_not_trusted() -> None:
    marker = '[[GT_LOCATOR {"slide":1,"kind":"pptx"}]]'
    ready = ReadyChunk(
        chunk=RetrievedChunk(
            "chunk-1", "collection-1", "provider", f"{marker}\nEvidence", "", 0.9
        ),
        source=_source(1, "slides.pptx", source_type=SourceType.FILE),
        retrieval_position=6,
    )

    result = ground_generated_answer(
        GeneratedAnswer(
            blocks=(
                GeneratedBlock(
                    id="block-1", kind="answer", text="Answer", chunk_ids=("chunk-1",)
                ),
            )
        ),
        {"chunk-1": ready},
        allowed_kinds={"answer"},
    )

    assert result.citations[0].locator == ChunkLocator(label="匹配片段 6")
    assert result.citations[0].excerpt == "Evidence"


def test_valid_looking_marker_from_non_office_source_is_untrusted() -> None:
    marker = '[[GT_LOCATOR {"kind":"pptx","slide":999}]]'
    ready = ReadyChunk(
        chunk=RetrievedChunk(
            "chunk-1", "collection-1", "provider", f"{marker}\nUser content", "", 0.9
        ),
        source=_source(1, "notes.txt", source_type=SourceType.FILE),
        retrieval_position=2,
    )

    result = ground_generated_answer(
        GeneratedAnswer(
            blocks=(
                GeneratedBlock(
                    id="block-1", kind="answer", text="Answer", chunk_ids=("chunk-1",)
                ),
            )
        ),
        {"chunk-1": ready},
        allowed_kinds={"answer"},
    )

    assert result.citations[0].locator == ChunkLocator(label="匹配片段 2")
    assert result.citations[0].excerpt == f"{marker}\nUser content"


@pytest.mark.parametrize(
    ("source_type", "name"),
    [
        (SourceType.TEXT, "Pasted text"),
        (SourceType.FILE, "notes.txt"),
    ],
)
@pytest.mark.parametrize(
    ("q", "a", "expected"),
    [
        ("[[GT_LOCATOR", "", "[[GT_LOCATOR"),
        (
            "Question with [[GT_LOCATOR evidence",
            "Answer body",
            "Question with [[GT_LOCATOR evidence\nAnswer body",
        ),
    ],
)
def test_non_office_marker_text_remains_resolvable_exact_evidence(
    source_type: SourceType,
    name: str,
    q: str,
    a: str,
    expected: str,
) -> None:
    ready = ReadyChunk(
        chunk=RetrievedChunk("chunk-1", "collection-1", "provider", q, a, 0.9),
        source=_source(1, name, source_type=source_type),
        retrieval_position=2,
    )

    result = ground_generated_answer(
        GeneratedAnswer(
            blocks=(
                GeneratedBlock(
                    id="block-1", kind="answer", text="Answer", chunk_ids=("chunk-1",)
                ),
            )
        ),
        {"chunk-1": ready},
        allowed_kinds={"answer"},
    )

    assert result.status == "ok"
    assert result.citations[0].locator == ChunkLocator(label="匹配片段 2")
    assert result.citations[0].excerpt == expected


def test_out_of_bounds_xlsx_marker_falls_back_to_chunk_location() -> None:
    marker = (
        '[[GT_LOCATOR {"cell_range":"XFE1:XFE2","kind":"xlsx",'
        '"sheet":"Week 1"}]]'
    )
    ready = ReadyChunk(
        chunk=RetrievedChunk(
            "chunk-1", "collection-1", "provider", f"{marker}\nEvidence", "", 0.9
        ),
        source=_source(1, "scores.xlsx", source_type=SourceType.FILE),
        retrieval_position=3,
    )

    result = ground_generated_answer(
        GeneratedAnswer(
            blocks=(
                GeneratedBlock(
                    id="block-1", kind="answer", text="Answer", chunk_ids=("chunk-1",)
                ),
            )
        ),
        {"chunk-1": ready},
        allowed_kinds={"answer"},
    )

    assert result.citations[0].locator == ChunkLocator(label="匹配片段 3")
    assert result.citations[0].excerpt == "Evidence"


def test_image_sources_use_filename_without_guessing_a_region() -> None:
    ready = ReadyChunk(
        chunk=RetrievedChunk(
            "chunk-1", "collection-1", "provider", "Diagram evidence", "", 0.9
        ),
        source=_source(1, "diagram.png", source_type=SourceType.FILE),
        retrieval_position=1,
    )

    result = ground_generated_answer(
        GeneratedAnswer(
            blocks=(
                GeneratedBlock(
                    id="block-1", kind="answer", text="Answer", chunk_ids=("chunk-1",)
                ),
            )
        ),
        {"chunk-1": ready},
        allowed_kinds={"answer"},
    )

    assert result.citations[0].locator == ImageLocator(filename="diagram.png")
    assert result.citations[0].locator.region is None
