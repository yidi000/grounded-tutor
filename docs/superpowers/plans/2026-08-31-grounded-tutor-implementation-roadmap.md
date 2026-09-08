# Grounded Tutor Implementation Roadmap

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a locally runnable, testable, open-source Grounded Tutor MVP whose primary journey is uploading existing study material, asking cited questions, and optionally entering a diagnostic learning loop.

**Architecture:** A React/TypeScript SPA calls a FastAPI service that owns product state in SQLite. FastGPT is isolated behind a Dataset adapter for parsing, indexing, and retrieval; an OpenAI-compatible generation adapter produces structured tutor responses. Every external service also has an in-memory fake so development and CI do not require secrets.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic Settings, httpx, pytest, React 19, TypeScript, Vite, TanStack Query, Zod, Vitest, Playwright, GitHub Actions.

---

## Repository structure

```text
grounded-tutor/
├── apps/
│   ├── api/
│   │   ├── alembic/
│   │   ├── src/grounded_tutor/
│   │   │   ├── adapters/
│   │   │   ├── domain/
│   │   │   ├── repositories/
│   │   │   ├── routers/
│   │   │   └── services/
│   │   └── tests/
│   └── web/
│       ├── src/
│       │   ├── api/
│       │   ├── components/
│       │   ├── features/
│       │   └── routes/
│       └── tests/
├── evals/
│   ├── cases/
│   └── reports/
├── fastgpt/
├── samples/
├── docs/
└── .github/workflows/
```

## Delivery phases

| Phase | Detailed plan | Runnable outcome | Exit command |
|---|---|---|---|
| 1 | `2026-08-31-grounded-ask-foundation.md` Tasks 1–6, then `2026-09-02-grounded-tutor-remaining-mvp.md` Foundation 7–11 | Create Workspace, upload/paste verified formats, review versions, activate Source, and use structured cited ASK in the Evidence Notebook | `make verify-foundation` |
| 2 | `2026-08-31-trust-and-evaluation.md` | Citation enforcement, idempotency, isolation, traces, Bad Cases, automated evals | `make verify-trust` |
| 3 | `2026-08-31-learning-loop.md` plus revised Learning 5/7 in `2026-09-02-grounded-tutor-remaining-mvp.md` | Optional diagnostic, 3–5 concept plan, cited LEARN → ASK → CHECK, pause/resume | `make verify-learning` |
| 4 | `2026-08-31-open-source-release.md` plus the read-only demo addition in `2026-09-02-grounded-tutor-remaining-mvp.md` | Reproducible setup, deterministic no-write demo, safe sample data, CI, and public release checklist | `make release-check` |
| 5 | Separate post-P0 account and cloud-workspace specification | Account/password access with owner-isolated persistent Workspaces; implementation starts only after its security design is approved | Defined by the future account specification |

Implement Phases 1–4 in order. After every task in the referenced plans, run its checks, report the diff and results, and stop until the user says `继续`; the revised tasks make these gates explicit. Do not start Phase 5, P1 webpage import, or P2 whole-site sync before all four P0 phases pass.

## Deferred basic Q&A and upload guidance (2026-09-08)

User-approved backlog only; do not implement now. Scheduling is undecided and
this does not expand the current P0 release gate or authorize free-chat work.

- Offer brief general explanations for basic questions without usable evidence,
  clearly labeled as general knowledge not verified against the user's sources.
  Show a deterministic upload-material prompt and upload entry point.
- Keep source-supported answers on the existing citation-validated path. Never
  invent citations or guess the contents of missing documents.
- Distinguish missing evidence from retrieval/model failures; failures retain
  explicit error and retry behavior rather than falling back silently.
- Persist the answer type so history restoration preserves its provenance label.
  General answers must not become evidence for diagnostics, scoring or mastery.
- Initial scope is single-turn basic Q&A. Context-aware multi-turn free chat needs
  a separate scope decision. Model accuracy and basic-question classification
  cannot be guaranteed; define evaluation cases before implementation.

Acceptance coverage when scheduled: no-source basic question, source-supported
question, out-of-source question, missing-document question, provider failure,
history reload, and separation from learning assessment.

## Locked technical decisions

- Use one FastGPT Dataset per Topic Workspace and one Collection per Source.
- Treat FastGPT as an external knowledge service, not the product database.
- During ingestion, hold a per-Workspace lock and set the new Collection to `forbid=true`; activate it only after the user accepts the processed preview.
- Use FastGPT `searchTest` for retrieval and a separate OpenAI-compatible generation adapter for structured answers.
- Keep all API keys server-side; the browser never receives FastGPT or model credentials.
- Store product records in SQLite for P0 and access them through repositories so PostgreSQL can replace SQLite later.
- Use fake FastGPT and fake generation adapters in unit tests, browser tests, and pull-request CI.
- Use real-service integration tests only when `RUN_LIVE_INTEGRATION=1` is explicitly set.

### P0 ingestion safety boundary

- Run the API through `make api-dev`, which fixes Uvicorn to one worker. The
  per-Workspace ingestion lock is process-local; multi-worker or multi-instance
  deployment is unsupported until it is replaced by a distributed lease.
- Every Source attempt derives a stable opaque FastGPT marker from its local
  Source UUID. The backend sends that marker as a Collection tag and in the
  remote-only Collection name, then uses the official bounded `listV2` API to
  reconcile uncertain create results. Tags are only an enhancement because
  they may require a commercial FastGPT deployment; exact name-marker matching
  is the baseline.
- Remote reconciliation is best effort, not an atomic create-disabled
  guarantee. If FastGPT list and update operations remain unavailable, the
  local Source is `failed`; the remote Collection may still be enabled. The
  Task 6 checkpoint is therefore not end-to-end query-safe by itself.
- Foundation Task 8 must fail closed: ASK filters every retrieval result against
  local `READY` Source Collection IDs. A remote Collection that is missing,
  ambiguous, `review`, or `failed` locally must never reach generation even if
  FastGPT still reports it in Dataset search results.
- Source ingestion POSTs are not yet idempotent and clients must not retry them
  automatically. A persistent `Idempotency-Key` contract plus a distributed
  lock/lease is a required pre-public, multi-worker follow-up.

## Approved-spec coverage

| Specification area | Implementation location |
|---|---|
| Workspace create, rename, view, switch, and isolation | Foundation Tasks 2, 4, 9, and 10; Trust Task 3 |
| File/text upload, expanded PPTX/XLSX/image formats, processing settings, estimated preview, FastGPT review, activation | Foundation Tasks 5–7, 8A, and 10 |
| Capability-driven settings and creation-time model choices | Revised Foundation Task 7A and Task 10 |
| Grounded ASK, structured blocks, refusal, language matching, Evidence Anchors | Revised Foundation Tasks 8 and 11; revised Trust Task 1 |
| Diagnostic invitation, consent, cooldown, inferred/confirmed profile separation | Learning Tasks 2 and 3 |
| Three-to-five-concept PLAN, rebuild confirmation, and skip | Learning Task 4 |
| LEARN depth controls and immediate CHECK | Learning Task 5 |
| Cross-scenario pause, resume, unrelated-topic suggestion | Learning Tasks 2, 6, and 7 |
| Idempotency, trace, Bad Cases, prompt boundaries | Trust Tasks 2–4 |
| 48 automated cases and honest measured report | Trust Task 5; Learning Task 7; Release Task 4 |
| GitHub-safe open-source release | Trust Task 6 and all Release tasks |
| Deterministic read-only public demo and local-upload handoff | Revised Foundation Tasks 9 and 11; Release addition |
| Account/password and user-owned cloud Workspaces | Post-P0 Phase 5 after separate security and product design |
| P1 single-page import/search and P2 site sync | Explicitly deferred until the P0 release gate passes |

## User-owned gates

These gates do not block scaffolding or fake-adapter development:

1. Before the first live FastGPT integration test, the repository owner places `FASTGPT_BASE_URL` and a Dataset-capable `FASTGPT_API_KEY` in `apps/api/.env`.
2. Before the first live generated answer, the repository owner places `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` for an OpenAI-compatible provider in `apps/api/.env`.
3. Before the public demo, the repository owner approves one copyright-safe sample topic. If no topic is supplied, use the self-authored “RAG Fundamentals” sample included in Phase 4.
4. Before the first GitHub push, the repository owner confirms the destination account and repository visibility, then restores valid GitHub CLI authentication or authorizes an equivalent Git credential flow.

Secrets must never be pasted into issues, plan files, chat transcripts, commits, screenshots, or evaluation reports.

## Global completion gate

- [ ] `make verify` exits 0 from a clean clone using fake adapters.
- [ ] `RUN_LIVE_INTEGRATION=1 make test-live` exits 0 on the owner's machine with local secrets.
- [ ] The nine P0 end-to-end journeys in the approved product specification pass.
- [ ] Evaluation reports distinguish target thresholds from measured results.
- [ ] `git grep` and secret scanning find no credentials, private course material, FastGPT account IDs, or private Dataset IDs.
- [ ] A third party can run the demo with their own FastGPT and model accounts by following the README.
