from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from grounded_tutor.adapters.fastgpt import RetrievedChunk
from grounded_tutor.domain.answers import (
    ChunkLocator,
    Citation,
    GeneratedAnswer,
    GroundedAnswer,
    GroundedContentBlock,
    GroundedContentKind,
    ImageLocator,
    PptxLocator,
    SourceLocator,
    XlsxLocator,
)
from grounded_tutor.domain.models import SourceStatus, SourceType
from grounded_tutor.repositories.sources import SourceSummary
from grounded_tutor.services.previews import (
    IMAGE_EXTENSIONS,
    MAX_PPTX_LOCATOR_TITLE_CHARS,
    MAX_PPTX_SLIDES,
    MAX_XLSX_ROWS,
)
from grounded_tutor.services.sources import (
    LOCATOR_MARKER_PREFIX,
    LOCATOR_MARKER_TOKEN,
    serialize_locator_marker,
)

MAX_LOCATOR_MARKER_CHARS = len(
    serialize_locator_marker(
        PptxLocator(
            slide=MAX_PPTX_SLIDES,
            title="[" * MAX_PPTX_LOCATOR_TITLE_CHARS,
        )
    )
)
XLSX_RANGE_PATTERN = re.compile(
    r"([A-Z]{1,3})([1-9][0-9]*):([A-Z]{1,3})([1-9][0-9]*)"
)
MAX_TRUSTED_XLSX_COLUMN = 16_384


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
        _citation(ready, citation_ids[ready.chunk.chunk_id])
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
        and bool(_chunk_analysis(ready)[0])
        and ready.retrieval_position >= 1
    )


def _citation(ready: ReadyChunk, citation_id: str) -> Citation:
    excerpt, locator = _chunk_analysis(ready)
    return Citation(
        id=citation_id,
        source_id=ready.source.id,
        source_name=ready.source.name,
        source_version=ready.source.version,
        chunk_id=ready.chunk.chunk_id,
        excerpt=excerpt,
        locator=locator,
    )


def _chunk_analysis(ready: ReadyChunk) -> tuple[str, SourceLocator]:
    raw = "\n".join(
        text.strip() for text in (ready.chunk.q, ready.chunk.a) if text.strip()
    )
    source = ready.source
    suffix = Path(source.name).suffix.lower()
    if source.source_type is SourceType.FILE and suffix in IMAGE_EXTENSIONS:
        return raw, ImageLocator(filename=source.name)
    if source.source_type is SourceType.FILE and suffix in {".pptx", ".xlsx"}:
        excerpt, locator = _office_chunk_analysis(ready.chunk, source)
        return excerpt, locator or ChunkLocator(
            label=f"匹配片段 {ready.retrieval_position}"
        )
    return raw, ChunkLocator(label=f"匹配片段 {ready.retrieval_position}")


def _office_chunk_analysis(
    chunk: RetrievedChunk, source: SourceSummary
) -> tuple[str, SourceLocator | None]:
    raw_q, raw_a = chunk.q, chunk.a
    q, a = raw_q.strip(), raw_a.strip()
    fields = (q, a)
    token_count = sum(text.count(LOCATOR_MARKER_TOKEN) for text in fields)
    candidates: list[SourceLocator] = []
    if token_count == 1:
        for text in fields:
            if text:
                locator = _trusted_office_locator(text.splitlines()[0], source)
                if locator is not None:
                    candidates.append(locator)

    first_answer_line = raw_a.splitlines()[0] if raw_a else ""
    boundary_line = raw_q + first_answer_line
    boundary_locator = (
        _trusted_office_locator(boundary_line, source)
        if raw_q and first_answer_line and "\n" not in raw_q
        else None
    )
    if boundary_locator is not None:
        expected_token_count = 1 if LOCATOR_MARKER_TOKEN in q else 0
        if token_count == expected_token_count:
            candidates.append(boundary_locator)

    boundary_attempt = "\n" not in raw_q and (
        (raw_q and LOCATOR_MARKER_PREFIX.startswith(raw_q))
        or (
            raw_q.startswith(LOCATOR_MARKER_PREFIX)
            and "]]" not in raw_q
        )
    )
    cleaned_fields: list[str] = []
    for position, text in enumerate(fields):
        lines = text.splitlines()
        if boundary_attempt and position == 0:
            lines = []
        elif boundary_attempt and position == 1 and lines:
            lines = lines[1:]
        cleaned = "\n".join(
            line for line in lines if LOCATOR_MARKER_TOKEN not in line
        ).strip()
        if cleaned:
            cleaned_fields.append(cleaned)
    locator = candidates[0] if len(candidates) == 1 else None
    return "\n".join(cleaned_fields), locator


def _trusted_office_locator(marker: str, source: SourceSummary) -> SourceLocator | None:
    suffix = Path(source.name).suffix.lower()
    if (
        len(marker) > MAX_LOCATOR_MARKER_CHARS
        or not marker.startswith(LOCATOR_MARKER_PREFIX)
        or not marker.endswith("]]")
    ):
        return None
    encoded = marker[len(LOCATOR_MARKER_PREFIX) : -2]
    try:
        payload = json.loads(encoded, object_pairs_hook=_unique_object)
        if not isinstance(payload, dict):
            return None
        if suffix == ".pptx":
            allowed = {"kind", "slide"} | ({"title"} if "title" in payload else set())
            if set(payload) != allowed or payload.get("kind") != "pptx":
                return None
            title = payload.get("title")
            if title is not None and (
                not isinstance(title, str)
                or title != title.strip()
                or not title
                or len(title) > MAX_PPTX_LOCATOR_TITLE_CHARS
            ):
                return None
            locator = PptxLocator.model_validate(payload, strict=True)
            if (
                locator.slide > MAX_PPTX_SLIDES
                or marker != serialize_locator_marker(locator)
            ):
                return None
            return locator
        if (
            set(payload) != {"cell_range", "kind", "sheet"}
            or payload.get("kind") != "xlsx"
            or not isinstance(payload.get("cell_range"), str)
            or not _valid_xlsx_range(payload["cell_range"])
            or not isinstance(payload.get("sheet"), str)
            or payload["sheet"] != payload["sheet"].strip()
            or not 1 <= len(payload["sheet"]) <= 31
        ):
            return None
        locator = XlsxLocator.model_validate(payload, strict=True)
        return locator if marker == serialize_locator_marker(locator) else None
    except (TypeError, ValueError, json.JSONDecodeError, ValidationError):
        return None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate locator key")
        result[key] = value
    return result


def _valid_xlsx_range(value: str) -> bool:
    match = XLSX_RANGE_PATTERN.fullmatch(value)
    if match is None:
        return False
    start_column, start_row, end_column, end_row = match.groups()
    start = _column_number(start_column), int(start_row)
    end = _column_number(end_column), int(end_row)
    return (
        start[0] <= end[0] <= MAX_TRUSTED_XLSX_COLUMN
        and start[1] <= end[1] <= MAX_XLSX_ROWS
    )


def _column_number(letters: str) -> int:
    value = 0
    for letter in letters:
        value = value * 26 + ord(letter) - ord("A") + 1
    return value
