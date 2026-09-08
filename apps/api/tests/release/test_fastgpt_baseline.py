"""Sanitize synthetic exports without leaking their private values."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts/sanitize_fastgpt_export.py"


def sanitizer():
    spec = importlib.util.spec_from_file_location("sanitize", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_nested_fields_key_value_headers_and_json_strings_are_removed():
    data = {
        "nodes": [
            {
                "nodeId": "n1",
                "flowNodeType": "chatNode",
                "inputs": [
                    {"key": "Authorization", "value": "secret-value"},
                    {
                        "key": "datasets",
                        "value": [{"datasetId": "private", "name": "private-course"}],
                    },
                    {"key": "systemPrompt", "value": "Public teaching prompt"},
                    {
                        "key": "system_httpJsonBody",
                        "value": '{"api_key":"body-secret","query":"hello"}',
                    },
                ],
            }
        ],
        "edges": [{"source": "n1", "target": "n2"}],
        "cookie": "private-cookie",
        "url": "https://private.example/path?token=secret",
    }
    result = sanitizer().sanitize(data)
    text = json.dumps(result)
    for secret in ("secret-value", "private-course", "private-cookie", "body-secret", "datasetId"):
        assert secret not in text
    assert result["edges"] == data["edges"]
    assert "Public teaching prompt" in text
    assert result["url"] == "https://example.invalid/redacted"


def test_cli_refuses_input_alias_and_does_not_echo_invalid_input(tmp_path):
    source = tmp_path / "private.json"
    source.write_text('{"api_key":"sensitive-marker"}')
    alias = tmp_path / "alias.json"
    alias.symlink_to(source)
    for output in (source, alias):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(source), str(output)],
            capture_output=True,
            check=False,
        )
        assert result.returncode != 0
        assert b"sensitive-marker" not in result.stdout + result.stderr
    assert "sensitive-marker" in source.read_text()
    source.write_text("invalid-sensitive-marker")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(source), str(tmp_path / "out.json")],
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert b"sensitive-marker" not in result.stdout + result.stderr


def test_baseline_contains_no_private_identifiers_or_credentials():
    data = json.loads((ROOT / "fastgpt/baseline.sanitized.json").read_text())
    text = json.dumps(data).lower()
    for forbidden in (
        "authorization",
        "api_key",
        "apikey",
        "teamid",
        "tmbid",
        "datasetid",
        "appid",
        "fastgpt-",
    ):
        assert forbidden not in text
    assert len(data["nodes"]) == 13 and data["edges"]
    assert sanitizer().sanitize(data) == data


def test_cli_accepts_bom_and_refuses_existing_output(tmp_path):
    source = tmp_path / "input.json"
    output = tmp_path / "output.json"
    source.write_text('{"nodes":[],"api_key":"private-marker"}', encoding="utf-8-sig")
    command = [sys.executable, str(SCRIPT), str(source), str(output)]
    result = subprocess.run(command, capture_output=True, check=False)
    assert result.returncode == 0
    assert json.loads(output.read_text()) == {"nodes": []}
    assert b"private-marker" not in result.stdout + result.stderr
    output.write_text("existing-review")
    assert subprocess.run(command, capture_output=True, check=False).returncode != 0
    assert output.read_text() == "existing-review"
