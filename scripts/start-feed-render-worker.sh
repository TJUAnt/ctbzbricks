#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 离线路径追踪属于 CPU/内存重负载；专用进程默认串行，避免与 GLB 计算任务争抢资源。
export WORKER_ID="${WORKER_ID:-feed-render}"
export WORKER_TASK_TYPES="component.feed_render.materialize"
export WORKER_CONCURRENCY="${WORKER_CONCURRENCY:-1}"
export WORKER_LEASE_DURATION="${WORKER_LEASE_DURATION:-10m}"
export WORKER_HEARTBEAT_INTERVAL="${WORKER_HEARTBEAT_INTERVAL:-30s}"
export FEED_RENDER_TIMEOUT="${FEED_RENDER_TIMEOUT:-5m}"

exec "${SCRIPT_DIR}/start-go-worker.sh"
