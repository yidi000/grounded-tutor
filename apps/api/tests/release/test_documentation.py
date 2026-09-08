"""Check public documentation paths and evaluation inventory without network calls."""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
DOCUMENTS = (
    "README.md", "README.en.md", "docs/local-development.md", "LICENSE", "CONTRIBUTING.md", "docs/architecture.md",
    "docs/evaluation.md", "docs/security-and-data.md",
)


@pytest.mark.parametrize("path", DOCUMENTS)
def test_public_document_and_local_links_exist(path):
    document = ROOT / path
    text = document.read_text()
    assert text.strip()
    for target in re.findall(r"\]\(([^)]+)\)", text):
        if "://" not in target and not target.startswith("#"):
            assert (document.parent / target.split("#")[0]).is_file(), target


def test_readmes_link_to_separate_targets_and_measured_results():
    for filename in ("README.md", "README.en.md"):
        text = (ROOT / filename).read_text()
        assert "](docs/local-development.md)" in text
        assert "](docs/evaluation.md)" in text
        assert "](evals/reports/public-p0.md)" in text
    guide = (ROOT / "docs/local-development.md").read_text()
    assert "## Target thresholds" in guide and "## Measured results" in guide
    assert "](../evals/reports/public-p0.json)" in guide


def test_readmes_share_install_commands_and_language_navigation():
    chinese = (ROOT / "README.md").read_text()
    english = (ROOT / "README.en.md").read_text()
    assert "[English](README.en.md)" in chinese
    assert "[简体中文](README.md)" in english
    assert re.findall(r"```sh\n(.*?)```", chinese, re.S) == re.findall(
        r"```sh\n(.*?)```", english, re.S
    )


def test_evaluation_documents_every_case():
    text = (ROOT / "docs/evaluation.md").read_text()
    for name in ("p0.jsonl", "learning.jsonl"):
        for line in (ROOT / "evals/cases" / name).read_text().splitlines():
            case = json.loads(line)
            assert case["id"] in text
