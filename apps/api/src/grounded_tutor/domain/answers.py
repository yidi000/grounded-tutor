from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_ANSWER_BLOCKS = 32
MAX_ANSWER_CITATIONS = 64
MAX_BLOCK_TEXT_CHARS = 6000
MAX_CITATION_EXCERPT_CHARS = 12000
MAX_CITATION_CONTEXT_CHARS = 2000

GroundedContentKind = Literal["answer", "definition", "explanation", "example"]


class GeneratedBlock(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    kind: GroundedContentKind
    text: str
    chunk_ids: tuple[str, ...] = ()


class GeneratedAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    blocks: tuple[GeneratedBlock, ...]


class GroundedContentBlock(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    kind: GroundedContentKind
    text: str
    citation_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("id", "text")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value.strip()

    @field_validator("citation_ids")
    @classmethod
    def require_valid_citation_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not citation_id.strip() for citation_id in value):
            raise ValueError("citation ids must not be blank")
        if len(set(value)) != len(value):
            raise ValueError("citation ids must be unique")
        return value


class ChunkLocator(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["chunk"] = "chunk"
    label: str

    @field_validator("label")
    @classmethod
    def require_label(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("label must not be blank")
        return value.strip()


class PdfLocator(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["pdf"] = "pdf"
    page: int = Field(ge=1)
    section: str | None = None


class DocxLocator(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["docx"] = "docx"
    heading_path: tuple[str, ...] = ()
    paragraph: int | None = Field(default=None, ge=1)


class PptxLocator(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["pptx"] = "pptx"
    slide: int = Field(ge=1)
    title: str | None = None


class XlsxLocator(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["xlsx"] = "xlsx"
    sheet: str
    cell_range: str | None = None

    @field_validator("sheet")
    @classmethod
    def require_sheet(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("sheet must not be blank")
        return value.strip()


class ImageLocator(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["image"] = "image"
    filename: str
    region: str | None = None

    @field_validator("filename")
    @classmethod
    def require_filename(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("filename must not be blank")
        return value.strip()


SourceLocator = Annotated[
    ChunkLocator | PdfLocator | DocxLocator | PptxLocator | XlsxLocator | ImageLocator,
    Field(discriminator="kind"),
]


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    source_id: UUID
    source_name: str
    source_version: int = Field(ge=1)
    chunk_id: str
    excerpt: str
    context_before: str | None = Field(default=None, max_length=MAX_CITATION_CONTEXT_CHARS)
    context_after: str | None = Field(default=None, max_length=MAX_CITATION_CONTEXT_CHARS)
    locator: SourceLocator

    @field_validator("id", "source_name", "chunk_id", "excerpt")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value.strip()


class SimpleSuggestedAction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["add_material", "rephrase", "start_diagnostic"]


class WorkspaceSuggestionAction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["suggest_new_workspace"] = "suggest_new_workspace"
    proposed_title: str


class ResumeActivityAction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["resume_activity"] = "resume_activity"
    label: str
    checkpoint: str


SuggestedAction = Annotated[
    SimpleSuggestedAction | WorkspaceSuggestionAction | ResumeActivityAction,
    Field(discriminator="type"),
]


class GroundedAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["ok", "insufficient_material"]
    answer_blocks: tuple[GroundedContentBlock, ...]
    citations: tuple[Citation, ...]
