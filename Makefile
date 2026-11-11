.PHONY: install format lint typecheck imports test check run openapi openapi-check api-lint \
	api-breaking schemathesis api-check audit download-models test-models docker-build docker-run clean

# bash for `set -o pipefail` in recipes (macOS make 3.81 has no .SHELLFLAGS).
SHELL := bash

# Pinned here, where Dependabot does not look: bump them by hand.
SPECTRAL := npx --yes @stoplight/spectral-cli@6.17.1
PIP_AUDIT := uvx pip-audit@2.10.1
OASDIFF_IMAGE := tufin/oasdiff:v1.35.0
BASE_SPEC := .openapi-base.json
OASDIFF_IGNORE := oasdiff-ignore.txt

install:
	uv sync --locked

format:
	uv run ruff format .

lint:
	uv run ruff check .

typecheck:
	uv run mypy

imports:
	uv run lint-imports

test:
	uv run pytest

# The tests marked `slow` need the downloaded models (make download-models); they fail, not skip,
# when the files are missing. `make check` deselects them.
test-models:
	uv run pytest -m slow tests/test_models.py

# The one command CI runs: format, lint, types, import contracts, tests with coverage, spec drift.
check:
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy
	uv run lint-imports
	uv run coverage run -m pytest
	uv run coverage report
	$(MAKE) openapi-check

run:
	uv run python -m formlens

# openapi.json is generated from the app; never edit it by hand.
openapi:
	uv run python scripts/export_openapi.py

openapi-check:
	uv run python scripts/export_openapi.py --check

api-lint:
	$(SPECTRAL) lint openapi.json --fail-severity=warn

# Compare with the spec on origin/main; breaking changes (errors) fail. Needs oasdiff or Docker.
# Changes listed in $(OASDIFF_IGNORE) are accepted: the example routes the template shipped were
# removed on purpose. Delete the file once this branch is merged into main.
api-breaking:
	@if ! git cat-file -e origin/main:openapi.json 2>/dev/null; then \
		echo "origin/main has no openapi.json yet; skipping the breaking-change check."; exit 0; \
	fi; \
	git show origin/main:openapi.json > $(BASE_SPEC); \
	if command -v oasdiff >/dev/null 2>&1; then \
		oasdiff breaking $(BASE_SPEC) openapi.json --fail-on ERR --err-ignore $(OASDIFF_IGNORE); \
	else \
		docker run --rm -v "$(CURDIR):/spec:ro" $(OASDIFF_IMAGE) \
			breaking /spec/$(BASE_SPEC) /spec/openapi.json --fail-on ERR \
			--err-ignore /spec/$(OASDIFF_IGNORE); \
	fi

# Starts the service, runs Schemathesis with every check and phase, stops the service.
schemathesis:
	scripts/run_schemathesis.sh

api-check: openapi-check api-lint api-breaking schemathesis

# Every dependency group, the contract tooling too. pipefail: a failed export must not pass as
# an empty, clean audit.
audit:
	set -o pipefail; uv export --locked --no-emit-project --all-groups --quiet \
		| $(PIP_AUDIT) --disable-pip -r /dev/stdin

# Downloads the pinned model for VLM_BACKEND (default mlx) into MODELS_PATH (default models/):
# make download-models VLM_BACKEND=transformers
download-models:
	scripts/download_models.sh

docker-build:
	docker build -t formlens:local .

# Needs a .env (cp .env.example .env). HOST and PORT are forced: the server must listen on 0.0.0.0.
# ENVIRONMENT is forced too, as in compose.yaml: --env-file would otherwise replace the image's
# `production` with the `local` of .env.example. -e wins over --env-file.
docker-run:
	docker run --rm -p 8000:8000 --read-only --tmpfs /tmp --env-file .env \
		-e HOST=0.0.0.0 -e PORT=8000 -e ENVIRONMENT=production formlens:local

clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache .hypothesis .import_linter_cache .schemathesis \
		htmlcov .coverage .coverage.* $(BASE_SPEC)
	find . -path ./.venv -prune -o -name __pycache__ -type d -prune -exec rm -rf {} +
