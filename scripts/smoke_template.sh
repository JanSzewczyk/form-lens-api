#!/usr/bin/env bash
# Prove that a project made from this template passes its own gates.
#
# Copies the files of the working tree (tracked, plus new files that are not ignored) to a
# temporary directory, runs scripts/init_project.py there, then `uv sync --locked`,
# `make openapi` and `make check`. The CI job `template-smoke` runs this script too.
#
# Usage: scripts/smoke_template.sh [--rename-only]
#   (default)       rename and remove the example (init_project.py --without-example)
#   --rename-only   rename only, keep the example
# Set SMOKE_KEEP=1 to keep the temporary directory (its path is printed).
set -euo pipefail

cd "$(dirname "$0")/.."
TEMPLATE="$PWD"

case "${1:-}" in
    "") flags=(--without-example); variant="without the example" ;;
    --rename-only) flags=(); variant="rename only" ;;
    *) echo "usage: $0 [--rename-only]" >&2; exit 2 ;;
esac

SMOKE="$(mktemp -d "${TMPDIR:-/tmp}/template-smoke.XXXXXX")"
cleanup() {
    if [ "${SMOKE_KEEP:-0}" = 1 ]; then
        echo "kept: $SMOKE"
    else
        rm -rf "$SMOKE"
    fi
}
trap cleanup EXIT

# Never reuse the environment of the shell or of the template: the copy builds its own.
run() { env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT "$@"; }

echo "== template smoke ($variant) in $SMOKE"
git ls-files -z --cached --others --exclude-standard \
    | while IFS= read -r -d '' file; do [ -e "$file" ] && printf '%s\0' "$file"; done \
    | tar --null -T - -cf - \
    | tar -xf - -C "$SMOKE"

cd "$SMOKE"
run uv run --no-project python scripts/init_project.py orders-api ${flags[@]+"${flags[@]}"}
run uv sync --locked
run make openapi
if [ "${#flags[@]}" -gt 0 ]; then
    # init_project.py deleted itself in the copy; the template's copy lists what still names
    # the removed example (after `make openapi`, so the regenerated spec is checked too).
    run uv run --no-project python "$TEMPLATE/scripts/init_project.py" \
        --check-references --root "$SMOKE"
fi
run make check
echo "== template smoke ($variant): green"
