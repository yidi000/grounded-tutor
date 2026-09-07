# Pause, ASK detours, and exact resume (Learning Task 6)

The existing chat API now runs through the tutor orchestrator. Asking during PLAN, a diagnostic, a lesson, or an immediate check preserves one suspended activity. A second ASK keeps that same saved activity; no nested activity stack is created.

ASK generation happens under the same Workspace lock as source and learning writes. Suspension is staged only immediately before the chat repository saves the answer, so the answer, its replay record, and the ActivityState change commit together. Provider failure, cancellation, or ordinary persistence failure keeps the original learning checkpoint. A lost commit acknowledgement can leave the complete operation durable; retrying its request key returns that saved answer without repeating the suspension or generation.

A successful detour returns a `resume_activity` action with the actual saved checkpoint and a specific label (for example, `继续第 2 题`). An insufficient-material answer still returns its resume action alongside add-material/rephrase suggestions. Chat history adds the current resume action to the most recent exchange, without changing saved messages. After resuming, history no longer shows that action. Replaying an old ASK after resuming does not suspend learning again.

Routes are relative to `/api/workspaces/{workspace_id}/learning`:

| Method | Route | Request / response |
|---|---|---|
| GET | `/activity` | Read the persisted ActivitySnapshot and its exact saved activity payload |
| POST | `/activity/pause` | `checkpoint`, `idempotency_key`; pause only the activity matching that checkpoint |
| POST | `/activity/resume` | `checkpoint`, `idempotency_key`; restore only that saved activity |

The effective checkpoint and activity payload remain visible while `snapshot.active_mode` is ASK. `kind` distinguishes idle, plan, diagnostic, lesson, concept, check, and check_skip. Public payloads reuse existing question/lesson/plan schemas and never contain answer keys or draft answers. Extra command fields are rejected.

| Checkpoint | Resume behavior |
|---|---|
| `diagnostic:{id}:question:{n}` | Same pending diagnostic question; earlier answers/skips stay unchanged |
| `lesson:{id}` | Same saved lesson and depth |
| `concept:{id}:ready` | Same next concept, awaiting explicit lesson start; no implicit generation |
| `check:{id}` | Same unanswered immediate check |
| `check:{id}:skipped` | Same skip-confirmation step; resume does not itself continue or mark mastery |
| `plan:{id}` | Same stored learning plan |

Explicit resume validates Workspace ownership, mode, checkpoint shape, current question/Concept/plan state, and READY source versions. It rejects stale commands, completed/superseded targets, and invalid evidence without changing the paused state. Read-only snapshots and original request replays preserve historical payloads. Request replay is an operation receipt; GET `/activity` is the source of current state after later actions.

Closing a page needs no additional write: saved operations already persisted their checkpoint, while an unsubmitted answer exists only in the client. Reading another Workspace does not pause, resume, or alter the original one. The existing pause snapshot and tables are reused, so this task adds no database migration.

Tests cover diagnostic question 2, exact lesson depth, pending checks, skipped-check confirmation, PLAN, a next-concept checkpoint, repeated ASK, explicit pause, refreshed API reads, Workspace isolation, stale source/command rejection, concurrent writes, cancellation, ordinary commit failure, and lost acknowledgements. Existing ASK/API regression tests remain part of full validation.

This is backend orchestration only. Desktop activity controls, automatic UI restoration, and the complete visible journey remain Task 7. The deployed FastGPT learning contracts still need live verification; no remote application was changed or published in this task.
