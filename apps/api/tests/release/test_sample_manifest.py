"""Public sample provenance and safe, runnable configuration defaults."""

import hashlib
import json
from pathlib import Path

from dotenv import dotenv_values

from grounded_tutor.config import Settings

ROOT = Path(__file__).resolve().parents[4]


def test_sample_manifest_is_public_and_complete():
    directory = ROOT / "samples/rag-fundamentals"
    manifest = json.loads((directory / "manifest.json").read_text())
    assert manifest["license"] == "CC0-1.0"
    assert manifest["created_for"] == "Grounded Tutor demonstration"
    assert manifest["files"] == ["01-rag-overview.md", "02-retrieval-quality.md"]
    assert set(manifest["sha256"]) == set(manifest["files"])
    for name in manifest["files"]:
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == manifest["sha256"][name]


def test_example_configuration_is_safe_and_loadable():
    root = ROOT / ".env.example"
    api = ROOT / "apps/api/.env.example"
    assert root.read_bytes() == api.read_bytes()
    values = dotenv_values(api)
    assert values["FASTGPT_API_KEY"] == values["LLM_API_KEY"] == ""
    assert values["RUN_LIVE_INTEGRATION"] == "0"
    settings = Settings(_env_file=None, **{key.lower(): value for key, value in values.items()})
    assert settings.external_mode == "fake"
    assert not settings.enable_local_admin and not settings.supports_image_files
    assert settings.database_url.startswith("sqlite:///")
