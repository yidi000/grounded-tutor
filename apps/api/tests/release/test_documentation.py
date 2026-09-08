"""Check public documentation paths and evaluation inventory without network calls."""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
DOCUMENTS = (
    "README.md", "LICENSE", "CONTRIBUTING.md", "docs/architecture.md",
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


def test_readme_separates_targets_and_results():
    text = (ROOT / "README.md").read_text()
    assert "Target thresholds" in text and "Measured results" in text


def test_evaluation_documents_every_case():
    text = (ROOT / "docs/evaluation.md").read_text()
    for name in ("p0.jsonl", "learning.jsonl"):
        for line in (ROOT / "evals/cases" / name).read_text().splitlines():
            case = json.loads(line)
            assert case["id"] in text
