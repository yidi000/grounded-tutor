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
