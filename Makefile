.PHONY: api-dev api-test api-lint web-test web-build web-e2e verify-foundation

api-dev:
	.venv/bin/uvicorn grounded_tutor.main:app --app-dir apps/api/src --reload --workers 1

api-test:
	.venv/bin/pytest apps/api/tests -q

api-lint:
	.venv/bin/ruff check apps/api

web-test:
	npm --prefix apps/web test -- --run

web-build:
	npm --prefix apps/web run build

web-e2e:
	npm --prefix apps/web exec playwright test -- --config=apps/web/playwright.config.ts apps/web/tests/foundation.spec.ts

verify-foundation: api-test api-lint web-test web-build web-e2e

.PHONY: verify-trust
verify-trust:
	bash scripts/check_public_files.sh
	$(MAKE) api-test api-lint web-test web-build
	.venv/bin/python -m grounded_tutor.evaluation.runner --cases evals/cases/p0.jsonl --output evals/reports/local.json
	.venv/bin/python scripts/summarize_evaluation.py evals/reports/local.json evals/reports/summary.json
	git diff --check
	git diff --cached --check

.PHONY: verify-learning
verify-learning: verify-trust
	.venv/bin/python -m grounded_tutor.evaluation.learning --cases evals/cases/learning.jsonl --output evals/reports/learning-local.json
	npm --prefix apps/web exec playwright test -- --config=apps/web/playwright.config.ts

.PHONY: test-live
test-live:
	.venv/bin/python scripts/test_live.py

.PHONY: release-check
release-check: export RUN_LIVE_INTEGRATION=0
release-check: export EXTERNAL_MODE=fake
release-check: export DEMO_READ_ONLY=false
release-check: export ENABLE_LOCAL_ADMIN=false
release-check: verify-learning
	.venv/bin/python -c 'from grounded_tutor.main import app; assert app.title == "Grounded Tutor API"'
	.venv/bin/python scripts/render_evaluation_report.py --check
	bash scripts/check_secrets.sh
	git diff --check
	git diff --cached --check
