from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from grounded_tutor.adapters.fastgpt import RetrievedChunk
from grounded_tutor.domain.answers import (
    ChunkLocator,
    Citation,
    GeneratedAnswer,
    GroundedAnswer,
    GroundedContentBlock,
    GroundedContentKind,
)
from grounded_tutor.domain.models import SourceStatus
from grounded_tutor.repositories.sources import SourceSummary


@dataclass(frozen=True, slots=True)
class ReadyChunk:
    chunk: RetrievedChunk
    source: SourceSummary
    retrieval_position: int


def ground_generated_answer(
    generated: GeneratedAnswer,
    ready_chunks: dict[str, ReadyChunk],
    *,
    allowed_kinds: set[GroundedContentKind],
) -> GroundedAnswer:
    normalized_ids = [block.id.strip() for block in generated.blocks]
    duplicate_ids = {
        block_id for block_id, count in Counter(normalized_ids).items() if block_id and count > 1
    }
    valid: list[tuple[str, GroundedContentKind, str, tuple[str, ...]]] = []
    for block in generated.blocks:
        block_id = block.id.strip()
        text = block.text.strip()
        chunk_ids = tuple(dict.fromkeys(chunk_id.strip() for chunk_id in block.chunk_ids))
        if (
            not block_id
            or block_id in duplicate_ids
            or not text
            or block.kind not in allowed_kinds
            or not chunk_ids
            or any(not _is_resolvable(chunk_id, ready_chunks) for chunk_id in chunk_ids)
        ):
            continue
        valid.append((block_id, block.kind, text, chunk_ids))

    if not valid:
        return GroundedAnswer(status="insufficient_material", answer_blocks=(), citations=())

    used_chunk_ids = {chunk_id for _, _, _, chunk_ids in valid for chunk_id in chunk_ids}
    ordered_chunks = [
        ready for chunk_id, ready in ready_chunks.items() if chunk_id in used_chunk_ids
    ]
    citation_ids = {
        ready.chunk.chunk_id: f"citation-{position}"
        for position, ready in enumerate(ordered_chunks, start=1)
    }
    citations = tuple(
        Citation(
            id=citation_ids[ready.chunk.chunk_id],
            source_id=ready.source.id,
            source_name=ready.source.name,
            source_version=ready.source.version,
            chunk_id=ready.chunk.chunk_id,
            excerpt=_excerpt(ready.chunk),
            locator=ChunkLocator(label=f"匹配片段 {ready.retrieval_position}"),
        )
        for ready in ordered_chunks
    )
    blocks = tuple(
        GroundedContentBlock(
            id=block_id,
            kind=kind,
            text=text,
            citation_ids=tuple(
                citation_ids[chunk_id]
                for chunk_id in ready_chunks
                if chunk_id in set(chunk_ids)
            ),
        )
        for block_id, kind, text, chunk_ids in valid
    )
    return GroundedAnswer(status="ok", answer_blocks=blocks, citations=citations)


def _is_resolvable(chunk_id: str, ready_chunks: dict[str, ReadyChunk]) -> bool:
    ready = ready_chunks.get(chunk_id)
    return (
        bool(chunk_id)
        and ready is not None
        and ready.chunk.chunk_id == chunk_id
        and ready.source.status is SourceStatus.READY
        and bool(_excerpt(ready.chunk))
        and ready.retrieval_position >= 1
    )


def _excerpt(chunk: RetrievedChunk) -> str:
    return "\n".join(text.strip() for text in (chunk.q, chunk.a) if text.strip())
