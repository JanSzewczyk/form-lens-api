<div align="center">

# 🐍 formlens

[![CI](https://img.shields.io/github/actions/workflow/status/JanSzewczyk/form-lens-api/ci.yml?branch=main&logo=githubactions&logoColor=white&label=CI)](https://github.com/JanSzewczyk/form-lens-api/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/dynamic/regex?url=https://raw.githubusercontent.com/JanSzewczyk/form-lens-api/main/.python-version&search=(%5Cd%2B%5C.%5Cd%2B)&replace=%241&label=Python&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/dynamic/regex?url=https://raw.githubusercontent.com/JanSzewczyk/form-lens-api/main/uv.lock&search=name%20%3D%20%22fastapi%22%5Cnversion%20%3D%20%22(%5B%5E%22%5D%2B)%22&replace=%241&label=FastAPI&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License: Proprietary](https://img.shields.io/badge/License-Proprietary-red.svg)](LICENSE)

**FastAPI service that extracts structured data from forms with a document model that runs locally**

[Features](#-features) • [Run it](#run-it) • [API](#-api) • [Configuration](#-configuration) • [Deployment](#-deployment)

</div>

---

## 👋 Hello there!

FormLens API by Szum-Tech turns forms into structured data with IBM's Granite-Docling model,
which runs on your machine through [Docling](https://github.com/docling-project/docling); no
document leaves it. **Stage 0 is the working but empty skeleton**: typed settings (including the
model settings), structured logging, one error format (Problem Details), a generated and checked
OpenAPI contract, a pinned model download, Docker and CI. There is no parsing endpoint yet; it
arrives in Stage 1. It runs on Python 3.15 with uv, Ruff, mypy (strict) and pytest.

### ⚡ Quick Start

```bash
git clone https://github.com/JanSzewczyk/form-lens-api.git
cd form-lens-api
cp .env.example .env
make install
make download-models   # about 0.6 GB, once; not needed to start the service in Stage 0
make run
```

The API listens on http://127.0.0.1:8000; `curl http://127.0.0.1:8000/health` answers `{"status": "ok"}`.

## ✨ Features

### 🚀 What You Get

- **🩺 Health and readiness** — `GET /health` for liveness; `GET /health/ready` runs every registered check and answers a 503 problem that names the checks that failed
- **🔧 Typed settings** — pydantic-settings reads the environment and `.env`, and the service refuses to start on an invalid value
- **📝 Structured logs** — JSON or console output, an `X-Request-ID` on every response and log line, one access line per request, values under keys such as `password` or `token` redacted
- **🚨 One error format** — RFC 9457 Problem Details for 400, 404, 405, 422, 500 and every domain error, each domain error with its own stable `type`
- **📄 Checked OpenAPI contract** — `openapi.json` is generated from the app, committed, drift-checked by `make check`, linted by Spectral, diffed by oasdiff and fuzzed by Schemathesis
- **📑 Pagination** — a `Page[T]` envelope with `limit` and `offset` parameters
- **🔁 Strict requests** — a single-value query parameter sent twice is a 422, not a silent pick; a trailing slash is a 404, not a redirect
- **🛑 Graceful shutdown** — open requests get `GRACEFUL_SHUTDOWN_SECONDS` after SIGTERM, and responses carry no `Server` header

### 🧱 Tech Stack

- [![FastAPI](https://img.shields.io/badge/dynamic/regex?url=https://raw.githubusercontent.com/JanSzewczyk/form-lens-api/main/uv.lock&search=name%20%3D%20%22fastapi%22%5Cnversion%20%3D%20%22(%5B%5E%22%5D%2B)%22&replace=%241&label=FastAPI&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/) — routing, validation and the OpenAPI document
- [![Pydantic](https://img.shields.io/badge/dynamic/regex?url=https://raw.githubusercontent.com/JanSzewczyk/form-lens-api/main/uv.lock&search=name%20%3D%20%22pydantic%22%5Cnversion%20%3D%20%22(%5B%5E%22%5D%2B)%22&replace=%241&label=Pydantic&logo=pydantic&logoColor=white)](https://docs.pydantic.dev/) — request, response and problem models
- [![Pydantic Settings](https://img.shields.io/badge/dynamic/regex?url=https://raw.githubusercontent.com/JanSzewczyk/form-lens-api/main/uv.lock&search=name%20%3D%20%22pydantic-settings%22%5Cnversion%20%3D%20%22(%5B%5E%22%5D%2B)%22&replace=%241&label=Pydantic%20Settings&logo=pydantic&logoColor=white)](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) — typed configuration from the environment and `.env`
- [![structlog](https://img.shields.io/badge/dynamic/regex?url=https://raw.githubusercontent.com/JanSzewczyk/form-lens-api/main/uv.lock&search=name%20%3D%20%22structlog%22%5Cnversion%20%3D%20%22(%5B%5E%22%5D%2B)%22&replace=%241&label=structlog)](https://www.structlog.org/) — structured logging on top of the stdlib `logging`
- [![Uvicorn](https://img.shields.io/badge/dynamic/regex?url=https://raw.githubusercontent.com/JanSzewczyk/form-lens-api/main/uv.lock&search=name%20%3D%20%22uvicorn%22%5Cnversion%20%3D%20%22(%5B%5E%22%5D%2B)%22&replace=%241&label=Uvicorn)](https://www.uvicorn.org/) — the ASGI server, started by `python -m formlens`

- **Docling with Granite-Docling** — the document model; planned for Stage 1 and **not a dependency yet**. Its licences are in [docs/licenses.md](docs/licenses.md)

### 🧪 Quality Gates

- [![Ruff](https://img.shields.io/badge/dynamic/regex?url=https://raw.githubusercontent.com/JanSzewczyk/form-lens-api/main/uv.lock&search=name%20%3D%20%22ruff%22%5Cnversion%20%3D%20%22(%5B%5E%22%5D%2B)%22&replace=%241&label=Ruff&logo=ruff&logoColor=white)](https://docs.astral.sh/ruff/) — format and lint, with security, async, logging and docstring rules
- [![mypy](https://img.shields.io/badge/dynamic/regex?url=https://raw.githubusercontent.com/JanSzewczyk/form-lens-api/main/uv.lock&search=name%20%3D%20%22mypy%22%5Cnversion%20%3D%20%22(%5B%5E%22%5D%2B)%22&replace=%241&label=mypy)](https://mypy.readthedocs.io/) — `strict = true` with the Pydantic plugin and extra error codes, over `src`, `tests` and `scripts`
- [![import-linter](https://img.shields.io/badge/dynamic/regex?url=https://raw.githubusercontent.com/JanSzewczyk/form-lens-api/main/uv.lock&search=name%20%3D%20%22import-linter%22%5Cnversion%20%3D%20%22(%5B%5E%22%5D%2B)%22&replace=%241&label=import-linter)](https://import-linter.readthedocs.io/) — contracts: the core is layered and only the entry point imports uvicorn
- [![pytest](https://img.shields.io/badge/dynamic/regex?url=https://raw.githubusercontent.com/JanSzewczyk/form-lens-api/main/uv.lock&search=name%20%3D%20%22pytest%22%5Cnversion%20%3D%20%22(%5B%5E%22%5D%2B)%22&replace=%241&label=pytest&logo=pytest&logoColor=white)](https://docs.pytest.org/) — strict mode, warnings are errors, random order, 60 s timeout per test
- [![coverage](https://img.shields.io/badge/dynamic/regex?url=https://raw.githubusercontent.com/JanSzewczyk/form-lens-api/main/uv.lock&search=name%20%3D%20%22coverage%22%5Cnversion%20%3D%20%22(%5B%5E%22%5D%2B)%22&replace=%241&label=coverage)](https://coverage.readthedocs.io/) — branch coverage of `src` and `scripts`, at least 95%
- [![Hypothesis](https://img.shields.io/badge/dynamic/regex?url=https://raw.githubusercontent.com/JanSzewczyk/form-lens-api/main/uv.lock&search=name%20%3D%20%22hypothesis%22%5Cnversion%20%3D%20%22(%5B%5E%22%5D%2B)%22&replace=%241&label=Hypothesis)](https://hypothesis.readthedocs.io/) — property-based tests
- [![Schemathesis](https://img.shields.io/badge/dynamic/regex?url=https://raw.githubusercontent.com/JanSzewczyk/form-lens-api/main/uv.lock&search=name%20%3D%20%22schemathesis%22%5Cnversion%20%3D%20%22(%5B%5E%22%5D%2B)%22&replace=%241&label=Schemathesis)](https://schemathesis.readthedocs.io/) — every check and phase against a running server

### 🤖 Automation & DevOps

- [![uv](https://img.shields.io/badge/uv-DE5FE9?logo=uv&logoColor=white)](https://docs.astral.sh/uv/) — `uv.lock` and `uv sync --locked` everywhere; one uv version for the image and CI
- [![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)](https://www.docker.com/) — multi-stage image, non-root user, `HEALTHCHECK`, and a `compose.yaml` that runs it read-only
- [![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)](https://docs.github.com/actions) — `make check`, the contract tooling, the image and a free-threaded run on every pull request
- [![Dependabot](https://img.shields.io/badge/Dependabot-025E8C?logo=dependabot&logoColor=white)](https://docs.github.com/code-security/dependabot) — weekly updates for uv, Actions and Docker images, after a 7-day cooldown
- **python-semantic-release** — versions, tags and GitHub Releases from Conventional Commits on `main`
- **pip-audit** — every locked dependency group, on every pull request and weekly

### 🧭 Scope & Design Decisions

- **One error format** — every error is Problem Details; clients branch on `type`, never on `detail`
- **Docs off by default** — `/docs`, `/redoc` and `/openapi.json` exist only with `DOCS_ENABLED=true`; leave them off on a public API
- **`python -m`, not the `uvicorn` command** — the module configures logging before uvicorn starts (see [Run it](#run-it))
- **One worker, one replica** — anything kept in memory is per process (see [Deployment](#-deployment))
- **No authentication** — out of scope; put it in a dependency on the routers you want to protect, and publish the security scheme in the OpenAPI document
- **Structure when it hurts** — a module starts with the default shape and grows only when its rules demand it ([architecture.md](docs/explanation/architecture.md))

---

## 📖 Table of Contents

- [✨ Features](#-features)
- [🎯 Run it](#run-it)
- [📃 Commands](#-commands)
- [📡 API](#-api)
- [🧱 Architecture](#-architecture)
- [🧪 Testing](#-testing)
- [🔧 Configuration](#-configuration)
- [🔒 Security](#-security)
- [🚀 Deployment](#-deployment)
- [🤖 CI](#-ci)
- [📁 Project Structure](#-project-structure)
- [📚 Documentation](#-documentation)
- [🩺 Troubleshooting](#-troubleshooting)
- [📝 Changelog](#-changelog)
- [🤝 Contributing](#-contributing)
- [📜 License](#-license)
- [📧 Contact & Support](#-contact--support)

---

## Run it

### 📋 Prerequisites

- **[Python](https://www.python.org/downloads/)** 3.15 — uv installs it for you when it is missing
- **macOS 14 or newer on Apple Silicon** for the default `VLM_BACKEND=mlx`, the backend this project uses on Apple Silicon (macOS 14 is the minimum for the macOS `mlx` wheels). This project has run it only there. On other systems set `VLM_BACKEND=transformers`; that backend has been neither downloaded nor run so far
- **[uv](https://docs.astral.sh/uv/)** 0.13.7 or newer, for dependencies and virtual environments
- **GNU Make** to run the commands below
- **Git** for version control
- **Docker** (optional) for `make docker-build`, `make docker-run`, Compose and `make api-breaking` without a local oasdiff
- **Node.js** (optional) for `make api-lint`, which runs Spectral through `npx`

### 📦 Installation

#### 1. Clone the Repository

```bash
git clone https://github.com/JanSzewczyk/form-lens-api.git
cd form-lens-api
```

#### 2. Install Dependencies

```bash
make install
```

This creates `.venv/` and installs the exact versions from `uv.lock` (`uv sync --locked`).

#### 3. Configure the Environment

```bash
cp .env.example .env
```

#### 4. Download the Model

```bash
make download-models
```

This fetches the model pinned for `VLM_BACKEND` (about 0.6 GB for `mlx`) into `MODELS_PATH`
(`models/` by default, git-ignored) as `models/ibm-granite--granite-docling-258M-mlx/`. It needs
network access and uv, and does nothing when the pinned revision is already there. A relative
`MODELS_PATH` is read from the working directory, as the service reads it (`make` runs from the
repository root). `make test-models` then checks that the files are in place. An empty
`MODELS_PATH` or `VLM_BACKEND` is refused, by the script as by the service. Licences:
[docs/licenses.md](docs/licenses.md).

**The script reads only the process environment, never `.env`.** `make download-models` and
`make test-models` see the variables you export and the ones you pass to `make`, not the ones in
`.env`: a `.env` with `MODELS_PATH=/elsewhere` or `VLM_BACKEND=transformers` moves the service
(`make run`) but not the download or the check. To point them elsewhere, export the variables or
pass them on the command line, with the same values for all three commands:

```bash
make download-models VLM_BACKEND=transformers MODELS_PATH=/data/models
make test-models VLM_BACKEND=transformers MODELS_PATH=/data/models
```

This is a known gap: the script repeats the defaults and the validation of `Settings` in bash.
One source for both is a Stage 1 follow-up (see
[architecture.md](docs/explanation/architecture.md#carry-forward-notes-for-stage-1)).

`HF_CLI` replaces the downloader (the tests use a fake one). It is split on spaces into a command
and its arguments, so a path that contains a space does not work; point it at a wrapper script
whose path has none.

#### 5. Start the Service

```bash
make run
```

`make run` is `python -m formlens`. The API listens on http://127.0.0.1:8000. The
interactive docs (`/docs`, `/redoc`) and the spec (`/openapi.json`) are **off by default**, and
`.env.example` keeps them off. Set `DOCS_ENABLED=true` in your `.env` to read them while you
develop; leave them off on a public API.

Start it with `python -m formlens`, not with the `uvicorn` command. The module configures
logging before it starts uvicorn and tells uvicorn to leave it alone (`log_config=None`) and to skip
its own access log. If you must use the CLI, pass `--factory`
(`uvicorn formlens.main:create_app --factory`); you then get uvicorn's default log format
next to ours.

#### 6. Check It Works

```bash
curl http://127.0.0.1:8000/health
```

```json
{"status": "ok"}
```

---

## 📃 Commands

| Command | Purpose |
| --- | --- |
| `make install` | Install locked dependencies (`uv sync --locked`) |
| `make run` | Start the service (`python -m formlens`) |
| `make format` | Ruff format |
| `make lint` | Ruff lint |
| `make typecheck` | mypy, strict |
| `make imports` | import-linter contracts (module boundaries) |
| `make test` | pytest, without the `slow` tests that need the downloaded models |
| `make test-models` | The `slow` tests: fail unless the pinned model files are under `MODELS_PATH` (run `make download-models` first) |
| `make download-models` | Download the pinned Granite-Docling model for `VLM_BACKEND` into `MODELS_PATH` (needs network, uv and about 0.6 GB) |
| `make check` | What CI runs: format check, lint, mypy, import contracts, tests with coverage, OpenAPI drift |
| `make openapi` | Regenerate `openapi.json` from the app (never edit it by hand) |
| `make openapi-check` | Fail if `openapi.json` is out of date |
| `make api-lint` | Spectral on `openapi.json`, failing on warnings (needs Node; runs `npx`) |
| `make api-breaking` | oasdiff against `origin/main:openapi.json`, failing on breaking changes except those listed in `oasdiff-ignore.txt` (the removed example routes; delete the file after the first merge to `main`); needs oasdiff or Docker |
| `make schemathesis` | Start the service, run Schemathesis with every check and phase, stop it |
| `make api-check` | `openapi-check`, `api-lint`, `api-breaking` and `schemathesis` |
| `make audit` | pip-audit on every locked dependency group |
| `make docker-build` / `make docker-run` | Build and run the image (needs Docker and a `.env`) |
| `make clean` | Remove caches and generated files |

`make check` is what CI runs; run it before you push.

---

## 📡 API

### 🔌 Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness (`get_health`): `{"status": "ok"}` while the process serves requests |
| `GET` | `/health/ready` | Readiness (`get_readiness`): 200 when every registered check passes, else a 503 problem |

The spec is generated from the app into `openapi.json` by `make openapi` and committed; never edit
it by hand. `make check` fails when it is out of date, and `make api-check` lints it, compares it
with `main` for breaking changes and runs Schemathesis against a live server. With
`DOCS_ENABLED=true` the service also serves `/docs`, `/redoc` and `/openapi.json`.

### 🔎 Example

```bash
curl http://127.0.0.1:8000/health/ready
```

```json
{"status": "ready", "checks": {}}
```

Register a check with `register_readiness_check(app, "storage", check)`; its name then appears in
`checks` (`"ok"`), and a failing one turns the answer into a 503 `service-not-ready` problem that
names the check, not the error.

### 🚨 Errors

Every error is `application/problem+json` (RFC 9457) with `type`, `title`, `status`, `detail` and,
when known, `request_id`. Validation errors add `errors` with only `loc`, `msg` and `type`; the
submitted value is never echoed. Clients branch on `type`. See
[docs/reference/problem-types.md](docs/reference/problem-types.md).

```json
{
  "type": "about:blank",
  "title": "Not Found",
  "status": 404,
  "detail": "Not Found",
  "request_id": "..."
}
```

A 500 is answered by `UnhandledErrorMiddleware`, the innermost middleware, so it carries the
`X-Request-ID` header and, when CORS is on, the CORS headers (checked against uvicorn). The body is
the generic problem with the `request_id`; the traceback is logged once, on the `request_completed`
line of that request, without local variables.

Known limits:

- If the application fails after the response has started, the status and headers are already
  sent and cannot be replaced. The server cuts the connection and logs the traceback itself, while
  the `request_completed` line keeps the status that was sent but is logged at `error` with
  `aborted_by` set to the exception type.
- A failure in the middleware themselves is answered by Starlette's backstop handler: still the
  generic problem, but without `X-Request-ID` or CORS headers.
- A refused CORS preflight is a 400 problem too; a successful preflight is Starlette's bodyless
  `OK` (`text/plain`), which is not an error.

---

## 🧱 Architecture

`main.py` only wires the app: settings, logging, problem handlers, the OpenAPI clean-up, readiness,
the routers and three middleware (request context outermost, then CORS when it is on, then the 500
answer). import-linter enforces the layers of the core, top to bottom:

```mermaid
flowchart TD
    entry["__main__ — entry point, the only module that imports uvicorn"]
    factory["main — create_app, wiring only"]
    features["health · middleware · openapi · logging_config · pagination"]
    foundations["problems · config · query · types"]
    entry --> factory --> features --> foundations
```

See [docs/explanation/architecture.md](docs/explanation/architecture.md) for why the layers are
drawn this way.

Start every module with the default shape (router, schemas, models, service, repository); see
[docs/how-to/add-a-module.md](docs/how-to/add-a-module.md) and
[docs/explanation/architecture.md](docs/explanation/architecture.md).

---

## 🧪 Testing

```bash
make test
```

- Tests mirror `src/`. They build settings with `Settings(_env_file=None)` (`make_settings` in
  `tests/conftest.py`) and replace dependencies with `app.dependency_overrides`. There is no
  factories module yet; a test sets the values it asserts on inline.
- An autouse fixture in `tests/conftest.py` removes every setting from the environment, so an
  exported `DOCS_ENABLED=true` cannot change a test. The `slow` tests are exempt: they read
  `MODELS_PATH` and `VLM_BACKEND` from the environment.
- Tests of the core use `/health` and the probe routes of `tests/probes.py`, so they never depend
  on a domain module.
- pytest runs in strict mode: unknown markers and config keys fail, and so does any warning.
- The order is random (pytest-randomly); `uv run pytest -p no:randomly` replays a run in file
  order. Every test has a 60 s timeout.
- `make check` runs the suite under coverage with branches and fails below 95%.
- Tests marked `slow` need the downloaded model and are deselected by default. `make test-models`
  runs them and **fails**, not skips, when the pinned files are missing. A test of a real
  conversion arrives in Stage 1.
- `tests/test_download_models.py` runs the download script against a fake downloader, so it needs
  no network.

### Manual offline check

Nobody has automated this yet. After `make download-models`, turn the network off (Wi-Fi off or
cable out), then:

```bash
make run                         # in one terminal
curl http://127.0.0.1:8000/health   # in another: {"status": "ok"}
```

The service must start and answer without network access. Stage 0 never loads the model, so this
only proves that nothing at start-up needs the network; repeat it with a real conversion in Stage 1.

---

## 🔧 Configuration

The service reads all settings from the environment or `.env` (see `.env.example`); the download script reads the environment only (see [Download the Model](#4-download-the-model)):

| Variable | Default | Meaning |
| --- | --- | --- |
| `APP_NAME` | `formlens` | API title |
| `ENVIRONMENT` | `local` | `local`, `test` or `production` |
| `LOG_LEVEL` | `INFO` | `DEBUG` to `CRITICAL` |
| `LOG_FORMAT` | `auto` | `json`, `console`, or `auto` (console when `local`, otherwise JSON) |
| `DOCS_ENABLED` | `false` | Serve `/docs`, `/redoc`, `/openapi.json` |
| `CORS_ORIGINS` | `[]` | JSON list of allowed origins; empty turns CORS off |
| `HOST`, `PORT`, `RELOAD` | `127.0.0.1`, `8000`, `false` | Server binding |
| `GRACEFUL_SHUTDOWN_SECONDS` | `20` | Time open requests get after SIGTERM; keep it below the orchestrator's grace period |
| `DEFAULT_PAGE_SIZE` | `20` | Page size when `limit` is omitted |
| `MODELS_PATH` | `./models` | Folder with the downloaded models; a relative path is read from the working directory; an empty value is refused |
| `VLM_BACKEND` | `mlx` | `mlx` (the backend this project uses on Apple Silicon) or `transformers` |
| `MAX_UPLOAD_MB` | `25` | Largest accepted upload, in megabytes (1 or more) |
| `MAX_CONCURRENCY` | `1` | Documents converted at the same time (1 or more) |

Every key is optional. An invalid value stops the service at start-up instead of failing later.
`MODELS_PATH`, `VLM_BACKEND`, `MAX_UPLOAD_MB` and `MAX_CONCURRENCY` are read and validated in
Stage 0 but nothing uses them until Stage 1.

---

## 🔒 Security

- **Docs and spec off** — `/docs`, `/redoc` and `/openapi.json` are served only with `DOCS_ENABLED=true`
- **CORS off** — empty `CORS_ORIGINS` adds no CORS middleware; when on, credentials are not allowed
- **Nothing echoed back** — validation errors return `loc`, `msg` and `type` but never the submitted value, and a 500 carries no exception details
- **Redacted logs** — values under keys containing `password`, `token`, `authorization`, `api_key`, `secret` or `cookie` are logged as `***`; a safety net, not a licence to log secrets
- **No `Server` header** — uvicorn's server header is turned off
- **Hardened container** — the image runs as user `10001`, the virtual environment belongs to root, and `compose.yaml` adds a read-only filesystem, no capabilities and `no-new-privileges`
- **Audited dependencies** — `make audit` runs pip-audit on every locked group, in CI on every pull request and weekly; Dependabot waits 7 days before proposing a new release

Report a vulnerability through [GitHub issues](https://github.com/JanSzewczyk/form-lens-api/issues).

---

## 🚀 Deployment

```bash
make docker-build
make docker-run
docker compose up --build
```

The image is multi-stage, runs as a non-root user and has a health check. `compose.yaml` runs it
with a read-only filesystem. Docker is not required for development.

`compose.yaml` reads `.env` through `env_file` with `required: false`, which needs Docker Compose
2.24 or newer. `make docker-run` and `compose.yaml` force `ENVIRONMENT=production`, `HOST` and
`PORT`; everything else comes from your `.env`.

Run one worker and one replica. Anything the app keeps in memory is per process, so a second
worker or replica would not see it.

Set `GRACEFUL_SHUTDOWN_SECONDS` below your orchestrator's grace period (Kubernetes: 30 s by
default). Behind a proxy, also set uvicorn's `FORWARDED_ALLOW_IPS`.

---

## 🤖 CI

`.github/workflows/ci.yml` runs on pushes to `main`, on pull requests, weekly and on demand:

- `check` — `make check`, a coverage summary and the dependency audit; the only job of the weekly run
- `api` — Spectral, oasdiff against `main` and Schemathesis (`make api-check`)
- `docker` — builds the image and starts it through `compose.yaml` until its health check passes, then calls `/health`
- `free-threaded` — the tests on free-threaded Python; informational, it never blocks a merge

Actions are pinned to exact version tags. `.github/dependabot.yml` proposes weekly updates for uv,
GitHub Actions and the Docker images, grouping minor and patch releases.

### 🏷️ Releases

`.github/workflows/release.yml` runs python-semantic-release on every push to `main`. It reads the
Conventional Commits since the last tag: `feat` bumps the minor version, `fix` and `perf` the patch
version, and `!` or a `BREAKING CHANGE:` footer the major version (while the version is `0.x`, a
breaking change bumps the minor). Other types release nothing. A release updates `version` in
`pyproject.toml` and `uv.lock`, pushes a `chore(release): X.Y.Z` commit and the `vX.Y.Z` tag, adds the
release to `CHANGELOG.md` and creates the GitHub Release with generated notes. Preview the next
version locally with `uv run --group release semantic-release --noop version --print`.


If `main` is protected, the workflow's token must be allowed to push to it (a ruleset bypass).

---

## 📁 Project Structure

```text
src/formlens/
  main.py            create_app(settings): wiring only
  __main__.py        python -m formlens
  config.py          Settings (pydantic-settings), get_settings dependency
  logging_config.py  structlog on stdlib: JSON or console, redaction, idempotent
  middleware.py      request id, bound log context, one access-log line per request
  problems.py        Problem Details model, handlers for 404/405/422/500, domain error mapping
  openapi.py         API metadata and the document clean-up
  query.py           rejects a single-value query parameter given more than once
  types.py           IsoDate, IsoAwareDatetime, WholeNumber
  pagination.py      Page[T] envelope and limit/offset parameters
  health/            GET /health (liveness), GET /health/ready (readiness, 503 problem)
tests/               mirrors src
scripts/             export_openapi.py, run_schemathesis.sh, download_models.sh
docs/                how-to guides, reference, explanation, licences
models/              downloaded models (git-ignored)
```

### 📂 Key Directories

- **`src/formlens/`** — the service; the core modules above plus one package per feature
- **`tests/`** — pytest suite, one test module per source module, with `conftest.py` and the probe routes of `probes.py`
- **`scripts/`** — the OpenAPI export, the Schemathesis runner and `download_models.sh` (the pinned model download) that the Makefile calls
- **`docs/`** — how-to guides, the problem type reference and the architecture notes

### 🧾 Important Configuration Files

- **`pyproject.toml`** — dependencies and groups, Ruff, mypy, pytest, coverage and import-linter
- **`uv.lock`** — the locked versions every install uses
- **`Makefile`** — every command above
- **`.env.example`** — every setting with its default
- **`openapi.json`** — the generated contract
- **`.spectral.yaml`**, **`schemathesis.toml`** — rules for the contract tooling
- **`Dockerfile`**, **`compose.yaml`**, **`.dockerignore`** — the image and how to run it
- **`.github/workflows/ci.yml`**, **`.github/workflows/release.yml`**, **`.github/dependabot.yml`** — CI, releases and dependency updates

---

## 📚 Documentation

- **How-to**
  - [Add a module](docs/how-to/add-a-module.md)
- **Reference** — [Problem types](docs/reference/problem-types.md)
- **Explanation** — [Architecture](docs/explanation/architecture.md)
- **Licences** — [Models and libraries](docs/licenses.md)

---

## 🩺 Troubleshooting

- **`/docs` answers 404** — the docs are off by default; set `DOCS_ENABLED=true` in `.env`
- **`/health/` answers 404** — a trailing slash is not redirected; call `/health`
- **Two log formats side by side** — the service was started with the `uvicorn` command; use `make run` or pass `--factory`
- **`make openapi-check` fails** — the API changed; run `make openapi` and commit `openapi.json`
- **`make schemathesis` says the port is in use** — set `SCHEMATHESIS_PORT` to a free port
- **`make api-breaking` skips the check** — `origin/main` has no `openapi.json` yet
- **`make test-models` fails** — the pinned model is not in `MODELS_PATH`; run `make download-models` with the same `VLM_BACKEND` and `MODELS_PATH`, exported or passed to `make` (neither command reads `.env`)
- **`make download-models` says uvx is missing** — install [uv](https://docs.astral.sh/uv/), or set `HF_CLI` to another Hugging Face downloader (split on spaces; no space inside its path)
- **Compose rejects `env_file`** — `required: false` needs Docker Compose 2.24 or newer
- **The container ignores `ENVIRONMENT`, `HOST` or `PORT` from `.env`** — `make docker-run` and `compose.yaml` force them on purpose

---

## 📝 Changelog

Releases and their changes are listed on the repository's GitHub Releases page. The first release
also generates `CHANGELOG.md` from the Conventional Commits.

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Run `make check` until it passes
4. Commit your changes using [Conventional Commits](https://www.conventionalcommits.org/)
5. Open a Pull Request

---

## 📜 License

This project is proprietary: all rights reserved by Szum-Tech. See the [LICENSE](LICENSE) file. The
licences of the models and libraries it uses are listed in [docs/licenses.md](docs/licenses.md).

---

## 📧 Contact & Support

- 🐛 [Open an issue](https://github.com/JanSzewczyk/form-lens-api/issues)
- ⭐ [Star this repository](https://github.com/JanSzewczyk/form-lens-api)
- 👨‍💻 Check out the maintainer's [GitHub profile](https://github.com/JanSzewczyk)

---

<div align="center">

**Made with ❤️ by [Szum-Tech](https://github.com/JanSzewczyk)**

If this service helped you, please consider giving it a ⭐ on GitHub!

[⬆ Back to Top](#-formlens)

</div>
