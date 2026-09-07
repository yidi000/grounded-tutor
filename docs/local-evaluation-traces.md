# Local execution traces and Bad Cases

ASK requests through the API record a local execution snapshot after the chat
transaction settles. Same-key successful replays return the saved answer without
rerunning retrieval/generation or adding another execution trace. Direct embedded
ChatService callers must inject a TraceRecorder to enable recording.

A trace stores a generated request ID, workspace and route, permitted retrieval
chunk IDs/scores/text with source identity/version/type/order, each generation
attempt and its outcome, validation and final answer, and elapsed timings. Only
the workspace-filtered evidence is retained; rejected foreign hits are not copied.
These snapshots support offline inspection and replay of the recorded generated
blocks through the grounding verifier. There is no endpoint that reruns a model,
changes learning state, or edits a case. Automated evaluation follows in Task 5.

External failures, validation failure after the correction retry, wrong-route
results supplied by an evaluator, and unexpected execution exceptions create an
open Bad Case with their trace. A supported correction or ordinary insufficient
material response does not. Wrong-route evaluation is a recorder category at this
stage; the evaluator itself has not been built. Trace and Bad Case commit together.

Recursive redaction omits credential-like keys (authorization, api_key, token,
secret, cookie) and diagnostic header/exception/raw-response fields before saving.
Provider exception strings are never passed to the recorder. The trace still
contains the question and source text needed for reproduction; it is private local
study data, not a public telemetry feed. Do not publish the database or trace exports.

## Inspect locally

Apply migrations and explicitly enable inspection on a direct loopback listener:

```sh
.venv/bin/alembic -c apps/api/alembic.ini upgrade head
ENABLE_LOCAL_ADMIN=true make api-dev
curl 'http://127.0.0.1:8000/api/admin/evals/traces?limit=20'
curl 'http://127.0.0.1:8000/api/admin/evals/bad-cases?limit=20'
```

GET lists accept `workspace_id` and `limit` (1–100, default 50). Details are at
`/api/admin/evals/traces/{trace_id}` and `/api/admin/evals/bad-cases/{case_id}`;
`workspace_id` optionally restricts those lookups too. Responses are read-only.
The flag defaults to false. Demo mode, non-loopback peers, and non-local Host
names receive 404 before database access. Forwarded headers are not used by the
gate. Do not expose these routes through a public reverse proxy or configure
proxy middleware to turn remote callers into trusted local peers/hosts.

## Failure and retention boundary

A tracing database failure logs only the generated request ID and preserves the
primary answer/error. It cannot undo an already committed answer or force a model
retry; the trace may be missing in that failure case. Forced termination before
recording also cannot leave a complete trace. No automatic retention or deletion
job is included; add one before long-running deployments accumulate large snapshots.
