from collections import Counter
from pathlib import Path

import pytest

from grounded_tutor.evaluation.runner import load_cases, run_suite

CASES = Path(__file__).resolve().parents[4] / "evals/cases/p0.jsonl"


def test_p0_suite_has_required_distribution():
    cases = load_cases(CASES)
    assert len(cases) == 40
    assert Counter(case.category for case in cases) == {
        "grounded_answer": 10,
        "insufficient_material": 8,
        "workspace_isolation": 6,
        "citation_validation": 6,
        "source_state": 4,
        "idempotency": 3,
        "recovery": 3,
    }
    assert {case.id for case in cases} == {
        f"{prefix}-{i:02}"
        for prefix, count in [
            ("GA", 10),
            ("IM", 8),
            ("WI", 6),
            ("CV", 6),
            ("SS", 4),
            ("ID", 3),
            ("RC", 3),
        ]
        for i in range(1, count + 1)
    }


@pytest.mark.asyncio
async def test_real_journeys_pass_and_are_deterministic():
    cases = load_cases(CASES)
    first = await run_suite(cases)
    second = await run_suite(cases)
    assert first == second
    assert first["executed"] == 40
    assert first["execution_errors"] == 0
    assert all(result["passed"] for result in first["results"])
    assert first["metrics"]["journey_pass_rate"] == 1


@pytest.mark.asyncio
async def test_wrong_expectations_are_measured_failures():
    case = load_cases(CASES)[0].model_copy(
        update={
            "expected_source_names": ["missing"],
            "forbidden_source_names": ["Notes"],
            "expected_external_calls": {"search": 0, "generate": 0},
        }
    )
    report = await run_suite([case])
    assert report["executed"] == 1
    assert report["execution_errors"] == 0
    assert not report["results"][0]["passed"]
    assert report["metrics"]["journey_pass_rate"] == 0
    assert report["metrics"]["unauthorized_external_call_count"] == 2


def test_loader_rejects_duplicate_ids_and_invalid_records(tmp_path):
    path = tmp_path / "cases.jsonl"
    line = CASES.read_text().splitlines()[0]
    path.write_text(line + "\n" + line + "\n")
    with pytest.raises(ValueError, match="Duplicate"):
        load_cases(path)
    path.write_text('{"id":"bad"}\n')
    with pytest.raises(ValueError):
        load_cases(path)


@pytest.mark.asyncio
async def test_execution_error_is_not_a_metric_failure(monkeypatch):
    from grounded_tutor.evaluation import runner

    async def broken(_case):
        raise RuntimeError("sensitive exception content")

    monkeypatch.setattr(runner, "observe", broken)
    report = await run_suite(load_cases(CASES)[:1])
    assert report["executed"] == 0
    assert report["execution_errors"] == 1
    assert report["results"][0]["error"] == "RuntimeError"
    assert "sensitive" not in str(report)
    assert report["metrics"]["journey_pass_rate"] == 0
    assert report["metrics"]["grounded_citation_coverage"] is None


@pytest.mark.asyncio
async def test_product_citation_regression_is_detected(monkeypatch):
    from grounded_tutor.services import chat

    original = chat.ground_generated_answer

    def corrupt(*args, **kwargs):
        answer = original(*args, **kwargs)
        return answer.model_copy(
            update={
                "citations": tuple(
                    c.model_copy(update={"source_version": 999}) for c in answer.citations
                )
            }
        )

    monkeypatch.setattr(chat, "ground_generated_answer", corrupt)
    report = await run_suite(load_cases(CASES)[:1])
    assert not report["results"][0]["passed"]
    assert report["metrics"]["grounded_citation_coverage"] == 0


@pytest.mark.parametrize("mode,exit_code", [("pass", 0), ("fail", 1), ("invalid", 2)])
def test_cli_writes_report_and_distinguishes_exit_codes(tmp_path, mode, exit_code):
    import json
    import subprocess
    import sys

    case = json.loads(CASES.read_text().splitlines()[0])
    if mode == "fail":
        case["expected_status"] = "insufficient_material"
    if mode == "invalid":
        case["unexpected"] = True
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps(case) + "\n")
    targets = tmp_path / "targets.json"
    targets.write_text(json.dumps({"journey_pass_rate": 1}))
    output = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "grounded_tutor.evaluation.runner",
            "--cases",
            str(path),
            "--targets",
            str(targets),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == exit_code, result.stderr
    report = json.loads(output.read_text())
    assert report["exit_code"] == exit_code
    if mode != "invalid":
        assert len(report["configuration_hash"]) == 64
        assert len(report["git_commit"]) == 40
        assert report["timestamp"]
        assert report["metrics"]["journey_pass_rate"] == (1 if mode == "pass" else 0)


@pytest.mark.parametrize("targets", [[], {}, {"typo": 1}, {"journey_pass_rate": "yes"}])
def test_invalid_targets_are_configuration_errors(tmp_path, monkeypatch, targets):
    import json
    import sys

    from grounded_tutor.evaluation.runner import main

    path = tmp_path / "targets.json"
    path.write_text(json.dumps(targets))
    output = tmp_path / "report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["eval", "--cases", str(CASES), "--targets", str(path), "--output", str(output)],
    )
    assert main() == 2
    assert json.loads(output.read_text())["exit_code"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["citations", "answer_blocks"])
async def test_duplicate_identifiers_are_rejected(monkeypatch, field):
    from grounded_tutor.services import chat

    original = chat.ground_generated_answer

    def duplicate(*args, **kwargs):
        answer = original(*args, **kwargs)
        return answer.model_copy(update={field: getattr(answer, field) * 2})

    monkeypatch.setattr(chat, "ground_generated_answer", duplicate)
    report = await run_suite(load_cases(CASES)[:1])
    assert not report["results"][0]["passed"]


def test_cli_does_not_load_application_settings(tmp_path):
    import os
    import subprocess
    import sys

    path = tmp_path / "cases.jsonl"
    path.write_text(CASES.read_text().splitlines()[0] + "\n")
    targets = tmp_path / "targets.json"
    targets.write_text('{"journey_pass_rate":1}')
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "grounded_tutor.evaluation.runner",
            "--cases",
            str(path),
            "--targets",
            str(targets),
            "--output",
            str(tmp_path / "report.json"),
        ],
        env={**os.environ, "DATABASE_URL": "broken://invalid", "EXTERNAL_MODE": "invalid"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
