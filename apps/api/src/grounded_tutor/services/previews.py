from __future__ import annotations

import csv
import re
from collections.abc import Iterator, Mapping
from io import BytesIO, StringIO
from pathlib import Path
from typing import ClassVar
from uuid import UUID
from zipfile import ZipFile

from bs4 import BeautifulSoup
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

from grounded_tutor.domain.ingestion import (
    ChunkSettings,
    PreviewItem,
    PreviewResponse,
    PreviewWarning,
)
from grounded_tutor.repositories.workspaces import WorkspaceRepository

MAX_PREVIEW_ITEMS = 50
MAX_PREVIEW_EXCERPT_CHARS = 500
# Deterministic P0 guardrails. They bound parser inputs and output work; they do
# not claim to sandbox third-party parsers or provide a wall-clock timeout.
DEFAULT_MAX_EXTRACTED_CHARACTERS = 40_000_000
MAX_DOCX_ARCHIVE_MEMBERS = 1_000
MAX_DOCX_UNCOMPRESSED_BYTES = 80_000_000
MAX_DOCX_COMPRESSION_RATIO = 100.0
MAX_DOCX_BLOCKS = 10_000
MAX_PDF_PAGES = 500
SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx", ".md", ".txt", ".html", ".csv"})


class PreviewError(RuntimeError):
    """Stable, content-free failure exposed by the local preview boundary."""

    _MESSAGES: ClassVar[Mapping[str, str]] = {
        "file_too_large": "The uploaded file exceeds the preview size limit.",
        "text_too_large": "The pasted text exceeds the preview size limit.",
        "source_too_large": "The extracted source text exceeds the preview limit.",
        "source_work_limit_exceeded": "The source exceeds the preview processing limit.",
        "unsafe_archive": "The document archive exceeds safe preview limits.",
        "unreadable_text": "The pasted text is not valid Unicode text.",
        "invalid_source_name": "The source name is invalid.",
        "unsupported_file_type": "This file type is not supported for preview.",
        "empty_source": "The source does not contain readable text.",
        "encrypted_pdf": "Encrypted PDF files cannot be previewed.",
        "unreadable_file": "The file could not be read for preview.",
    }

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(self._MESSAGES[code])


class PreviewWorkspaceNotFoundError(LookupError):
    pass


class PreviewService:
    def __init__(
        self,
        workspaces: WorkspaceRepository,
        *,
        max_upload_bytes: int,
        max_preview_text_bytes: int,
        max_extracted_characters: int,
    ) -> None:
        _require_positive_limit(max_upload_bytes)
        _require_positive_limit(max_preview_text_bytes)
        _require_positive_limit(max_extracted_characters)
        self._workspaces = workspaces
        self.max_upload_bytes = max_upload_bytes
        self.max_preview_text_bytes = max_preview_text_bytes
        self.max_extracted_characters = max_extracted_characters

    def from_text(
        self,
        workspace_id: UUID,
        *,
        source_name: str,
        text: str,
        settings: ChunkSettings,
    ) -> PreviewResponse:
        _validate_text_budget(
            text,
            max_text_bytes=self.max_preview_text_bytes,
            max_characters=self.max_extracted_characters,
        )
        self._require_workspace(workspace_id)
        return preview_text(
            text,
            settings,
            source_name=source_name,
            max_text_bytes=self.max_preview_text_bytes,
            max_extracted_characters=self.max_extracted_characters,
        )

    def from_file(
        self,
        workspace_id: UUID,
        *,
        filename: str,
        content: bytes,
        settings: ChunkSettings,
    ) -> PreviewResponse:
        _validate_file_size(content, self.max_upload_bytes)
        self._require_workspace(workspace_id)
        return preview_file(
            filename,
            content,
            settings,
            max_upload_bytes=self.max_upload_bytes,
            max_extracted_characters=self.max_extracted_characters,
        )

    def _require_workspace(self, workspace_id: UUID) -> None:
        if self._workspaces.get(workspace_id) is None:
            raise PreviewWorkspaceNotFoundError


def preview_text(
    text: str,
    settings: ChunkSettings,
    *,
    source_name: str = "Pasted text",
    max_text_bytes: int | None = None,
    max_extracted_characters: int | None = None,
) -> PreviewResponse:
    _validate_text_budget(
        text,
        max_text_bytes=max_text_bytes,
        max_characters=max_extracted_characters,
    )
    clean_text = text.strip()
    if not clean_text:
        raise PreviewError("empty_source")
    items: list[PreviewItem] = []
    preview_truncated = False
    for position, segment in enumerate(_segments(clean_text, settings), start=1):
        if position > MAX_PREVIEW_ITEMS:
            preview_truncated = True
            break
        items.append(
            PreviewItem(
                position=position,
                text=segment[:MAX_PREVIEW_EXCERPT_CHARS],
                character_count=len(segment),
                truncated=len(segment) > MAX_PREVIEW_EXCERPT_CHARS,
            )
        )
    if not items:
        raise PreviewError("empty_source")
    warnings = []
    if settings.training_type == "qa":
        warnings.append(PreviewWarning(code="qa_generated_after_processing"))
    if preview_truncated:
        warnings.append(PreviewWarning(code="preview_truncated"))
    return PreviewResponse(
        source_name=source_name,
        character_count=len(clean_text),
        items=items,
        warnings=warnings,
    )


def preview_file(
    filename: str,
    content: bytes,
    settings: ChunkSettings,
    *,
    max_upload_bytes: int,
    max_extracted_characters: int = DEFAULT_MAX_EXTRACTED_CHARACTERS,
) -> PreviewResponse:
    _require_positive_limit(max_extracted_characters)
    _validate_file_size(content, max_upload_bytes)
    source_name = filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    if not 1 <= len(source_name) <= 255:
        raise PreviewError("invalid_source_name")
    suffix = Path(source_name).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS or not Path(source_name).stem:
        raise PreviewError("unsupported_file_type")
    try:
        text = _extract_text(
            suffix,
            content,
            max_extracted_characters=max_extracted_characters,
        )
    except PreviewError:
        raise
    except Exception:  # noqa: BLE001 -- all third-party parser failures cross a safe boundary
        raise PreviewError("unreadable_file") from None
    return preview_text(
        text,
        settings,
        source_name=source_name,
        max_extracted_characters=max_extracted_characters,
    )


def _extract_text(
    suffix: str,
    content: bytes,
    *,
    max_extracted_characters: int,
) -> str:
    if suffix in {".md", ".txt"}:
        return _bounded_text(content.decode("utf-8-sig"), max_extracted_characters)
    if suffix == ".html":
        soup = BeautifulSoup(content.decode("utf-8-sig"), "html.parser")
        for hidden in soup(["script", "style", "noscript", "template"]):
            hidden.decompose()
        return _bounded_text(
            soup.get_text("\n", strip=True), max_extracted_characters
        )
    if suffix == ".csv":
        rows = csv.reader(
            StringIO(content.decode("utf-8-sig"), newline=""), strict=True
        )
        extracted_rows: list[str] = []
        extracted_characters = 0
        for row in rows:
            cells = [cell.strip() for cell in row]
            if any(cells):
                extracted = " | ".join(cells)
                extracted_characters = _next_extracted_size(
                    extracted_characters,
                    extracted,
                    has_previous=bool(extracted_rows),
                    max_extracted_characters=max_extracted_characters,
                )
                extracted_rows.append(extracted)
        return "\n".join(extracted_rows)
    if suffix == ".docx":
        _preflight_docx(content)
        document = Document(BytesIO(content))
        blocks: list[str] = []
        extracted_characters = 0
        work_units = 0
        for block in document.iter_inner_content():
            if isinstance(block, Paragraph):
                work_units += 1
                if work_units > MAX_DOCX_BLOCKS:
                    raise PreviewError("source_work_limit_exceeded")
                extracted = block.text.strip()
                if extracted:
                    extracted_characters = _next_extracted_size(
                        extracted_characters,
                        extracted,
                        has_previous=bool(blocks),
                        max_extracted_characters=max_extracted_characters,
                        separator_size=2,
                    )
                    blocks.append(extracted)
            elif isinstance(block, Table):
                for row in block.rows:
                    row_work_units = 1 + len(row.cells)
                    if work_units + row_work_units > MAX_DOCX_BLOCKS:
                        raise PreviewError("source_work_limit_exceeded")
                    work_units += row_work_units
                    extracted = " | ".join(cell.text.strip() for cell in row.cells)
                    if extracted.strip():
                        extracted_characters = _next_extracted_size(
                            extracted_characters,
                            extracted,
                            has_previous=bool(blocks),
                            max_extracted_characters=max_extracted_characters,
                            separator_size=2,
                        )
                        blocks.append(extracted)
        return "\n\n".join(blocks)
    reader = PdfReader(BytesIO(content))
    if reader.is_encrypted:
        raise PreviewError("encrypted_pdf")
    if len(reader.pages) > MAX_PDF_PAGES:
        raise PreviewError("source_work_limit_exceeded")
    pages: list[str] = []
    extracted_characters = 0
    for page in reader.pages:
        extracted = (page.extract_text() or "").strip()
        if extracted:
            extracted_characters = _next_extracted_size(
                extracted_characters,
                extracted,
                has_previous=bool(pages),
                max_extracted_characters=max_extracted_characters,
                separator_size=2,
            )
            pages.append(extracted)
    return "\n\n".join(pages)


def _preflight_docx(content: bytes) -> None:
    with ZipFile(BytesIO(content)) as archive:
        members = archive.infolist()
    if len(members) > MAX_DOCX_ARCHIVE_MEMBERS:
        raise PreviewError("unsafe_archive")
    uncompressed_bytes = sum(member.file_size for member in members)
    compressed_bytes = sum(member.compress_size for member in members)
    if uncompressed_bytes > MAX_DOCX_UNCOMPRESSED_BYTES:
        raise PreviewError("unsafe_archive")
    if uncompressed_bytes and compressed_bytes == 0:
        raise PreviewError("unsafe_archive")
    if compressed_bytes and uncompressed_bytes / compressed_bytes > MAX_DOCX_COMPRESSION_RATIO:
        raise PreviewError("unsafe_archive")
    if any(
        member.file_size
        and (
            member.compress_size == 0
            or member.file_size / member.compress_size > MAX_DOCX_COMPRESSION_RATIO
        )
        for member in members
    ):
        raise PreviewError("unsafe_archive")


def _next_extracted_size(
    current_size: int,
    text: str,
    *,
    has_previous: bool,
    max_extracted_characters: int,
    separator_size: int = 1,
) -> int:
    next_size = current_size + len(text) + (separator_size if has_previous else 0)
    if next_size > max_extracted_characters:
        raise PreviewError("source_too_large")
    return next_size


def _bounded_text(text: str, max_extracted_characters: int) -> str:
    if len(text) > max_extracted_characters:
        raise PreviewError("source_too_large")
    return text


def _validate_file_size(content: bytes, max_upload_bytes: int) -> None:
    _require_positive_limit(max_upload_bytes)
    if len(content) > max_upload_bytes:
        raise PreviewError("file_too_large")


def _validate_text_budget(
    text: str,
    *,
    max_text_bytes: int | None,
    max_characters: int | None,
) -> None:
    if max_text_bytes is not None:
        _require_positive_limit(max_text_bytes)
        try:
            text_bytes = len(text.encode("utf-8"))
        except UnicodeEncodeError:
            raise PreviewError("unreadable_text") from None
        if text_bytes > max_text_bytes:
            raise PreviewError("text_too_large")
    if max_characters is not None:
        _require_positive_limit(max_characters)
        if len(text) > max_characters:
            raise PreviewError("source_too_large")


def _require_positive_limit(limit: int) -> None:
    if type(limit) is not int or limit <= 0:
        raise ValueError("preview resource limits must be positive integers")


def _segments(text: str, settings: ChunkSettings) -> Iterator[str]:
    split_mode = "paragraph" if settings.setting_mode == "auto" else settings.split_mode
    if split_mode == "size":
        yield from _split_to_size(text, settings.chunk_size)
        return
    if split_mode == "char":
        candidates = _split_on_delimiter(text, settings.splitter)
    else:
        candidates = _split_paragraphs(text)
    for candidate in candidates:
        candidate = candidate.strip()
        if candidate:
            yield from _split_to_size(candidate, settings.chunk_size)


def _split_on_delimiter(text: str, delimiter: str) -> Iterator[str]:
    start = 0
    while True:
        boundary = text.find(delimiter, start)
        if boundary < 0:
            yield text[start:]
            return
        yield text[start:boundary]
        start = boundary + len(delimiter)


def _split_paragraphs(text: str) -> Iterator[str]:
    start = 0
    for boundary in re.finditer(r"(?:\r?\n[ \t]*){2,}", text):
        yield text[start : boundary.start()]
        start = boundary.end()
    yield text[start:]


def _split_to_size(text: str, size: int) -> Iterator[str]:
    for start in range(0, len(text), size):
        segment = text[start : start + size]
        if segment:
            yield segment
