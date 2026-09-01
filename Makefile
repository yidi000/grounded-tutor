.PHONY: api-test api-lint web-test web-build verify-foundation

api-test:
	.venv/bin/pytest apps/api/tests -q

api-lint:
	.venv/bin/ruff check apps/api

web-test:
	npm --prefix apps/web test -- --run

web-build:
	npm --prefix apps/web run build

verify-foundation: api-test api-lint web-test web-build
