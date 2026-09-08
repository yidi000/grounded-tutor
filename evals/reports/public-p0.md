# P0 deterministic evaluation report

Evaluated commit: `9366d84a2e184c1eb90b660af16d294a1ed03099`. Timestamp: `2026-09-08T03:01:04.062317+00:00`.
Configuration hash: `1415e4189a59b35766f90ef9f5c2033beeee5632f959dce74a1014f75059a5a1`.

Mode: fake; isolated SQLite per case. Executed 48/48; passed 48/48.

[Machine-readable report](public-p0.json) · [Definitions and case inventory](../../docs/evaluation.md)

## Targets and measured results

| Metric | Target | Measured | Meets target |
|---|---|---|---|
| grounded_citation_coverage | 1 | 1.0 | True |
| insufficient_material_refusal_rate | 1 | 1.0 | True |
| cross_workspace_leakage_count | 0 | 0 | True |
| unauthorized_external_call_count | 0 | 0 | True |
| idempotent_replay_rate | 1 | 1.0 | True |
| journey_pass_rate | 1 | 1.0 | True |
| learning_journey_pass_rate | 1 | 1.0 | True |

## Categories

| Category | Passed | Total | Pass rate |
|---|---|---|---|
| citation_validation | 6 | 6 | 1.0 |
| grounded_answer | 10 | 10 | 1.0 |
| idempotency | 3 | 3 | 1.0 |
| insufficient_material | 8 | 8 | 1.0 |
| learning | 8 | 8 | 1.0 |
| recovery | 3 | 3 | 1.0 |
| source_state | 4 | 4 | 1.0 |
| workspace_isolation | 6 | 6 | 1.0 |

## Case outcomes

Passed: CV-01, CV-02, CV-03, CV-04, CV-05, CV-06, GA-01, GA-02, GA-03, GA-04, GA-05, GA-06, GA-07, GA-08, GA-09, GA-10, ID-01, ID-02, ID-03, IM-01, IM-02, IM-03, IM-04, IM-05, IM-06, IM-07, IM-08, LR-01, LR-02, LR-03, LR-04, LR-05, LR-06, LR-07, LR-08, RC-01, RC-02, RC-03, SS-01, SS-02, SS-03, SS-04, WI-01, WI-02, WI-03, WI-04, WI-05, WI-06

Failed: none

## Limitations

- Fake providers and disposable SQLite: these are software behavior measurements, not model accuracy.
- Citation coverage checks structure and evidence identity, not semantic entailment.
- Provider-call budgets do not audit arbitrary network traffic.
- Learning executed counts attempted journeys, including failed journeys; its runner does not classify errors separately.
- No browser, live service, latency, teaching-effectiveness or multi-user deployment measurement is included.
- The Git commit identifies the evaluated application baseline; hashes also identify cases and renderer content.

## Reproduction

Run from the repository root with test dependencies installed:

```sh
.venv/bin/python scripts/render_evaluation_report.py
.venv/bin/python scripts/render_evaluation_report.py --render-only
```

The first command re-executes both suites and records fresh time/provenance, so metadata can change. The second renders Markdown from the saved public JSON byte-for-byte without model calls. Raw intermediate reports exist only in a temporary directory and are removed after rendering.
