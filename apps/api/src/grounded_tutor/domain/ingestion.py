from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from grounded_tutor.domain.answers import SourceLocator

PUBLIC_CHUNK_SETTING_ALIASES = frozenset(
    {
        "trainingType",
        "indexPrefixTitle",
        "customPdfParse",
        "chunkSettingMode",
        "chunkSplitMode",
        "chunkSize",
        "indexSize",
        "chunkSplitter",
        "qaPrompt",
    }
)


class ChunkSettings(BaseModel):
    """Source-processing settings using FastGPT's public field names at the boundary."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", strict=True)

    training_type: Literal["chunk", "qa"] = Field(
        default="chunk",
        alias="trainingType",
        validation_alias=AliasChoices("trainingType", "training_type"),
    )
    index_prefix_title: bool = Field(
        default=True,
        alias="indexPrefixTitle",
        validation_alias=AliasChoices("indexPrefixTitle", "index_prefix_title"),
    )
    custom_pdf_parse: bool = Field(
        default=False,
        alias="customPdfParse",
        validation_alias=AliasChoices("customPdfParse", "custom_pdf_parse"),
    )
    setting_mode: Literal["auto", "custom"] = Field(
        default="auto",
        alias="chunkSettingMode",
        validation_alias=AliasChoices("chunkSettingMode", "setting_mode"),
    )
    split_mode: Literal["paragraph", "size", "char"] = Field(
        default="paragraph",
        alias="chunkSplitMode",
        validation_alias=AliasChoices("chunkSplitMode", "split_mode"),
    )
    chunk_size: int = Field(
        default=1000,
        alias="chunkSize",
        validation_alias=AliasChoices("chunkSize", "chunk_size"),
    )
    index_size: int = Field(
        default=256,
        alias="indexSize",
        validation_alias=AliasChoices("indexSize", "index_size"),
    )
    splitter: str = Field(
        default="",
        max_length=20,
        alias="chunkSplitter",
        validation_alias=AliasChoices("chunkSplitter", "splitter"),
    )
    qa_prompt: str = Field(
        default="",
        max_length=4000,
        alias="qaPrompt",
        validation_alias=AliasChoices("qaPrompt", "qa_prompt"),
    )

    @model_validator(mode="after")
    def validate_fastgpt_bounds(self) -> ChunkSettings:
        if self.training_type == "chunk" and not 100 <= self.chunk_size <= 3000:
            raise ValueError("chunkSize must be between 100 and 3000 in chunk mode")
        if self.index_size < 32:
            raise ValueError("indexSize must be at least 32")
        if self.index_size > self.chunk_size:
            raise ValueError("indexSize must not exceed chunkSize")
        if self.setting_mode == "custom" and self.split_mode == "char" and not self.splitter:
            raise ValueError("chunkSplitter is required for custom delimiter splitting")
        return self


class PreviewItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    position: int
    text: str
    character_count: int
    truncated: bool = False
    locator: SourceLocator | None = None


class PreviewWarning(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: Literal["qa_generated_after_processing", "preview_truncated"]


class PreviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    authority: Literal["estimated"] = "estimated"
    source_name: str
    character_count: int
    items: list[PreviewItem]
    warnings: list[PreviewWarning]


class TextPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source_name: str = Field(min_length=1, max_length=255)
    text: str
    settings: ChunkSettings = Field(default_factory=ChunkSettings)

    @field_validator("source_name", mode="before")
    @classmethod
    def trim_source_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("settings", mode="before")
    @classmethod
    def require_public_setting_aliases(cls, value: object) -> object:
        return validate_public_chunk_settings(value)


def validate_public_chunk_settings(value: object) -> ChunkSettings:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) and key in PUBLIC_CHUNK_SETTING_ALIASES for key in value
    ):
        raise ValueError("settings must use public field aliases")
    return ChunkSettings.model_validate(value)
