#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${GO_ROOT}/.." && pwd)"

# shellcheck source=../../scripts/dev-env.sh
source "${PROJECT_ROOT}/scripts/dev-env.sh"
ctbz_load_dev_environment
ctbz_require_database_url
ctbz_go_cache

if [[ -z "${PART_PREVIEW_GLTFPACK_PATH:-}" ]]; then
  native_path="${PROJECT_ROOT}/.tools/meshoptimizer-v1.2/gltfpack"
  npm_path="${PROJECT_ROOT}/.tools/gltfpack-npm-v1.2.0/cli.js"
  if [[ -x "${native_path}" ]]; then
    export PART_PREVIEW_GLTFPACK_PATH="${native_path}"
  elif [[ -x "${npm_path}" ]]; then
    export PART_PREVIEW_GLTFPACK_PATH="${npm_path}"
  else
    echo "error: install gltfpack or set PART_PREVIEW_GLTFPACK_PATH" >&2
    exit 1
  fi
fi

# 专用 Worker 只消费预生成任务，避免维护期间推进未授权的 Import/Artifact 任务。
export WORKER_ID="${WORKER_ID:-part-preview-prebuild}"
export WORKER_TASK_TYPES="component.part_preview.prebuild"
export WORKER_CONCURRENCY="1"
# Supabase session pool 较小；专用 Worker 复用一个 session，几何/Storage 仍在 Handler 内 8 路并发。
export DATABASE_POOL_MIN_CONNS="1"
export DATABASE_POOL_MAX_CONNS="${PART_PREVIEW_DATABASE_MAX_CONNS:-1}"
# 远程 pooler 的批量准备可能超过 30 秒；较长 lease 防止健康连接排队时被误判为失联。
export WORKER_LEASE_DURATION="${PART_PREVIEW_WORKER_LEASE_DURATION:-5m}"
export WORKER_HEARTBEAT_INTERVAL="${PART_PREVIEW_WORKER_HEARTBEAT_INTERVAL:-30s}"

cd "${GO_ROOT}"
exec go run ./cmd/worker
