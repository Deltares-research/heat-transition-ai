#!/usr/bin/env bash
# Run the backend (FastAPI/uvicorn) and frontend (Vite) dev servers together.
#
#   ./scripts/dev.sh
#
# Ctrl+C stops both.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

# `npm run dev` is a wrapper: killing its PID leaves the actual vite process
# listening on the port. Killing by port is what actually frees it.
#
# uvicorn runs WITHOUT --reload here on purpose: --reload spawns its worker
# via multiprocessing, which on Windows duplicates the listening socket
# handle into that worker — killing the supervisor then leaves the worker
# silently holding the port open with no parent left to kill it through.
kill_port() {
    local port="$1"
    netstat -ano | grep -E "[:.]${port}[^0-9].*LISTENING" | awk '{print $NF}' | sort -u |
        while read -r pid; do
            taskkill //PID "$pid" //F //T >/dev/null 2>&1 || true
        done
}

pids=()
cleanup() {
    trap - EXIT INT TERM
    echo
    echo "stopping..."
    for pid in "${pids[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    kill_port "$BACKEND_PORT"
    kill_port "$FRONTEND_PORT"
}
trap cleanup EXIT INT TERM

cd "$ROOT"
echo "backend  -> http://localhost:${BACKEND_PORT}"
uv run uvicorn src.api.app:app --port "$BACKEND_PORT" &
pids+=("$!")

cd "$ROOT/webapp"
echo "frontend -> http://localhost:${FRONTEND_PORT}"
npm run dev -- --port "$FRONTEND_PORT" &
pids+=("$!")

wait
