from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
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
    max_upload_bytes: int = 20_000_000
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])


@lru_cache
def get_settings() -> Settings:
    return Settings()
