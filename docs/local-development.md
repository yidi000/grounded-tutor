# Local deployment and development guide

A desktop-first evidence notebook for learners studying their own documents.
It connects questions, explanations and short checks to inspectable source text,
so the learner can examine where an answer came from.

## Capabilities

Create, rename and delete topic Workspaces; import files or paste text; review and accept processed
sources; ask questions with numbered citations; restore saved history. Optional
micro-diagnostics lead to finite learning plans, cited lessons and immediate
checks. Pause a learning activity, ask a question, and resume its saved checkpoint.

## Non-goals

This is a local single-user prototype, not a public multi-user service. Accounts,
mobile design, images, webpage import and whole-site sync are not implemented.
General-knowledge Q&A with an upload reminder is deferred. Missing evidence does
not authorize uncited answers. Saved history does not enable model chat memory.

## Architecture

React/Vite provides the UI, FastAPI owns product behavior, and SQLite stores local
history, source versions and learning progress. FastGPT supplies document processing
and retrieval; an OpenAI-compatible endpoint supplies structured generation.
See [architecture](../docs/architecture.md).

## Fake-adapter quick start

Use Python 3.12 or 3.13, Node.js 24 and npm, Git and Make. The commands below are
for a POSIX shell, run from the repository root after cloning or downloading it.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e 'apps/api[test]'
npm --prefix apps/web ci
```

For a fresh installation, copy the template without overwriting existing settings:

```sh
test -f apps/api/.env || cp apps/api/.env.example apps/api/.env
.venv/bin/alembic -c apps/api/alembic.ini upgrade head
make api-dev
```

The template selects fake providers with blank keys. If you already have live
settings, use a separate checkout for this walkthrough. Do not overwrite your
existing database or configuration. In a second terminal, from the same root:

```sh
VITE_APP_MODE=local npm --prefix apps/web run dev -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173`; the dev server proxies `/api` to port 8000. Create a
Workspace, add the [original sample material](../samples/rag-fundamentals/README.md),
review processing and accept it. Fake providers produce deterministic fixture
responses, not meaningful AI answers, and their remote-like state is in memory.
Use live mode to study real documents; fake mode is for interface exploration.

For the fixed read-only frontend demonstration, no backend is needed:

```sh
VITE_APP_MODE=demo_read_only npm --prefix apps/web run dev -- --host 127.0.0.1 --port 5173
```

This starts a local 只读示例 with a fixed answer and inspectable citation. The
在本地使用我的资料 link opens bundled setup instructions. The demo has no live
chat or upload and does not save visitor input. Its original Chinese fixture text
is dedicated under CC0; application code remains MIT.

For the static artifact run `make demo-build`; for production-build browser checks
under a repository subpath run `make demo-check`. `VITE_PUBLIC_BASE_PATH` controls
the build base (default `/`). `make release-check` includes the nested-path demo
checks. Pages packaging exists but no deployment URL is available yet.

This release distributes source code for local deployment. No hosted service or
public demo deployment is provided. The optional Pages workflow remains inactive;
leave `DEMO_PAGES_APPROVED` unset. No FastGPT or model key belongs in GitHub or
the frontend. See [release checks](../docs/release-checklist.md).

Deleting a topic permanently removes its cloud dataset and local sources, chat
history and learning progress after confirmation. See [deletion behavior and
retry handling](../docs/workspace-deletion.md).

## Live FastGPT and model-provider setup

Edit only your ignored `apps/api/.env`: set `EXTERNAL_MODE=live`, your FastGPT
service origin and key, and the generation endpoint, key and model. Restart the
API after configuration changes. Existing sources in fake mode do not provision
real cloud datasets; use a new Workspace for live material.

The generator can be a dedicated FastGPT application or another compatible
endpoint. For FastGPT, select the actual model in that application's workflow,
keep history zero and tools disabled, and use the versioned structured prompt.
Follow [the exact generation setup](../docs/fastgpt-generation.md). Keep images off.
Never place keys in frontend variables, tracked files or browser screenshots.

## Testing

```sh
npm --prefix apps/web exec -- playwright install chrome
make verify-learning
```

The gate runs backend tests, Ruff, frontend tests/build, 40 ASK evaluations,
8 learning evaluations and desktop Playwright journeys. Browser dependencies may
need installation on Linux. CI is configured to run the release gate and secret scan, including desktop
journeys; see the repository Actions tab for hosted execution results. Live probes are opt-in and incur external
service calls; see [evaluation](../docs/evaluation.md).

To run the existing live probes explicitly with your local credentials:

```sh
RUN_LIVE_INTEGRATION=1 make test-live
```

Without opt-in the command stops before loading settings. It checks required
configuration names without printing values and suppresses pytest tracebacks.
It creates temporary cloud datasets using synthetic material and attempts cleanup;
provider failures may require manual cleanup. Images remain conditional on the
existing disabled-by-default capability. No credentials are copied into test files.

Before release, stage the intended files and run `make release-check`. It includes
`verify-learning`, API import, saved public report consistency and redacted secret
scans of all Git history plus staged/working tracked snapshots. Install Gitleaks
8.30.1 or run Docker for the pinned scanner fallback. Missing tools or findings
fail the gate. See the [release checklist](../docs/release-checklist.md).

## Target thresholds

Deterministic citation coverage, refusal, replay and journey ratios must equal 1;
workspace leakage and unauthorized provider-call counts must equal 0. These are
software acceptance targets, not claims of model accuracy. Definitions and the
48-case inventory are in [evaluation](../docs/evaluation.md).

## Measured results

See the generated [public evaluation report](../evals/reports/public-p0.md) and its
[machine-readable measurements](../evals/reports/public-p0.json) for the current
published snapshot, evaluated commit, timestamp, category outcomes and targets.
The JSON contains measured values; the Markdown is rendered from that JSON.
Regenerate both by running `.venv/bin/python scripts/render_evaluation_report.py`.

These deterministic results do not measure model accuracy. Earlier live synthetic
learning and Office checks are separate integration evidence; see
[integration scope](../docs/learning-ui.md) and [generation verification](../docs/fastgpt-generation.md).
The public snapshot contains no raw source text, answers, traces or service configuration.

## Limitations and roadmap

Run one API worker on loopback only: Workspace locks are process-local and there
is no account authentication. Python dependencies are not fully pinned, so setup
is documented but not yet an exact reproducible environment. Structural citation
checks cannot guarantee semantic faithfulness. Provider availability and output
vary; unsupported or malformed answers fail closed. See the
[roadmap](../docs/superpowers/plans/2026-08-31-grounded-tutor-implementation-roadmap.md)
for release work and deferred accounts, cloud Workspaces and basic Q&A.

## Security, data and contributions

Read [security and data handling](../docs/security-and-data.md) before live use or
sharing diagnostics, and [contribution guidelines](../CONTRIBUTING.md) before
submitting changes. Raw traces and evaluation reports can contain source text.

## License

Project code is under the [MIT License](../LICENSE). The two original sample documents
have a separate CC0 dedication in their [sample README](../samples/rag-fundamentals/README.md).
Third-party dependencies retain their own licenses.
