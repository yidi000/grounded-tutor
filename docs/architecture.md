# Architecture

The desktop Evidence Notebook is a React/Vite client. Its local development server
proxies API requests to FastAPI. The API owns Workspace isolation, idempotent writes,
source approval, grounding checks and the learning state machine.

SQLite is the product database: it stores Workspaces, source versions, conversations,
answer blocks and citation snapshots, diagnostics, plans, lessons, checks, attempts
and activity checkpoints. FastGPT is an external document/retrieval service, not
conversation storage. Each Workspace maps to a Dataset; sources map to Collections.
New material is processed and reviewed before local READY status permits retrieval.

ASK searches the Workspace dataset, filters candidates against locally eligible
sources, sends evidence and a code-owned output contract to the generator, validates
structured output and citations, then saves the exchange. The generator may be a
separate model endpoint or a dedicated FastGPT application. Its workflow should not
perform another search, call tools or retain history. See
[generation configuration](fastgpt-generation.md).

The optional learning loop uses consented diagnostics, a finite plan, cited lessons
and deterministic checks. Server-only answer keys are not sent with unanswered
questions. ASK interruptions preserve a resumable checkpoint; reloads restore saved
state rather than generating a replacement. See [learning UI](learning-ui.md).

Fake adapters replace external providers for development; Playwright's test server
adds deterministic learning fixtures. The read-only demo uses fixed frontend data.
Neither provides evidence of live model intelligence. New product state is persisted
locally, while fake provider collections disappear on process restart.

The supported deployment is one local API process/worker. Locks are in memory,
there is no user authentication, and Workspace isolation is not account authorization.
Accounts, distributed locking and cloud deployment need separate design. Migrations
run explicitly with Alembic; startup checks that the schema is current.
