#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
GO_API_PORT="${GO_BACKEND_PORT:-8080}"
LEGACY_API_PORT="${BACKEND_PORT:-8000}"
GO_API_HEALTH_URL="${GO_API_HEALTH_URL:-http://${BACKEND_HOST}:${GO_API_PORT}/health/live}"
LEGACY_API_HEALTH_URL="${LEGACY_API_HEALTH_URL:-http://${BACKEND_HOST}:${LEGACY_API_PORT}/api/health}"
BACKEND_READY_TIMEOUT_SECONDS="${BACKEND_READY_TIMEOUT_SECONDS:-60}"
START_LEGACY_API="${START_LEGACY_API:-0}"
START_COMPONENT_WORKERS="${START_COMPONENT_WORKERS:-1}"

CHILD_NAMES=()
CHILD_PIDS=()

stop_children() {
  local pid
  for pid in "${CHILD_PIDS[@]}"; do
    if kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
    fi
  done
}

trap stop_children EXIT INT TERM

start_child() {
  local name="$1"
  local launcher="$2"
  "${launcher}" &
  CHILD_NAMES+=("${name}")
  CHILD_PIDS+=("$!")
}

assert_children_running() {
  local index
  for ((index = 0; index < ${#CHILD_PIDS[@]}; index += 1)); do
    if ! kill -0 "${CHILD_PIDS[index]}" 2>/dev/null; then
      echo "${CHILD_NAMES[index]} exited during startup." >&2
      wait "${CHILD_PIDS[index]}"
    fi
  done
}

wait_for_health() {
  local name="$1"
  local url="$2"
  local attempt
  echo "Waiting for ${name} health: ${url}"
  for ((attempt = 1; attempt <= BACKEND_READY_TIMEOUT_SECONDS; attempt += 1)); do
    if curl -fsS --max-time 2 "${url}" >/dev/null 2>&1; then
      return 0
    fi
    assert_children_running
    sleep 1
  done
  echo "${name} did not become ready within ${BACKEND_READY_TIMEOUT_SECONDS}s." >&2
  return 1
}

start_child "Go API" "${SCRIPT_DIR}/start-backend.sh"

if [[ "${START_LEGACY_API}" == "1" ]]; then
  start_child "Legacy API" "${SCRIPT_DIR}/start-legacy-backend.sh"
fi

if [[ "${START_COMPONENT_WORKERS}" == "1" ]]; then
  start_child "Go Worker" "${SCRIPT_DIR}/start-go-worker.sh"
fi

wait_for_health "Go API" "${GO_API_HEALTH_URL}"
if [[ "${START_LEGACY_API}" == "1" ]]; then
  wait_for_health "Legacy API" "${LEGACY_API_HEALTH_URL}"
fi
assert_children_running

start_child "Frontend" "${SCRIPT_DIR}/start-frontend.sh"

echo
echo "Development topology started:"
echo "  Go API                 http://${BACKEND_HOST}:${GO_API_PORT}"
if [[ "${START_LEGACY_API}" == "1" ]]; then
  echo "  Legacy API             http://${BACKEND_HOST}:${LEGACY_API_PORT}"
fi
if [[ "${START_COMPONENT_WORKERS}" == "1" ]]; then
  echo "  Go Worker              12 durable task types (artifact/import/GLB/validation/relation/feed image/cleanup/pixel2d)"
fi
echo "  Frontend               http://${FRONTEND_HOST:-127.0.0.1}:${FRONTEND_PORT:-5173}"
echo
echo "Press Ctrl+C to stop the development topology."

# Waiting for any child is not portable to macOS Bash 3.2, so poll while also
# surfacing the first unexpected child exit.
while true; do
  assert_children_running
  sleep 1
done
