#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=dev-env.sh
source "${SCRIPT_DIR}/dev-env.sh"
ctbz_load_dev_environment
ctbz_require_database_url

if [[ -z "${AUTH_JWT_SECRET:-}" && -z "${AUTH_JWKS_URL:-}" && -z "${AUTH_JWT_ISSUER:-}" ]]; then
  echo "warning: JWT verification is not configured; protected /api/v1 routes will fail closed" >&2
fi

ctbz_go_cache

echo "Go backend: http://${GO_BACKEND_HOST}:${GO_BACKEND_PORT}"
echo "Environment: ${APP_ENV}"
echo "Storage provider: ${STORAGE_PROVIDER}"
echo "Shared env: $([[ -f "${CTBZ_SHARED_ENV_FILE}" ]] && echo loaded || echo missing)"
echo "Go env: $([[ -f "${CTBZ_GO_ENV_FILE}" ]] && echo loaded || echo missing)"

cd "${CTBZ_PROJECT_ROOT}/backend-go"
exec go run ./cmd/api
