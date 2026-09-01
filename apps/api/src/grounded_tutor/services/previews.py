from __future__ import annotations

import csv
import re
from collections.abc import Iterator, Mapping
from io import BytesIO, StringIO
from pathlib import Path
from typing import ClassVar
from uuid import UUID

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
SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx", ".md", ".txt", ".html", ".csv"})


class PreviewError(RuntimeError):
    """Stable, content-free failure exposed by the local preview boundary."""

    _MESSAGES: ClassVar[Mapping[str, str]] = {
        "file_too_large": "The uploaded file exceeds the preview size limit.",
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
    def __init__(self, workspaces: WorkspaceRepository, *, max_upload_bytes: int) -> None:
        self._workspaces = workspaces
        self.max_upload_bytes = max_upload_bytes

    def from_text(
        self,
        workspace_id: UUID,
        *,
        source_name: str,
        text: str,
        settings: ChunkSettings,
    ) -> PreviewResponse:
        self._require_workspace(workspace_id)
        return preview_text(text, settings, source_name=source_name)

    def from_file(
        self,
        workspace_id: UUID,
        *,
        filename: str,
        content: bytes,
        settings: ChunkSettings,
    ) -> PreviewResponse:
        self._require_workspace(workspace_id)
        return preview_file(
            filename,
            content,
            settings,
            max_upload_bytes=self.max_upload_bytes,
        )

    def _require_workspace(self, workspace_id: UUID) -> None:
        if self._workspaces.get(workspace_id) is None:
            raise PreviewWorkspaceNotFoundError


def preview_text(
    text: str,
    settings: ChunkSettings,
    *,
    source_name: str = "Pasted text",
) -> PreviewResponse:
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
) -> PreviewResponse:
    if len(content) > max_upload_bytes:
        raise PreviewError("file_too_large")
    source_name = filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    if not 1 <= len(source_name) <= 255:
        raise PreviewError("invalid_source_name")
    suffix = Path(source_name).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS or not Path(source_name).stem:
        raise PreviewError("unsupported_file_type")
    try:
        text = _extract_text(suffix, content)
    except PreviewError:
        raise
    except Exception:  # noqa: BLE001 -- all third-party parser failures cross a safe boundary
        raise PreviewError("unreadable_file") from None
    return preview_text(text, settings, source_name=source_name)


def _extract_text(suffix: str, content: bytes) -> str:
    if suffix in {".md", ".txt"}:
        return content.decode("utf-8-sig")
    if suffix == ".html":
        soup = BeautifulSoup(content.decode("utf-8-sig"), "html.parser")
        for hidden in soup(["script", "style", "noscript", "template"]):
            hidden.decompose()
        return soup.get_text("\n", strip=True)
    if suffix == ".csv":
        rows = csv.reader(
            StringIO(content.decode("utf-8-sig"), newline=""), strict=True
        )
        extracted_rows = []
        for row in rows:
            cells = [cell.strip() for cell in row]
            if any(cells):
                extracted_rows.append(" | ".join(cells))
        return "\n".join(extracted_rows)
    if suffix == ".docx":
        document = Document(BytesIO(content))
        blocks = []
        for block in document.iter_inner_content():
            if isinstance(block, Paragraph):
                blocks.append(block.text.strip())
            elif isinstance(block, Table):
                blocks.extend(
                    " | ".join(cell.text.strip() for cell in row.cells)
                    for row in block.rows
                )
        return "\n\n".join(block for block in blocks if block.strip())
    reader = PdfReader(BytesIO(content))
    if reader.is_encrypted:
        raise PreviewError("encrypted_pdf")
    return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)


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
