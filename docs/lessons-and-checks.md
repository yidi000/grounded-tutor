# Cited lessons and immediate checks (Learning Task 5)

This task adds the backend LEARN/CHECK loop. ASK detours and resume orchestration remain Task 6; the desktop learning UI remains Task 7. Generation uses the plan concept's cited chunk IDs and source versions, intersected with currently READY local sources.

Routes are relative to `/api/workspaces/{workspace_id}/learning`:

| Method | Route | Request / result |
|---|---|---|
| POST | `/concepts/{concept_id}/lessons` | `idempotency_key`, optional `depth`: standard, simpler, more_examples, deeper |
| GET | `/lessons/{lesson_id}` | Exact saved lesson, without generation |
| POST | `/concepts/{concept_id}/checks` | `idempotency_key`; create a check from the active lesson or return its pending check |
| GET | `/checks/{assessment_id}` | Saved public question, with no answer key |
| POST | `/checks/{assessment_id}/answers` | `idempotency_key` and either `response` or `skip: true` |
| POST | `/checks/{assessment_id}/continue` | `idempotency_key`, strict `confirm_continue: true`; continue after a skipped check |

Lessons expose `content_blocks` with definition, explanation, and example kinds, plus citations and available depths. All three kinds must be present and every generated block must pass grounding validation; partial validation never silently starts the lesson. Changing depth keeps the Concept ID. Each concept/depth variant is saved once and reused; a new request key does not regenerate a saved variant. Saved historical GETs and exact request replays remain stable, while new lesson requests refuse stale evidence.

Checks use the Concept's stored check kind: single choice compares exact option identity; structured short answers compare exact accepted alternatives after Unicode NFKC, case, and whitespace normalization. These checks do not perform free-form semantic grading. Answer keys must have literal normalized support in the cited evidence; this is a structural check, not proof of semantic entailment. Invalid lesson or question generation is retried once, then returns `insufficient_material` without changing progress. Provider and persistence failures use existing redacted errors.

Checks begin only from an active saved lesson. Starting again while a check is pending returns that same question. A submitted check cannot be answered again under a new request key. The check stores its originating Lesson ID, so a wrong answer restores the exact lesson depth.

| Answer | Concept / activity result |
|---|---|
| Correct | Concept completed; next unfinished concept becomes active in LEARN, or the plan completes and returns to ASK |
| Incorrect | Concept needs_review; LEARN returns to the same saved lesson |
| Skip | Concept not_assessed; CHECK waits for explicit continuation, with no wrong/correct claim |
| Confirm continuation | Next unfinished concept becomes active, or the plan completes; the skipped concept remains not_assessed |

Advancing selects the next unfinished concept from stored plan order and never generates the next lesson implicitly. Lesson start confirms entry from PLAN only for its first unfinished concept. Suspended activities, foreign Workspace resources, superseded plans, out-of-order requests, and stale check submissions cannot advance progress. Source changes during generation refuse the generated output. New check recovery, answers, and skip continuation recheck that every saved citation source/version is still READY. Stale recovery returns insufficient_material; stale answers/continuation return learning_conflict without progress. GET and exact request replay preserve historical results. Valid answers use their saved evidence snapshot without another model call.

Attempt, checkpoint, concept/plan state, and request replay result commit atomically using the existing Workspace lock and learning request helper. Regression tests cover ordinary rollback, lost commit acknowledgement, cancellation, exact depth restoration, skip confirmation, duplicate submissions, source staleness, and a complete API lesson/check journey. Diagnostic grading shares the same tested deterministic helper.

Migration `0011_lessons_checks` creates Lesson variants and ImmediateCheck links to their originating lesson and final Attempt, with composite Workspace foreign keys. The supported P0 is still one SQLite server worker. Existing domain migration round trips and the API tests cover the migration path.

Local verification uses fake model results and HTTP-mocked transport. The deployed FastGPT application's lesson and single-question output contracts have not been verified live. This task does not modify or publish the remote application and does not yet provide the desktop teaching UI.
