"""Public reports preserve failures and exclude raw evaluation content."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts/render_evaluation_report.py"


def renderer():
    spec = importlib.util.spec_from_file_location("public_report", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def reports():
    cases = [json.loads(line) for line in (ROOT / "evals/cases/p0.jsonl").read_text().splitlines()]
    learning = [
        json.loads(line) for line in (ROOT / "evals/cases/learning.jsonl").read_text().splitlines()
    ]
    targets = json.loads((ROOT / "evals/targets.json").read_text())
    return {
        "timestamp": "2026-09-08T00:00:00+00:00",
        "git_commit": "a" * 40,
        "configuration_hash": "b" * 64,
        "configuration": {"private": "private-marker"},
        "metrics": targets,
        "total": 40,
        "executed": 40,
        "execution_errors": 0,
        "results": [
            {"id": c["id"], "passed": True, "error": None, "observed": {"secret": "private-marker"}}
            for c in cases
        ],
    }, {
        "total": 8,
        "executed": 8,
        "passed": 8,
        "cases": [{"id": c["id"], "passed": True} for c in learning],
    }


def test_failures_and_measured_values_are_preserved_without_raw_text(reports):
    ask, learning = reports
    ask["results"][0]["passed"] = False
    ask["metrics"] = dict(ask["metrics"], journey_pass_rate=39 / 40)
    learning["cases"][0]["passed"] = False
    learning["passed"] = 7
    module = renderer()
    report = module.build_report(ask, learning)
    assert report["passed_cases"] == 46
    assert report["failed_ids"] == ["GA-01", "LR-01"]
    assert report["measured_metrics"]["journey_pass_rate"] == 39 / 40
    assert report["target_thresholds"]["journey_pass_rate"] == 1
    assert "private-marker" not in json.dumps(report) + module.markdown(report)
    assert "#bad-case-ga-01" in module.markdown(report)


def test_incomplete_cases_and_non_numeric_metrics_are_rejected(reports):
    ask, learning = reports
    module = renderer()
    learning["cases"].pop()
    with pytest.raises(ValueError):
        module.build_report(ask, learning)
    learning["cases"].append({"id": "LR-08", "passed": True})
    ask["metrics"]["journey_pass_rate"] = "private-marker"
    with pytest.raises(ValueError):
        module.build_report(ask, learning)


def test_committed_report_and_markdown_match_inventory():
    module = renderer()
    report = json.loads((ROOT / "evals/reports/public-p0.json").read_text())
    assert report["total_cases"] == 48
    assert report["executed_cases"] == 48
    assert report["adapter_mode"] == "fake"
    assert set(report["passed_ids"] + report["failed_ids"]) == set(module.inventory())
    assert (ROOT / "evals/reports/public-p0.md").read_text() == module.markdown(report)
