.PHONY: install format lint typecheck imports test check run migrate evaluate openapi openapi-check api-lint \
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

# The tests marked `slow` need the downloaded models (make download-models) and, for the extraction, a running
# Ollama with LLM_MODEL pulled: the model files check, the real model through the app, the offline check and the
# end-to-end extraction. They fail, not skip, when a model is missing or Ollama does not answer.
# `make check` deselects them.
test-models:
	uv run pytest -m slow

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

# Creates or updates the tables of DB_URL (default sqlite:///./formlens.db). The service refuses to
# start on a database that is not at the newest revision.
migrate:
	uv run python -m formlens migrate

# Reads the 48 synthetic documents of tests/golden/ with the real document model and the local model, and prints
# how many fields it got right and how many empty fields it filled anyway. Needs `make download-models` and a
# running Ollama with LLM_MODEL pulled (docs/how-to/run-the-llm.md); it stops with a message when either is
# missing. The parsed texts are cached in .golden/, so a new prompt or model does not parse again.
evaluate:
	uv run python -m tests.golden.evaluate

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
# an empty, clean audit. On Linux the lock pins torch and torchvision as `2.15.0+cpu`, a local version
# that is not on PyPI, so pip-audit would skip them and still exit 0; sed drops the `+cpu` so the same
# release on PyPI is audited (the advisories name the release, not the build).
audit:
	set -o pipefail; uv export --locked --no-emit-project --all-groups --quiet \
		| sed 's/+cpu / /' \
		| $(PIP_AUDIT) --disable-pip -r /dev/stdin

# Downloads the pinned model for VLM_BACKEND (default mlx) into MODELS_PATH (default models/). Both
# are read like the service reads them: the environment, then .env, then the defaults.
# make download-models VLM_BACKEND=transformers
download-models:
	scripts/download_models.sh

docker-build:
	docker build -t formlens:local .

# Needs a .env (cp .env.example .env) and the transformers model (make download-models
# VLM_BACKEND=transformers), mounted read-only; MODELS_PATH (default models/) names the host folder.
# HOST, PORT, ENVIRONMENT, VLM_BACKEND, MODELS_PATH and DB_URL are forced: the server must listen on 0.0.0.0,
# --env-file would replace the image's `production` with the `local` of .env.example, `mlx` does not
# run in a Linux container, the container sees the model at /models and the database at /data (the named
# volume formlens-data). The container migrates the database before it serves. Ollama runs on the host:
# LLM_BASE_URL defaults to host.docker.internal, which --add-host makes work on Linux too. -e wins over --env-file.
docker-run:
	docker run --rm -p 8000:8000 --read-only --tmpfs /tmp --env-file .env \
		--volume "$(abspath $(or $(MODELS_PATH),models)):/models:ro" \
		--volume formlens-data:/data --add-host host.docker.internal:host-gateway \
		-e HOST=0.0.0.0 -e PORT=8000 -e ENVIRONMENT=production \
		-e VLM_BACKEND=transformers -e MODELS_PATH=/models \
		-e DB_URL=sqlite:////data/formlens.db \
		-e LLM_BASE_URL=$(or $(LLM_BASE_URL),http://host.docker.internal:11434/v1) formlens:local

clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache .hypothesis .import_linter_cache .schemathesis \
		htmlcov .coverage .coverage.* $(BASE_SPEC)
	find . -path ./.venv -prune -o -name __pycache__ -type d -prune -exec rm -rf {} +
