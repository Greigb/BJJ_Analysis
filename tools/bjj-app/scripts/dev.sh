#!/usr/bin/env bash
# Run backend (FastAPI on :8000) and frontend (Vite on :5173) concurrently.
# Ctrl-C stops both.

set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_ROOT"

if [ ! -d .venv ]; then
  echo "Error: .venv not found. Run: python3.11 -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'"
  exit 1
fi

if [ ! -d web/node_modules ]; then
  echo "Error: web/node_modules not found. Run: cd web && npm install"
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

pids=()
trap 'kill "${pids[@]}" 2>/dev/null || true' INT TERM EXIT

echo "Starting FastAPI backend on http://127.0.0.1:8000 ..."
uvicorn server.main:app --reload --host 127.0.0.1 --port 8000 &
pids+=($!)

echo "Starting SvelteKit frontend on http://127.0.0.1:5173 ..."
(cd web && npm run dev) &
pids+=($!)

echo
echo "Backend:  http://127.0.0.1:8000/api/health"
echo "Frontend: http://127.0.0.1:5173   (open this in your browser)"
echo
echo "Ctrl-C to stop both."
wait
