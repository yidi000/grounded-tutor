"""Export only numeric evaluation measurements, never inputs or exception text."""

import json
import math
import sys
from pathlib import Path

COUNTS = ("total", "executed", "execution_errors", "exit_code")
METRICS = (
    "grounded_citation_coverage",
    "insufficient_material_refusal_rate",
    "cross_workspace_leakage_count",
    "unauthorized_external_call_count",
    "idempotent_replay_rate",
    "journey_pass_rate",
)


def main():
    source, target = map(Path, sys.argv[1:])
    report = json.loads(source.read_text())
    summary = {name: report[name] for name in COUNTS}
    if any(type(value) is not int or value < 0 for value in summary.values()):
        raise ValueError
    metrics = {
        name: report["metrics"][name] for name in METRICS if name in report["metrics"]
    }
    if any(
        value is not None
        and (type(value) not in (int, float) or not math.isfinite(value))
        for value in metrics.values()
    ):
        raise ValueError
    summary["metrics"] = metrics
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError):
        print("Cannot create sanitized evaluation summary.", file=sys.stderr)
        sys.exit(1)
