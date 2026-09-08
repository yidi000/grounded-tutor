# Trust verification

Run from the repository root after installing the API test dependencies and running
`npm --prefix apps/web ci`:

```sh
make verify-trust
```

The gate stops on the first failure and runs, in order:

1. Public-file check against both staged blobs and current tracked files.
2. Backend tests, Ruff, frontend tests and the frontend production build.
3. All 40 deterministic evaluation cases and their acceptance targets.
4. Numeric-only evaluation summary, then unstaged and staged whitespace checks.

The public-file guard rejects `.env`/`.env.*`, unapproved evaluation reports,
nonempty report placeholders, symlinks/submodules/unmerged entries, FastGPT-shaped
keys and bearer tokens of credential length. It also searches exact sensitive values
from the process environment, root `.env` and `apps/api/.env`, including private
Dataset/App IDs and both parts of FastGPT `key-appId` credentials. It never sources
an environment file or prints matches/filenames. Short synthetic tokens such as the
adapter tests' `Bearer secret` are permitted unless present in local sensitive
configuration. This fixed-pattern guard complements the broader historical scan;
it is not proof that every possible credential format is absent.

Exit codes for the guard: 0 clean, 1 blocked entries, 2 unable to complete. Stage new
files before the final gate; untracked files are not publication candidates yet.
Only the empty `evals/reports/.gitkeep` is approved for tracking. Additional public
reports require an explicit filename exception and content review.

GitHub Actions runs the same gate on pushes and pull requests using Python 3.12 and
Node 24, with pip/npm caches and read-only repository permissions. There are no live
FastGPT/LLM secrets in either workflow. Only `evals/reports/summary.json` is uploaded
on success: a fixed set of numeric counts and metrics. Full evaluation reports,
source inputs, exception text, browser traces and database files are not uploaded.
The summary writer rejects non-numeric values before writing. See the official
[setup-node](https://github.com/actions/setup-node) and
[artifact action](https://github.com/actions/upload-artifact) documentation.

The separate secret-scan workflow fetches complete history and runs pinned Gitleaks
8.30.1 against all refs with full output redaction. It uses the official container,
requires no Gitleaks action license, and does not upload a findings artifact or post
PR comments. [Gitleaks usage](https://github.com/gitleaks/gitleaks#usage).
For an installed native copy, the equivalent local scan is:

```sh
gitleaks git . --log-opts=--all --redact=100 --no-banner
```

`verify-trust` itself does not require Docker or Gitleaks locally. The newer
`release-check` gate includes `verify-learning`, desktop E2E, public report
consistency and the shared history/index/worktree secret scan. CI is now configured
for that release gate; the separate secret-scan job also uses the shared script.
See [release readiness](release-checklist.md). GitHub-hosted execution must still
be checked after an authorized push; these files do not configure branch protection.
