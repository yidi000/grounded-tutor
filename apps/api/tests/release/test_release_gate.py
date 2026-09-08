"""Release gate composes offline checks and never silently skips secret scanning."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_release_gate_forces_offline_and_includes_required_checks():
    text = (ROOT / "Makefile").read_text()
    assert "release-check: export RUN_LIVE_INTEGRATION=0" in text
    assert "release-check: export EXTERNAL_MODE=fake" in text
    assert "release-check: verify-learning" in text
    assert "render_evaluation_report.py --check" in text
    assert "scripts/check_secrets.sh" in text


def test_report_check_detects_drift_without_overwriting(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "report_check", ROOT / "scripts/render_evaluation_report.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("public-p0.json", "public-p0.md"):
        (tmp_path / name).write_bytes((ROOT / "evals/reports" / name).read_bytes())
    monkeypatch.setattr(module.sys, "argv", ["renderer", "--check", "--output-dir", str(tmp_path)])
    assert module.main() == 0
    markdown = tmp_path / "public-p0.md"
    markdown.write_text("changed by owner")
    assert module.main() == 1
    assert markdown.read_text() == "changed by owner"


def test_gitleaks_exception_is_one_graph_key_line_in_one_file():
    import json
    import re
    import tomllib

    config = tomllib.loads((ROOT / ".gitleaks.toml").read_text())
    assert config["extend"] == {"useDefault": True}
    assert len(config["rules"]) == 1
    rule = config["rules"][0]
    assert rule["id"] == "generic-api-key"
    assert len(rule["allowlists"]) == 1
    allow = rule["allowlists"][0]
    assert allow["condition"] == "AND" and allow["regexTarget"] == "line"
    assert len(allow["paths"]) == len(allow["regexes"]) == 1
    data = json.loads((ROOT / "fastgpt/baseline.sanitized.json").read_text())
    key = data["nodes"][2]["inputs"][4]["value"][3]["key"]
    assert any(key in str(edge) for edge in data["edges"])
    assert re.search(allow["paths"][0], "fastgpt/baseline.sanitized.json")
    assert not re.search(allow["paths"][0], "other.json")
    assert re.search(allow["regexes"][0], f'"key": "{key}",')
    assert not re.search(allow["regexes"][0], '"key": "different-secret",')
    assert not re.search(allow["regexes"][0], f'"api_key": "{key}",')
