# fastapi-szumplate

FastAPI service. Python 3.15, uv, Ruff, mypy (strict), pytest.

## Commands

- `make check` is the gate: Ruff format check, Ruff lint, mypy, import contracts, tests with
  coverage, OpenAPI drift. Run it before every commit.
- `make run` starts the service (`python -m fastapi_szumplate`). Tests use `uv run pytest`.
- `make openapi` regenerates `openapi.json`. It is generated from the app; never edit it by hand.
  Commit it with any change that alters the API.
- `make api-check` runs Spectral, oasdiff and Schemathesis (needs Node, Docker or oasdiff).
- Add dependencies with `uv add` (runtime) or `uv add --group test|dev|api`, and commit `uv.lock`.
- `make audit` runs pip-audit on every locked dependency group.
- One test: `uv run pytest tests/test_problems.py::test_name`. Order is random (pytest-randomly);
  `-p no:randomly` replays it in file order. Warnings are errors (`filterwarnings = ["error"]`).

## Layout

- Service core: `config.py`, `logging_config.py`, `middleware.py`, `problems.py`, `openapi.py`,
  `types.py`, `pagination.py`, `query.py`, `health/`.
<!-- begin:example -->
- Example domain: `src/fastapi_szumplate/library/` and `tests/library/`, mounted by one
  `include_library(app)` call in `main.py`. Nothing else may import `library`. Remove it with
  `docs/how-to/remove-the-example.md`.
- `books` uses the default module shape; `loans` is hexagonal.
<!-- end:example -->
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
- Tests build settings with `Settings(_env_file=None)` (see `tests/conftest.py: make_settings`),
  replace dependencies with `app.dependency_overrides` (cleared afterwards by the `app` fixture)
  and build data with factories, setting every value the test asserts on.
  The example's factories are in `tests/library/factories.py`. <!-- only:example -->
- Tests of the core use `/health` and the probe routes of `tests/probes.py` (fixture
  `probe_app`).
  They never call the example's routes, so they survive removing the example; <!-- only:example -->
  `tests/library/` holds the example-bound ones. <!-- only:example -->
  `make smoke-template` proves a copy without the example passes `make check`. <!-- only:template -->
- Logging: structlog, constant event names, snake_case fields, no f-strings, no `print`. Log a
  handled error once, where it is handled. Never log secrets; the `redact` processor is a safety
  net, not a licence.
- Route docstrings: summary and consumer prose only, no `Args:`/`Returns:` sections.
- Do not lower `fail_under` in `pyproject.toml`. Do not skip or delete a failing test to get green.
- Commit messages follow Conventional Commits: `type(scope): imperative summary`.

## Gotchas

- The uv version is pinned twice: the `uv` image in `Dockerfile` and `UV_VERSION` in
  `.github/workflows/ci.yml` (`tests/test_tooling.py` checks they match). Dependabot does not
  bump the Spectral, oasdiff and pip-audit pins in `Makefile`.
- `README.md` must name every make target (`tests/test_docs.py`).
- `uv run --python 3.15t` replaces `.venv` with the free-threaded build; `uv sync` restores it.
<!-- begin:template -->
- A line ending in an audience marker (`only:template`, `begin:example` … `end:example`, also as
  `# ...` outside Markdown) is kept or dropped by `scripts/init_project.py` in a project copy.
  Text that names the example (library, book, loan, isbn) must sit inside an `example` block,
  or `make smoke-template` fails its reference check.
- `tests/test_init_project.py` and `make smoke-template` copy tracked and untracked
  (not ignored) files, so a stray file in the repo root can fail them. Move it out first.
<!-- end:template -->
