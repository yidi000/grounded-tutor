# Grounded micro-diagnostic (Learning Task 3)

The backend now supports an explicitly consented, persisted 3–5 question diagnostic. The desktop learning cards are Task 7; this change does not yet add a diagnostic UI.

All routes are relative to `/api/workspaces/{workspace_id}/diagnostics`:

| Method | Route | Purpose |
|---|---|---|
| POST | empty | Start with `consent: true`, `goal`, `idempotency_key`; optional `background`, `invitation_id` |
| GET | `/{diagnostic_id}` | Reload persisted questions and the next unanswered question |
| POST | `/{diagnostic_id}/answers` | Submit `question_id`, `idempotency_key` and either `response` or `skip: true` |
| GET | `/{diagnostic_id}/summary` | Return concept results, with no overall ability percentage |

Starting requires a locally READY, current Source. Foreign collection hits never reach generation. Invalid generated content is retried once; invalid or insufficient evidence returns `insufficient_material` without assessments or activity progress. A source change while generating also refuses the result. Repeating the same start request replays its result; after an insufficient-material response, use a new request key to try with new material.

An invitation ID binds to exactly one diagnostic, including retries with different request keys. Starting marks its invitation accepted and stores explicitly supplied profile fields only after successful generation. Other active or suspended learning is not overwritten. Generation uses the same app-scoped Workspace lock as ingestion; this P0 still requires one server worker.

Questions use single-choice or exact structured short answers. Public question schemas explicitly omit answer keys and explanations. Keys, explanation blocks, and source/version references are stored in Assessment; feedback appears after an answer. Key validation checks literal normalized support in cited text, not semantic entailment or educational quality. Short answers accept exact normalized alternatives (Unicode NFKC, case, whitespace); they do not use substring or keyword-based grading. Broader paraphrase grading is deferred.

Answers must follow stored question order. Each accepted answer/skip, its Attempt, checkpoint, and request replay record commit together. Skip is `not_assessed` with null response/result; it is never a wrong answer. Completion returns ActivityState to ASK. A concept is understood only when every question for that concept is correct; a wrong answer yields `needs_review`, otherwise unanswered/skipped questions yield `not_assessed`.

Migration `0009_diagnostics` adds the diagnostic group and ordered links to existing Assessment/Attempt rows, with composite Workspace and Attempt ownership constraints. Downgrading removes the groups and links, preserving pre-existing assessments and attempts.

Verification includes deterministic service/API tests and an HTTP-mocked OpenAI-compatible adapter test. The deployed FastGPT application was previously configured for ASK blocks; its support for the new `questions` output contract has not been verified live. It must support that contract before presenting this diagnostic flow as live-ready. No remote workflow is changed by this backend task.
