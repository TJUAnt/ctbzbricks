#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=dev-env.sh
source "${SCRIPT_DIR}/dev-env.sh"
ctbz_load_dev_environment
ctbz_require_database_url
ctbz_go_cache

echo "Component Notification Worker"
echo "Environment: ${APP_ENV}"
echo "Monitoring: http://${NOTIFICATION_WORKER_METRICS_HOST:-127.0.0.1}:${NOTIFICATION_WORKER_METRICS_PORT:-9091}"

cd "${CTBZ_PROJECT_ROOT}/backend-go"
# 通知进程独立编译和 exec；它不注册 Task/GLB 能力，也不依赖对象存储配置。
go build -o "${GOCACHE}/ctbzbricks-notification-worker" ./cmd/notification-worker
exec "${GOCACHE}/ctbzbricks-notification-worker"
