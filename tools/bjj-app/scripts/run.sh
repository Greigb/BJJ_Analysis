#!/usr/bin/env bash
# Production mode: build the frontend, then start FastAPI binding to 0.0.0.0
# so your phone (on the same wifi) can reach it.

set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_ROOT"

if [ ! -d .venv ]; then
  echo "Error: .venv not found. See scripts/dev.sh for setup."
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "Building frontend..."
(cd web && npm run build)

echo
echo "Starting production server on http://0.0.0.0:8000 ..."
echo "Local: http://127.0.0.1:8000"
echo "LAN:   http://$(ipconfig getifaddr en0 2>/dev/null || echo '<your-mac-ip>'):8000"
echo
exec uvicorn server.main:app --host 0.0.0.0 --port 8000
