#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=dev-env.sh
source "${SCRIPT_DIR}/dev-env.sh"
ctbz_load_dev_environment
ctbz_require_database_url

PYTHON_EXECUTABLE="$(ctbz_python_executable)"
LEGACY_HOST="${BACKEND_HOST:-127.0.0.1}"
LEGACY_PORT="${BACKEND_PORT:-8000}"
LEGACY_APP_MODULE="${BACKEND_APP_MODULE:-src.api.main:app}"
LEGACY_RELOAD="${BACKEND_RELOAD:-1}"
export PYTHONPATH="${CTBZ_PROJECT_ROOT}/backend${PYTHONPATH:+:${PYTHONPATH}}"

ARGS=(-m uvicorn "${LEGACY_APP_MODULE}" --host "${LEGACY_HOST}" --port "${LEGACY_PORT}")
if [[ "${LEGACY_RELOAD}" == "1" || "${LEGACY_RELOAD}" == "true" || "${LEGACY_RELOAD}" == "yes" ]]; then
  ARGS+=(--reload --reload-dir "${CTBZ_PROJECT_ROOT}/backend/src" --reload-dir "${CTBZ_PROJECT_ROOT}/backend/config")
fi

echo "Legacy API: http://${LEGACY_HOST}:${LEGACY_PORT}"
echo "Python: ${PYTHON_EXECUTABLE}"

cd "${CTBZ_PROJECT_ROOT}"
exec "${PYTHON_EXECUTABLE}" "${ARGS[@]}"
