# Grounded ASK Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working vertical slice where a learner creates a Topic Workspace, uploads or pastes study material, reviews FastGPT-processed chunks, activates the source, and receives a cited answer grounded only in that Workspace.

**Architecture:** FastAPI owns Workspace and Source state in SQLite and calls FastGPT through a typed adapter. A React SPA uses REST endpoints and never receives external-service keys. Fake adapters drive all deterministic tests; live tests are opt-in.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic Settings, httpx, pytest, React 19, TypeScript, Vite, TanStack Query, Zod, Vitest, Playwright.

---

## File map

- `Makefile`: repeatable install, run, and verification commands.
- `apps/api/src/grounded_tutor/config.py`: environment configuration only.
- `apps/api/src/grounded_tutor/db.py`: engine, sessions, and migration startup guard.
- `apps/api/src/grounded_tutor/domain/models.py`: SQLAlchemy Workspace, Source, Conversation, and Message records.
- `apps/api/src/grounded_tutor/domain/schemas.py`: public request/response contracts.
- `apps/api/src/grounded_tutor/adapters/fastgpt.py`: FastGPT protocol, HTTP implementation, and response mapping.
- `apps/api/src/grounded_tutor/adapters/generation.py`: OpenAI-compatible structured generation protocol.
- `apps/api/src/grounded_tutor/services/workspaces.py`: Workspace lifecycle.
- `apps/api/src/grounded_tutor/services/previews.py`: safe local extraction and estimated chunk preview.
- `apps/api/src/grounded_tutor/services/sources.py`: ingestion lock, disable/review/activate flow.
- `apps/api/src/grounded_tutor/services/chat.py`: retrieve, generate, and persist cited answers.
- `apps/api/src/grounded_tutor/routers/*.py`: HTTP-only request validation and service calls.
- `apps/web/src/api/client.ts`: typed API calls.
- `apps/web/src/features/workspaces/*`: Workspace and source-management UI.
- `apps/web/src/features/chat/*`: cited chat UI.

### Task 1: Scaffold the monorepo and health endpoint

**Files:**
- Create: `.gitignore`
- Create: `Makefile`
- Create: `apps/api/pyproject.toml`
- Create: `apps/api/src/grounded_tutor/__init__.py`
- Create: `apps/api/src/grounded_tutor/main.py`
- Create: `apps/api/tests/test_health.py`

- [ ] **Step 1: Write the failing health test**

```python
from fastapi.testclient import TestClient

from grounded_tutor.main import app


def test_health() -> None:
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Add the Python package metadata and install the test environment**

Create `apps/api/pyproject.toml` with Python `>=3.12,<3.14`, package directory `src`, runtime dependencies `fastapi`, `uvicorn[standard]`, `sqlalchemy`, `alembic`, `pydantic-settings`, `httpx`, `python-multipart`, `pypdf`, `python-docx`, and `beautifulsoup4`, plus test dependencies `pytest`, `pytest-asyncio`, `respx`, and `ruff`. Run:

```bash
python3 -m venv .venv
.venv/bin/pip install -e 'apps/api[test]'
.venv/bin/pytest apps/api/tests/test_health.py -q
```

Expected: FAIL during import because `grounded_tutor.main` does not exist.

- [ ] **Step 3: Add the minimal application**

```python
# apps/api/src/grounded_tutor/main.py
from fastapi import FastAPI

app = FastAPI(title="Grounded Tutor API", version="0.1.0")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

Create `.gitignore` with `.venv/`, `node_modules/`, `.env`, `*.db`, `.pytest_cache/`, `.ruff_cache/`, `dist/`, `playwright-report/`, and `test-results/`. Add Make targets `api-test`, `api-lint`, `web-test`, `web-build`, and `verify-foundation`; commands must call `.venv/bin/pytest`, `.venv/bin/ruff`, `npm --prefix apps/web test -- --run`, and `npm --prefix apps/web run build`.

- [ ] **Step 4: Verify the scaffold**

Run: `.venv/bin/pytest apps/api/tests/test_health.py -q && .venv/bin/ruff check apps/api`

Expected: `1 passed` and Ruff exits 0.

- [ ] **Step 5: Commit**

```bash
git add .gitignore Makefile apps/api
git commit -m "chore: scaffold grounded tutor api"
```

### Task 2: Add configuration, persistence, and migrations

**Files:**
- Create: `apps/api/src/grounded_tutor/config.py`
- Create: `apps/api/src/grounded_tutor/db.py`
- Create: `apps/api/src/grounded_tutor/domain/models.py`
- Create: `apps/api/src/grounded_tutor/domain/schemas.py`
- Create: `apps/api/alembic.ini`
- Create: `apps/api/alembic/env.py`
- Create: `apps/api/alembic/versions/0001_workspace_sources.py`
- Create: `apps/api/tests/test_models.py`

- [ ] **Step 1: Write the failing persistence test**

```python
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from grounded_tutor.domain.models import Base, Source, SourceStatus, SourceType, Workspace


def test_workspace_and_source_are_isolated() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        workspace = Workspace(title="Statistics", dataset_id="dataset-1")
        session.add(workspace)
        session.flush()
        session.add(Source(
            workspace_id=workspace.id,
            name="week-1.pdf",
            source_type=SourceType.FILE,
            status=SourceStatus.REVIEW,
            collection_id="collection-1",
            ingestion_config={"trainingType": "chunk"},
        ))
        session.commit()
        stored = session.scalar(select(Source).where(Source.workspace_id == workspace.id))
    assert stored is not None
    assert stored.collection_id == "collection-1"
    assert stored.status is SourceStatus.REVIEW
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest apps/api/tests/test_models.py -q`

Expected: FAIL because `domain.models` does not exist.

- [ ] **Step 3: Implement the records and settings**

Define `Workspace(id: UUID, title, dataset_id, created_at, updated_at)`, `Source(id: UUID, workspace_id, name, source_type, origin_uri, collection_id, status, version, ingestion_config JSON, error_message, created_at, updated_at)`, `Conversation(id, workspace_id, created_at)`, and `Message(id, conversation_id, role, mode, content, citations JSON, idempotency_key, created_at)`. Use string enums exactly as follows:

```python
class SourceType(str, Enum):
    FILE = "file"
    TEXT = "text"
    WEBPAGE = "webpage"


class SourceStatus(str, Enum):
    UPLOADING = "uploading"
    PARSING = "parsing"
    INDEXING = "indexing"
    REVIEW = "review"
    READY = "ready"
    FAILED = "failed"
```

`Settings` must expose `database_url`, `fastgpt_base_url`, `fastgpt_api_key`, `llm_base_url`, `llm_api_key`, `llm_model`, `external_mode` (`fake` or `live`), `max_upload_bytes=20_000_000`, and `allowed_origins=["http://localhost:5173"]`. Secret fields use `SecretStr`; no setting value is logged.

- [ ] **Step 4: Generate and verify the first migration**

Run:

```bash
cd apps/api
../../.venv/bin/alembic upgrade head
cd ../..
.venv/bin/pytest apps/api/tests/test_models.py -q
```

Expected: migration succeeds and `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add apps/api
git commit -m "feat: add workspace persistence model"
```

### Task 3: Define FastGPT and generation adapter contracts

**Files:**
- Create: `apps/api/src/grounded_tutor/adapters/fastgpt.py`
- Create: `apps/api/src/grounded_tutor/adapters/generation.py`
- Create: `apps/api/src/grounded_tutor/adapters/fakes.py`
- Create: `apps/api/tests/adapters/test_fastgpt.py`

- [ ] **Step 1: Write failing HTTP mapping tests**

```python
import httpx
import pytest
import respx

from grounded_tutor.adapters.fastgpt import FastGPTClient, SearchRequest


@pytest.mark.asyncio
@respx.mock
async def test_search_maps_fastgpt_results() -> None:
    route = respx.post("https://fastgpt.test/api/core/dataset/searchTest").mock(
        return_value=httpx.Response(200, json={"code": 200, "data": [{
            "id": "chunk-1", "q": "Mean is an average.", "a": "",
            "datasetId": "dataset-1", "collectionId": "collection-1",
            "sourceName": "notes.pdf", "sourceId": "source-remote-1", "score": 0.91,
        }]})
    )
    client = FastGPTClient("https://fastgpt.test", "secret")
    results = await client.search(SearchRequest(dataset_id="dataset-1", text="mean"))
    assert route.called
    assert results[0].chunk_id == "chunk-1"
    assert results[0].score == 0.91
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest apps/api/tests/adapters/test_fastgpt.py -q`

Expected: FAIL because `FastGPTClient` is undefined.

- [ ] **Step 3: Implement typed protocols and HTTP methods**

Create immutable dataclasses `DatasetRef(dataset_id)`, `CollectionRef(collection_id, inserted_count)`, `ProcessedChunk(chunk_id, q, a)`, and `RetrievedChunk(chunk_id, collection_id, source_name, q, a, score)`. Define `FastGPTPort` methods:

```python
class FastGPTPort(Protocol):
    async def create_dataset(
        self,
        name: str,
        vector_model: str | None = None,
        agent_model: str | None = None,
        vlm_model: str | None = None,
    ) -> DatasetRef: ...
    async def delete_dataset(self, dataset_id: str) -> None: ...
    async def create_file_collection(self, dataset_id: str, filename: str, content: bytes, config: dict[str, object]) -> CollectionRef: ...
    async def create_text_collection(self, dataset_id: str, name: str, text: str, config: dict[str, object]) -> CollectionRef: ...
    async def set_collection_forbidden(self, collection_id: str, forbidden: bool) -> None: ...
    async def list_collection_data(self, collection_id: str, page_size: int = 30) -> list[ProcessedChunk]: ...
    async def search(self, request: SearchRequest) -> list[RetrievedChunk]: ...
```

Map these official endpoints exactly: dataset create/delete, local file create, text create, collection update with `forbid`, data v2 list, and `searchTest`. Raise `ExternalServiceError(service="fastgpt", safe_message=...)` for non-2xx responses, `code != 200`, timeout, or malformed data. Do not include the response authorization header in the exception.

Define `GenerationPort.generate_answer(question, chunks) -> GeneratedAnswer` where `GeneratedAnswer` has `answer: str` and `claims: list[GeneratedClaim]`; each `GeneratedClaim` contains `text` and `chunk_ids`.

- [ ] **Step 4: Verify adapters and fakes**

Run: `.venv/bin/pytest apps/api/tests/adapters -q && .venv/bin/ruff check apps/api`

Expected: all adapter tests pass; Ruff exits 0.

- [ ] **Step 5: Commit**

```bash
git add apps/api
git commit -m "feat: add external service adapters"
```

### Task 4: Implement Workspace creation and listing

**Files:**
- Create: `apps/api/src/grounded_tutor/dependencies.py`
- Create: `apps/api/src/grounded_tutor/repositories/workspaces.py`
- Create: `apps/api/src/grounded_tutor/services/workspaces.py`
- Create: `apps/api/src/grounded_tutor/routers/workspaces.py`
- Modify: `apps/api/src/grounded_tutor/main.py`
- Create: `apps/api/tests/api/test_workspaces.py`

- [ ] **Step 1: Write the failing API test**

```python
def test_create_workspace_creates_fastgpt_dataset(client, fake_fastgpt) -> None:
    response = client.post("/api/workspaces", json={"title": "Intro Statistics"})
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Intro Statistics"
    assert body["source_count"] == 0
    assert fake_fastgpt.created_datasets == ["Intro Statistics"]


def test_rename_workspace_does_not_recreate_dataset(client, seeded_workspace, fake_fastgpt) -> None:
    response = client.patch(f"/api/workspaces/{seeded_workspace.id}", json={"title": "Statistics Review"})
    assert response.status_code == 200
    assert response.json()["title"] == "Statistics Review"
    assert fake_fastgpt.created_datasets == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest apps/api/tests/api/test_workspaces.py -q`

Expected: FAIL with 404 for `/api/workspaces`.

- [ ] **Step 3: Implement the endpoint**

Implement `POST /api/workspaces`, `GET /api/workspaces`, `GET /api/workspaces/{workspace_id}`, and `PATCH /api/workspaces/{workspace_id}`. Validate trimmed titles from 1–120 characters. The create request accepts optional advanced `vector_model`, `agent_model`, and `vlm_model` strings; blank values are omitted so FastGPT uses its system defaults. Call `FastGPTPort.create_dataset()` before committing the Workspace. Rename only changes the product title in P0 and does not recreate the Dataset. If FastGPT creation fails, return HTTP 502 and do not write a Workspace. Return `WorkspaceResponse(id, title, source_count, ready_source_count, created_at)`; never return `dataset_id` to the browser.

- [ ] **Step 4: Verify success and rollback cases**

Run: `.venv/bin/pytest apps/api/tests/api/test_workspaces.py -q`

Expected: tests for create, list, detail, rename, invalid title, missing Workspace, and FastGPT failure all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api
git commit -m "feat: add topic workspaces"
```

### Task 5: Build safe source settings and local preview

**Files:**
- Create: `apps/api/src/grounded_tutor/domain/ingestion.py`
- Create: `apps/api/src/grounded_tutor/services/previews.py`
- Create: `apps/api/src/grounded_tutor/routers/previews.py`
- Create: `apps/api/tests/services/test_previews.py`
- Create: `apps/api/tests/fixtures/statistics.txt`

- [ ] **Step 1: Write failing preview tests**

```python
from grounded_tutor.domain.ingestion import ChunkSettings
from grounded_tutor.services.previews import preview_text


def test_custom_separator_preview_is_deterministic() -> None:
    preview = preview_text(
        "Mean is an average.\n---\nMedian is the middle value.",
        ChunkSettings(training_type="chunk", setting_mode="custom", split_mode="char", chunk_size=1000, index_size=256, splitter="---"),
    )
    assert [item.text for item in preview.items] == ["Mean is an average.", "Median is the middle value."]
    assert preview.authority == "estimated"


def test_rejects_chunk_size_outside_fastgpt_range() -> None:
    with pytest.raises(ValueError):
        ChunkSettings(training_type="chunk", setting_mode="custom", split_mode="size", chunk_size=50, index_size=32)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest apps/api/tests/services/test_previews.py -q`

Expected: FAIL because ingestion contracts do not exist.

- [ ] **Step 3: Implement settings and parsers**

Implement `ChunkSettings` with API aliases `trainingType`, `indexPrefixTitle`, `customPdfParse`, `chunkSettingMode`, `chunkSplitMode`, `chunkSize`, `indexSize`, `chunkSplitter`, and `qaPrompt`. Enforce `chunkSize` 100–3000 for chunk mode, `indexSize >= 32`, `indexSize <= chunkSize`, separator length at most 20, and QA prompt length at most 4000. Support local extraction for `.pdf`, `.docx`, `.md`, `.txt`, `.html`, and `.csv`; reject encrypted PDFs, empty text, unsupported extensions, and files over `max_upload_bytes` with safe messages.

`POST /api/workspaces/{workspace_id}/source-previews/file` and `/text` return `PreviewResponse(authority="estimated", source_name, character_count, items, warnings)`. For QA mode, return source excerpts and warning code `qa_generated_after_processing`; do not invent question-answer pairs locally.

- [ ] **Step 4: Verify parsing and validation**

Run: `.venv/bin/pytest apps/api/tests/services/test_previews.py -q`

Expected: tests cover TXT, DOCX, PDF, delimiter splitting, size splitting, empty input, unsupported type, and QA warning; all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api
git commit -m "feat: add source processing preview"
```

### Task 6: Implement disabled ingestion and processed-data review

**Files:**
- Create: `apps/api/src/grounded_tutor/repositories/sources.py`
- Create: `apps/api/src/grounded_tutor/services/source_locks.py`
- Create: `apps/api/src/grounded_tutor/services/sources.py`
- Create: `apps/api/src/grounded_tutor/routers/sources.py`
- Modify: `apps/api/src/grounded_tutor/main.py`
- Create: `apps/api/tests/services/test_sources.py`
- Create: `apps/api/tests/api/test_sources.py`

- [ ] **Step 1: Write the failing state-transition test**

```python
@pytest.mark.asyncio
async def test_new_collection_is_disabled_until_acceptance(source_service, fake_fastgpt, workspace) -> None:
    source = await source_service.ingest_text(
        workspace_id=workspace.id,
        name="week-1",
        text="Mean is an average.",
        settings=ChunkSettings(),
    )
    assert source.status is SourceStatus.REVIEW
    assert fake_fastgpt.forbidden_calls == [(source.collection_id, True)]
    assert source.processed_preview[0].q == "Mean is an average."
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest apps/api/tests/services/test_sources.py -q`

Expected: FAIL because `SourceService` does not exist.

- [ ] **Step 3: Implement the ingestion transaction**

For each Workspace, use an `asyncio.Lock` from `WorkspaceLockRegistry`. While holding it: create a local Source in `INDEXING`; call the appropriate FastGPT create method; immediately call `set_collection_forbidden(collection_id, True)`; persist the Collection ID; fetch up to 30 processed items; transition to `REVIEW`; then release the lock. On any error after Collection creation, attempt to keep it forbidden, set the Source to `FAILED`, store only a safe error message, and preserve the retryable ingestion configuration.

Expose:

```text
POST /api/workspaces/{workspace_id}/sources/file
POST /api/workspaces/{workspace_id}/sources/text
GET  /api/workspaces/{workspace_id}/sources
GET  /api/workspaces/{workspace_id}/sources/{source_id}/processed-preview
```

Return 409 if the Workspace is locked by another ingestion request, 404 for cross-Workspace Source IDs, and 422 for invalid settings.

- [ ] **Step 4: Verify states and failure recovery**

Run: `.venv/bin/pytest apps/api/tests/services/test_sources.py apps/api/tests/api/test_sources.py -q`

Expected: tests cover FILE, TEXT, immediate forbid, processed preview, concurrent 409, FastGPT failure, and cross-Workspace access; all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api
git commit -m "feat: add review-gated source ingestion"
```

### Task 7: Activate or reprocess reviewed Sources

**Files:**
- Modify: `apps/api/src/grounded_tutor/services/sources.py`
- Modify: `apps/api/src/grounded_tutor/routers/sources.py`
- Create: `apps/api/tests/api/test_source_review.py`

- [ ] **Step 1: Write failing activation tests**

```python
def test_accept_review_enables_collection(client, seeded_review_source, fake_fastgpt) -> None:
    response = client.post(
        f"/api/workspaces/{seeded_review_source.workspace_id}/sources/{seeded_review_source.id}/accept"
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert fake_fastgpt.forbidden_calls[-1] == (seeded_review_source.collection_id, False)


def test_cannot_accept_failed_source(client, seeded_failed_source) -> None:
    response = client.post(
        f"/api/workspaces/{seeded_failed_source.workspace_id}/sources/{seeded_failed_source.id}/accept"
    )
    assert response.status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest apps/api/tests/api/test_source_review.py -q`

Expected: FAIL with 404 for the accept endpoint.

- [ ] **Step 3: Implement review actions**

Add `POST .../accept`, `POST .../reprocess`, and `DELETE .../sources/{source_id}`. Accept performs `forbid=false` before committing `READY`. Reprocess keeps the old Collection forbidden, creates a new Source version and new Collection, and never overwrites old citations. Delete disables the Collection before marking the local Source deleted; P0 uses soft deletion locally.

- [ ] **Step 4: Verify the complete Source state machine**

Run: `.venv/bin/pytest apps/api/tests/api/test_source_review.py apps/api/tests/services/test_sources.py -q`

Expected: all valid transitions pass and invalid transitions return 409 without changing FastGPT state.

- [ ] **Step 5: Commit**

```bash
git add apps/api
git commit -m "feat: add source review activation"
```

### Task 8: Implement grounded retrieval and cited answer generation

**Files:**
- Modify: `apps/api/src/grounded_tutor/adapters/generation.py`
- Create: `apps/api/src/grounded_tutor/services/chat.py`
- Create: `apps/api/src/grounded_tutor/routers/chat.py`
- Modify: `apps/api/src/grounded_tutor/main.py`
- Create: `apps/api/tests/services/test_chat.py`
- Create: `apps/api/tests/api/test_chat.py`

- [ ] **Step 1: Write the failing grounded-answer test**

```python
@pytest.mark.asyncio
async def test_chat_returns_only_mapped_citations(chat_service, workspace, ready_source, fake_fastgpt) -> None:
    fake_fastgpt.search_results = [RetrievedChunk(
        chunk_id="chunk-1", collection_id=ready_source.collection_id,
        source_name=ready_source.name, q="Mean is an average.", a="", score=0.91,
    )]
    result = await chat_service.ask(workspace.id, "What is a mean?", "request-1")
    assert result.answer == "The mean is an average."
    assert result.citations[0].source_id == ready_source.id
    assert result.citations[0].chunk_id == "chunk-1"


@pytest.mark.asyncio
async def test_chat_refuses_when_retrieval_is_empty(chat_service, workspace) -> None:
    result = await chat_service.ask(workspace.id, "What is a p-value?", "request-2")
    assert result.status == "insufficient_material"
    assert result.citations == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest apps/api/tests/services/test_chat.py -q`

Expected: FAIL because `ChatService` does not exist.

- [ ] **Step 3: Implement retrieval, generation, and citation mapping**

Implement `OpenAICompatibleGenerationClient` with `httpx`: call `{LLM_BASE_URL}/chat/completions`, request JSON output, validate it as `GeneratedAnswer`, use `LLM_MODEL`, and raise a safe `ExternalServiceError` without response headers or prompt contents. `ChatService.ask(workspace_id, question, idempotency_key)` must reject a Workspace with no READY Source, call `searchTest` with `searchMode="mixedRecall"`, `limit=5000`, configurable similarity, and no external search, filter any result whose Collection is not a local READY Source, and refuse if nothing remains. Pass chunks to `GenerationPort` with a system rule that every factual claim must name one or more supplied chunk IDs. Map chunk IDs to local Source IDs and persist the user/assistant messages in one transaction.

Expose `POST /api/workspaces/{workspace_id}/chat` with `{conversation_id?, message, idempotency_key}`. Return `answer`, `status`, `citations[{source_id, source_name, source_version, chunk_id, excerpt}]`, and `suggested_actions`. The browser response must not contain Dataset IDs or Collection IDs.

- [ ] **Step 4: Verify ASK isolation and refusal**

Run: `.venv/bin/pytest apps/api/tests/services/test_chat.py apps/api/tests/api/test_chat.py -q`

Expected: tests cover cited success, empty retrieval refusal, non-ready chunk filtering, cross-Workspace isolation, Chinese response selection, and no-secret response bodies; all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api
git commit -m "feat: add grounded cited chat api"
```

### Task 9: Scaffold the React application and typed API client

**Files:**
- Create: `apps/web/package.json`
- Create: `apps/web/tsconfig.json`
- Create: `apps/web/vite.config.ts`
- Create: `apps/web/index.html`
- Create: `apps/web/src/main.tsx`
- Create: `apps/web/src/app.tsx`
- Create: `apps/web/src/api/client.ts`
- Create: `apps/web/src/api/types.ts`
- Create: `apps/web/src/app.test.tsx`

- [ ] **Step 1: Write the failing shell test**

```tsx
import { render, screen } from "@testing-library/react";
import { App } from "./app";

it("shows the product entry point", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: "Grounded Tutor" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "创建学习主题" })).toBeInTheDocument();
});
```

- [ ] **Step 2: Install web dependencies and verify failure**

Run:

```bash
npm --prefix apps/web install
npm --prefix apps/web test -- --run
```

Expected: FAIL because `src/app.tsx` does not exist.

- [ ] **Step 3: Implement the application shell and client**

Use React Router with `/` and `/workspaces/:workspaceId`. Use TanStack Query for server state. `apiFetch<T>()` must set JSON headers when appropriate, preserve multipart boundaries, parse the standard API error body, and throw `ApiError(status, code, message)`. Define TypeScript unions matching backend values exactly: `SourceType = "file" | "text" | "webpage"` and `SourceStatus = "uploading" | "parsing" | "indexing" | "review" | "ready" | "failed"`.

- [ ] **Step 4: Verify tests and production build**

Run: `npm --prefix apps/web test -- --run && npm --prefix apps/web run build`

Expected: Vitest passes and Vite creates `apps/web/dist`.

- [ ] **Step 5: Commit**

```bash
git add apps/web
git commit -m "chore: scaffold grounded tutor web"
```

### Task 10: Build Workspace and four-step Source UI

**Files:**
- Create: `apps/web/src/features/workspaces/workspace-list.tsx`
- Create: `apps/web/src/features/workspaces/workspace-page.tsx`
- Create: `apps/web/src/features/sources/source-drawer.tsx`
- Create: `apps/web/src/features/sources/source-wizard.tsx`
- Create: `apps/web/src/features/sources/processing-settings.tsx`
- Create: `apps/web/src/features/sources/preview-step.tsx`
- Create: `apps/web/src/features/sources/review-step.tsx`
- Create: `apps/web/src/features/sources/source-wizard.test.tsx`

- [ ] **Step 1: Write the failing primary-journey UI test**

```tsx
it("keeps file upload primary and webpage import out of P0", async () => {
  render(<SourceWizard workspaceId="workspace-1" onComplete={() => undefined} />);
  expect(screen.getByRole("button", { name: "上传本地资料" })).toBeVisible();
  expect(screen.getByRole("button", { name: "粘贴文本" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "导入网页" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "粘贴文本" }));
  expect(screen.getByText("1. 选择来源")).toBeVisible();
  expect(screen.getByText("2. 处理设置")).toBeVisible();
  expect(screen.getByText("3. 数据预览")).toBeVisible();
  expect(screen.getByText("4. 确认处理")).toBeVisible();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm --prefix apps/web test -- --run src/features/sources/source-wizard.test.tsx`

Expected: FAIL because Source Wizard components do not exist.

- [ ] **Step 3: Implement the Source experience**

The empty Workspace shows local upload as the primary button and pasted text as secondary. Workspace creation uses FastGPT system-default models unless the operator expands advanced settings and supplies vector, text-processing, or visual model IDs. The persistent Source drawer and chat attachment button open the same wizard. Recommended settings use chunk mode and automatic splitting. Advanced Source settings expose only `trainingType`, `indexPrefixTitle`, `customPdfParse`, `chunkSettingMode`, `chunkSplitMode`, `chunkSize`, `indexSize`, `chunkSplitter`, and `qaPrompt`. The preview clearly labels local output “预计结果”; the review step labels FastGPT output “实际处理结果”. Only the accept button changes `review` to `ready`.

- [ ] **Step 4: Verify states and accessibility**

Run: `npm --prefix apps/web test -- --run && npm --prefix apps/web run build`

Expected: tests cover file/text selection, recommended/advanced settings, validation, preview warning, review acceptance, failed state, retry, keyboard navigation, and accessible labels; all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web
git commit -m "feat: add source ingestion experience"
```

### Task 11: Build cited chat and foundation browser test

**Files:**
- Create: `apps/web/src/features/chat/chat-panel.tsx`
- Create: `apps/web/src/features/chat/message.tsx`
- Create: `apps/web/src/features/chat/citation-drawer.tsx`
- Create: `apps/web/src/features/chat/chat-panel.test.tsx`
- Create: `apps/web/playwright.config.ts`
- Create: `apps/web/tests/foundation.spec.ts`
- Modify: `Makefile`

- [ ] **Step 1: Write the failing browser journey**

```ts
test("upload material and ask a cited question", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "创建学习主题" }).click();
  await page.getByLabel("主题名称").fill("Intro Statistics");
  await page.getByRole("button", { name: "创建" }).click();
  await page.getByRole("button", { name: "粘贴文本" }).click();
  await page.getByLabel("资料名称").fill("Week 1 notes");
  await page.getByLabel("资料正文").fill("Mean is an average.");
  await page.getByRole("button", { name: "继续" }).click();
  await page.getByRole("button", { name: "生成预览" }).click();
  await page.getByRole("button", { name: "确认处理" }).click();
  await page.getByRole("button", { name: "接受并启用" }).click();
  await page.getByLabel("向资料提问").fill("What is a mean?");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByText("The mean is an average.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Week 1 notes 引用 1" })).toBeVisible();
});
```

- [ ] **Step 2: Run the component test to verify it fails**

Run: `npm --prefix apps/web test -- --run src/features/chat/chat-panel.test.tsx`

Expected: FAIL because chat components do not exist.

- [ ] **Step 3: Implement cited chat**

Disable the composer until at least one Source is READY and show “先上传资料或粘贴文本”. Render assistant status `insufficient_material` as a conservative refusal with “继续添加资料”; do not show a web-search button in P0. Each citation button opens source name, source version, chunk excerpt, and chunk ID. Dragging a file onto the composer opens the shared Source Wizard rather than uploading silently.

- [ ] **Step 4: Run the complete foundation gate**

Run:

```bash
make verify-foundation
npm --prefix apps/web exec playwright test tests/foundation.spec.ts
```

Expected: backend tests, frontend tests, build, and the foundation browser journey all pass using fake adapters.

- [ ] **Step 5: Commit**

```bash
git add apps/web Makefile
git commit -m "feat: complete grounded ask vertical slice"
```
