#!/usr/bin/env bash
# Start the service with a fake parser (tests/schemathesis_app.py, so no model is loaded), run
# Schemathesis against openapi.json with every check and phase, stop it.
# Usage: scripts/run_schemathesis.sh [extra schemathesis arguments]
set -euo pipefail

cd "$(dirname "$0")/.."

PORT="${SCHEMATHESIS_PORT:-8765}"

# Something already answering there would be tested instead of this service.
if curl --silent --max-time 2 "http://127.0.0.1:$PORT/" >/dev/null 2>&1; then
    echo "Port $PORT is already in use; set SCHEMATHESIS_PORT to a free one." >&2
    exit 1
fi

LOG="$(mktemp -t schemathesis-server.XXXXXX)"
# A throwaway database: the service refuses to start on one that is not migrated, and a run must not
# touch ./formlens.db. The fake extractor and the stopped worker keep every extraction `pending`.
WORK="$(mktemp -d -t schemathesis-db.XXXXXX)"
export DB_URL="sqlite:///$WORK/formlens.db"
# The stateful phase queues thousands of documents; the full queue is covered by its own HTTP test.
export QUEUE_MAX_PENDING="${QUEUE_MAX_PENDING:-1000000}"
(ENVIRONMENT=test LOG_FORMAT=json uv run python -m formlens migrate >"$LOG" 2>&1) || {
    echo "The migration failed; its log:" >&2
    cat "$LOG" >&2
    rm -rf "$WORK" "$LOG"
    exit 1
}

# The same server settings as `python -m formlens`: no Server header, no access log (the middleware
# writes it). Only the app differs: a test factory with a fake parser; production code has no switch.
ENVIRONMENT=test LOG_FORMAT=json LOG_LEVEL=INFO \
    uv run uvicorn --factory tests.schemathesis_app:create_schemathesis_app \
    --host 127.0.0.1 --port "$PORT" --no-server-header --no-access-log >"$LOG" 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true; wait "$SERVER_PID" 2>/dev/null || true; rm -rf "$LOG" "$WORK"' EXIT

for _ in $(seq 1 60); do
    if curl --silent --fail --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null; then
        break
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "The server exited early; its log:" >&2
        cat "$LOG" >&2
        exit 1
    fi
    sleep 0.5
done
curl --silent --fail --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null || {
    echo "The server did not answer on port $PORT; its log:" >&2
    cat "$LOG" >&2
    exit 1
}

status=0
uv run --group api schemathesis run openapi.json \
    --url "http://127.0.0.1:$PORT" --checks all "$@" || status=$?
if [ "$status" -ne 0 ]; then
    echo "Server log (last 40 lines):" >&2
    tail -n 40 "$LOG" >&2
fi
exit "$status"
