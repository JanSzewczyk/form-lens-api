#!/usr/bin/env bash
# Start the service, run Schemathesis against openapi.json with every check and phase, stop it.
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

HOST=127.0.0.1 PORT="$PORT" ENVIRONMENT=test LOG_FORMAT=json LOG_LEVEL=INFO \
    uv run python -m fastapi_szumplate >"$LOG" 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true; wait "$SERVER_PID" 2>/dev/null || true; rm -f "$LOG"' EXIT

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
