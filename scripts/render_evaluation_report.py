"""Run fixed fake suites and publish only allowlisted measurements and provenance."""

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIMITATIONS = [
    "Fake providers and disposable SQLite: these are software behavior measurements, not model accuracy.",
    "Citation coverage checks structure and evidence identity, not semantic entailment.",
    "Provider-call budgets do not audit arbitrary network traffic.",
    "Learning executed counts attempted journeys, including failed journeys; its runner does not classify errors separately.",
    "No browser, live service, latency, teaching-effectiveness or multi-user deployment measurement is included.",
    "The Git commit identifies the evaluated application baseline; hashes also identify cases and renderer content.",
]


def inventory():
    result = {}
    for name in ("p0.jsonl", "learning.jsonl"):
        for line in (ROOT / "evals/cases" / name).read_text().splitlines():
            case = json.loads(line)
            result[case["id"]] = case.get("category", "learning")
    return result


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_report(ask, learning):
    expected = inventory()
    rows = ask["results"] + learning["cases"]
    if len(rows) != len(expected) or {r["id"] for r in rows} != set(expected):
        raise ValueError("Invalid case inventory")
    if any(type(r["passed"]) is not bool for r in rows):
        raise ValueError("Invalid outcome")
    if any(
        type(s[k]) is not int or s[k] < 0
        for s in (ask, learning)
        for k in ("total", "executed")
    ):
        raise ValueError("Invalid counts")
    errors = sum(r.get("error") is not None for r in ask["results"])
    if (
        ask["total"] != len(ask["results"])
        or learning["total"] != len(learning["cases"])
        or ask["executed"] != ask["total"] - errors
        or learning["executed"] != learning["total"]
    ):
        raise ValueError("Inconsistent counts")
    if any(r["passed"] and r.get("error") is not None for r in ask["results"]):
        raise ValueError("Inconsistent error outcome")
    targets = json.loads((ROOT / "evals/targets.json").read_text())
    metrics = {name: ask["metrics"][name] for name in targets}
    if any(
        v is not None and (type(v) not in (int, float) or not math.isfinite(v))
        for v in metrics.values()
    ):
        raise ValueError("Invalid metrics")
    for key, length in (("git_commit", 40), ("configuration_hash", 64)):
        if not re.fullmatch(rf"[a-f0-9]{{{length}}}", ask[key]):
            raise ValueError("Invalid provenance")
    timestamp = datetime.fromisoformat(ask["timestamp"]).isoformat()
    passed = sorted(r["id"] for r in rows if r["passed"])
    failed = sorted(r["id"] for r in rows if not r["passed"])
    categories = defaultdict(lambda: {"total": 0, "passed": 0})
    for row in rows:
        category = categories[expected[row["id"]]]
        category["total"] += 1
        category["passed"] += row["passed"]
    for category in categories.values():
        category["pass_rate"] = category["passed"] / category["total"]
    hashes = {
        name: digest(ROOT / name)
        for name in (
            "evals/cases/p0.jsonl",
            "evals/cases/learning.jsonl",
            "evals/targets.json",
            "scripts/render_evaluation_report.py",
        )
    }
    config = {"ask_configuration_hash": ask["configuration_hash"], "files": hashes}
    metrics["learning_journey_pass_rate"] = sum(
        r["passed"] for r in learning["cases"]
    ) / len(learning["cases"])
    targets["learning_journey_pass_rate"] = 1
    return {
        "schema_version": 1,
        "git_commit": ask["git_commit"],
        "timestamp": timestamp,
        "adapter_mode": "fake",
        "database": "isolated-sqlite",
        "configuration_hash": hashlib.sha256(
            json.dumps(config, sort_keys=True).encode()
        ).hexdigest(),
        "provenance": config,
        "total_cases": len(rows),
        "executed_cases": ask["executed"] + learning["executed"],
        "ask_execution_errors": errors,
        "passed_cases": len(passed),
        "passed_ids": passed,
        "failed_ids": failed,
        "category_metrics": dict(sorted(categories.items())),
        "target_thresholds": targets,
        "measured_metrics": metrics,
        "target_checks": {
            k: metrics[k] is not None and metrics[k] == v for k, v in targets.items()
        },
        "limitations": LIMITATIONS,
    }


def markdown(report):
    lines = [
        "# P0 deterministic evaluation report",
        "",
        f"Evaluated commit: `{report['git_commit']}`. Timestamp: `{report['timestamp']}`.",
        f"Configuration hash: `{report['configuration_hash']}`.",
        "",
        (
            f"Mode: {report['adapter_mode']}; isolated SQLite per case. "
            f"Executed {report['executed_cases']}/{report['total_cases']}; "
            f"passed {report['passed_cases']}/{report['total_cases']}."
        ),
        "",
        "[Machine-readable report](public-p0.json) · [Definitions and case inventory](../../docs/evaluation.md)",
        "",
        "## Targets and measured results",
        "",
        "| Metric | Target | Measured | Meets target |",
        "|---|---|---|---|",
    ]
    for key, target in report["target_thresholds"].items():
        lines.append(
            f"| {key} | {target} | {report['measured_metrics'][key]} | {report['target_checks'][key]} |"
        )
    lines += [
        "",
        "## Categories",
        "",
        "| Category | Passed | Total | Pass rate |",
        "|---|---|---|---|",
    ]
    for key, value in report["category_metrics"].items():
        lines.append(
            f"| {key} | {value['passed']} | {value['total']} | {value['pass_rate']} |"
        )
    lines += [
        "",
        "## Case outcomes",
        "",
        "Passed: " + ", ".join(report["passed_ids"]),
        "",
        "Failed: "
        + (
            ", ".join(f"[{i}](#bad-case-{i.lower()})" for i in report["failed_ids"])
            or "none"
        ),
        "",
    ]
    for case in report["failed_ids"]:
        lines += [
            f"### Bad Case {case}",
            "",
            "This case failed. Re-run its fixed fixture locally to inspect the failure; raw traces are intentionally excluded.",
            "",
        ]
    lines += ["## Limitations", ""] + [f"- {item}" for item in report["limitations"]]
    lines += [
        "",
        "## Reproduction",
        "",
        "Run from the repository root with test dependencies installed:",
        "",
        "```sh",
        ".venv/bin/python scripts/render_evaluation_report.py",
        ".venv/bin/python scripts/render_evaluation_report.py --render-only",
        "```",
        "",
        (
            "The first command re-executes both suites and records fresh time/provenance, so metadata can change. "
            "The second renders Markdown from the saved public JSON byte-for-byte without model calls. "
            "Raw intermediate reports exist only in a temporary directory and are removed after rendering."
        ),
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "evals/reports")
    parser.add_argument("--render-only", action="store_true")
    args = parser.parse_args()
    output = args.output_dir
    if args.render_only:
        report = json.loads((output / "public-p0.json").read_text())
    else:
        with tempfile.TemporaryDirectory(prefix="tutor-evaluation-") as directory:
            paths = []
            for module, cases in (("runner", "p0"), ("learning", "learning")):
                target = Path(directory) / f"{cases}.json"
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        f"grounded_tutor.evaluation.{module}",
                        "--cases",
                        f"evals/cases/{cases}.jsonl",
                        "--output",
                        str(target),
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    check=False,
                )
                if result.returncode not in (0, 1, 2):
                    raise ValueError("Evaluator failed")
                paths.append(json.loads(target.read_text()))
            report = build_report(*paths)
        output.mkdir(parents=True, exist_ok=True)
        (output / "public-p0.json").write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n"
        )
    (output / "public-p0.md").write_text(markdown(report))
    print(
        f"Public evaluation: {report['passed_cases']}/{report['total_cases']} passed."
    )
    return int(bool(report["failed_ids"]) or not all(report["target_checks"].values()))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError):
        print(
            "Cannot generate public evaluation report; details withheld.",
            file=sys.stderr,
        )
        sys.exit(2)
