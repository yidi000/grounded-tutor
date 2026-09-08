# Limestone and burgundy desktop review

Implemented selected palette 2 with a persistent topic rail and facing reading
columns. Shared CSS changes cover conversation, citation, source wizard, empty
states and learning. Font is self-hosted Noto Serif SC 600 for headings; body/UI
remain Noto Sans SC. No new dependencies or API behavior changes.

Validation on 2026-09-08:
- Frontend: 63 tests passed; production build passed.
- Desktop E2E: 16 passed, 16 intentional cross-mode skips, 1280×720/1440×900.
- Static production demo: 2 passed, including repository base path/no writes.
- Impeccable detector: completed, no emitted findings for apps/web/src.
- Independent visual reviewer inspected synthetic citation, demo, custom settings
  and pending preview captures; no blocking layout/typography regressions found.
- Palette contrast: ink/paper 13.33:1; burgundy/paper 8.15:1;
  secondary text/paper 5.28:1; secondary text/citation tint 5.27:1.
- git diff --check passed.

The first isolated E2E attempt exposed hard-coded API port 8000 in the learning
fixture, while the temporary test server used 8018. The temporary test fixture
was aligned with 8018 for the passing rerun and restored afterward. No test
behavior changes are shipped. Source upload/review, citation focus restoration,
history isolation, learning detours/recovery and failed-import retry passed.

Scope: desktop only, light theme only. This is not a complete WCAG certification
or a fresh live FastGPT/back-end release gate. No backend changes were made.
The browser mockups were direction references; inactive decorative mode tabs were
not added. Existing contextual learning actions remain functional.

Publication is separate: no remote/push/deployment performed. Before publication,
run the full release gate on the final candidate and verify actual hosted CI,
Pages and a clean clone. Pages is a read-only demo, not hosted model-backed chat.
