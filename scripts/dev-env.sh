#!/usr/bin/env bash

# Shared local-development environment loading for the Go API and Workers.
# Source this file; do not execute it directly.

CTBZ_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CTBZ_PROJECT_ROOT="$(cd "${CTBZ_SCRIPT_DIR}/.." && pwd)"
CTBZ_SHARED_ENV_FILE="${BACKEND_SHARED_ENV_FILE:-${CTBZ_PROJECT_ROOT}/backend/.env}"
CTBZ_GO_ENV_FILE="${GO_BACKEND_ENV_FILE:-${CTBZ_PROJECT_ROOT}/backend-go/.env}"

ctbz_load_env_file() {
  local env_file="$1"
  if [[ -f "${env_file}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${env_file}"
    set +a
  fi
}

ctbz_load_dev_environment() {
  local variable_name
  local index
  local caller_env_names=()
  local caller_env_values=()
  local managed_names=(
    APP_ENV GO_BACKEND_HOST GO_BACKEND_PORT DATABASE_URL
    AUTH_JWT_SECRET AUTH_JWKS_URL AUTH_JWT_ISSUER AUTH_JWT_AUDIENCE
    STORAGE_PROVIDER STORAGE_BUCKET STORAGE_KEY_PREFIX
    SUPABASE_URL SUPABASE_PUBLISHABLE_KEY SUPABASE_STORAGE_SERVICE_ROLE_KEY
    SUPABASE_SECRET_KEY COMPONENT_REPO_STORAGE_PROVIDER LDRAW_ROOT
    PART_PREVIEW_GLTFPACK_PATH
    FEED_RENDER_BLENDER_PATH FEED_RENDER_TIMEOUT
    COMPONENT_IMPORT_PARSER_VERSION COMPONENT_IMPORT_SNAPSHOT_SCHEMA
    COMPONENT_IMPORT_MAX_ATTEMPTS WORKER_ID WORKER_TASK_TYPES WORKER_CONCURRENCY
    WORKER_HEALTH_CHECK_INTERVAL WORKER_POLL_INTERVAL WORKER_LEASE_DURATION
    WORKER_HEARTBEAT_INTERVAL WORKER_RETRY_DELAY
    WORKER_POLL_INTERVAL_SECONDS WORKER_LEASE_DURATION_SECONDS
    WORKER_HEARTBEAT_INTERVAL_SECONDS WORKER_RETRY_DELAY_SECONDS
  )

  # Explicit caller values have the highest priority. Shared values load first;
  # backend-go/.env can then override them for the Go-owned runtime.
  for variable_name in "${managed_names[@]}"; do
    if [[ "${!variable_name+x}" == "x" ]]; then
      caller_env_names+=("${variable_name}")
      caller_env_values+=("${!variable_name}")
    fi
  done

  ctbz_load_env_file "${CTBZ_SHARED_ENV_FILE}"
  ctbz_load_env_file "${CTBZ_GO_ENV_FILE}"

  for ((index = 0; index < ${#caller_env_names[@]}; index += 1)); do
    variable_name="${caller_env_names[index]}"
    printf -v "${variable_name}" '%s' "${caller_env_values[index]}"
    export "${variable_name}"
  done

  export APP_ENV="${APP_ENV:-development}"
  export GO_BACKEND_HOST="${GO_BACKEND_HOST:-127.0.0.1}"
  export GO_BACKEND_PORT="${GO_BACKEND_PORT:-8080}"
  export STORAGE_PROVIDER="${STORAGE_PROVIDER:-${COMPONENT_REPO_STORAGE_PROVIDER:-disabled}}"
  export STORAGE_BUCKET="${STORAGE_BUCKET:-component-artifacts}"
  # 使用仓库中已安装的固定版本工具，环境显式指定仍优先；不在启动时下载或编译。
  if [[ -z "${PART_PREVIEW_GLTFPACK_PATH:-}" && -x "${CTBZ_PROJECT_ROOT}/.tools/meshoptimizer-v1.2/gltfpack" ]]; then
    export PART_PREVIEW_GLTFPACK_PATH="${CTBZ_PROJECT_ROOT}/.tools/meshoptimizer-v1.2/gltfpack"
  fi
  # 开发环境优先发现已安装的 Blender；生产镜像应显式配置固定 4.1 可执行文件。
  if [[ -z "${FEED_RENDER_BLENDER_PATH:-}" ]]; then
    if command -v blender >/dev/null 2>&1; then
      export FEED_RENDER_BLENDER_PATH="$(command -v blender)"
    elif [[ -x "/Applications/Blender.app/Contents/MacOS/Blender" ]]; then
      export FEED_RENDER_BLENDER_PATH="/Applications/Blender.app/Contents/MacOS/Blender"
    fi
  fi
  export STORAGE_KEY_PREFIX="${STORAGE_KEY_PREFIX:-component-repo}"
}

ctbz_require_database_url() {
  if [[ -z "${DATABASE_URL:-}" ]]; then
    echo "error: DATABASE_URL is required; configure ${CTBZ_GO_ENV_FILE} or export it before startup" >&2
    exit 1
  fi
}

ctbz_python_executable() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    printf '%s\n' "${PYTHON_BIN}"
  elif [[ -x "${CTBZ_PROJECT_ROOT}/.venv-app/bin/python" ]]; then
    printf '%s\n' "${CTBZ_PROJECT_ROOT}/.venv-app/bin/python"
  elif [[ -x "${CTBZ_PROJECT_ROOT}/.venv/bin/python" ]]; then
    printf '%s\n' "${CTBZ_PROJECT_ROOT}/.venv/bin/python"
  else
    printf '%s\n' "python3"
  fi
}

ctbz_go_cache() {
  local go_cache_dir="${GOCACHE:-${TMPDIR:-/tmp}/ctbzbricks-go-cache}"
  mkdir -p "${go_cache_dir}"
  export GOCACHE="${go_cache_dir}"
}
