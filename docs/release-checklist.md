# Local release readiness

This checklist prepares a local release candidate. It does not authorize remote
creation, push, visibility changes, GitHub Pages deployment or public publication.
The application is still a local single-user prototype with images disabled.

## Gate

Stage the intended changes, then run `make release-check` from the repository root.
The target forces `EXTERNAL_MODE=fake` and `RUN_LIVE_INTEGRATION=0`, disables local
administration and keeps API read-only mode off for isolated behavior tests.
No live service calls are part of this gate.

- `verify-learning` includes backend/release/sample/baseline tests, Ruff, frontend
  tests, production build, the 40 ASK and 8 learning evaluations and desktop E2E.
- The API import smoke check verifies module initialization, not full deployment.
- `render_evaluation_report.py --check` checks the saved JSON-to-Markdown snapshot
  without modifying it. The saved public report is dated and may describe an
  earlier evaluated commit; fresh evaluations above do not silently rewrite it.
- `check_secrets.sh` scans full Git history and both staged and working tracked
  snapshots with redacted Gitleaks output. Ignored local files are not exported.
  The existing public-file guard checks known local private values separately.
- Whitespace checks inspect staged and unstaged diffs.

Use Gitleaks 8.30.1 on PATH, or Docker for the pinned `v8.30.1` fallback. The fallback
mounts the worktree and common Git directory read-only to support worktrees.
The only rule exception is the exact historical BTB classification branch `key`
line in `fastgpt/baseline.sanitized.json`, under the generic-key rule. It is a graph
identifier with an edge reference, not a credential. Default rules remain enabled;
an actual scanner probe confirmed that another API-key line in that file is blocked.

No scanner available, Docker unavailable, or a secret finding means failure, never
an implicit skip. Scanners do not prove the absence of all sensitive information.

CI installs Chrome with its OS dependencies because Playwright selects the Chrome
channel. Its workflow has read-only repository permissions, full checkout history
and no provider credentials. Only a restricted numeric evaluation summary is uploaded;
raw traces and browser failure artifacts remain unshared. Hosted CI has not run yet.

## Checks before publication

- [x] Run the complete local release gate on the staged candidate.
- [x] Verify installation in a fresh directory without copying real `.env` or databases.
- [x] Inspect Git history and remotes; no remote is configured. Final status is checked after commit.
- [x] Verify the built read-only demo reset, no-write proof, base path and local-setup link locally.
- [ ] Repeat those checks at the real hosted URL after approved deployment.
- [ ] Obtain the owner's exact account/organization, repository name and visibility.
- [ ] Obtain explicit authorization before creating a remote, pushing or deploying.
- [ ] After publication: verify CI/Pages, clean clone and the actual deployed URL.

Deterministic demo packaging is now included. Pages remains inactive until explicit
publication approval, repository setup and `DEMO_PAGES_APPROVED=true`. Build jobs
also check the actual default branch. Root/custom-domain and repository paths use
Pages metadata; nested path behavior has been verified locally. Accounts and cloud
Workspaces remain deferred.

## Local evidence (2026-09-08)

`make release-check` exited 0: 958 backend tests passed, 7 opted-out live tests
skipped, 58 frontend tests passed, all 48 deterministic cases passed, and desktop
E2E had 14 passed with 14 deliberate mode/project skips. Production build, API
import, saved report consistency and whitespace checks passed. Gitleaks 8.30.1
scanned 54 historical commits and both tracked snapshots without unresolved findings.
The single graph-identifier false positive was independently reviewed; a real
scanner positive/negative probe confirmed the narrow exception does not hide a
synthetic API credential in the same file.

A tracked-only temporary clone was overlaid with the staged candidate and given
fresh Python and npm dependencies. With a new example-only config, migrations,
API startup, 958 backend tests, 58 frontend tests and production build passed.
This local run used Python 3.13.12 and Node 25.9.0; configured hosted CI uses Python
3.12 and Node 24 and has not executed yet. Python dependencies are not fully locked.
The Docker fallback was syntax/review checked; actual local scans used the native
checksum-verified binary because Docker was not running.

GitHub CLI authentication was not verified. No remote, repository, push, Pages
configuration or publication was created. The static demo packaging follow-up below completes the local artifact; repository
details and explicit publication approval are still required.

## Static demo package

The fixed Chinese RAG fixture is version `rag-demo-v1`, recursively frozen, with
explicit CC0 provenance and resolvable citations. Production-build browser tests
run on 1280×720 and 1440×900 at `/grounded-demo/`, checking citations, reload reset,
empty local/session storage, no API or write requests, and setup-page round trips.
`release-check` now includes these tests after the existing local/demo journeys.

The Pages workflow uses official pinned actions, a Node 24 build, lockfile install,
unit and static browser tests before building the actual Pages base path. The build
job has read-only content/Pages permissions; only deployment gets Pages write and
OIDC permissions. Concurrency is separated by branch. Jobs require both the explicit
`DEMO_PAGES_APPROVED=true` variable and the actual default branch. Only `apps/web/dist`
is uploaded, without provider credentials. No workflow has been enabled or deployed.

After publication is explicitly approved, configure Pages with GitHub Actions as
its source and set the approval variable. Repository name, owner, visibility and
Git authentication must be confirmed first. The final hosted URL, root/custom-domain
behavior and hosted CI remain to be verified after deployment. See the official
[Vite Pages guide](https://vite.dev/guide/static-deploy.html#github-pages) and
[Pages configuration action](https://github.com/actions/configure-pages).

Final local package gate (2026-09-08): exit 0, 960 backend passed/7 live skipped,
60 frontend passed, 48 deterministic cases passed, 14 existing desktop journeys
passed/14 mode skips, and 2 static-demo journeys passed. Gitleaks history plus
staged/working tracked snapshots, API import, report check and build passed.
Independent review passed after fixing cross-branch deployment cancellation.

## Source-only release candidate (2026-09-08)

The owner selected source distribution for local deployment only. No hosted
service or Pages deployment is in scope; keep DEMO_PAGES_APPROVED unset.

The candidate includes the limestone/burgundy desktop redesign, confirmed topic
deletion with scoped cloud/local cleanup, and isolated E2E ports. Temporary
Impeccable images and question state are ignored; PRODUCT.md and DESIGN.md record
the approved product and design direction.

Fresh `make release-check` exited 0: backend980 passed/7 opted-out live skips,
frontend69 passed, 40 ASK and8 learning evaluations passed, desktop18 passed
with18 cross-mode skips, and2 static-demo browser tests passed. Ruff, production
build, API import, report consistency and staged/working whitespace checks passed.
Gitleaks8.30.1 scanned57 historical commits plus staged and working tracked
snapshots without findings. The public-file guard reported0 blocked entries.

These checks are deterministic and do not make new live-model quality claims.
GitHub remote creation, push and hosted CI remain outside this local commit step.

A clean source export used fresh Python3.13.12 dependencies, template-only fake
settings and a new SQLite database: all11 migrations, API import, CRUD smoke and
8 deletion tests passed. Fresh npm installation initially exposed undeclared
Node typings (TS2591). Added pinned @types/node24.13.3 and explicit Node types;
a second clean npm ci and cache-free production build passed. Frontend69 tests
and forced TypeScript rebuild also passed after that fix; secret scans were
repeated successfully. The available host used Node25.9.0/npm11.12.1, so Node24
specifically remains unverified locally. No real configuration or database was
copied into the clean export.
