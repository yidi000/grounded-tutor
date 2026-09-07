# Finite grounded learning plans (Learning Task 4)

The backend creates 3–5 ordered concepts from a completed diagnostic, its explicitly confirmed goal, its concept results, and current READY source evidence. It does not create lessons or immediate-check questions yet (Task 5), and the desktop cards remain Task 7.

Routes are relative to `/api/workspaces/{workspace_id}/plans`:

| Method | Route | Request / result |
|---|---|---|
| POST | empty | `diagnostic_id`, `idempotency_key`; create or return the existing plan for that diagnostic |
| GET | empty | All Workspace plans in creation order, including superseded history |
| GET | `/{plan_id}` | Stored goal, diagnostic origin, concept order/status/objective/check kind/evidence refs |
| POST | `/{plan_id}/rebuild` | `diagnostic_id`, `idempotency_key`, strict `confirm_rebuild: true` |
| POST | `/{plan_id}/concepts/{concept_id}/skip` | `idempotency_key`; skip an unfinished concept |

No reorder endpoint exists. Extra request fields (including an unconfirmed replacement goal) are rejected. A diagnostic must belong to this Workspace and have 3–5 answered or skipped questions before it can create a plan. `not_assessed` remains unknown in the model input; no overall ability percentage is produced.

Each concept has a distinct title, objective, stable server-assigned order, immediate-check kind (`single_choice` or `structured_short`), and citation snapshots in `evidence_refs`. Those refs include source ID, name, version, chunk, excerpt, and locator for later evidence panels. Validation checks that every cited chunk resolves to current local READY material; it does not prove semantic entailment or pedagogical quality. Invalid output is retried once. Missing/invalid evidence returns `insufficient_material` without replacing any existing plan. A source change during generation also refuses the result.

Rebuild confirmation applies to the specified old plan ID. A stale confirmation for an already superseded plan is rejected. New concepts, provenance, activity state, replay result, and the old plan's `superseded` status commit together. Failures leave the previous plan intact; a lost commit acknowledgement replays the durable result on retry. Ordinary create calls with a different request key return the current plan for the same diagnostic, rather than silently regenerating it. Reusing one request key with changed input is a conflict.

Skipping marks only an unfinished concept `not_assessed`. Completed concepts, assessments, and attempts are preserved. Skipping the currently active concept returns to PLAN; lesson activation belongs to Task 5. When every concept is completed or skipped, the path is finished and the activity returns to ASK. A finished path is not a claim that skipped concepts are mastered. Suspended or unrelated activities cannot be overwritten by plan changes.

Migration `0010_learning_plans` adds `Concept.check_kind` and a Workspace-scoped `plan_origins` relation. Existing concepts default to single choice. Upgrade/downgrade tests preserve pre-existing active concepts, assessments, and attempts. The P0 remains single-process SQLite: ingestion, diagnostic, and plan writes share the Workspace lock and atomic replay helper.

Verified locally with fake provider service/API tests, HTTP-mocked generation transport, migration round trips, and the full trust gate. The deployed FastGPT application's `concepts` response contract has not been verified live; no remote workflow or desktop UI was changed by this task.
