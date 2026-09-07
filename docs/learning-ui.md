# Desktop learning loop

The local notebook now renders the saved learning activity below ASK history.
The existing right-hand ContextPanel opens citations from lessons and feedback.
The read-only demo remains unchanged. No mobile or image support is added.

- An offered diagnostic is an inline card with an editable goal and optional
  background. Only clicking Start sends explicit consent and the persisted
  invitation ID. Dismissal is persisted with the existing cooldown policy.
- Diagnostics show one saved question at a time, with skip and exit controls.
  The completed checkpoint restores the generate-plan action after a reload.
- Plans show the finite concept list, saved evidence counts and statuses.
  The next unfinished concept can be started or skipped.
- Lessons expose standard, simpler, more examples and deeper variants. Content
  and feedback reuse the existing numbered citation renderer.
- Checks show deterministic grading feedback. Wrong answers return to the saved
  lesson; correct answers advance. Skips require explicit confirmation to advance
  and retain the not-assessed status.
- Pause and ASK use the Task 6 orchestrator. Resume reads the actual saved question
  or lesson. The selected Workspace scopes queries and mutations; drafts are not
  written into mastery or checkpoints.

Mutation retries reuse a key for the same pending operation in the current browser
session, including topic switches. After successful writes the UI reloads server
state rather than treating an idempotent receipt as the current activity. Reload
restores completed checkpoints; unsubmitted answer drafts and transient diagnostic feedback
are not persisted. The latest submitted check result, explanation and citations
are read from the saved Attempt and Assessment, including after topic switches
and page reloads. Unsubmitted checks never expose an answer key or explanation. Historical ASK remains available separately.

The only new server routes are GET
`/api/workspaces/{workspace_id}/diagnostics/invitation` and POST
`/api/workspaces/{workspace_id}/diagnostics/invitation/{invitation_id}/dismiss`.
They reuse the existing invitation service and Workspace lock. No schema migration.

Run `make verify-learning`: foundation/trust checks, 40 existing evaluations,
8 isolated SQLite learning evaluations (`LR-01` through `LR-08`), and desktop
Playwright journeys. Playwright explicitly runs `apps/api/tests/e2e_app.py`, which
supplies deterministic educational fixtures only to the test server. These are
software behavior checks, not measurements of live model teaching quality.

The deployed FastGPT application has been verified for ASK in earlier work. Its
learning generation contracts (diagnostic questions, plans, checks) still require
live configuration and integration verification before claiming the entire new
learning loop works with the cloud model. This task does not publish a remote
workflow or call live model APIs.
