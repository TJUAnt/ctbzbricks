#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

HOST="${BACKEND_HOST:-127.0.0.1}"
PORT="${BACKEND_PORT:-8000}"
APP_MODULE="${BACKEND_APP_MODULE:-src.api.main:app}"
RELOAD="${BACKEND_RELOAD:-1}"

if [[ -n "${PYTHON_BIN:-}" ]]; then
  PYTHON_EXECUTABLE="${PYTHON_BIN}"
elif [[ -x "${PROJECT_ROOT}/.venv-app/bin/python" ]]; then
  PYTHON_EXECUTABLE="${PROJECT_ROOT}/.venv-app/bin/python"
elif [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
  PYTHON_EXECUTABLE="${PROJECT_ROOT}/.venv/bin/python"
else
  PYTHON_EXECUTABLE="python3"
fi

if [[ ! -f "${PROJECT_ROOT}/backend/src/.env" && ! -f "${PROJECT_ROOT}/backend/.env" ]]; then
  echo "warning: backend/src/.env or backend/.env not found; database config must come from shell env" >&2
fi

export PYTHONPATH="${PROJECT_ROOT}/backend${PYTHONPATH:+:${PYTHONPATH}}"

ARGS=(
  -m uvicorn
  "${APP_MODULE}"
  --host "${HOST}"
  --port "${PORT}"
)

if [[ "${RELOAD}" == "1" || "${RELOAD}" == "true" || "${RELOAD}" == "yes" ]]; then
  ARGS+=(
    --reload
    --reload-dir "${PROJECT_ROOT}/backend/src"
    --reload-dir "${PROJECT_ROOT}/backend/config"
  )
fi

echo "Backend: http://${HOST}:${PORT}"
echo "Python: ${PYTHON_EXECUTABLE}"
echo "Storage provider: ${COMPONENT_REPO_STORAGE_PROVIDER:-configured default}"
cd "${PROJECT_ROOT}"
exec "${PYTHON_EXECUTABLE}" "${ARGS[@]}"
