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
| 1 | `2026-08-31-grounded-ask-foundation.md` | Create Workspace, upload/paste material, review chunks, activate Source, ask cited questions | `make verify-foundation` |
| 2 | `2026-08-31-trust-and-evaluation.md` | Citation enforcement, idempotency, isolation, traces, Bad Cases, automated evals | `make verify-trust` |
| 3 | `2026-08-31-learning-loop.md` | Optional diagnostic, 3–5 concept plan, LEARN → ASK → CHECK, pause/resume | `make verify-learning` |
| 4 | `2026-08-31-open-source-release.md` | Reproducible setup, safe sample data, CI, public release checklist | `make release-check` |

Implement the phases in order. Each phase is independently demonstrable and ends with a commit; do not start P1 webpage import or P2 whole-site sync before all four P0 phases pass.

## Locked technical decisions

- Use one FastGPT Dataset per Topic Workspace and one Collection per Source.
- Treat FastGPT as an external knowledge service, not the product database.
- During ingestion, hold a per-Workspace lock and set the new Collection to `forbid=true`; activate it only after the user accepts the processed preview.
- Use FastGPT `searchTest` for retrieval and a separate OpenAI-compatible generation adapter for structured answers.
- Keep all API keys server-side; the browser never receives FastGPT or model credentials.
- Store product records in SQLite for P0 and access them through repositories so PostgreSQL can replace SQLite later.
- Use fake FastGPT and fake generation adapters in unit tests, browser tests, and pull-request CI.
- Use real-service integration tests only when `RUN_LIVE_INTEGRATION=1` is explicitly set.

## Approved-spec coverage

| Specification area | Implementation location |
|---|---|
| Workspace create, rename, view, switch, and isolation | Foundation Tasks 2, 4, 9, and 10; Trust Task 3 |
| File/text upload, processing settings, estimated preview, FastGPT review, activation | Foundation Tasks 5–7 and 10 |
| Grounded ASK, refusal, language matching, citations | Foundation Tasks 8 and 11; Trust Task 1 |
| Diagnostic invitation, consent, cooldown, inferred/confirmed profile separation | Learning Tasks 2 and 3 |
| Three-to-five-concept PLAN, rebuild confirmation, reorder/skip | Learning Task 4 |
| LEARN depth controls and immediate CHECK | Learning Task 5 |
| Cross-scenario pause, resume, unrelated-topic suggestion | Learning Tasks 2, 6, and 7 |
| Idempotency, trace, Bad Cases, prompt boundaries | Trust Tasks 2–4 |
| 48 automated cases and honest measured report | Trust Task 5; Learning Task 7; Release Task 4 |
| GitHub-safe open-source release | Trust Task 6 and all Release tasks |
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
