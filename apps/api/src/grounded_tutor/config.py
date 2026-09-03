from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

API_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_URL = f"sqlite:///{API_ROOT / 'grounded_tutor.db'}"


class Settings(BaseSettings):
    """Runtime configuration loaded from the API-local .env file when present."""

    model_config = SettingsConfigDict(
        env_file=API_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = DEFAULT_DATABASE_URL
    fastgpt_base_url: str = "http://localhost:3000"
    fastgpt_api_key: SecretStr = SecretStr("")
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = "gpt-4o-mini"
    external_mode: Literal["fake", "live"] = "fake"
    demo_read_only: bool = False
    supports_custom_pdf_parse: bool = False
    supports_vector_model: bool = False
    supports_agent_model: bool = False
    supports_vlm_model: bool = False
    supports_image_files: bool = False
    max_upload_bytes: int = Field(default=20_000_000, gt=0)
    max_preview_text_bytes: int = Field(default=20_000_000, gt=0)
    max_extracted_characters: int = Field(default=40_000_000, gt=0)
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    @field_validator(
        "max_upload_bytes",
        "max_preview_text_bytes",
        "max_extracted_characters",
        mode="before",
    )
    @classmethod
    def reject_boolean_resource_limits(cls, value: object) -> object:
        if isinstance(value, bool):
            # Pydantic validators must use ValueError so invalid settings are
            # collected into a ValidationError instead of escaping directly.
            raise ValueError(  # noqa: TRY004
                "preview resource limits must be positive integers"
            )
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


def capability_request_is_supported(*, requested: object, supported: bool) -> bool:
    return not bool(requested) or supported
