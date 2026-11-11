#!/usr/bin/env bash
# Download the pinned Granite-Docling model for VLM_BACKEND into MODELS_PATH (default: models/).
#
# Usage: scripts/download_models.sh              # or: make download-models
#        VLM_BACKEND=transformers scripts/download_models.sh
#        make download-models VLM_BACKEND=transformers MODELS_PATH=/data/models
#
# The script holds no defaults and no pins. It asks scripts/resolve_model.py, which reads the two
# settings through `ModelSettings` exactly as the service does: the environment (and the variables
# `make` passes on) first, then a `.env` in the working directory, then the defaults. So a `.env`
# with VLM_BACKEND or MODELS_PATH moves the download and the service together, and the environment
# beats `.env` for both. An empty or unknown value is refused (exit 2), as the service refuses it.
# Only the two model settings are read: an unrelated bad value in `.env` does not block a download.
# The resolver runs through `uv run --no-sync`, so the project environment must exist: `make install`.
#
# The model goes to $MODELS_PATH/<owner>--<repo>, the folder name Docling looks for when it is given
# the models folder as `artifacts_path`. A relative MODELS_PATH is read from the working directory,
# as the service reads it; `make` runs from the repository root, so there it means the same folder.
# The repositories and revisions are pinned in src/formlens/modelspec.py: bump them there and in
# docs/licenses.md together (tests/test_docs.py fails until they agree).
# Running it again with the pinned revision already in place downloads nothing.
#
# HF_CLI replaces the downloader; the tests use it to stay offline. It is split on spaces into a
# command and its arguments, so a path that contains a space does not work: point HF_CLI at a
# wrapper script whose path has none. The default is pinned here, where Dependabot does not look:
# bump it by hand. It runs outside uv.lock, so `make audit` does not see it.
# Exit codes: 0 done, 1 the tooling failed, 2 a setting is refused.
# Bash 3.2 compatible (macOS /bin/bash).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HF_CLI="${HF_CLI:-uvx --from huggingface_hub==2.4.0 hf}"

if ! command -v uv >/dev/null 2>&1; then
    echo "'uv' not found; install uv (https://docs.astral.sh/uv/)." >&2
    exit 1
fi

# From the caller's directory, so `.env` and a relative MODELS_PATH resolve as they do for the service.
# --no-sync: never change the environment here; --no-python-downloads: never fetch an interpreter.
ERRORS="$(mktemp)"
trap 'rm -f -- "$ERRORS"' EXIT
STATUS=0
RESOLVED="$(uv run --project "$ROOT" --no-sync --no-python-downloads python "$ROOT/scripts/resolve_model.py" 2>"$ERRORS")" || STATUS=$?
if [ "$STATUS" -eq 3 ]; then
    cat -- "$ERRORS" >&2
    exit 2
fi
if [ "$STATUS" -ne 0 ]; then
    cat -- "$ERRORS" >&2
    echo "Could not read the settings (exit $STATUS); run 'make install' to create the project environment." >&2
    exit 1
fi
REPO="" REVISION="" FOLDER="" MODELS_PATH=""
{
    IFS= read -r REPO
    IFS= read -r REVISION
    IFS= read -r FOLDER
    IFS= read -r MODELS_PATH
} <<< "$RESOLVED" || true
if [ -z "$REPO" ] || [ -z "$REVISION" ] || [ -z "$FOLDER" ] || [ -z "$MODELS_PATH" ]; then
    echo "scripts/resolve_model.py printed an unexpected answer: $RESOLVED" >&2
    exit 1
fi
case "$MODELS_PATH" in
    -*) MODELS_PATH="./$MODELS_PATH" ;;  # a path that starts with '-' is not an option for mkdir, rm or the downloader
esac

TARGET="$MODELS_PATH/$FOLDER"
MARKER="$TARGET/.revision"

if [ -f "$MARKER" ] && [ -f "$TARGET/config.json" ] && [ "$(cat "$MARKER")" = "$REVISION" ]; then
    echo "$REPO is already at revision $REVISION in $TARGET; nothing to download."
    exit 0
fi

read -r -a HF <<< "$HF_CLI"
if [ "${#HF[@]}" -eq 0 ]; then
    echo "HF_CLI is empty or only spaces; set it to a downloader command or unset it." >&2
    exit 1
fi
if ! command -v "${HF[0]}" >/dev/null 2>&1; then
    echo "'${HF[0]}' not found; install uv (https://docs.astral.sh/uv/) or set HF_CLI." >&2
    exit 1
fi

echo "Downloading $REPO at revision $REVISION into $TARGET ..."
mkdir -p -- "$TARGET"
rm -f -- "$MARKER"
"${HF[@]}" download "$REPO" --revision "$REVISION" --local-dir "$TARGET"
echo "$REVISION" > "$MARKER"
echo "Done: $REPO at revision $REVISION is in $TARGET."
