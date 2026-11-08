# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

<!-- begin:template -->
### Added

- Typed settings (`ENVIRONMENT`, `LOG_LEVEL`, `LOG_FORMAT`, `DOCS_ENABLED`, `CORS_ORIGINS`, server
  binding, paging and example-domain limits) with a documented `.env.example`.
- Structured logging with structlog on stdlib: JSON or console output, key redaction, one access
  log line per request and an `X-Request-ID` header bound to every log line.
- `python -m fastapi_szumplate` entry point.
- Problem Details (RFC 9457) for every error: 404, 405 with `Allow`, validation (only `loc`, `msg`,
  `type`), 400 and a generic 500; one stable `type` per domain error.
- Generated, committed and drift-checked `openapi.json`; contract tests for it; Spectral rules,
  oasdiff and Schemathesis targets.
- Liveness (`/health`) and readiness (`/health/ready`) endpoints.
- Example domain under `library/` (books and loans) with six rules, atomic guards and parallel
  tests; in-memory repositories behind ports with a shared contract suite.
- import-linter contracts for module boundaries.
- OpenAPI links from the create operations to the get, update, lend and return operations, and a
  `schemathesis.toml`, so stateful Schemathesis reaches the operations that need an id.
- Multi-stage Dockerfile, `compose.yaml` and Dependabot.
- CI jobs for the contract tooling, the image, a template smoke test and an informational
  free-threaded Python run.
- `scripts/init_project.py` to rename a copy and optionally remove the example.
- Documentation: how-to guides, problem type reference and architecture notes.

### Fixed

- Logged tracebacks no longer include local variables: a frame's `scope` holds the request
  headers, `Authorization` included. The console format uses the plain traceback formatter.
- A 500 now carries the `X-Request-ID` header and the CORS headers: the catch-all moved from
  Starlette's outermost middleware into `UnhandledErrorMiddleware`, and the traceback is logged
  once, on the `request_completed` line.
- The ISBN pattern is `^[0-9]{13}$`: non-ASCII digits (Arabic-Indic, fullwidth) were accepted
  because the regex engine reads `\d` as any Unicode digit, so one ISBN could be stored twice.
- A refused CORS preflight is a Problem Details 400, not plain text.
- A JSON body with an integer of more than 4300 digits is a 422 `json_invalid`, not a 400. Only
  FastAPI's own body-parsing 400 is reclassified: a 400 that application code raises from a
  `ValueError` keeps its status and detail.
- A request that fails after its response started is logged at `error` with `aborted_by`, not as
  an `info` line with the status that was sent.
- Key redaction also masks read-only mappings (Starlette `Headers`, `QueryParams`) and mappings
  inside lists and tuples.
- An `HTTPException` with a status that forbids content (204, 205, 304) has no body; one with a
  status `http.HTTPStatus` does not know (499) keeps it instead of turning into a 500; a detail
  that is not text is left out instead of being stringified.
- `make openapi-check` no longer depends on environment variables such as `APP_NAME`.
- `init_project.py --without-example` keeps a `pyproject.toml` table placed after the
  import-linter contracts.

### Changed

- Dependency floors raised to the locked versions; CI actions pinned to verified versions.
- Coverage threshold raised from 90 to 95.
- uvicorn no longer sends a `server` header and gives open requests `GRACEFUL_SHUTDOWN_SECONDS`
  (20) after SIGTERM instead of waiting without limit.
- Records below the log level are dropped before any processor runs; stdlib records keep their
  `extra=` fields (redacted like the rest).
- The OpenAPI `servers` entry is relative (`/`), so the docs call the host that serves them.
- Stricter tooling: mypy `warn_unreachable` with nine extra error codes and the Pydantic plugin's
  strict init; pytest `strict` mode with warnings as errors and required plugins; Ruff adds the
  RUF, FAST, ASYNC, BLE, C4, SIM, RET, PIE, PERF, PGH, RSE, FLY, ISC, A, PLE, PLW, ARG, DTZ and TRY
  families and formats code in docstrings.
- Import contracts layer the core (entry point, factory, features, foundations) and keep uvicorn
  in the entry point; they replace the "core never imports the factory" contract.
- Packaging: `license = "MIT"` with the licence file in the wheel, a `Private :: Do Not Upload`
  classifier, a `fastapi-szumplate` console script, a bounded hatchling and a minimum uv version.
  Coverage also measures `scripts/`.
- CI: actions pinned to exact versions, runs on pushes to `main`, pull requests and on demand (a
  pull request commit is no longer tested twice), the weekly run no longer cancels a push run,
  jobs have timeouts and checkouts keep no credentials. The image job builds with Buildx and the
  GitHub Actions cache and waits for the image's own HEALTHCHECK to report `healthy`; the check
  job writes the coverage table to the job summary.
- The image: the build context is an allowlist, `LICENSE` reaches the package metadata, the
  virtual environment is owned by root, the user is numeric (`10001:10001`) and the health check
  probes every 2 s while the container starts. `compose.yaml` uses the image's health check.
- Dependabot waits 7 days after a release, writes Conventional Commit messages and opens major
  updates on their own.
- `make audit` covers every dependency group, pins pip-audit and writes no `requirements.txt`;
  `make clean` removes every cache.
- `run_schemathesis.sh` refuses a port that is already in use and cleans up its log;
  `init_project.py` leaves `.claude/` alone and reminds you of the `LICENSE` holder.
<!-- end:template -->
