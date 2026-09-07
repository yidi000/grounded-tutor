# Grounded Tutor Remaining MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the review-gated Source lifecycle, structured cited ASK, Evidence Notebook desktop UI, grounded learning presentation, and read-only public demo without expanding the approved P0 scope.

**Architecture:** The existing FastAPI service remains the only owner of product state and the only caller of FastGPT and the generation provider. The React SPA consumes stable public contracts and renders one desktop activity surface with a shared Composer and ContextPanel. Public demo mode uses versioned static fixtures and blocks writes in both the browser and API; local mode enables real Workspace and Source operations.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic, httpx, pytest, React 19, TypeScript, Vite, TanStack Query, Zod, Vitest, Testing Library, Playwright, plain CSS, Fontsource.

---

## Plan authority and checkpoint rule

This plan supersedes only these sections of the 2026-08-31 plans:

- Foundation Tasks 7, 8, 8A, 9, 10, and 11.
- New Foundation Task 7A.
- Trust Task 1.
- Learning Tasks 5 and 7.
- The read-only sample behavior in Release Tasks 1, 2, and 6.

Foundation Tasks 1–6 are already implemented and remain the baseline. Unchanged Trust Tasks 2–6 and Learning Tasks 1–4 and 6 still execute in the roadmap order. For release, run Release Tasks 1–5, then Release Task 6 Steps 1–4, then the Release addition, and finally Release Task 6 Step 5 after the user authorizes publication.

Every task in all referenced plans is a user review checkpoint. Finish the task, run its listed checks, report the diff and results, then stop. Do not start the next task until the user says `继续`; the revised tasks below label this rule as `STOP GATE`.

Before editing code in any task, activate `ponytail` at its default full level and inspect the existing flow before adding files or dependencies. Frontend tasks additionally require `frontend-design`. These skill requirements apply equally to unchanged tasks in the older referenced plans.

## P0 exclusions

- No mobile-specific layout or browser acceptance gate.
- No webpage import, network search, or whole-site crawl.
- No embedded PDF or Office viewer and no long-term original-file storage.
- No Workspace model changes after creation.
- No plan concept reordering.
- No image-index/OCR toggle and no ASK/PLAN/LEARN/CHECK top-level tabs.
- No account/password implementation. After the open-source P0 release, accounts require a separate security and product specification covering ownership, sessions, password handling, deletion, and cross-account isolation.

## Dependency order

```text
Foundation 7 -> 7A -> 8 -> 8A -> 9 -> 10 -> 11
                                      |
Trust 1-6 ----------------------------+
                                      v
Learning 1-4 -> revised Learning 5 -> Learning 6 -> revised Learning 7
                                      |
                                      v
Release 1-6 with read-only demo additions
```

Task 8A must finish before Task 9 so the UI reads the real format capability response instead of advertising unverified formats.

The migration chain is linear: `0001_workspace_sources` → `0002_source_lifecycle` → `0003_workspace_model_choices` → `0004_message_content_blocks` → Trust `0005_idempotency` → Trust `0006_traces_bad_cases` → Learning `0007_learning_state`. Every migration declares the preceding revision as `down_revision`; do not create Alembic branches.

## File map

### API files to create or extend

- `apps/api/src/grounded_tutor/domain/models.py`: Source lineage/deletion, Workspace model choices, and persisted chat records.
- `apps/api/src/grounded_tutor/domain/schemas.py`: stable public request/response types.
- `apps/api/src/grounded_tutor/domain/answers.py`: one shared structured block and citation contract for ASK, LEARN, and CHECK.
- `apps/api/src/grounded_tutor/domain/errors.py`: one public error-code union used by routers and OpenAPI.
- `apps/api/src/grounded_tutor/repositories/sources.py`: version-aware Source lifecycle and READY Collection lookup.
- `apps/api/src/grounded_tutor/services/sources.py`: accept, reprocess, and soft-delete orchestration.
- `apps/api/src/grounded_tutor/services/chat.py`: retrieval, READY filtering, generation validation, retry, and persistence.
- `apps/api/src/grounded_tutor/services/previews.py`: PPTX/XLSX extraction and bounded image metadata preview.
- `apps/api/src/grounded_tutor/routers/capabilities.py`: read-only ingestion capability endpoint.
- `apps/api/src/grounded_tutor/middleware.py`: API-level `demo_read_only` write guard.

### Web files to create

- `apps/web/src/app.tsx`: mode selection, route composition, and top-level query providers.
- `apps/web/src/api/client.ts`: fetch wrapper and stable `ApiError`.
- `apps/web/src/api/types.ts`: TypeScript mirror of public API unions.
- `apps/web/src/components/app-shell.tsx`: desktop top bar and three-column layout.
- `apps/web/src/components/context-panel.tsx`: the single owner of evidence and material context views.
- `apps/web/src/components/conversation-surface.tsx`: the single owner of the shared Composer.
- `apps/web/src/features/workspaces/topic-rail.tsx`: local Workspace controls or one non-editable demo topic.
- `apps/web/src/features/sources/source-wizard.tsx`: the complete select/settings/estimate/process/review flow.
- `apps/web/src/features/chat/chat-view.tsx`: messages and ASK state.
- `apps/web/src/features/chat/evidence-anchor.tsx`: accessible citation trigger and focus return.
- `apps/web/src/features/learning/*`: diagnostic, plan, lesson, check, activity-resume, and new-topic cards inside the shared activity surface.
- `apps/web/src/demo/fixture.ts`: immutable versioned demo Workspace, answer blocks, and citations.
- `apps/web/src/styles/tokens.css`: approved color, type, spacing, focus, motion, and desktop layout tokens.

## Shared contract decisions

Use these names unchanged in later tasks:

```python
GroundedContentKind = Literal["answer", "definition", "explanation", "example"]
ChatStatus = Literal["ok", "insufficient_material"]
SourceLocator = PdfLocator | DocxLocator | PptxLocator | XlsxLocator | ImageLocator | ChunkLocator
```

```ts
export type GroundedContentKind = "answer" | "definition" | "explanation" | "example";
export type ChatStatus = "ok" | "insufficient_material";
export type AppMode = "local" | "demo_read_only";
```

All successful factual content uses `GroundedContentBlock`. There is no second citation shape for learning activities and no browser-side parsing of provider text.

### Foundation Task 7: Complete Source review, versioning, and removal

**Outcome:** A reviewed Source can be accepted, reprocessed only with newly supplied original input, or safely removed. Historical versions remain available for old citations but are excluded from current retrieval.

**Files:**

- Create: `apps/api/alembic/versions/0002_source_lifecycle.py`
- Modify: `apps/api/src/grounded_tutor/domain/models.py`
- Modify: `apps/api/src/grounded_tutor/domain/schemas.py`
- Modify: `apps/api/src/grounded_tutor/repositories/sources.py`
- Modify: `apps/api/src/grounded_tutor/repositories/workspaces.py`
- Modify: `apps/api/src/grounded_tutor/services/sources.py`
- Modify: `apps/api/src/grounded_tutor/routers/sources.py`
- Create: `apps/api/tests/api/test_source_review.py`
- Modify: `apps/api/tests/services/test_sources.py`
- Modify: `apps/api/tests/api/test_workspaces.py`

- [ ] **Step 1: Write failing lifecycle and migration tests**

```python
def test_reprocess_text_requires_the_original_text_again(client, ready_source) -> None:
    response = client.post(
        f"/api/workspaces/{ready_source.workspace_id}/sources/{ready_source.id}/reprocess/text",
        json={"source_name": ready_source.name, "text": "", "settings": {}},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "empty_source"}}


def test_accept_rejects_empty_actual_result(client, review_source, fake_fastgpt) -> None:
    fake_fastgpt.collections[review_source.collection_id].chunks = []
    response = client.post(
        f"/api/workspaces/{review_source.workspace_id}/sources/{review_source.id}/accept"
    )
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "empty_processed_source"}}


def test_reprocessed_source_keeps_lineage(client, ready_source) -> None:
    response = client.post(
        f"/api/workspaces/{ready_source.workspace_id}/sources/{ready_source.id}/reprocess/text",
        json={
            "source_name": ready_source.name,
            "text": "Replacement material",
            "settings": {"trainingType": "chunk"},
        },
    )
    assert response.status_code == 201
    assert response.json()["source"]["version"] == ready_source.version + 1
    assert response.json()["source"]["replaces_source_id"] == str(ready_source.id)
```

- [ ] **Step 2: Run the focused tests and confirm the missing routes/schema**

Run:

```bash
.venv/bin/pytest apps/api/tests/api/test_source_review.py apps/api/tests/test_models.py -q
```

Expected: FAIL because the lifecycle columns and review routes do not exist.

- [ ] **Step 3: Add the minimal Source lifecycle fields**

Add one migration and matching model fields:

```python
lineage_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
replaces_source_id: Mapped[UUID | None] = mapped_column(
    ForeignKey("sources.id", ondelete="RESTRICT"), nullable=True
)
superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

The migration backfills `lineage_id=id` for existing rows before making it non-null. Extend `SourceSummary` and `SourceResponse` with the same four fields. Keep the existing `SourceStatus` values; lifecycle visibility is represented by timestamps, not extra remote-state-like statuses.

- [ ] **Step 4: Add version-aware repository operations**

Implement these exact repository operations and cover each with service tests:

```python
def create_indexing(
    self,
    *,
    source_id: UUID,
    workspace_id: UUID,
    name: str,
    source_type: SourceType,
    origin_uri: str | None,
    ingestion_config: dict[str, Any],
    lineage_id: UUID | None = None,
    replaces_source_id: UUID | None = None,
    version: int = 1,
) -> SourceSummary:
    source = Source(
        id=source_id,
        workspace_id=workspace_id,
        name=name,
        source_type=source_type,
        origin_uri=origin_uri,
        status=SourceStatus.INDEXING,
        version=version,
        lineage_id=lineage_id or source_id,
        replaces_source_id=replaces_source_id,
        ingestion_config=dict(ingestion_config),
        error_message=None,
    )
    return self._persist_new(source)


def ready_collection_ids(self, workspace_id: UUID) -> dict[str, SourceSummary]:
    records = self._session.scalars(
        select(Source).where(
            Source.workspace_id == workspace_id,
            Source.status == SourceStatus.READY,
            Source.superseded_at.is_(None),
            Source.deleted_at.is_(None),
            Source.collection_id.is_not(None),
        )
    )
    return {record.collection_id: _summary(record) for record in records}
```

Also add `mark_ready`, `mark_superseded`, and `mark_deleted`. All Workspace-scoped reads exclude `deleted_at` by default; an explicit historical lookup may include superseded rows for citation rendering.

Update `WorkspaceRepository._summary_query()` so `source_count` excludes deleted and superseded versions and `ready_source_count` counts only non-deleted, non-superseded READY rows. Historical versions remain addressable only through the explicit citation-history lookup.

- [ ] **Step 5: Implement review actions with fail-closed remote ordering**

Expose these routes:

```text
POST   /api/workspaces/{workspace_id}/sources/{source_id}/accept
POST   /api/workspaces/{workspace_id}/sources/{source_id}/reprocess/text
POST   /api/workspaces/{workspace_id}/sources/{source_id}/reprocess/file
DELETE /api/workspaces/{workspace_id}/sources/{source_id}
```

Use the existing per-Workspace lock. Reprocess calls the existing `_ingest` path with `lineage_id`, `replaces_source_id`, and incremented `version`; the request always includes the replacement file bytes or text. The new Collection remains forbidden in `REVIEW`. Accept first confirms at least one actual processed item, enables the new Collection, disables the previously active version when present, then persists new `READY` and old `superseded_at`. If replacement disable fails, re-forbid the new Collection and leave local state unchanged. Delete disables the remote Collection before setting `deleted_at`; a remote failure leaves the Source visible and returns `external_service_error`.

- [ ] **Step 6: Verify the complete Source state machine**

Run:

```bash
.venv/bin/alembic -c apps/api/alembic.ini upgrade head
.venv/bin/pytest apps/api/tests/api/test_source_review.py apps/api/tests/services/test_sources.py apps/api/tests/test_models.py -q
.venv/bin/ruff check apps/api
git diff --check
```

Expected: migration succeeds; tests cover accept, empty-result rejection, file/text reprocess, new-input requirement, version lineage, superseded filtering, soft deletion, current/READY Workspace counts, invalid transitions, cross-Workspace IDs, and remote rollback; Ruff and diff checks exit 0.

- [ ] **Step 7: Commit and STOP GATE**

```bash
git add apps/api
git commit -m "feat: complete source review lifecycle"
```

Report the new public routes, migration, state-machine tests, and commit. Stop for user approval.

### Foundation Task 7A: Stabilize capabilities, errors, model choices, and demo writes

**Outcome:** The browser can discover only verified ingestion controls and formats, Workspace model choices are persisted as read-only metadata, every relevant error uses a stable code, and API writes are rejected in public demo mode.

**Files:**

- Create: `apps/api/alembic/versions/0003_workspace_model_choices.py`
- Create: `apps/api/src/grounded_tutor/domain/errors.py`
- Create: `apps/api/src/grounded_tutor/routers/capabilities.py`
- Modify: `apps/api/src/grounded_tutor/config.py`
- Modify: `apps/api/src/grounded_tutor/domain/models.py`
- Modify: `apps/api/src/grounded_tutor/domain/schemas.py`
- Modify: `apps/api/src/grounded_tutor/repositories/workspaces.py`
- Modify: `apps/api/src/grounded_tutor/services/workspaces.py`
- Modify: `apps/api/src/grounded_tutor/middleware.py`
- Modify: `apps/api/src/grounded_tutor/routers/common.py`
- Modify: `apps/api/src/grounded_tutor/routers/previews.py`
- Modify: `apps/api/src/grounded_tutor/routers/sources.py`
- Modify: `apps/api/src/grounded_tutor/routers/workspaces.py`
- Modify: `apps/api/src/grounded_tutor/main.py`
- Create: `apps/api/tests/api/test_capabilities.py`
- Create: `apps/api/tests/api/test_demo_read_only.py`
- Modify: `apps/api/tests/api/test_previews.py`
- Modify: `apps/api/tests/api/test_sources.py`
- Modify: `apps/api/tests/api/test_workspaces.py`

- [ ] **Step 1: Write failing public-contract tests**

```python
def test_capabilities_report_only_verified_formats(client) -> None:
    response = client.get("/api/capabilities/source-ingestion")
    assert response.status_code == 200
    assert response.json()["accepted_extensions"] == [".csv", ".docx", ".html", ".md", ".pdf", ".txt"]
    assert response.json()["read_only_demo"] is False


def test_demo_mode_rejects_every_write(demo_client) -> None:
    attempts = [
        demo_client.post("/api/workspaces", json={"title": "No write"}),
        demo_client.patch("/api/workspaces/00000000-0000-0000-0000-000000000000", json={"title": "No write"}),
        demo_client.delete("/api/workspaces/00000000-0000-0000-0000-000000000000/sources/00000000-0000-0000-0000-000000000000"),
    ]
    assert {(response.status_code, response.json()["detail"]["code"]) for response in attempts} == {
        (403, "demo_read_only")
    }


def test_workspace_returns_immutable_model_choices(model_capable_client) -> None:
    response = model_capable_client.post(
        "/api/workspaces",
        json={"title": "RAG", "vector_model": "text-embedding-3-small"},
    )
    assert response.status_code == 201
    assert response.json()["model_choices"] == {
        "vector_model": "text-embedding-3-small",
        "agent_model": None,
        "vlm_model": None,
    }
```

- [ ] **Step 2: Run the contract tests and confirm failure**

Run:

```bash
.venv/bin/pytest apps/api/tests/api/test_capabilities.py apps/api/tests/api/test_demo_read_only.py apps/api/tests/api/test_workspaces.py -q
```

Expected: FAIL because capabilities, persisted model choices, and the demo guard are absent.

- [ ] **Step 3: Define one public error union**

Create `PublicErrorCode` as the source of truth for router annotations and contract tests:

```python
PublicErrorCode = Literal[
    "demo_read_only",
    "empty_processed_source",
    "empty_source",
    "external_service_error",
    "file_too_large",
    "idempotency_key_reused",
    "invalid_chunk_settings",
    "invalid_source_transition",
    "persistence_error",
    "processed_preview_unavailable",
    "request_body_too_large",
    "source_not_found",
    "source_too_large",
    "source_work_limit_exceeded",
    "text_too_large",
    "unreadable_file",
    "unsafe_archive",
    "unsupported_file_type",
    "unsupported_workspace_model",
    "validation_error",
    "workspace_ingestion_busy",
    "workspace_not_found",
]
```

Change `ApiErrorDetail.code` from `str` to `PublicErrorCode`. Keep all router responses in the shape `{"detail":{"code":"workspace_not_found"}}`; do not expose internal exception messages.

- [ ] **Step 4: Persist creation-time Workspace model choices**

Add nullable `vector_model`, `agent_model`, and `vlm_model` columns and return them under:

```python
class WorkspaceModelChoices(BaseModel):
    vector_model: str | None
    agent_model: str | None
    vlm_model: str | None


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    source_count: int
    ready_source_count: int
    model_choices: WorkspaceModelChoices
    created_at: datetime
    updated_at: datetime
```

`WorkspaceSummary` exposes a `model_choices` property that returns the nested public shape from the three stored columns, so `WorkspaceResponse.model_validate(summary)` remains valid. There is no PATCH route for model fields. A model change requires a new Workspace.

- [ ] **Step 5: Add capability response and explicit deployment flags**

Add `demo_read_only: bool = False` plus explicit `supports_custom_pdf_parse`, `supports_vector_model`, `supports_agent_model`, `supports_vlm_model`, and `supports_image_files` booleans to `Settings`; default all provider-specific support flags to `False`.

Return this stable shape from `GET /api/capabilities/source-ingestion`:

```python
class CapabilityItem(BaseModel):
    key: str
    supported: bool
    disabled_reason: Literal["deployment_not_verified", "demo_read_only"] | None


class SourceIngestionCapabilities(BaseModel):
    accepted_extensions: list[str]
    max_upload_bytes: int
    settings: list[CapabilityItem]
    workspace_models: list[CapabilityItem]
    read_only_demo: bool
```

The route sorts extensions, uses `SUPPORTED_EXTENSIONS`, and derives every optional control from explicit settings. It never probes FastGPT on a browser request. Preview, Source ingestion, and Workspace creation reuse the same capability function: requesting unsupported PDF enhancement returns `invalid_chunk_settings`, while sending a disabled model field returns `unsupported_workspace_model`; neither request reaches FastGPT.

- [ ] **Step 6: Enforce demo mode before routing**

Extend the existing middleware module with a small ASGI middleware. For `demo_read_only=True`, allow only `GET`, `HEAD`, and `OPTIONS`; return HTTP 403 with `demo_read_only` for every other method before request-body parsing. Health and capabilities remain readable.

- [ ] **Step 7: Verify contracts, migration, and regression suite**

Run:

```bash
.venv/bin/alembic -c apps/api/alembic.ini upgrade head
.venv/bin/pytest apps/api/tests/api/test_capabilities.py apps/api/tests/api/test_demo_read_only.py apps/api/tests/api/test_workspaces.py apps/api/tests/api/test_previews.py apps/api/tests/api/test_sources.py apps/api/tests/api/test_source_review.py -q
.venv/bin/ruff check apps/api
git diff --check
```

Expected: all public codes appear in OpenAPI, unknown codes fail contract tests, demo mode performs no service calls, model choices round-trip but cannot be patched, and existing Source behavior remains green.

- [ ] **Step 8: Commit and STOP GATE**

```bash
git add apps/api
git commit -m "feat: expose verified ingestion capabilities"
```

Report the capability JSON, demo-write matrix, model-choice persistence, tests, and commit. Stop for user approval.

### Foundation Task 8: Implement structured grounded ASK

**Outcome:** ASK returns renderable content blocks whose citation IDs resolve to READY Sources in the current Workspace. Invalid model output is retried once, then reduced to supported blocks or conservatively refused.

**Files:**

- Create: `apps/api/alembic/versions/0004_message_content_blocks.py`
- Create: `apps/api/src/grounded_tutor/domain/answers.py`
- Modify: `apps/api/src/grounded_tutor/domain/models.py`
- Modify: `apps/api/src/grounded_tutor/domain/schemas.py`
- Modify: `apps/api/src/grounded_tutor/adapters/generation.py`
- Modify: `apps/api/src/grounded_tutor/adapters/fakes.py`
- Create: `apps/api/src/grounded_tutor/repositories/chat.py`
- Create: `apps/api/src/grounded_tutor/services/grounding.py`
- Create: `apps/api/src/grounded_tutor/services/chat.py`
- Create: `apps/api/src/grounded_tutor/routers/chat.py`
- Modify: `apps/api/src/grounded_tutor/dependencies.py`
- Modify: `apps/api/src/grounded_tutor/main.py`
- Create: `apps/api/tests/services/test_grounding.py`
- Create: `apps/api/tests/services/test_chat.py`
- Create: `apps/api/tests/api/test_chat.py`

- [ ] **Step 1: Write failing structured-grounding tests**

```python
def test_unknown_chunk_is_removed(ready_chunks) -> None:
    generated = GeneratedAnswer(
        blocks=(
            GeneratedBlock(id="block-1", kind="answer", text="Supported", chunk_ids=("chunk-1",)),
            GeneratedBlock(id="block-2", kind="answer", text="Unsupported", chunk_ids=("missing",)),
        )
    )
    result = ground_generated_answer(generated, ready_chunks, allowed_kinds={"answer"})
    assert [block.text for block in result.answer_blocks] == ["Supported"]
    assert result.answer_blocks[0].citation_ids == ("citation-1",)


def test_all_invalid_blocks_become_insufficient_material(ready_chunks) -> None:
    generated = GeneratedAnswer(
        blocks=(GeneratedBlock(id="block-1", kind="answer", text="Guess", chunk_ids=()),)
    )
    result = ground_generated_answer(generated, ready_chunks, allowed_kinds={"answer"})
    assert result.status == "insufficient_material"
    assert result.answer_blocks == ()
    assert result.citations == ()


def test_ask_rejects_non_answer_block_kind(ready_chunks) -> None:
    generated = GeneratedAnswer(
        blocks=(GeneratedBlock(id="block-1", kind="definition", text="A definition", chunk_ids=("chunk-1",)),)
    )
    result = ground_generated_answer(generated, ready_chunks, allowed_kinds={"answer"})
    assert result.status == "insufficient_material"
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run:

```bash
.venv/bin/pytest apps/api/tests/services/test_grounding.py apps/api/tests/services/test_chat.py -q
```

Expected: FAIL because the shared answer contract and ChatService do not exist.

- [ ] **Step 3: Define the shared block, locator, and citation contract**

Create Pydantic models with immutable public fields:

```python
class GeneratedBlock(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    kind: Literal["answer", "definition", "explanation", "example"]
    text: str
    chunk_ids: tuple[str, ...] = ()


class GeneratedAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)
    blocks: tuple[GeneratedBlock, ...]


class GroundedContentBlock(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    kind: Literal["answer", "definition", "explanation", "example"]
    text: str = Field(min_length=1)
    citation_ids: tuple[str, ...] = Field(min_length=1)


class ChunkLocator(BaseModel):
    kind: Literal["chunk"] = "chunk"
    label: str


class PdfLocator(BaseModel):
    kind: Literal["pdf"] = "pdf"
    page: int = Field(ge=1)
    section: str | None = None


class DocxLocator(BaseModel):
    kind: Literal["docx"] = "docx"
    heading_path: tuple[str, ...] = ()
    paragraph: int | None = Field(default=None, ge=1)


class PptxLocator(BaseModel):
    kind: Literal["pptx"] = "pptx"
    slide: int = Field(ge=1)
    title: str | None = None


class XlsxLocator(BaseModel):
    kind: Literal["xlsx"] = "xlsx"
    sheet: str
    cell_range: str | None = None


class ImageLocator(BaseModel):
    kind: Literal["image"] = "image"
    filename: str
    region: str | None = None


SourceLocator = Annotated[
    ChunkLocator | PdfLocator | DocxLocator | PptxLocator | XlsxLocator | ImageLocator,
    Field(discriminator="kind"),
]


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    source_id: UUID
    source_name: str
    source_version: int
    chunk_id: str
    excerpt: str
    context_before: str | None = None
    context_after: str | None = None
    locator: SourceLocator


class SimpleSuggestedAction(BaseModel):
    type: Literal["add_material", "rephrase", "start_diagnostic"]


class WorkspaceSuggestionAction(BaseModel):
    type: Literal["suggest_new_workspace"] = "suggest_new_workspace"
    proposed_title: str


class ResumeActivityAction(BaseModel):
    type: Literal["resume_activity"] = "resume_activity"
    label: str
    checkpoint: str


SuggestedAction = Annotated[
    SimpleSuggestedAction | WorkspaceSuggestionAction | ResumeActivityAction,
    Field(discriminator="type"),
]


class GroundedAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: Literal["ok", "insufficient_material"]
    answer_blocks: tuple[GroundedContentBlock, ...]
    citations: tuple[Citation, ...]


def ground_generated_answer(
    generated: GeneratedAnswer,
    ready_chunks: dict[str, RetrievedChunk],
    *,
    allowed_kinds: set[GroundedContentKind],
) -> GroundedAnswer:
    raise NotImplementedError
```

Provider output uses `GeneratedBlock(id, kind, text, chunk_ids)` and never accepts browser citation IDs. Public output replaces provider chunk IDs with locally generated citation IDs.

Use one provider method across tutor modes:

```python
@dataclass(frozen=True, slots=True)
class GenerationRequest:
    mode: Literal["ASK", "LEARN", "CHECK"]
    instruction: str
    chunks: tuple[RetrievedChunk, ...]


class GenerationPort(Protocol):
    async def generate_content(self, request: GenerationRequest) -> GeneratedAnswer:
        raise NotImplementedError
```

- [ ] **Step 4: Implement deterministic READY filtering and grounding**

`ChatService.ask(workspace_id, message, conversation_id, idempotency_key)` performs this order:

1. Resolve the Workspace Dataset and `SourceRepository.ready_collection_ids(workspace_id)`.
2. Return `insufficient_material` without provider calls when the READY map is empty.
3. Call FastGPT `searchTest` once and discard every hit whose Collection is absent from the READY map.
4. Return `insufficient_material` without generation when no hit remains.
5. Generate structured blocks; validate IDs, non-empty citations, and `kind="answer"` for ASK.
6. If provider JSON fails schema parsing or any parsed block fails grounding validation, retry generation exactly once with a bounded validation summary that contains no source text.
7. Drop still-invalid blocks. If none remain, return `insufficient_material`.
8. Persist user and assistant messages only after validation.

The fallback locator is `ChunkLocator(label=f"匹配片段 {retrieval_position}")`. Do not infer page, section, or paragraph from chunk IDs.

- [ ] **Step 5: Implement the OpenAI-compatible adapter and API route**

`OpenAICompatibleGenerationClient` posts to `{llm_base_url}/chat/completions`, requests JSON output, validates `GeneratedAnswer`, and raises the existing redacted external-service error. Expose:

```python
class ChatRequest(BaseModel):
    conversation_id: UUID | None = None
    message: str = Field(min_length=1, max_length=8_000)
    idempotency_key: str = Field(min_length=1, max_length=255)


class ChatResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    status: Literal["ok", "insufficient_material"]
    answer_blocks: tuple[GroundedContentBlock, ...]
    citations: tuple[Citation, ...]
    suggested_actions: tuple[SuggestedAction, ...]
```

Return HTTP 200 for `insufficient_material`. Map provider failures to `external_service_error`; never return Dataset IDs, Collection IDs, prompts, or provider response bodies.

- [ ] **Step 6: Add persistence without changing the existing text field contract**

Migration `0004_message_content_blocks.py` adds nullable JSON `content_blocks` and makes `Message.idempotency_key` nullable. User messages store their text in `content` with a null key; assistant messages store a plain-text concatenation in `content`, structured blocks in `content_blocks`, citations in the existing `citations` JSON column, and the request key. An `insufficient_material` result still persists the user message and an assistant status message with empty blocks/citations, so the response always has conversation and message IDs. Trust Task 2 later makes retries idempotent through `RequestRecord`; do not invent `:user`/`:assistant` derivative keys. This avoids a second message table while keeping historical rows readable.

- [ ] **Step 7: Verify retry, filtering, persistence, and API secrecy**

Run:

```bash
.venv/bin/alembic -c apps/api/alembic.ini upgrade head
.venv/bin/pytest apps/api/tests/services/test_grounding.py apps/api/tests/services/test_chat.py apps/api/tests/api/test_chat.py -q
.venv/bin/pytest apps/api/tests -q
.venv/bin/ruff check apps/api
git diff --check
```

Expected: tests cover successful blocks, malformed provider JSON, blank text, dangling IDs, empty citations, non-`answer` ASK blocks, one retry only, partial block removal, complete refusal, READY filtering, cross-Workspace filtering, language preservation, persistence rollback, and secret-free responses; the complete API suite passes.

- [ ] **Step 8: Commit and STOP GATE**

```bash
git add apps/api
git commit -m "feat: add structured grounded ask"
```

Report the response JSON, validation matrix, test counts, and commit. Stop for user approval.

### Foundation Task 8A: Add verified PPTX, XLSX, and image inputs

**Outcome:** PPTX and XLSX are locally normalized into location-marked text before review-gated ingestion. PNG, JPEG, and WebP are available only when the deployment explicitly confirms image-file support; their local estimate reports bounded image metadata and the actual review remains authoritative.

**Files:**

- Modify: `apps/api/pyproject.toml`
- Modify: `apps/api/src/grounded_tutor/config.py`
- Modify: `apps/api/src/grounded_tutor/domain/ingestion.py`
- Modify: `apps/api/src/grounded_tutor/services/previews.py`
- Modify: `apps/api/src/grounded_tutor/services/sources.py`
- Modify: `apps/api/src/grounded_tutor/services/grounding.py`
- Modify: `apps/api/src/grounded_tutor/routers/capabilities.py`
- Modify: `apps/api/tests/services/test_previews.py`
- Modify: `apps/api/tests/services/test_sources.py`
- Create: `apps/api/tests/fixtures/slides.pptx`
- Create: `apps/api/tests/fixtures/workbook.xlsx`
- Create: `apps/api/tests/fixtures/diagram.png`
- Create: `apps/api/tests/live/test_source_formats_live.py`

- [ ] **Step 1: Write failing format and locator tests**

```python
def test_pptx_preview_preserves_slide_location(slides_bytes) -> None:
    preview = preview_file("slides.pptx", slides_bytes, ChunkSettings())
    assert preview.items[0].locator == PptxLocator(slide=1, title="Chunking")


def test_xlsx_preview_preserves_sheet_and_range(workbook_bytes) -> None:
    preview = preview_file("scores.xlsx", workbook_bytes, ChunkSettings())
    assert preview.items[0].locator == XlsxLocator(sheet="Week 1", cell_range="A1:B3")


def test_image_capability_stays_off_without_provider_confirmation(client) -> None:
    extensions = client.get("/api/capabilities/source-ingestion").json()["accepted_extensions"]
    assert ".png" not in extensions
```

- [ ] **Step 2: Run focused tests and confirm unsupported formats**

Run:

```bash
.venv/bin/pytest apps/api/tests/services/test_previews.py apps/api/tests/services/test_sources.py apps/api/tests/api/test_capabilities.py -q
```

Expected: the new cases fail with `unsupported_file_type` or missing locator metadata.

- [ ] **Step 3: Add only the required parsers**

Add `python-pptx`, `openpyxl`, and `Pillow` to the existing API dependencies. Extract the DOCX ZIP safety checks into a shared `preflight_zip_package` helper and reuse the same member-count, uncompressed-size, compression-ratio, and malformed-directory limits for DOCX, PPTX, and XLSX.

PPTX extraction emits one bounded record per slide with slide number, title, and shape text in reading order. XLSX extraction opens with `read_only=True` and `data_only=True`, rejects macros and external links, skips empty cells, caps sheets/rows/cells, and emits the used cell range. Pillow calls `verify()` before reading width, height, and format; it does not run OCR.

Extend `PreviewItem` with `locator: SourceLocator | None = None`, importing the discriminated union from `domain.answers`. Existing formats keep `None`; Task 8A returns typed PPTX/XLSX/image locators that the frontend treats as an estimate until actual processing finishes.

- [ ] **Step 4: Normalize Office files for traceable ingestion**

Use one internal type:

```python
@dataclass(frozen=True, slots=True)
class NormalizedMaterial:
    remote_kind: Literal["file", "text"]
    content: bytes | str
```

For PPTX and XLSX, serialize extracted records to text with one compact marker before each record:

```text
[[GT_LOCATOR {"kind":"pptx","slide":1,"title":"Chunking"}]]
Slide body text
```

Send that normalized text through `create_text_collection` while preserving the local Source name and type. `grounding.py` removes the marker from excerpts and returns the locator only when a valid marker is present in the retrieved chunk; otherwise it uses `ChunkLocator`. PDF, DOCX, Markdown, TXT, HTML, and CSV keep their current ingestion path.

- [ ] **Step 5: Gate images on explicit provider support**

When `supports_image_files=False`, preview and ingestion return `unsupported_file_type` and capabilities omit image extensions. When true, accept `.png`, `.jpg`, `.jpeg`, and `.webp`, show a local metadata estimate, send original bytes to FastGPT, and use `ImageLocator(filename=source.name)` unless the provider returns a reliable region. Do not add OCR, image-index controls, or guessed regions.

- [ ] **Step 6: Add an opt-in live compatibility probe**

`apps/api/tests/live/test_source_formats_live.py` is skipped unless `RUN_LIVE_INTEGRATION=1`. It creates a temporary Dataset, ingests one tiny fixture per enabled format, confirms actual processed data is non-empty, disables and deletes only resources created by the test, and never prints keys or raw provider responses. A failed image probe leaves `supports_image_files` disabled; it does not block PPTX/XLSX local-normalization support.

- [ ] **Step 7: Verify parsers, bounds, locators, and capabilities**

Run:

```bash
.venv/bin/pip install -e 'apps/api[test]'
.venv/bin/pytest apps/api/tests/services/test_previews.py apps/api/tests/services/test_sources.py apps/api/tests/services/test_grounding.py apps/api/tests/api/test_capabilities.py -q
.venv/bin/pytest apps/api/tests/live/test_source_formats_live.py -q
.venv/bin/ruff check apps/api
git diff --check
```

Expected: deterministic local tests pass; live tests skip without credentials; corrupt ZIP, oversized workbook, decompression bomb, malformed image, unsupported image mode, and locator-fallback cases are covered.

- [ ] **Step 8: Commit and STOP GATE**

```bash
git add apps/api
git commit -m "feat: support verified study material formats"
```

Report which formats are always available, which require deployment confirmation, parser safety results, and the commit. Stop for user approval.

### Foundation Task 9: Scaffold the Evidence Notebook shell

**Required skills:** Use `frontend-design` for the approved visual system and `ponytail` for the smallest component boundary that preserves shared ownership.

**Outcome:** The React application builds in local and read-only demo modes and renders the approved desktop shell, one shared Composer, one shared ContextPanel, and one demo topic.

**Files:**

- Create: `apps/web/package.json`
- Create: `apps/web/package-lock.json`
- Create: `apps/web/tsconfig.json`
- Create: `apps/web/vite.config.ts`
- Create: `apps/web/index.html`
- Create: `apps/web/src/main.tsx`
- Create: `apps/web/src/app.tsx`
- Create: `apps/web/src/config.ts`
- Create: `apps/web/src/api/client.ts`
- Create: `apps/web/src/api/types.ts`
- Create: `apps/web/src/components/app-shell.tsx`
- Create: `apps/web/src/components/context-panel.tsx`
- Create: `apps/web/src/components/conversation-surface.tsx`
- Create: `apps/web/src/components/composer.tsx`
- Create: `apps/web/src/features/workspaces/topic-rail.tsx`
- Create: `apps/web/src/demo/fixture.ts`
- Create: `apps/web/src/styles/tokens.css`
- Create: `apps/web/src/test/setup.ts`
- Create: `apps/web/src/app.test.tsx`

- [ ] **Step 1: Write failing local/demo shell tests**

```tsx
it("renders the local three-column Evidence Notebook", () => {
  render(<App mode="local" />);
  expect(screen.getByRole("banner")).toHaveTextContent("Grounded Tutor");
  expect(screen.getByRole("navigation", { name: "学习主题" })).toBeVisible();
  expect(screen.getByRole("main")).toBeVisible();
  expect(screen.getByRole("complementary", { name: "上下文" })).toBeVisible();
  expect(screen.getAllByLabelText("向资料提问")).toHaveLength(1);
});


it("renders one immutable sample topic in demo mode", () => {
  render(<App mode="demo_read_only" />);
  expect(screen.getByText("示例主题")).toBeVisible();
  expect(screen.getByText("RAG 基础")).toBeVisible();
  expect(screen.queryByRole("button", { name: "创建学习主题" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "上传你的资料" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "在本地使用我的资料" })).toBeVisible();
});
```

- [ ] **Step 2: Install exact dependencies and confirm the test fails**

Create this minimal `package.json` before installation:

```json
{
  "name": "grounded-tutor-web",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest"
  }
}
```

Run:

```bash
npm --prefix apps/web install --save-exact react@19 react-dom@19 @tanstack/react-query@5 zod@4 @fontsource/noto-sans-sc @fontsource/noto-serif-sc @fontsource/ibm-plex-mono
npm --prefix apps/web install --save-dev --save-exact typescript vite @vitejs/plugin-react vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event @types/react @types/react-dom @playwright/test
npm --prefix apps/web test -- --run
```

Expected: dependencies and lockfile are created, then tests fail because the application files do not exist.

- [ ] **Step 3: Mirror backend contracts exactly**

Create Zod schemas only for the Foundation contracts that exist at this stage: capabilities, Workspace, Source, and Chat. Derive `PublicErrorCode`, `SourceStatus`, `SourceType`, `SourceIngestionCapabilities`, Workspace types, `GroundedContentBlock`, the discriminated `SourceLocator`, `Citation`, `SuggestedAction`, `ChatRequest`, and `ChatResponse` with `z.infer`. `apiFetch(schema, input, init)` parses successful JSON with the supplied schema instead of using unchecked casts. API failures throw only this stable error shape:

```ts
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: PublicErrorCode,
  ) {
    super(code);
  }
}
```

The wrapper adds `Content-Type: application/json` only for JSON bodies and leaves multipart boundaries to the browser. It never contains FastGPT or model keys.

- [ ] **Step 4: Implement a single-owner shell**

Use this ownership tree and no parallel drawers or composers:

```tsx
<AppShell
  topicRail={<TopicRail mode={mode} />}
  conversation={
    <ConversationSurface>
      <Composer mode={mode} />
    </ConversationSurface>
  }
  contextPanel={<ContextPanel />}
/>
```

`App` receives `mode` for tests; `main.tsx` reads `VITE_APP_MODE`, accepting only `local` or `demo_read_only`. Demo mode reads only the immutable fixture and never mounts Workspace mutation controls. Local mode creates a QueryClient and loads capabilities before exposing supported controls.

- [ ] **Step 5: Implement the approved desktop visual tokens**

Import only the specified self-hosted weights: Noto Sans SC 400/600/700, Noto Serif SC 600/700, and IBM Plex Mono 500/600. Define the approved color and spacing variables in `tokens.css`, a three-column grid for `min-width: 1280px`, central column `minmax(640px, 1fr)`, TopicRail 168px, and ContextPanel 304px. Use a visible keyboard focus ring and a `prefers-reduced-motion` rule. Do not add mobile navigation or breakpoints below the P0 viewport.

- [ ] **Step 6: Verify shell, build, ownership, and layout CSS**

Run:

```bash
npm --prefix apps/web test -- --run
npm --prefix apps/web run build
rg -n "<Composer|<ContextPanel" apps/web/src
git diff --check
```

Expected: tests pass, Vite builds, the scan shows one Composer owner and one ContextPanel owner, no runtime font CDN exists, and the diff is clean.

- [ ] **Step 7: Commit and STOP GATE**

```bash
git add apps/web
git commit -m "feat: scaffold evidence notebook shell"
```

Report screenshots at `1280×720` and `1440×900`, component/build tests, ownership scan, and the commit. Stop for user approval.

### Foundation Task 10: Build Workspace creation and the Source Wizard

**Required skills:** Use `frontend-design` and `ponytail` before editing React or CSS.

**Outcome:** Local users can create, select, and rename a topic; optionally choose verified models at creation; upload or paste material; inspect an estimated preview; process it; inspect actual results; and accept it for ASK. Demo users see no write controls.

**Files:**

- Create: `apps/web/src/features/workspaces/workspace-dialog.tsx`
- Modify: `apps/web/src/features/workspaces/topic-rail.tsx`
- Create: `apps/web/src/features/sources/source-panel.tsx`
- Create: `apps/web/src/features/sources/source-wizard.tsx`
- Create: `apps/web/src/features/sources/processing-settings.tsx`
- Create: `apps/web/src/features/sources/source-wizard.test.tsx`
- Create: `apps/web/src/features/workspaces/workspace-dialog.test.tsx`
- Modify: `apps/web/src/components/context-panel.tsx`
- Modify: `apps/web/src/components/composer.tsx`
- Modify: `apps/web/src/api/client.ts`

- [ ] **Step 1: Write failing primary-flow and explanation tests**

```tsx
it("keeps the simple settings path primary and explains advanced fields inline", async () => {
  render(<SourceWizard workspaceId="workspace-1" capabilities={capabilities} />);
  await user.click(screen.getByRole("button", { name: "粘贴文本" }));
  expect(screen.getByText("推荐设置" )).toBeVisible();
  await user.click(screen.getByRole("button", { name: "高级设置" }));
  expect(screen.getByLabelText("片段长度")).toBeVisible();
  expect(screen.getByText(/影响每个片段保留多少上下文/)).toBeVisible();
  expect(screen.getByText(/推荐/)).toBeVisible();
});


it("does not offer a provider-unverified control", async () => {
  render(<SourceWizard workspaceId="workspace-1" capabilities={capabilitiesWithoutPdfEnhancement} />);
  await user.click(screen.getByRole("button", { name: "高级设置" }));
  expect(screen.getByLabelText("增强 PDF 解析")).toBeDisabled();
  expect(screen.getByText("当前部署尚未验证此能力")).toBeVisible();
});
```

- [ ] **Step 2: Run focused tests and confirm missing UI**

Run:

```bash
npm --prefix apps/web test -- --run src/features/sources/source-wizard.test.tsx src/features/workspaces/workspace-dialog.test.tsx
```

Expected: FAIL because Workspace and Source controls do not exist.

- [ ] **Step 3: Add creation-time model controls**

The Workspace dialog shows title first and a collapsed `模型配置（高级）`. It renders only capability-supported model fields, explains purpose and index impact inline, omits blank values from POST JSON, and displays chosen values read-only after creation. There is no edit-model action.

TopicRail wires the existing list/select/rename endpoints in local mode. The top bar shows the current READY count as `资料 · N 已就绪`. Demo mode keeps one non-editable topic and hides create and rename actions.

- [ ] **Step 4: Implement the Wizard as one reducer-driven flow**

Use one local reducer rather than a form framework:

```ts
export type WizardStage =
  | "select"
  | "settings"
  | "estimate"
  | "processing"
  | "review"
  | "ready"
  | "failed";

export type WizardInput =
  | { kind: "file"; file: File }
  | { kind: "text"; sourceName: string; text: string };
```

The file/text value stays only in component memory. Drag/drop opens the Wizard with the file selected and does not call an API. Refreshing or reopening a reprocess flow shows `重新选择原资料后处理新版本`; no request is sent until replacement input exists.

- [ ] **Step 5: Wire estimate, process, review, accept, and reprocess**

Call the existing preview endpoints for `预计片段`, then Source ingestion for `正在读取并整理资料`, then display the returned or re-fetched `实际处理结果`. Do not invent provider progress stages. Only `接受并用于问答` calls the accept route. Reprocess selects the matching file/text route and sends the replacement input plus settings. Map the stable error union to the exact recovery states in the approved frontend specification and keep entered text/settings after recoverable failures.

Advanced settings cover exactly `trainingType`, `indexPrefixTitle`, `customPdfParse`, `chunkSettingMode`, `chunkSplitMode`, `chunkSize`, `indexSize`, `chunkSplitter`, and `qaPrompt`. Each rendered field has a student-facing name, purpose, effect, recommended use, and inline disabled reason when applicable; explanations cannot exist only in tooltips.

- [ ] **Step 6: Register materials in the shared ContextPanel**

`source-panel.tsx` supplies the `全部资料` view to the existing ContextPanel. It lists current versions, READY/review/failed state, actual-review action, reprocess action, and safe delete. Do not create a Source drawer. The top bar, empty Workspace, ContextPanel, and Composer attachment action all open the same SourceWizard.

- [ ] **Step 7: Verify UI states, accessibility, and build**

Run:

```bash
npm --prefix apps/web test -- --run
npm --prefix apps/web run build
git diff --check
```

Expected: tests cover empty Workspace, create/select/rename, READY count, file/text selection, capability-driven formats, every advanced setting and inline explanation, invalid settings focus, estimate/actual labels, generic processing state, actual review, accept, new-input reprocess, READY, failure recovery, model configuration, demo omission, keyboard order, and focus restoration; build and diff checks pass.

- [ ] **Step 8: Commit and STOP GATE**

```bash
git add apps/web
git commit -m "feat: add source review experience"
```

Report the supported-format UI, Source state matrix, component/build tests, screenshots, and commit. Stop for user approval.

### Foundation Task 11: Render structured ASK and Evidence Anchors

**Required skills:** Use `frontend-design` and `ponytail` before editing React or CSS.

**Outcome:** Local ASK renders structured answer blocks and accessible numbered anchors; selecting an anchor displays its exact citation context in the shared right panel. The complete desktop foundation journey passes in local and demo modes.

**Files:**

- Create: `apps/web/src/features/chat/chat-view.tsx`
- Create: `apps/web/src/features/chat/answer-block.tsx`
- Create: `apps/web/src/features/chat/evidence-anchor.tsx`
- Create: `apps/web/src/features/chat/citation-detail.tsx`
- Create: `apps/web/src/features/chat/chat-view.test.tsx`
- Create: `apps/web/src/test/render-chat-app.tsx`
- Modify: `apps/web/src/components/context-panel.tsx`
- Modify: `apps/web/src/components/conversation-surface.tsx`
- Modify: `apps/web/src/components/composer.tsx`
- Modify: `apps/web/src/demo/fixture.ts`
- Create: `apps/web/playwright.config.ts`
- Create: `apps/web/tests/foundation.spec.ts`
- Modify: `Makefile`

- [ ] **Step 1: Write failing block/anchor component tests**

```tsx
it("opens the cited source for the selected answer block and restores focus", async () => {
  renderChatApp(groundedResponse);
  const anchor = screen.getByRole("button", { name: "引用 1：Week 1 notes" });
  await user.click(anchor);
  expect(screen.getByRole("complementary", { name: "上下文" })).toHaveTextContent("Week 1 notes");
  expect(screen.getByText("匹配片段 1")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "关闭引用详情" }));
  expect(anchor).toHaveFocus();
});


it("renders insufficient material as a normal chat state", () => {
  renderChatApp(insufficientMaterialResponse);
  expect(screen.getByText("当前资料不足以支持这个答案")).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run focused tests and confirm missing components**

Run:

```bash
npm --prefix apps/web test -- --run src/features/chat/chat-view.test.tsx
```

Expected: FAIL because ChatView and EvidenceAnchor do not exist.

`renderChatApp` mounts the real AppShell, ConversationSurface, shared context state, and the single AppShell-owned ContextPanel. It must not mount ContextPanel inside ChatView; this keeps the test faithful to production ownership.

- [ ] **Step 3: Render anchors from structured IDs only**

`AnswerBlock` renders text and one numbered button per unique `citation_id` at the block end. Numbering restarts for each assistant message. It looks up citations by ID; a missing citation renders no anchor and records a development warning without displaying raw IDs. Do not calculate character offsets and do not draw evidence lines.

- [ ] **Step 4: Use the shared ContextPanel for citation details**

Selecting an anchor switches ContextPanel to `回答依据`, highlights the owning block, and shows source name/version, excerpt, optional before/after context, human locator, and a collapsed chunk ID. It shows only fields present in the response. Close or citation switch returns focus to the correct trigger. Reduced-motion mode removes the 180ms transition without changing state.

- [ ] **Step 5: Wire the Composer and conservative states**

Disable sending until a Workspace has a READY Source. Preserve draft text through retriable API errors. Render `insufficient_material` as an inline state with `添加相关资料` and `换一种问法`; do not add web search. Demo fixture includes one pre-generated structured answer and citations, while its Composer explains that real questions require the local version.

- [ ] **Step 6: Add the desktop foundation browser journeys**

```ts
test("local upload review accept and cited ASK", async ({ page }) => {
  await page.goto("/");
  await createWorkspace(page, "Intro Statistics");
  await pasteAndAccept(page, "Week 1 notes", "Mean is an average.");
  await page.getByLabel("向资料提问").fill("What is a mean?");
  await page.getByRole("button", { name: "发送" }).click();
  await page.getByRole("button", { name: "引用 1：Week 1 notes" }).click();
  await expect(page.getByRole("complementary", { name: "上下文" })).toContainText("Mean is an average.");
});


test("demo uses fixed data and performs no write request", async ({ page }) => {
  const writes: string[] = [];
  page.on("request", request => {
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method())) writes.push(request.url());
  });
  await page.goto("/");
  await page.getByRole("button", { name: /引用 1/ }).click();
  await expect(page.getByText("示例主题")).toBeVisible();
  expect(writes).toEqual([]);
});
```

Run each journey at `1280×720` and `1440×900`; assert `document.documentElement.scrollWidth === document.documentElement.clientWidth` and the central activity surface is at least 640px.

- [ ] **Step 7: Run the complete foundation gate**

Run:

```bash
make verify-foundation
npm --prefix apps/web exec playwright test tests/foundation.spec.ts
git diff --check
```

Expected: API tests, UI tests, Vite build, local journey, demo no-write journey, keyboard citation flow, both desktop viewports, and diff checks pass using fake adapters.

- [ ] **Step 8: Commit and STOP GATE**

```bash
git add apps/web Makefile
git commit -m "feat: complete evidence notebook foundation"
```

Report both viewport screenshots, full gate results, citation accessibility checks, and commit. Stop for user approval.

### Trust Task 1 adjustment: Harden the shared grounding verifier

**Outcome:** The original Trust Task 1 becomes an adversarial audit of the Foundation Task 8 verifier instead of creating a second answer schema or citation pipeline.

**Files:**

- Modify: `apps/api/src/grounded_tutor/services/grounding.py`
- Modify: `apps/api/src/grounded_tutor/services/chat.py`
- Create: `apps/api/tests/security/test_grounded_blocks.py`

- [ ] **Step 1: Add failing adversarial cases**

Cover duplicate block IDs, duplicate citation IDs, valid chunk ID from a non-READY Source, correct Collection in another Workspace, blank factual text, excessive block count, excessive citation count, provider text containing fake `[1]` labels, and model output that changes shape on retry.

- [ ] **Step 2: Run the audit tests**

Run: `.venv/bin/pytest apps/api/tests/security/test_grounded_blocks.py -q`

Expected: at least one bound or isolation case fails before hardening.

- [ ] **Step 3: Apply bounded deterministic validation**

Cap blocks, citations, block text, excerpts, and optional context using named constants. Citation validity depends only on the filtered retrieval map supplied by ChatService. Provider-authored bracket labels remain plain text and never become Evidence Anchors.

- [ ] **Step 4: Verify and STOP GATE**

Run:

```bash
.venv/bin/pytest apps/api/tests/security/test_grounded_blocks.py apps/api/tests/services/test_grounding.py apps/api/tests/services/test_chat.py -q
.venv/bin/ruff check apps/api
git diff --check
```

Commit with:

```bash
git add apps/api
git commit -m "test: harden grounded block validation"
```

Report the adversarial matrix and stop. Trust Tasks 2–6 then continue unchanged.

### Learning Task 5 revision: Ground LEARN and CHECK with the shared block contract

**Outcome:** Lessons return `content_blocks`; check feedback returns `explanation_blocks`. Both use the same citation validation, READY filtering, retry limit, and conservative refusal as ASK.

**Files:**

- Modify: `apps/api/src/grounded_tutor/adapters/generation.py`
- Modify: `apps/api/src/grounded_tutor/adapters/fakes.py`
- Create: `apps/api/src/grounded_tutor/services/lessons.py`
- Create: `apps/api/src/grounded_tutor/services/checks.py`
- Create: `apps/api/src/grounded_tutor/routers/learning.py`
- Modify: `apps/api/src/grounded_tutor/dependencies.py`
- Modify: `apps/api/src/grounded_tutor/main.py`
- Create: `apps/api/tests/services/test_lessons.py`
- Create: `apps/api/tests/services/test_checks.py`
- Create: `apps/api/tests/api/test_learning.py`

- [ ] **Step 1: Write failing shared-contract tests**

```python
@pytest.mark.asyncio
async def test_lesson_returns_grounded_content_blocks(lesson_service, active_concept) -> None:
    lesson = await lesson_service.create(active_concept.id, depth="standard")
    assert {block.kind for block in lesson.content_blocks} <= {"definition", "explanation", "example"}
    assert all(block.citation_ids for block in lesson.content_blocks)
    assert {citation.id for citation in lesson.citations} >= {
        citation_id for block in lesson.content_blocks for citation_id in block.citation_ids
    }


@pytest.mark.asyncio
async def test_create_check_hides_answer_key_and_keeps_grounded_feedback(check_service, active_concept) -> None:
    check = await check_service.create(active_concept.id)
    assert check.prompt
    assert check.options
    assert not hasattr(check, "answer_key")
    stored = check_service.get_internal(check.check_id)
    assert stored.answer_key
    assert stored.feedback_blocks


@pytest.mark.asyncio
async def test_check_feedback_uses_explanation_blocks(check_service, active_check) -> None:
    result = await check_service.submit(active_check.id, response="B", idempotency_key="check-1")
    assert all(block.kind == "explanation" for block in result.explanation_blocks)
    assert all(block.citation_ids for block in result.explanation_blocks)
```

- [ ] **Step 2: Run tests and confirm the learning handlers are absent**

Run:

```bash
.venv/bin/pytest apps/api/tests/services/test_lessons.py apps/api/tests/services/test_checks.py apps/api/tests/api/test_learning.py -q
```

Expected: FAIL because LessonService, CheckService, and learning routes do not exist.

- [ ] **Step 3: Reuse grounding and add one typed check-generation method**

Lesson generation calls `generate_content(GenerationRequest(mode="LEARN", instruction=lesson_prompt, chunks=chunks))` and passes the response through `ground_generated_answer(..., allowed_kinds={"definition", "explanation", "example"})`.

Extend `GenerationPort` once for immediate-check creation:

```python
@dataclass(frozen=True, slots=True)
class GeneratedCheck:
    kind: Literal["single_choice", "structured_short"]
    prompt: str
    options: tuple[str, ...]
    answer_key: tuple[str, ...]
    explanation: GeneratedAnswer


class GenerationPort(Protocol):
    async def generate_check(
        self,
        concept_title: str,
        objective: str,
        chunks: Sequence[RetrievedChunk],
    ) -> GeneratedCheck:
        raise NotImplementedError
```

`CheckService.create(concept_id)` retrieves READY evidence for the current Concept, calls `generate_check`, validates question kind/options/answer key, grounds `explanation` with `allowed_kinds={"explanation"}`, and persists an `Assessment` with answer key, evidence refs, feedback blocks, and citations. Return only the public question. Allow one generation retry; if validation still fails, return `insufficient_material` and create no Assessment.

`CheckService.submit` scores without another model call: normalize whitespace/case and compare against the stored answer-key tuple. It returns the already validated explanation blocks and citations. `更简单`, `更多例子`, and `更深入` keep the same Concept ID. A failed or skipped check stays on the current Concept; a passed check advances only after its Attempt and checkpoint commit succeeds.

- [ ] **Step 4: Return explicit response fields**

```python
class LessonResponse(BaseModel):
    concept_id: UUID
    depth: Literal["simpler", "standard", "more_examples", "deeper"]
    status: Literal["ok", "insufficient_material"]
    content_blocks: tuple[GroundedContentBlock, ...]
    citations: tuple[Citation, ...]
    available_depths: tuple[str, ...]


class CheckQuestionReadyResponse(BaseModel):
    status: Literal["ready"] = "ready"
    check_id: UUID
    kind: Literal["single_choice", "structured_short"]
    prompt: str
    options: tuple[str, ...]


class CheckQuestionUnavailableResponse(BaseModel):
    status: Literal["insufficient_material"] = "insufficient_material"
    suggested_action: Literal["add_material"] = "add_material"


CheckQuestionResponse = Annotated[
    CheckQuestionReadyResponse | CheckQuestionUnavailableResponse,
    Field(discriminator="status"),
]


class CheckResultResponse(BaseModel):
    check_id: UUID
    correct: bool | None
    status: Literal["ok", "insufficient_material"]
    explanation_blocks: tuple[GroundedContentBlock, ...]
    citations: tuple[Citation, ...]
    next_action: Literal["review_concept", "next_concept", "choose_after_skip", "add_material"]
    active_concept_id: UUID
```

Expose `POST /api/workspaces/{workspace_id}/concepts/{concept_id}/lessons`, `POST /api/workspaces/{workspace_id}/concepts/{concept_id}/checks`, and `POST /api/workspaces/{workspace_id}/checks/{check_id}/answers`. Every repository lookup includes the route Workspace ID and returns `workspace_not_found` or a non-revealing resource 404 for cross-Workspace IDs. If grounding yields no supported block, return `CheckQuestionUnavailableResponse` and do not create a check or update mastery from generated feedback.

- [ ] **Step 5: Verify the learning-loop service gate**

Run:

```bash
.venv/bin/pytest apps/api/tests/services/test_lessons.py apps/api/tests/services/test_checks.py apps/api/tests/api/test_learning.py apps/api/tests/services/test_grounding.py -q
.venv/bin/ruff check apps/api
git diff --check
```

Expected: tests cover depth variants, block kinds, check creation, typed creation refusal, hidden answer key, deterministic scoring, dangling citations, one retry, partial removal, refusal, pass/fail/skip, duplicate submission, atomic state, READY isolation, and cross-Workspace Concept/Check IDs.

- [ ] **Step 6: Commit and STOP GATE**

```bash
git add apps/api
git commit -m "feat: ground lessons and checks"
```

Report LEARN/CHECK response examples, grounding reuse, state tests, and the commit. Stop for user approval.

### Learning Task 7 revision: Present the continuous learning loop

**Required skills:** Use `frontend-design` and `ponytail` before editing React or CSS.

**Outcome:** Diagnostic, PLAN, LEARN, CHECK, ASK detours, exact diagnostic/lesson/check resume, plan rebuild, and unrelated-topic suggestions all render inside the existing ConversationSurface and reuse its Composer and ContextPanel.

**Files:**

- Create: `apps/web/src/features/learning/diagnostic-card.tsx`
- Create: `apps/web/src/features/learning/learning-plan-card.tsx`
- Create: `apps/web/src/features/learning/lesson-card.tsx`
- Create: `apps/web/src/features/learning/check-card.tsx`
- Create: `apps/web/src/features/learning/activity-dock.tsx`
- Create: `apps/web/src/features/learning/workspace-suggestion-card.tsx`
- Create: `apps/web/src/features/learning/learning-surface.test.tsx`
- Modify: `apps/web/src/api/types.ts`
- Modify: `apps/web/src/api/client.ts`
- Modify: `apps/web/src/components/conversation-surface.tsx`
- Modify: `apps/web/src/components/context-panel.tsx`
- Modify: `apps/web/src/features/workspaces/topic-rail.tsx`
- Create: `apps/web/tests/learning-loop.spec.ts`
- Create: `evals/cases/learning.jsonl`
- Modify: `Makefile`

- [ ] **Step 1: Write failing consent, rebuild, and resume component tests**

```tsx
it("does not start diagnosis without explicit consent", async () => {
  render(<DiagnosticCard invitation={invitation} />);
  await user.click(screen.getByRole("button", { name: "继续提问" }));
  expect(startDiagnostic).not.toHaveBeenCalled();
});


it("cancels plan rebuild without a request and restores focus", async () => {
  render(<LearningPlanCard plan={plan} />);
  const trigger = screen.getByRole("button", { name: "重建学习路径" });
  await user.click(trigger);
  await user.click(screen.getByRole("button", { name: "取消" }));
  expect(rebuildPlan).not.toHaveBeenCalled();
  expect(trigger).toHaveFocus();
});


it("names the exact suspended activity", () => {
  render(<ActivityDock action={{ type: "resume_activity", label: "继续第 2 题", checkpoint: "diagnostic-question-2" }} />);
  expect(screen.getByRole("button", { name: "继续第 2 题" })).toBeVisible();
});
```

- [ ] **Step 2: Run focused tests and confirm missing learning UI**

Run: `npm --prefix apps/web test -- --run src/features/learning/learning-surface.test.tsx`

Expected: FAIL because the learning components do not exist.

- [ ] **Step 3: Render all modes in ConversationSurface**

Diagnostic invitation is an inline card with `开始诊断` and `继续提问`. Questions show real progress plus skip and exit. PLAN shows 3–5 concepts with objective, status, and start action; it has no reorder UI. Lessons render `content_blocks` with the existing AnswerBlock/EvidenceAnchor path. Checks render `explanation_blocks` through the same path. ActivityDock sits above the one shared Composer.

Add Zod schemas for `LessonResponse`, the discriminated `CheckQuestionResponse`, and `CheckResultResponse` to `api/types.ts` only now that the backend contracts exist. Add their typed requests to `api/client.ts`; do not use unchecked response casts.

- [ ] **Step 4: Implement explicit high-impact confirmations**

Plan rebuild opens a confirmation dialog with cancel/confirm, preserves the historical plan, sends no request on cancel, and switches only after the new plan succeeds. WorkspaceSuggestionCard displays the proposed title and calls Workspace creation only after confirmation; rejection keeps the current Workspace, messages, and activity.

- [ ] **Step 5: Add learning evaluation cases and browser journeys**

Add `LR-01`–`LR-08` for invitation consent, dismissal cooldown, diagnostic skip, bounded plan, check detour/resume, failed-check review, passed-check advance, and reload recovery. Browser tests cover ASK → diagnostic → PLAN → LEARN → CHECK, DIAGNOSTIC → ASK → exact question resume, LEARN → ASK → exact concept resume, CHECK → ASK → exact question resume, plan rebuild cancel/confirm, unrelated-topic reject/confirm, and Evidence Anchors in LEARN/CHECK.

- [ ] **Step 6: Run the complete learning gate at both desktop viewports**

Run:

```bash
make verify-learning
npm --prefix apps/web exec playwright test tests/learning-loop.spec.ts
git diff --check
```

Expected: all API/UI tests pass, all 48 evaluation cases execute, both browser specs pass at `1280×720` and `1440×900`, no page-level horizontal scroll occurs, and the shared Composer/ContextPanel ownership remains unchanged.

- [ ] **Step 7: Commit and STOP GATE**

```bash
git add apps/web evals Makefile
git commit -m "feat: present the grounded learning loop"
```

Report the seven learning journey groups, evaluation results, desktop screenshots, accessibility checks, and commit. Stop for user approval.

### Release addition after Release Task 6 Step 4: Package the deterministic hosted read-only demo

**Outcome:** The public build always opens the same copyright-safe RAG sample, persists no visitor input, makes no write request, and clearly routes real uploads to local setup instructions.

**Files:**

- Modify: `apps/web/src/demo/fixture.ts`
- Create: `apps/web/src/demo/fixture.test.ts`
- Modify: `apps/web/tests/foundation.spec.ts`
- Modify: `apps/web/vite.config.ts`
- Create: `.github/workflows/demo-pages.yml`
- Modify: `README.md`
- Modify: `docs/security-and-data.md`
- Modify: `docs/release-checklist.md`
- Modify: `Makefile`

- [ ] **Step 1: Lock and test the demo seed**

The fixture exports a version string, one non-editable Workspace, copyright-safe source metadata, one structured answer, and matching citations. A unit test deep-freezes it and asserts every citation ID resolves.

- [ ] **Step 2: Prove reset and no-write behavior**

Playwright opens the demo, changes only ephemeral UI state, reloads, and asserts the initial fixture is restored. It records network requests and fails on every non-GET/HEAD/OPTIONS method. API tests separately prove `demo_read_only` rejects direct write calls.

- [ ] **Step 3: Document the two modes honestly**

README labels the hosted build `只读示例` and links `在本地使用我的资料` to exact local setup. Security documentation says visitor input is not saved because the demo does not provide live chat or upload; it does not claim cloud accounts or private storage.

- [ ] **Step 4: Build a static GitHub Pages artifact and add it to the release gate**

Configure Vite's base path from `VITE_PUBLIC_BASE_PATH`, leaving `/` as the local default. `demo-pages.yml` runs only after pushes to the approved default branch, installs from the lockfile, builds with `VITE_APP_MODE=demo_read_only`, uploads only `apps/web/dist`, and deploys with GitHub Pages' official actions. It receives no FastGPT, LLM, or repository secret other than the Pages deployment token provided by GitHub.

Run:

```bash
make release-check
git diff --check
```

Expected: fake-adapter verification, 48 evaluation cases, demo reset/no-write journeys, static demo production build, secret scan, and public-file audit pass.

- [ ] **Step 5: Commit and STOP GATE**

```bash
git add apps/web .github/workflows/demo-pages.yml README.md docs Makefile
git commit -m "feat: package read-only public demo"
```

Report fixture provenance, no-write evidence, Pages workflow permissions, release-check result, and commit. Stop before any GitHub publication or account-system work. After the user authorizes publication, execute Release Task 6 Step 5; verify both the clean clone and the deployed Pages URL, including the sample citation interaction and absence of non-read network requests.

## Approved frontend specification coverage

| Specification section | Executable coverage |
|---|---|
| First-view promise and one sample Workspace | Foundation 9 and Release addition |
| Desktop three-column Evidence Notebook | Foundation 9 and 11 |
| One shared Composer and ContextPanel | Foundation 9–11 and Learning 7 |
| Four-step Source Wizard plus actual review | Foundation 7, 7A, 8A, and 10 |
| Inline advanced-setting explanations | Foundation 7A and 10 |
| Creation-only Workspace model configuration | Foundation 7A and 10 |
| Structured Evidence Anchors and reliable locators | Foundation 8, 8A, and 11 |
| ASK → diagnostic → PLAN → LEARN → CHECK | Learning 5 and 7 plus unchanged Learning 1–4 and 6 |
| Conservative errors and recovery | Foundation 7, 7A, 8, 10, and 11 |
| Keyboard, focus, reduced motion, and desktop viewport gates | Foundation 9–11 and Learning 7 |
| Deterministic read-only demo with no writes | Foundation 7A, 9, 11, and Release addition |
| Future account/password boundary | Roadmap Phase 5; explicitly excluded from P0 implementation |

## Final P0 completion gate

- [ ] `make verify` exits 0 using fake adapters.
- [ ] `make release-check` exits 0 from a clean checkout.
- [ ] `RUN_LIVE_INTEGRATION=1 make test-live` passes on the owner's machine; if credentials are unavailable, report this as an unverified external gate.
- [ ] All public answer, lesson, and check blocks resolve every citation ID to a local READY Source version.
- [ ] Demo mode performs no write request and the API rejects direct writes.
- [ ] The two desktop viewports have no page-level horizontal scroll and retain a central surface of at least 640px.
- [ ] Secret and public-file scans contain no private key, Dataset ID, App ID, real student material, or account identifier.
- [ ] Git status is clean before publication.


## Phase 1 addendum: ASK history restoration (2026-09-07)

User-approved final Phase 1 scope, after completed Task 11:

- Restore persisted questions, structured answers, and citation snapshots after refresh.
- Keep the selected workspace in the URL and load its history when switching.
- Isolate histories, citation panels, loading, and late ASK results by workspace.
- Continue the latest persisted conversation; provide explicit loading/error/retry states.

Implemented with a read-only workspace history endpoint and the existing TanStack
Query cache. SQLite remains the source of truth. No schema migration, dependency,
model call, mobile work, or image support is added. History search, deletion,
pagination, and model conversational memory are outside this addendum.
