#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
BACKEND_HEALTH_URL="${BACKEND_HEALTH_URL:-http://${BACKEND_HOST}:${BACKEND_PORT}/api/health}"
BACKEND_READY_TIMEOUT_SECONDS="${BACKEND_READY_TIMEOUT_SECONDS:-60}"

BACKEND_PID=""
FRONTEND_PID=""

stop_children() {
  if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
    kill "${BACKEND_PID}" 2>/dev/null || true
  fi
  if [[ -n "${FRONTEND_PID}" ]] && kill -0 "${FRONTEND_PID}" 2>/dev/null; then
    kill "${FRONTEND_PID}" 2>/dev/null || true
  fi
}

trap stop_children EXIT INT TERM

"${SCRIPT_DIR}/start-backend.sh" &
BACKEND_PID="$!"

echo "Waiting for backend health: ${BACKEND_HEALTH_URL}"
BACKEND_READY=0
for ((attempt = 1; attempt <= BACKEND_READY_TIMEOUT_SECONDS; attempt += 1)); do
  if curl -fsS --max-time 2 "${BACKEND_HEALTH_URL}" >/dev/null 2>&1; then
    BACKEND_READY=1
    break
  fi
  if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
    echo "Backend process exited before becoming ready." >&2
    wait "${BACKEND_PID}"
  fi
  sleep 1
done

if [[ "${BACKEND_READY}" != "1" ]]; then
  echo "Backend did not become ready within ${BACKEND_READY_TIMEOUT_SECONDS}s." >&2
  exit 1
fi

"${SCRIPT_DIR}/start-frontend.sh" &
FRONTEND_PID="$!"

echo
echo "Dev servers starting:"
echo "  Backend  http://${BACKEND_HOST}:${BACKEND_PORT}"
echo "  Frontend http://${FRONTEND_HOST:-127.0.0.1}:${FRONTEND_PORT:-5173}"
echo
echo "Press Ctrl+C to stop both."

wait "${BACKEND_PID}" "${FRONTEND_PID}"
