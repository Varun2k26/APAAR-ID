#!/usr/bin/env bash
# One command: install deps, seed (first run or --reset), build the web app, serve everything on :8000.
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
command -v npm >/dev/null || { echo "Node.js 18+ is required"; exit 1; }
(cd backend && uv sync -q)
[ -d frontend/node_modules ] || (cd frontend && npm ci --no-audit --no-fund)
if [ "${1:-}" = "--reset" ] || [ ! -f data/apaar.db ]; then
  rm -f data/apaar.db data/apaar.db-wal data/apaar.db-shm
  (cd backend && uv run python -m seed.generate)
fi
(cd frontend && npm run build --silent >/dev/null)
echo ""
echo "  APAAR Registry → http://localhost:${PORT:-8000}    API docs → http://localhost:${PORT:-8000}/docs"
echo "  Demo logins are listed on the sign-in page (synthetic data)."
echo ""
cd backend && exec uv run uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
