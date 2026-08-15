#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=dev-env.sh
source "${SCRIPT_DIR}/dev-env.sh"
ctbz_load_dev_environment
ctbz_require_database_url

PYTHON_EXECUTABLE="$(ctbz_python_executable)"
export PYTHONPATH="${CTBZ_PROJECT_ROOT}/backend${PYTHONPATH:+:${PYTHONPATH}}"

echo "Python Component Import Worker"
echo "Python: ${PYTHON_EXECUTABLE}"

cd "${CTBZ_PROJECT_ROOT}/backend"
exec "${PYTHON_EXECUTABLE}" -m src.tools.run_component_import_worker
