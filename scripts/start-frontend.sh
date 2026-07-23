#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
FRONTEND_DIR="${PROJECT_ROOT}/frontend"

HOST="${FRONTEND_HOST:-127.0.0.1}"
PORT="${FRONTEND_PORT:-5173}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
NPM_EXECUTABLE="${NPM_BIN:-npm}"

if [[ ! -d "${FRONTEND_DIR}/node_modules" ]]; then
  echo "warning: frontend/node_modules not found; run npm install in frontend first" >&2
fi

echo "Frontend: http://${HOST}:${PORT}"
echo "API proxy: /api -> ${BACKEND_URL:-http://${BACKEND_HOST}:${BACKEND_PORT}}"
cd "${FRONTEND_DIR}"
exec "${NPM_EXECUTABLE}" run dev -- --host "${HOST}" --port "${PORT}"
