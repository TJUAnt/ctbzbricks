#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -n "${PYTHON_BIN:-}" ]]; then
  PYTHON_EXECUTABLE="${PYTHON_BIN}"
elif [[ -x "${PROJECT_ROOT}/.venv-app/bin/python" ]]; then
  PYTHON_EXECUTABLE="${PROJECT_ROOT}/.venv-app/bin/python"
elif [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
  PYTHON_EXECUTABLE="${PROJECT_ROOT}/.venv/bin/python"
else
  PYTHON_EXECUTABLE="python3"
fi

export PYTHONPATH="${PROJECT_ROOT}/backend${PYTHONPATH:+:${PYTHONPATH}}"

echo "Applying backend database migrations..."
echo "Python: ${PYTHON_EXECUTABLE}"
cd "${PROJECT_ROOT}/backend"
exec "${PYTHON_EXECUTABLE}" -m alembic -c alembic.ini upgrade head
