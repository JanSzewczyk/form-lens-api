# formlens

FastAPI service. Python 3.15, uv, Ruff, mypy (strict), pytest.

## Commands

- `make check` is the gate: Ruff format check, Ruff lint, mypy, import contracts, tests with
  coverage, OpenAPI drift. Run it before every commit.
- `make run` starts the service (`python -m formlens`). Tests use `uv run pytest`.
- `make migrate` creates or updates the SQLite database of `DB_URL` (`python -m formlens migrate`). The service
  refuses to start on a database that is not at head; it never creates tables. A change to a table is a change
  to `src/formlens/migrations/versions/v0001_initial.py` (Stage 2 is unreleased, so 0001 grows in place) **until
  the first merge to `main` or the first deploy; from then on every table change is a NEW revision** and 0001 is
  never edited again. While 0001 still grows, a database file migrated before a pull has the old 0001 and Alembic
  will not notice: after pulling a branch that edited 0001, delete your local `formlens.db` (and its `-wal` and
  `-shm` files) and run `make migrate` on a fresh file. The migration test compares the migrated schema with
  the models.
- `make evaluate` runs the golden set (`tests/golden/`) against the real document model and Ollama; it stops
  with a message when either is missing. Never invent its numbers: the README's Accuracy section says "not
  measured yet" until someone has run it.
- `make openapi` regenerates `openapi.json`. It is generated from the app; never edit it by hand.
  Commit it with any change that alters the API.
- `make api-check` runs Spectral, oasdiff and Schemathesis (needs Node, Docker or oasdiff).
- `make download-models` downloads the pinned model for `VLM_BACKEND` into `MODELS_PATH` (network,
  uv, about 0.6 GB). The script asks `scripts/resolve_model.py`, which reads the two settings
  through `ModelSettings` like the service does: environment and `make` variables, then `.env` in
  the working directory, then the defaults. It runs `uv run --no-sync`, so `make install` comes
  first: `make download-models VLM_BACKEND=transformers MODELS_PATH=/data/models`.
- `make test-models` runs the tests marked `slow` and fails, not skips, when the pinned model files
  are missing or Ollama does not answer. The default `addopts` is `-m "not slow"`, so `make check` and `uv run pytest`
  deselect them.
- Add dependencies with `uv add` (runtime) or `uv add --group test|dev|api`, and commit `uv.lock`.
- `make audit` runs pip-audit on every locked dependency group.
- `make docker-build` builds the image; `make docker-run` runs it (needs a `.env`, copy `.env.example`).
  `make clean` removes caches and generated files.
- One test: `uv run pytest tests/test_problems.py::test_name`. Order is random (pytest-randomly);
  `-p no:randomly` replays it in file order. Warnings are errors (`filterwarnings = ["error"]`).

## Layout

- Service core: `config.py`, `modelspec.py` (the pinned model repositories, revisions and files),
  `logging_config.py`, `middleware.py`, `problems.py`, `openapi.py`,
  `types.py`, `pagination.py`, `query.py`, `health/`.
- `parsing/`: the first domain module (`POST /v1/documents/parse`). `docling_parser.py` is the only
  module that imports Docling, inside `build_docling_parser`, and only `main.py` imports it; the rest
  works against the `DocumentParser` port, with `tests/fakes.py: FakeParser`. Import contracts enforce
  both. `tests/schemathesis_app.py` is the app `make schemathesis` fuzzes (fake parser).
- `database.py` (the SQLite engine: WAL, `BEGIN IMMEDIATE` for writes, `UtcDateTime`), `patterns.py` (client
  regular expressions in a linear-time engine: lookaround and backreferences are refused) and `migrations/`
  (Alembic inside the package, no `alembic.ini`, never `fileConfig`).
- `templates/`: default shape (`/v1/templates`). Invariants raise `InvalidTemplate` when an object is built;
  `json_schema.py` generates the schema; `repository.py` is the only SQL besides `extractions/adapters/`.
- `extractions/`: hexagonal. `domain/` (stdlib only: `Extraction` transitions, ports, errors), `service_layer/`
  (`ExtractionService`, `ExtractionProcessor.run_once`), `adapters/` (SQLite repository, Ollama extractor, Docling
  text, template catalog, `ThreadDeadline`), `entrypoints/` (routes, worker). Import contracts keep the domain and
  service layer free of frameworks and adapters, `httpx2` and `jsonschema` in `ollama_extractor.py`, SQLAlchemy in
  `database`, `migrations`, `templates.repository|tables` and `extractions.adapters`. Fakes and factories are in
  `tests/extractions/`; the Schemathesis app uses a fake extractor with the worker off.
- Add structure to a module only when it hurts (see `docs/explanation/architecture.md`).
  New modules start like `docs/how-to/add-a-module.md` says.

## Rules for changes

- A route parses, calls one service method and leaves errors to the registered handler. Rules live
  in the domain object or the service, not in routes.
- Every route has an explicit `operation_id`, a response model and `responses` for each status it
  returns (`problem_response(...)`). Routes with input document 422; routes with a JSON body also
  document 400.
- Every error is Problem Details. A new domain error gets its own `ProblemType` and a row in
  `docs/reference/problem-types.md` (a test checks this).
- A request that stored state forbids is 409, not 422. Guard a check-then-write rule atomically
  and add a parallel test with the `concurrency` marker; remove the guard once and confirm the
  test fails, running the mutant from a copy and printing the package `__file__` first.
- Tests build settings with `Settings(_env_file=None)` (see `tests/conftest.py: make_settings`) and
  replace dependencies with `app.dependency_overrides` (cleared afterwards by the `app` fixture).
  Build data with the factories (`tests/templates/factories.py`, `tests/extractions/factories.py`) and set every
  value the test asserts on.
- The autouse fixture `_isolate_from_exported_settings` (`tests/conftest.py`) deletes every setting
  from the environment for each test, so an exported `DOCS_ENABLED` cannot leak in. Tests marked
  `slow` are exempt: they read `MODELS_PATH`, `VLM_BACKEND`, `LLM_BASE_URL` and `LLM_MODEL` from the environment
  and `.env`. Every test that starts the app gets a private migrated database through the `db_url` fixture and
  `start_worker=False` with a fake extractor; none may touch `./formlens.db`.
- Tests of the core use `/health` and the probe routes of `tests/probes.py` (fixture
  `probe_app`).
- Logging: structlog, constant event names, snake_case fields, no f-strings, no `print`. Log a
  handled error once, where it is handled. Never log secrets; the `redact` processor is a safety
  net, not a licence.
- Route docstrings: summary and consumer prose only, no `Args:`/`Returns:` sections.
- Do not lower `fail_under` in `pyproject.toml`. Do not skip or delete a failing test to get green.
- Commit messages follow Conventional Commits: `type(scope): imperative summary`.

## Gotchas

- A client `pattern` must stay in `patterns.py`: Python's `re` takes exponential time on `(a+)+$`, and a thread
  stuck in it cannot be stopped, so one template could stop the queue for good.
- A single-transaction read-then-write under `BEGIN IMMEDIATE` is also correct on SQLite, so only a mutant that
  splits the read and the write goes red; do not claim the conditional `UPDATE` alone is proven.
- The Ollama request fields were never checked against a real Ollama; `docs/how-to/run-the-llm.md` says so.

- The uv version is pinned three times: the `uv` image in `Dockerfile` and `UV_VERSION` in
  `.github/workflows/ci.yml` and `release.yml` (`tests/test_tooling.py` checks they match). Dependabot does not
  bump the Spectral, oasdiff and pip-audit pins in `Makefile`.
- `README.md` must name every make target (`tests/test_docs.py`).
- The model downloader is pinned in `scripts/download_models.sh` (`uvx --from huggingface_hub==2.4.0 hf`).
  Dependabot does not bump it, and it runs outside `uv.lock`, so `make audit` does not see it or its
  dependencies (see `docs/licenses.md`). Bump it by hand.
- `torch` and `torchvision` are direct dependencies with a CPU index on Linux (`[tool.uv.sources]`);
  pip-audit skips the `+cpu` local version, so `make audit` strips it. A `torch` bump needs the version
  on both PyPI and the PyTorch CPU index.
- CI jobs `check` (`make check`) and `audit` (`make audit`) are separate, so a new advisory does not
  hide the code checks. Branch protection lists them by name (`Check ✅`, `Audit 🔒`); renaming one
  leaves pull requests waiting for a status that never arrives.
- `uv run --python 3.15t` replaces `.venv` with the free-threaded build; `uv sync` restores it.
