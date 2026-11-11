# syntax=docker/dockerfile:1

# The uv binary comes from a pinned image. Dependabot bumps only this tag, so
# tests/test_tooling.py fails until UV_VERSION in ci.yml matches it.
FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

FROM python:3.15-slim AS builder
COPY --from=uv /uv /uvx /bin/
# Compilers for the locked dependencies that have no wheel for Python 3.15 and build from source
# (pyclipper, tree-sitter). Only this stage has them; the runtime stage copies the built environment.
RUN apt-get update \
    && apt-get install --no-install-recommends --yes build-essential \
    && rm -rf /var/lib/apt/lists/*
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies first: this layer is rebuilt only when the lockfile changes. README and LICENSE are
# part of the package metadata (`readme`, `license-files`).
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-default-groups --no-install-project

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-default-groups --no-editable

FROM python:3.15-slim AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENVIRONMENT=production \
    HOST=0.0.0.0 \
    PORT=8000 \
    VLM_BACKEND=transformers \
    MODELS_PATH=/models \
    DB_URL=sqlite:////data/formlens.db

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home app \
    && mkdir /data && chown 10001:10001 /data
WORKDIR /app
# Owned by root: the process can read and run its code but not change it.
COPY --from=builder /app/.venv /app/.venv
# Numeric, so Kubernetes `runAsNonRoot` can verify that the user is not root.
USER 10001:10001

# The model is not in the image: mount the folder `make download-models VLM_BACKEND=transformers`
# filled, read-only, at /models. Without it the service stops at start-up with `model_load_failed`.
# `mlx` runs only on Apple Silicon, so the image uses `transformers`.
# The database lives in /data, the one folder the process may write (SQLite's WAL needs the folder, not only the
# file). Mount a volume there, or the data is lost with the container. A named volume copies this owner on first
# use; a bind mount must be writable by user 10001.
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --start-interval=2s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health', timeout=3)"]

# Migrate, then serve: the service refuses to start on a database that is not at the newest revision. The
# language model is not in the image either: LLM_BASE_URL must reach an Ollama (for the host's:
# http://host.docker.internal:11434/v1, see compose.yaml).
CMD ["sh", "-c", "python -m formlens migrate && exec python -m formlens"]
