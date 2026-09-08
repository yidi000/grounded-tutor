# Grounded Tutor

A desktop-first evidence notebook for learners studying their own documents.
It connects questions, explanations and short checks to inspectable source text,
so the learner can examine where an answer came from.

## Capabilities

Create topic Workspaces; import files or paste text; review and accept processed
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
See [architecture](docs/architecture.md).

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
Workspace, add the [original sample material](samples/rag-fundamentals/README.md),
review processing and accept it. Fake providers produce deterministic fixture
responses, not meaningful AI answers, and their remote-like state is in memory.
Use live mode to study real documents; fake mode is for interface exploration.

For the fixed read-only frontend demonstration, no backend is needed:

```sh
VITE_APP_MODE=demo_read_only npm --prefix apps/web run dev -- --host 127.0.0.1 --port 5173
```

This starts a local demo. Public hosting and its local-setup handoff are still
release work; no deployed demo URL is promised here.

## Live FastGPT and model-provider setup

Edit only your ignored `apps/api/.env`: set `EXTERNAL_MODE=live`, your FastGPT
service origin and key, and the generation endpoint, key and model. Restart the
API after configuration changes. Existing sources in fake mode do not provision
real cloud datasets; use a new Workspace for live material.

The generator can be a dedicated FastGPT application or another compatible
endpoint. For FastGPT, select the actual model in that application's workflow,
keep history zero and tools disabled, and use the versioned structured prompt.
Follow [the exact generation setup](docs/fastgpt-generation.md). Keep images off.
Never place keys in frontend variables, tracked files or browser screenshots.

## Testing

```sh
npm --prefix apps/web exec playwright install chromium
make verify-learning
```

The gate runs backend tests, Ruff, frontend tests/build, 40 ASK evaluations,
8 learning evaluations and desktop Playwright journeys. Browser dependencies may
need installation on Linux. CI currently runs the trust gate and secret scan;
the full learning gate is a local check. Live probes are opt-in and incur external
service calls; see [evaluation](docs/evaluation.md).

## Target thresholds

Deterministic citation coverage, refusal, replay and journey ratios must equal 1;
workspace leakage and unauthorized provider-call counts must equal 0. These are
software acceptance targets, not claims of model accuracy. Definitions and the
48-case inventory are in [evaluation](docs/evaluation.md).

## Measured results

The 2026-09-08 learning integration checkpoint (`802324e`) passed 40 ASK and
8 learning evaluation cases, 58 frontend tests and 14 desktop E2E tests; 14 E2E
cases were intentionally skipped for non-applicable project/mode combinations.
Live synthetic learning probes passed twice with the published generator,
including a run using default HTTP timeouts. Office regression passed 4 tests
with 1 image test skipped. See [integration scope](docs/learning-ui.md).
These are dated development observations, not a published reproducibility report
or proof of teaching quality. Release report packaging remains a later task.

## Limitations and roadmap

Run one API worker on loopback only: Workspace locks are process-local and there
is no account authentication. Python dependencies are not fully pinned, so setup
is documented but not yet an exact reproducible environment. Structural citation
checks cannot guarantee semantic faithfulness. Provider availability and output
vary; unsupported or malformed answers fail closed. See the
[roadmap](docs/superpowers/plans/2026-08-31-grounded-tutor-implementation-roadmap.md)
for release work and deferred accounts, cloud Workspaces and basic Q&A.

## Security, data and contributions

Read [security and data handling](docs/security-and-data.md) before live use or
sharing diagnostics, and [contribution guidelines](CONTRIBUTING.md) before
submitting changes. Raw traces and evaluation reports can contain source text.

## License

Project code is under the [MIT License](LICENSE). The two original sample documents
have a separate CC0 dedication in their [sample README](samples/rag-fundamentals/README.md).
Third-party dependencies retain their own licenses.
