#!/usr/bin/env bash
# Download the pinned Granite-Docling model for $VLM_BACKEND into $MODELS_PATH (default: models/).
#
# Usage: scripts/download_models.sh              # or: make download-models
#        VLM_BACKEND=transformers scripts/download_models.sh
#        make download-models VLM_BACKEND=transformers MODELS_PATH=/data/models
#
# The script reads the process environment only (and the variables `make` passes on), never `.env`:
# a `.env` with VLM_BACKEND or MODELS_PATH moves the service but not this download. To point the
# download elsewhere, export the variables or pass them to `make`. Only an unset variable selects
# its default; an empty VLM_BACKEND or MODELS_PATH is refused, as Settings refuses it.
#
# The model goes to $MODELS_PATH/<owner>--<repo>, the folder name Docling looks for when it is given
# the models folder as `artifacts_path`. A relative MODELS_PATH is read from the working directory,
# as the service reads it; `make` runs from the repository root, so there it means the same folder.
# The revisions are pinned: bump them here, in docs/licenses.md and in tests/model_pins.py together.
# Running it again with the pinned revision already in place downloads nothing.
#
# HF_CLI replaces the downloader; the tests use it to stay offline. It is split on spaces into a
# command and its arguments, so a path that contains a space does not work: point HF_CLI at a
# wrapper script whose path has none. The default is pinned here, where Dependabot does not look:
# bump it by hand. It runs outside uv.lock, so `make audit` does not see it.
# Bash 3.2 compatible (macOS /bin/bash).
set -euo pipefail

# Only an unset VLM_BACKEND or MODELS_PATH takes its default. An empty one is refused, as Settings
# refuses it: `${MODELS_PATH:-models}` would send the model to models/ while the service, given
# the same empty value, reads the working directory.
VLM_BACKEND="${VLM_BACKEND-mlx}"
MODELS_PATH="${MODELS_PATH-models}"
HF_CLI="${HF_CLI:-uvx --from huggingface_hub==2.4.0 hf}"

case "$VLM_BACKEND" in
    mlx)
        REPO="ibm-granite/granite-docling-258M-mlx"
        REVISION="e9939db25d2f296c8678d0491c4609a8c596c50a"
        ;;
    transformers)
        REPO="ibm-granite/granite-docling-258M"
        REVISION="982fe3b40f2fa73c365bdb1bcacf6c81b7184bfe"
        ;;
    *)
        echo "VLM_BACKEND must be 'mlx' or 'transformers', not '$VLM_BACKEND'." >&2
        exit 2
        ;;
esac

if [ -z "$MODELS_PATH" ]; then
    echo "MODELS_PATH must not be empty; unset it to use 'models'." >&2
    exit 2
fi
case "$MODELS_PATH" in
    -*) MODELS_PATH="./$MODELS_PATH" ;;  # a path that starts with '-' is not an option for mkdir, rm or the downloader
esac

TARGET="$MODELS_PATH/${REPO//\//--}"
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
