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
echo "Worker: not started by this launcher; use scripts/start-go-worker.sh or scripts/start-dev.sh"

cd "${CTBZ_PROJECT_ROOT}/backend-go"
# 直接 exec 编译产物，使上层启动器发送的退出信号到达服务本身，避免 go run 子进程残留。
go build -o "${GOCACHE}/ctbzbricks-api" ./cmd/api
exec "${GOCACHE}/ctbzbricks-api"
