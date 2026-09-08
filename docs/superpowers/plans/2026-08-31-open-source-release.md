# Open-Source Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package Grounded Tutor as a reproducible, credential-safe GitHub portfolio project with authorized sample material, honest evaluation results, CI, and clear setup instructions.

**Architecture:** The public repository runs with fake adapters by default and switches to owner-supplied services only through untracked environment variables. Release checks inspect tracked files, build both apps, execute 48 evaluation cases, and block publication when secrets or unauthorized materials are present.

**Tech Stack:** Markdown, MIT License, Make, GitHub Actions, Gitleaks, pytest, Vitest, Playwright.

---

> **2026-09-02 revision:** Execute Tasks 1–5 and Task 6 Steps 1–4 below, then the `Release addition after Release Task 6 Step 4` in `2026-09-02-grounded-tutor-remaining-mvp.md`. After its STOP GATE and explicit user publication approval, execute Task 6 Step 5. The addition supplies the deterministic hosted read-only demo, no-write proof, and local-upload handoff before publication.

### Task 1: Add safe configuration templates and original sample material

**Files:**
- Create: `.env.example`
- Create: `apps/api/.env.example`
- Create: `samples/rag-fundamentals/README.md`
- Create: `samples/rag-fundamentals/01-rag-overview.md`
- Create: `samples/rag-fundamentals/02-retrieval-quality.md`
- Create: `samples/rag-fundamentals/manifest.json`
- Create: `apps/api/tests/release/test_sample_manifest.py`

- [x] **Step 1: Write the failing sample authorization test**

```python
def test_sample_manifest_is_public_and_complete() -> None:
    manifest = json.loads(Path("samples/rag-fundamentals/manifest.json").read_text())
    assert manifest["license"] == "CC0-1.0"
    assert manifest["created_for"] == "Grounded Tutor demonstration"
    assert manifest["files"] == ["01-rag-overview.md", "02-retrieval-quality.md"]
    assert all((Path("samples/rag-fundamentals") / name).exists() for name in manifest["files"])
```

- [x] **Step 2: Run the test to verify failure**

Run: `.venv/bin/pytest apps/api/tests/release/test_sample_manifest.py -q`

Expected: FAIL because the manifest is absent.

- [x] **Step 3: Add templates and original material**

The API example contains names only: `EXTERNAL_MODE`, `DATABASE_URL`, `FASTGPT_BASE_URL`, `FASTGPT_API_KEY`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `RUN_LIVE_INTEGRATION`, and `ENABLE_LOCAL_ADMIN`; credential values are blank. Write two original documents covering RAG components, chunking, semantic/full-text/hybrid retrieval, Rerank, grounding, and evaluation. The manifest records CC0-1.0, purpose, file list, and SHA-256 hashes.

- [x] **Step 4: Verify manifest hashes and ignore rules**

Run: `.venv/bin/pytest apps/api/tests/release/test_sample_manifest.py -q && git check-ignore apps/api/.env`

Expected: sample test passes and the real `.env` path is ignored.

- [x] **Step 5: Commit**

```bash
git add .env.example apps/api/.env.example samples apps/api/tests/release
git commit -m "docs: add safe demo corpus and env templates"
```

Implementation notes (2026-09-08): Added identical fake-mode configuration templates,
original CC0 sample documents and SHA-256 manifest. The publication guard permits
only the two exact template paths while retaining credential scanning. Targeted
release/security tests: 19 passed; backend: 932 passed, 7 skipped; Ruff and public
file scan passed. Real local configuration remains ignored. Basic Q&A/upload
guidance is recorded separately as deferred work and is not implemented.

### Task 2: Add public documentation and licensing

**Files:**
- Create: `LICENSE`
- Create: `CONTRIBUTING.md`
- Create: `README.md`
- Create: `docs/architecture.md`
- Create: `docs/evaluation.md`
- Create: `docs/security-and-data.md`
- Create: `apps/api/tests/release/test_documentation.py`

- [x] **Step 1: Write the failing documentation test**

```python
@pytest.mark.parametrize("path", [
    "README.md", "LICENSE", "CONTRIBUTING.md", "docs/architecture.md",
    "docs/evaluation.md", "docs/security-and-data.md",
])
def test_required_public_document_exists(path: str) -> None:
    assert Path(path).is_file()


def test_readme_distinguishes_targets_from_results() -> None:
    text = Path("README.md").read_text()
    assert "Target thresholds" in text
    assert "Measured results" in text
```

- [x] **Step 2: Run the test to verify failure**

Run: `.venv/bin/pytest apps/api/tests/release/test_documentation.py -q`

Expected: FAIL because the public documents are absent.

- [x] **Step 3: Write exact setup and boundary documentation**

README sections are: problem, primary user, capabilities, non-goals, architecture, fake-adapter quick start, live FastGPT setup, model-provider setup, testing, target thresholds, measured results, limitations, roadmap, security/data, and license. Architecture distinguishes the local product database from FastGPT. Evaluation documents all 48 case IDs and formulas. Security/data prohibits credentials and real student material in issues, logs, screenshots, fixtures, and reports. CONTRIBUTING requires tests and a declaration that contributed sample data is redistributable.

- [x] **Step 4: Verify links and tests**

Run: `.venv/bin/pytest apps/api/tests/release/test_documentation.py -q && npx --yes markdown-link-check README.md`

Expected: tests pass and README links resolve.

- [x] **Step 5: Commit**

```bash
git add LICENSE CONTRIBUTING.md README.md docs apps/api/tests/release
git commit -m "docs: add open source project documentation"
```

Implementation notes (2026-09-08): Added README, MIT license, contribution,
architecture, evaluation and security/data documentation. All 48 case IDs are
listed with metric definitions and fake/live limitations. Eight documentation
checks passed (10 release tests total), including local link resolution using
the standard library rather than downloading a link-check dependency. Verified
Alembic upgrade and fake API startup against disposable SQLite; public-file scan
and Ruff passed. Dependency installation from a fresh network environment and
public demo deployment remain release audit work.

### Task 3: Sanitize the BTB Workflow as a non-production baseline

**Files:**
- Create: `fastgpt/baseline.sanitized.json`
- Create: `fastgpt/README.md`
- Create: `scripts/sanitize_fastgpt_export.py`
- Create: `apps/api/tests/release/test_fastgpt_baseline.py`

- [x] **Step 1: Write the failing sanitization test**

```python
def test_baseline_has_no_account_or_secret_fields() -> None:
    lowered = Path("fastgpt/baseline.sanitized.json").read_text().lower()
    for forbidden in ("authorization", "api_key", "apikey", "teamid", "tmbid", "datasetid", "appid", "fastgpt-"):
        assert forbidden not in lowered
```

- [x] **Step 2: Run the test to verify failure**

Run: `.venv/bin/pytest apps/api/tests/release/test_fastgpt_baseline.py -q`

Expected: FAIL because the sanitized baseline is absent.

- [x] **Step 3: Implement deterministic sanitization**

The script accepts explicit input and output paths. Recursively remove authorization, API key, team/member, Dataset, Collection, App, cookie, and user identifier fields; replace account-specific URLs with `https://example.invalid/redacted`; preserve node types, public prompts, and graph edges. Refuse to overwrite the input and never print removed values. Run it on the user export only after confirming the input path.

- [x] **Step 4: Validate the output**

Run: `.venv/bin/pytest apps/api/tests/release/test_fastgpt_baseline.py -q && python3 -m json.tool fastgpt/baseline.sanitized.json >/dev/null`

Expected: tests pass and JSON is valid.

- [x] **Step 5: Commit only safe artifacts**

```bash
git add fastgpt scripts/sanitize_fastgpt_export.py apps/api/tests/release/test_fastgpt_baseline.py
git commit -m "docs: add sanitized fastgpt baseline"
```

Implementation notes (2026-09-08): Generated a review-only copy from the original
BTB export without modifying it. Confirmed all 13 node IDs/types and 12 edges
match the original. Added BOM-aware deterministic sanitization with no-overwrite
protection, private-field/key-value removal, embedded JSON sanitization and URL
redaction. Release/security tests: 31 passed; Ruff, JSON parsing and publication
scan passed. No remote workflow was imported, executed or published. This tool
is not a universal secret detector; new exports require manual review.

### Task 4: Publish a reproducible evaluation report

**Files:**
- Create: `scripts/render_evaluation_report.py`
- Create: `evals/reports/public-p0.json`
- Create: `evals/reports/public-p0.md`
- Modify: `README.md`
- Create: `apps/api/tests/release/test_public_report.py`

- [x] **Step 1: Write the failing report test**

```python
def test_report_counts_match_case_files() -> None:
    report = json.loads(Path("evals/reports/public-p0.json").read_text())
    assert report["total_cases"] == 48
    assert report["executed_cases"] == 48
    assert report["adapter_mode"] == "fake"
    assert "target_thresholds" in report
    assert "measured_metrics" in report
```

- [x] **Step 2: Run the test to verify failure**

Run: `.venv/bin/pytest apps/api/tests/release/test_public_report.py -q`

Expected: FAIL because the public report is absent.

- [x] **Step 3: Generate measured results without rewriting failures**

Run all 48 cases from a clean database. The renderer includes commit hash, timestamp, adapter mode, configuration hash, passed/failed IDs, category metrics, target thresholds, measured metrics, and limitations. Preserve failing values and link their Bad Cases. README values must be read from the JSON report, never manually copied from targets.

- [x] **Step 4: Verify deterministic regeneration**

Run: `.venv/bin/pytest apps/api/tests/release/test_public_report.py -q && git diff --exit-code evals/reports/public-p0.json evals/reports/public-p0.md`

Expected: report tests pass and regeneration creates no diff.

- [x] **Step 5: Commit**

```bash
git add scripts/render_evaluation_report.py evals/reports/public-p0.json evals/reports/public-p0.md README.md apps/api/tests/release/test_public_report.py
git commit -m "docs: publish reproducible evaluation results"
```

Implementation notes (2026-09-08): Re-executed the fixed 40 ASK and 8 learning
cases with disposable SQLite; all 48 passed. Public JSON exports only measured
numbers, fixed case IDs, hashes and validated provenance, with targets separate.
Markdown and failure sections derive from JSON; README links the generated report.
Fixed-input render-only regeneration has no diff; fresh execution changes time
and provenance intentionally. Only these two report filenames bypass the private
report path block, not credential scanning. Release/security: 36 passed; backend:
949 passed, 7 skipped; Ruff and public-file scan passed. This is a local commit,
not GitHub publication, and does not measure live model or teaching quality.

### Task 5: Add opt-in live-service smoke tests

**Files:**
- Create: `apps/api/tests/live/test_fastgpt_live.py`
- Create: `apps/api/tests/live/test_generation_live.py`
- Modify: `Makefile`

- [ ] **Step 1: Write guarded live tests**

```python
pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_INTEGRATION") != "1",
    reason="set RUN_LIVE_INTEGRATION=1 with local credentials",
)


@pytest.mark.asyncio
async def test_live_fastgpt_create_upload_search_cleanup(live_fastgpt) -> None:
    dataset = await live_fastgpt.create_dataset("Grounded Tutor smoke test")
    try:
        await live_fastgpt.create_text_collection(
            dataset.dataset_id, "smoke", "Mean is an average.",
            {"trainingType": "chunk", "chunkSettingMode": "auto"},
        )
        assert await live_fastgpt.search(SearchRequest(dataset_id=dataset.dataset_id, text="What is a mean?"))
    finally:
        await live_fastgpt.delete_dataset(dataset.dataset_id)
```

- [ ] **Step 2: Verify normal CI skips live calls**

Run: `.venv/bin/pytest apps/api/tests/live -q`

Expected: tests are skipped and no network request occurs.

- [ ] **Step 3: Add an explicit credential-safe command**

`make test-live` checks the required FastGPT and model variable names are non-empty without echoing values, then runs only live tests. The FastGPT test deletes only the temporary Dataset ID it created in the same test.

- [ ] **Step 4: Run with owner-provided local credentials**

Run: `RUN_LIVE_INTEGRATION=1 make test-live`

Expected: create/upload/search/cleanup succeeds and generation returns valid structured JSON. If credentials are not provided, leave this gate pending and do not claim success.

- [ ] **Step 5: Commit tests without credentials**

```bash
git add apps/api/tests/live Makefile
git commit -m "test: add opt-in live service smoke tests"
```

### Task 6: Run the release audit and prepare GitHub publication

**Files:**
- Create: `docs/release-checklist.md`
- Modify: `Makefile`
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/secret-scan.yml`

- [ ] **Step 1: Define and run the release gate**

`make release-check` runs `make verify-learning`, release tests, production build, API import smoke test, Gitleaks, tracked-file audit, baseline and sample tests, report regeneration check, and `git diff --check`.

Run: `make release-check`

Expected: exit 0 with fake adapters, 48 cases executed, browser journeys passing, and no secret finding.

- [ ] **Step 2: Inspect exact local Git state**

```bash
git status --short
git remote -v
gh auth status
git log --oneline --decorate -10
```

Expected: clean worktree, intended commit history, approved or absent Remote, and GitHub CLI authenticated as the intended owner. PR history elsewhere and a ChatGPT GitHub plugin do not satisfy this gate.

- [ ] **Step 3: Obtain external-publication confirmation**

Ask for the exact GitHub account/organization, repository name, public/private visibility, and permission to create/connect the remote. Do not create a public repository, push, or change visibility before confirmation.

- [ ] **Step 4: Commit the release gate**

```bash
git add docs/release-checklist.md Makefile .github
git commit -m "chore: add open source release gate"
```

- [ ] **Step 5: Publish and verify a clean clone after confirmation**

Create or connect only the approved repository, push the approved branch, wait for CI and the Pages deployment, then clone to a new temporary directory and run `make verify-foundation`. Open the deployed Pages URL and verify the fixed sample answer, Evidence Anchor interaction, local-setup link, and absence of non-read network requests. Expected: push succeeds, CI and Pages are green, the hosted smoke test passes, and the clean clone runs with fake adapters and no local secret files.
