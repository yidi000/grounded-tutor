# Diagnostic Learning Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a user-consented micro-diagnostic, a 3–5 concept learning plan, grounded concept teaching, immediate checks, and reliable pause/resume without disrupting free chat.

**Architecture:** A deterministic Route Policy selects high-impact actions from explicit UI events and uses model classification only for low-risk learning intent. ActivityState persists the active mode and suspended checkpoint; PLAN, LEARN, ASK, and CHECK handlers share the existing retrieval and citation pipeline.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, pytest, React, TypeScript, TanStack Query, Vitest, Playwright.

---

> **2026-09-02 revision:** Execute Tasks 1–4 and 6 from this file. Execute the revised Tasks 5 and 7 from `2026-09-02-grounded-tutor-remaining-mvp.md` so LEARN/CHECK reuse the shared structured citation contract and Evidence Notebook shell.

### Task 1: Add activity and learning-domain persistence

**Files:**
- Modify: `apps/api/src/grounded_tutor/domain/models.py`
- Create: `apps/api/alembic/versions/0007_learning_state.py`
- Create: `apps/api/src/grounded_tutor/domain/learning.py`
- Create: `apps/api/tests/domain/test_learning_state.py`

- [x] **Step 1: Write the failing state test**

```python
def test_activity_can_suspend_check_for_ask() -> None:
    state = ActivitySnapshot(active_mode="CHECK", active_concept_id="concept-1", checkpoint="question-2")
    suspended = state.suspend_for("ASK")
    assert suspended.active_mode == "ASK"
    assert suspended.suspended_activity.mode == "CHECK"
    assert suspended.suspended_activity.checkpoint == "question-2"
```

- [x] **Step 2: Run the test to verify failure**

Run: `.venv/bin/pytest apps/api/tests/domain/test_learning_state.py -q`

Expected: FAIL because `ActivitySnapshot` does not exist.

- [x] **Step 3: Add types and tables**

Use exact mode values `ASK`, `PLAN`, `LEARN`, and `CHECK`. Add tables: `ActivityState(workspace_id unique, active_mode, active_concept_id, suspended_activity JSON, return_checkpoint, nudge_cooldown_until, updated_at)`, `LearnerProfile(workspace_id unique, inferred_fields JSON, confirmed_fields JSON)`, `LearningPlan(id, workspace_id, goal, status, created_at)`, `Concept(id, plan_id, order, title, objective, status, evidence_refs JSON)`, `Assessment(id, concept_id nullable, kind, prompt, options JSON, answer_key, evidence_refs JSON, feedback_blocks JSON, citations JSON)`, and `Attempt(id, assessment_id, response, result, status, created_at)`. Status enums must include `not_started`, `active`, `completed`, `needs_review`, and `not_assessed` where applicable. Diagnostic and immediate-check answers remain server-only; public schemas never expose `answer_key`.

**Implementation notes (2026-09-07):** Concept and Assessment also persist Workspace ownership; composite foreign keys prevent cross-Workspace links. Assessment `kind` records the question format, while `purpose` distinguishes diagnostic from immediate check. Diagnostic questions may have no Concept. Answer keys are JSON arrays stored only on the server. Skipped Attempts have null response/result and `not_assessed`; they do not update Concept mastery. Suspended activity JSON must be revalidated against Workspace ownership when the orchestrator is added in Task 6.

- [x] **Step 4: Run migration and domain tests**

Run: `cd apps/api && ../../.venv/bin/alembic upgrade head && cd ../.. && .venv/bin/pytest apps/api/tests/domain/test_learning_state.py -q`

Expected: migration succeeds; suspend, resume, skip, and completed-checkpoint tests pass.

- [x] **Step 5: Commit**

```bash
git add apps/api
git commit -m "feat: add learning activity state"
```

### Task 2: Implement deterministic routing and diagnostic invitation

**Files:**
- Create: `apps/api/src/grounded_tutor/services/routing.py`
- Create: `apps/api/src/grounded_tutor/services/diagnostic_invites.py`
- Modify: `apps/api/src/grounded_tutor/services/chat.py`
- Create: `apps/api/tests/services/test_routing.py`
- Create: `apps/api/tests/services/test_diagnostic_invites.py`

- [x] **Step 1: Write failing precedence tests**

```python
@pytest.mark.parametrize(("event", "activity", "expected"), [
    ("START_DIAGNOSTIC", None, "CHECK"),
    ("CONTINUE_CHECK", "CHECK", "CHECK"),
    ("ASK_QUESTION", "LEARN", "ASK"),
    (None, None, "ASK"),
])
def test_route_precedence(event, activity, expected) -> None:
    assert RoutePolicy().choose(event=event, active_mode=activity, classified_intent=None) == expected
```

- [x] **Step 2: Run tests to verify failure**

Run: `.venv/bin/pytest apps/api/tests/services/test_routing.py apps/api/tests/services/test_diagnostic_invites.py -q`

Expected: FAIL because Route Policy and invitation policy do not exist.

- [x] **Step 3: Implement route and invitation policies**

Precedence is: explicit UI event, active assessment/lesson, explicit textual intent, low-risk classifier, fallback ASK. Classifier output can suggest an invitation but cannot start CHECK, rebuild a plan, change Workspace, or call the network. Invite when the user explicitly says they are new/confused, asks how to learn, or asks for a test; otherwise require two related foundation questions in one conversation. The card has `开始诊断` and `继续提问`. Dismissal sets a 24-hour Workspace cooldown; acceptance clears the card and creates the diagnostic only once.

When a low-risk classifier detects an unrelated topic, return `WorkspaceSuggestionAction(type="suggest_new_workspace", proposed_title="Linear Algebra")` with the classifier's bounded proposed title; keep the current Workspace, messages, and activity unchanged until the user explicitly creates or selects another Workspace. Save classifier observations only in `LearnerProfile.inferred_fields`; save the user's stated goal and background only in `confirmed_fields`, and never overwrite confirmed values with an inference.

**Implementation boundary (2026-09-07):** Task 2 persists a single invitation and stable explicit-consent ID in ActivityState (migration 0008), and exposes the existing ASK suggestion in replies/history. Actual diagnostic creation and its consent endpoint remain in Task 3; it must use this stable ID for exactly-once creation/replay. The card labels are defined here; card rendering remains Task 7. No live classifier call is added. See `docs/diagnostic-invitations.md`.

- [x] **Step 4: Verify precedence and cooldown**

Run: `.venv/bin/pytest apps/api/tests/services/test_routing.py apps/api/tests/services/test_diagnostic_invites.py -q`

Expected: explicit actions win, ordinary questions stay ASK, a dismissal suppresses repeated invites, unrelated topics only produce a suggestion, inferred fields never overwrite confirmed fields, and the classifier never performs a high-impact action.

- [x] **Step 5: Commit**

```bash
git add apps/api
git commit -m "feat: add consented diagnostic invitation"
```

### Task 3: Generate and score the 3–5 question micro-diagnostic

**Files:**
- Modify: `apps/api/src/grounded_tutor/adapters/generation.py`
- Modify: `apps/api/src/grounded_tutor/adapters/fakes.py`
- Modify: `apps/api/src/grounded_tutor/dependencies.py`
- Create: `apps/api/src/grounded_tutor/services/diagnostics.py`
- Create: `apps/api/src/grounded_tutor/routers/diagnostics.py`
- Modify: `apps/api/src/grounded_tutor/main.py`
- Create: `apps/api/tests/services/test_diagnostics.py`
- Create: `apps/api/tests/api/test_diagnostics.py`

- [x] **Step 1: Write the failing diagnostic test**

```python
@pytest.mark.asyncio
async def test_diagnostic_has_bounded_grounded_questions(diagnostic_service, workspace) -> None:
    diagnostic = await diagnostic_service.start(workspace.id, goal="Understand descriptive statistics")
    assert 3 <= len(diagnostic.questions) <= 5
    assert all(question.evidence_refs for question in diagnostic.questions)
    assert all(question.kind in {"single_choice", "structured_short"} for question in diagnostic.questions)
```

- [x] **Step 2: Run the test to verify failure**

Run: `.venv/bin/pytest apps/api/tests/services/test_diagnostics.py -q`

Expected: FAIL because Diagnostic Service does not exist.

- [x] **Step 3: Implement start, answer, skip, and summary**

`POST /diagnostics` requires explicit `consent=true`, a READY Source, a user goal, and optional self-described background. Retrieve representative material and generate 3–5 structured questions with answer key, explanation, concept label, and chunk evidence through this typed extension of `GenerationPort`:

```python
@dataclass(frozen=True, slots=True)
class GeneratedDiagnosticQuestion:
    id: str
    kind: Literal["single_choice", "structured_short"]
    prompt: str
    options: tuple[str, ...]
    answer_key: tuple[str, ...]
    explanation: str
    concept_label: str
    chunk_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GeneratedDiagnostic:
    questions: tuple[GeneratedDiagnosticQuestion, ...]


class GenerationPort(Protocol):
    async def generate_diagnostic(
        self,
        goal: str,
        background: str | None,
        chunks: Sequence[RetrievedChunk],
    ) -> GeneratedDiagnostic:
        raise NotImplementedError
```

Validate the 3–5 bound, question kind, non-empty server-only answer key, and every chunk ID against READY retrieval before persistence; one generation retry is allowed, then return `insufficient_material`. `POST /diagnostics/{id}/answers` accepts exactly one question response and is idempotent. `skip=true` stores `not_assessed`, never incorrect. Summary returns concept-level results `understood`, `needs_review`, or `not_assessed`; it must not return a fake overall ability percentage.

- [x] **Step 4: Verify API and citation behavior**

Run: `.venv/bin/pytest apps/api/tests/services/test_diagnostics.py apps/api/tests/api/test_diagnostics.py -q`

Expected: tests cover missing consent, 3–5 bound, grounded answer keys, skip semantics, replay, and no overall percentage; all pass.

- [x] **Step 5: Commit**

```bash
git add apps/api
git commit -m "feat: add grounded micro diagnostic"
```

Implementation notes: see `docs/micro-diagnostics.md`. Local API/service and adapter verification covers this task; diagnostic desktop UI remains Task 7 and the deployed FastGPT questions contract is not yet live-verified.

### Task 4: Generate a finite grounded learning plan

**Files:**
- Modify: `apps/api/src/grounded_tutor/adapters/generation.py`
- Modify: `apps/api/src/grounded_tutor/adapters/fakes.py`
- Modify: `apps/api/src/grounded_tutor/dependencies.py`
- Create: `apps/api/src/grounded_tutor/services/plans.py`
- Create: `apps/api/src/grounded_tutor/routers/plans.py`
- Create: `apps/api/tests/services/test_plans.py`

- [x] **Step 1: Write the failing plan constraints test**

```python
@pytest.mark.asyncio
async def test_plan_contains_three_to_five_grounded_concepts(plan_service, completed_diagnostic) -> None:
    plan = await plan_service.create_from_diagnostic(completed_diagnostic.id)
    assert 3 <= len(plan.concepts) <= 5
    assert [concept.order for concept in plan.concepts] == list(range(1, len(plan.concepts) + 1))
    assert all(concept.objective and concept.evidence_refs for concept in plan.concepts)
```

- [x] **Step 2: Run the test to verify failure**

Run: `.venv/bin/pytest apps/api/tests/services/test_plans.py -q`

Expected: FAIL because Plan Service does not exist.

- [x] **Step 3: Implement plan creation and safe changes**

Extend `GenerationPort` with a separate plan response rather than forcing concepts into answer blocks:

```python
@dataclass(frozen=True, slots=True)
class GeneratedPlanConcept:
    title: str
    objective: str
    chunk_ids: tuple[str, ...]
    check_kind: Literal["single_choice", "structured_short"]


@dataclass(frozen=True, slots=True)
class GeneratedLearningPlan:
    concepts: tuple[GeneratedPlanConcept, ...]


class GenerationPort(Protocol):
    async def generate_plan(
        self,
        goal: str,
        diagnostic_summary: dict[str, str],
        chunks: Sequence[RetrievedChunk],
    ) -> GeneratedLearningPlan:
        raise NotImplementedError
```

Build 3–5 concepts from confirmed goal, diagnostic results, and READY source evidence. Validate every generated chunk ID before persistence. Every concept has title, objective, order, evidence refs, and an immediate-check type. Allow skip without deleting completed state. Do not expose a reorder endpoint in P0. Require a `confirm_rebuild=true` request for full regeneration; preserve the old plan as `superseded` rather than overwriting it.

- [x] **Step 4: Verify constraints and history**

Run: `.venv/bin/pytest apps/api/tests/services/test_plans.py -q`

Expected: bounds, evidence, skip, absence of a reorder route, completed preservation, rejected unconfirmed rebuild, and superseded history tests pass.

- [x] **Step 5: Commit**

```bash
git add apps/api
git commit -m "feat: add grounded learning plans"
```

Implementation notes: see `docs/learning-plans.md`. Includes persisted diagnostic provenance, check kinds, scoped skip/rebuild/history APIs, and atomic replay shared with diagnostics. Desktop UI remains Task 7; the deployed FastGPT concepts contract is not yet live-verified.

### Task 5: Add grounded lessons and immediate checks

**Files:**
- Create: `apps/api/src/grounded_tutor/services/lessons.py`
- Create: `apps/api/src/grounded_tutor/services/checks.py`
- Create: `apps/api/src/grounded_tutor/routers/learning.py`
- Create: `apps/api/tests/services/test_lessons.py`
- Create: `apps/api/tests/services/test_checks.py`

- [ ] **Step 1: Write failing learning-loop tests**

```python
@pytest.mark.asyncio
async def test_failed_check_returns_to_same_concept(check_service, active_concept) -> None:
    result = await check_service.submit(active_concept.id, response="B", idempotency_key="check-1")
    assert result.correct is False
    assert result.next_action == "review_concept"
    assert result.active_concept_id == active_concept.id


@pytest.mark.asyncio
async def test_passing_check_advances_to_next_concept(check_service, active_concept) -> None:
    result = await check_service.submit(active_concept.id, response="A", idempotency_key="check-2")
    assert result.correct is True
    assert result.next_action == "next_concept"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/pytest apps/api/tests/services/test_lessons.py apps/api/tests/services/test_checks.py -q`

Expected: FAIL because lesson and check services do not exist.

- [ ] **Step 3: Implement LEARN and CHECK handlers**

Lesson output is structured as `definition`, `explanation`, `example`, `citations`, and `available_depths`. “更简单”, “更多例子”, and “更深入” keep the same Concept ID. Immediate checks use single-choice or deterministic structured-short answers with evidence-backed explanations. Correct advances; incorrect sets `needs_review` and returns to the same concept; skip sets `not_assessed` and asks whether to continue. Persist state and Attempt atomically.

- [ ] **Step 4: Verify the loop and conservative errors**

Run: `.venv/bin/pytest apps/api/tests/services/test_lessons.py apps/api/tests/services/test_checks.py -q`

Expected: depth changes, cited lesson, pass, fail, skip, duplicate submission, and missing-evidence refusal tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api
git commit -m "feat: add learn ask check handlers"
```

### Task 6: Implement pause, ASK detours, and resume

**Files:**
- Create: `apps/api/src/grounded_tutor/services/orchestrator.py`
- Modify: `apps/api/src/grounded_tutor/services/chat.py`
- Create: `apps/api/tests/services/test_orchestrator.py`

- [ ] **Step 1: Write the failing resume test**

```python
@pytest.mark.asyncio
async def test_question_during_diagnostic_returns_resume_action(orchestrator, active_diagnostic) -> None:
    result = await orchestrator.handle_message(active_diagnostic.workspace_id, "What does this term mean?", "detour-0")
    assert result.mode == "ASK"
    assert result.actions[0].type == "resume_activity"
    assert result.actions[0].checkpoint == active_diagnostic.checkpoint
    resumed = await orchestrator.resume(active_diagnostic.workspace_id)
    assert resumed.checkpoint == active_diagnostic.checkpoint


@pytest.mark.asyncio
async def test_question_during_check_returns_resume_action(orchestrator, active_check) -> None:
    result = await orchestrator.handle_message(active_check.workspace_id, "Why is median robust?", "detour-1")
    assert result.mode == "ASK"
    assert result.actions[0].type == "resume_activity"
    assert result.actions[0].checkpoint == active_check.checkpoint
    resumed = await orchestrator.resume(active_check.workspace_id)
    assert resumed.checkpoint == active_check.checkpoint
```

- [ ] **Step 2: Run the test to verify failure**

Run: `.venv/bin/pytest apps/api/tests/services/test_orchestrator.py -q`

Expected: FAIL because Orchestrator does not exist.

- [ ] **Step 3: Implement activity stack rules**

Keep the four persisted modes from Task 1: a diagnostic is a CHECK-mode assessment whose checkpoint kind is `diagnostic`. During a diagnostic assessment, an immediate CHECK, or LEARN, a direct content question suspends the activity, calls ASK, and returns `ResumeActivityAction(type="resume_activity", label="继续第 2 题", checkpoint="diagnostic-question-2")` with the actual label and checkpoint. A page close persists only the last completed checkpoint; an unsubmitted answer never changes mastery. Workspace switching leaves the original ActivityState untouched. Resume loads the exact diagnostic question, Concept, or check question and does not regenerate it.

- [ ] **Step 4: Verify all cross-scenario transitions**

Run: `.venv/bin/pytest apps/api/tests/services/test_orchestrator.py -q`

Expected: diagnostic CHECK checkpoint→ASK→same diagnostic checkpoint, immediate CHECK→ASK→same check, LEARN→ASK→same concept, skip, page reload, Workspace switch, and failed-handler rollback tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api
git commit -m "feat: add resumable tutor orchestration"
```

### Task 7: Add learning UI and eight learning evaluation cases

**Files:**
- Create: `apps/web/src/features/learning/diagnostic-invite.tsx`
- Create: `apps/web/src/features/learning/diagnostic-panel.tsx`
- Create: `apps/web/src/features/learning/learning-plan.tsx`
- Create: `apps/web/src/features/learning/lesson-panel.tsx`
- Create: `apps/web/src/features/learning/check-panel.tsx`
- Create: `apps/web/src/features/learning/resume-card.tsx`
- Create: `apps/web/tests/learning-loop.spec.ts`
- Create: `evals/cases/learning.jsonl`
- Modify: `Makefile`

- [ ] **Step 1: Write the failing browser journey**

```ts
test("free chat can enter and resume the learning loop", async ({ page }) => {
  await seedReadyWorkspace(page, "Statistics");
  await page.getByLabel("向资料提问").fill("我是新手，应该怎么学？");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByText("要先做一个 3–5 题的小诊断吗？")).toBeVisible();
  await page.getByRole("button", { name: "开始诊断" }).click();
  await answerDiagnostic(page);
  await expect(page.getByRole("heading", { name: "学习路径" })).toBeVisible();
  await page.getByRole("button", { name: /开始概念 1/ }).click();
  await page.getByRole("button", { name: "检查理解" }).click();
  await page.getByRole("button", { name: "先问一个问题" }).click();
  await page.getByLabel("向资料提问").fill("为什么？");
  await page.getByRole("button", { name: "发送" }).click();
  await page.getByRole("button", { name: "继续刚才的检查" }).click();
  await expect(page.getByText(/题目/)).toBeVisible();
});
```

- [ ] **Step 2: Run the browser test to verify failure**

Run: `npm --prefix apps/web exec playwright test tests/learning-loop.spec.ts`

Expected: FAIL because the diagnostic invitation is absent.

- [ ] **Step 3: Implement learning UI and case data**

The invitation remains a card inside chat, not a modal. Diagnostic UI always offers skip and exit. The plan shows 3–5 concepts, evidence availability, and statuses. Lesson UI exposes the three depth controls and ASK composer. Check UI explains answers with citations. Resume Card names the suspended activity. Add evaluation IDs `LR-01`–`LR-08` for invite consent, invite dismissal cooldown, diagnostic skip, bounded plan, check detour/resume, failed check review, passed check advance, and page reload recovery.

- [ ] **Step 4: Run the complete learning gate**

Run: `make verify-learning`

Expected: all backend/frontend tests pass, all 48 evaluation cases execute, and both Playwright journeys pass with fake adapters.

- [ ] **Step 5: Commit**

```bash
git add apps/web evals Makefile
git commit -m "feat: complete diagnostic learning loop"
```
