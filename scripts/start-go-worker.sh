#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=dev-env.sh
source "${SCRIPT_DIR}/dev-env.sh"
ctbz_load_dev_environment
ctbz_require_database_url
ctbz_go_cache

echo "Go Worker"
echo "Environment: ${APP_ENV}"
echo "Storage provider: ${STORAGE_PROVIDER}"
if [[ -n "${LDRAW_ROOT:-}" ]]; then
  echo "Part preview capability: enabled"
else
  echo "Part preview capability: disabled (LDRAW_ROOT is not set)"
fi

cd "${CTBZ_PROJECT_ROOT}/backend-go"
# 直接 exec 编译产物，使上层启动器发送的退出信号到达服务本身，避免 go run 子进程残留。
go build -o "${GOCACHE}/ctbzbricks-worker" ./cmd/worker
exec "${GOCACHE}/ctbzbricks-worker"
