#!/usr/bin/env bash
# Download the pinned Granite-Docling model for $VLM_BACKEND into $MODELS_PATH (default: models/).
#
# Usage: scripts/download_models.sh              # or: make download-models
#        VLM_BACKEND=transformers scripts/download_models.sh
#
# The model goes to $MODELS_PATH/<owner>--<repo>, the folder name Docling looks for when it is given
# the models folder as `artifacts_path`. A relative MODELS_PATH is read from the working directory,
# as the service reads it; `make` runs from the repository root, so there it means the same folder.
# The revisions are pinned: bump them here, in docs/licenses.md and in tests/model_pins.py together.
# Running it again with the pinned revision already in place downloads nothing.
#
# HF_CLI replaces the downloader (a space-separated command); the tests use it to stay offline.
# The default is pinned here, where Dependabot does not look: bump it by hand.
# Bash 3.2 compatible (macOS /bin/bash).
set -euo pipefail

# Only an unset VLM_BACKEND means mlx. An empty one is refused, as Settings refuses it.
VLM_BACKEND="${VLM_BACKEND-mlx}"
MODELS_PATH="${MODELS_PATH:-models}"
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

TARGET="$MODELS_PATH/${REPO//\//--}"
MARKER="$TARGET/.revision"

if [ -f "$MARKER" ] && [ -f "$TARGET/config.json" ] && [ "$(cat "$MARKER")" = "$REVISION" ]; then
    echo "$REPO is already at revision $REVISION in $TARGET; nothing to download."
    exit 0
fi

read -r -a HF <<< "$HF_CLI"
if ! command -v "${HF[0]}" >/dev/null 2>&1; then
    echo "'${HF[0]}' not found; install uv (https://docs.astral.sh/uv/) or set HF_CLI." >&2
    exit 1
fi

echo "Downloading $REPO at revision $REVISION into $TARGET ..."
mkdir -p "$TARGET"
rm -f "$MARKER"
"${HF[@]}" download "$REPO" --revision "$REVISION" --local-dir "$TARGET"
echo "$REVISION" > "$MARKER"
echo "Done: $REPO at revision $REVISION is in $TARGET."
