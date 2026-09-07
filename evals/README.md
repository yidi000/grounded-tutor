# Deterministic P0 evaluation

From the repository root:

```sh
.venv/bin/python -m grounded_tutor.evaluation.runner --cases evals/cases/p0.jsonl --output evals/reports/local.json
.venv/bin/pytest apps/api/tests/evaluation -q
```

No provider credentials or network calls are needed. Each case runs the production
ASK service, grounding, repositories, history reader and trace recorder with fake
FastGPT/generation adapters and its own disposable SQLite database. The application
database is not modified. Source states are seeded directly; ingestion and lifecycle
transitions are covered by the separate application tests.

The 40 cases have fixed IDs and distribution: GA 10, IM 8, WI 6, CV 6, SS 4,
ID 3, RC 3. The JSONL fixtures and inputs are validated with Pydantic. Omitted
fixture fields use the defaults documented in `evaluation/schema.py`; generation
responses default to the existing FakeGeneration behavior (first supplied chunk).
Explicit responses can supply blocks, `invalid` (malformed output), or `failure`
(provider outage). Recovery journeys retry the original key after a real service
failure. Replay checks result identity, provider call counts and persisted history.

Reports contain UTC timestamp, Git commit, configuration/source hash, normalized
configuration, per-case expectations, observations/checks, measurements and separate
target checks. Generated reports are ignored by Git. Source hashes include the Python
application code, so uncommitted code changes remain distinguishable from HEAD.
Exit codes: **0** all cases and targets pass, **1** measured check/target failure,
**2** invalid configuration or case execution error. Per-case errors preserve the
exception type, not potentially sensitive exception text. A case execution error
does not stop the other cases. Empty and duplicate-ID suites are rejected.

Metrics (ratios are 0–1; no denominator is reported as `null`, never as success):

- Grounded citation coverage: returned blocks whose references all resolve to
  retrieved, eligible local evidence with matching source ID/name/version/excerpt,
  divided by all returned blocks in completed cases. This checks structural grounding,
  not whether a real model's prose is semantically entailed by the evidence.
- Insufficient-material refusal rate: expected refusal cases returning an empty
  insufficient-material answer divided by all expected refusal cases, including errors.
- Cross-workspace leakage count: unique offending chunk IDs per case found in
  generation inputs or foreign evidence text in the answer/history. Non-ready evidence
  passed to generation is also treated as a boundary violation.
- Unauthorized external call count: calls exceeding each case's explicit search and
  generation budget, plus any other FastGPT operation during ASK. Calls needed to seed
  fixtures are not made through providers. This does not audit arbitrary network traffic.
- Idempotent replay rate: replay cases preserving the complete result and making no
  additional provider calls divided by all replay cases. The P0 suite has one replay case;
  conflict and pending cases are separate journey checks.
- Journey pass rate: cases passing every check divided by all cases, including errors.

`evals/targets.json` is an acceptance policy, never the source of measured values.
Targets use exact equality (P0 ratios 1, violation counts 0). A custom target file may
select a non-empty subset for a focused suite. Execution errors invalidate the report
regardless of apparently good metrics from the remaining cases.

This suite does not measure live model accuracy, browser rendering, process-kill
recovery or concurrent request races. Existing unit/API/E2E tests and live integration
checks remain complementary. Trust Task 6 will wire the suite into the verification
command and CI; this task only supplies the evaluator.
