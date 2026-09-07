"""Measurements from observations, independent of acceptance targets."""


def summarize(results: list[dict]) -> dict:
    def rate(numerator, denominator):
        return numerator / denominator if denominator else None

    observed = [r for r in results if r["error"] is None]
    blocks = sum(r["observed"]["block_count"] for r in observed)
    refusals = [r for r in results if r["expected_status"] == "insufficient_material"]
    replays = [r for r in results if r["journey"] == "replay"]
    return {
        "grounded_citation_coverage": rate(
            sum(r["observed"]["grounded_blocks"] for r in observed), blocks
        ),
        "insufficient_material_refusal_rate": rate(
            sum(
                r["error"] is None
                and r["observed"]["status"] == "insufficient_material"
                and r["observed"]["block_count"] == 0
                and not r["observed"]["source_names"]
                for r in refusals
            ),
            len(refusals),
        ),
        "cross_workspace_leakage_count": sum(r["observed"]["leakage_count"] for r in observed),
        "unauthorized_external_call_count": sum(
            r["observed"]["unauthorized_calls"] for r in observed
        ),
        "idempotent_replay_rate": rate(
            sum(r["error"] is None and r["observed"]["replay_valid"] for r in replays), len(replays)
        ),
        "journey_pass_rate": rate(sum(r["passed"] for r in results), len(results)),
    }


def check_targets(metrics: dict, targets: dict) -> dict[str, bool]:
    return {
        name: metrics.get(name) is not None and metrics[name] == value
        for name, value in targets.items()
    }
