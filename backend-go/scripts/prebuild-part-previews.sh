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

if ! command -v psql >/dev/null 2>&1; then
  echo "error: psql is required to identify the target database" >&2
  exit 1
fi

database_target="$(psql "${DATABASE_URL}" -X -A -t -v ON_ERROR_STOP=1 \
  -c "SELECT current_database() || '@' || COALESCE(inet_server_addr()::text, 'local') || ':' || inet_server_port();")"
echo "Target database: ${database_target}"
echo "Target storage: ${STORAGE_PROVIDER:-disabled}/${STORAGE_BUCKET:-component-artifacts}/${STORAGE_KEY_PREFIX:-component-repo}/part-library-assets"

cd "${GO_ROOT}"
if [[ -n "${PART_LIBRARY_VERSION_ID:-}" ]]; then
  go run ./cmd/part-preview-prebuild --part-library-version-id "${PART_LIBRARY_VERSION_ID}"
else
  go run ./cmd/part-preview-prebuild
fi

if [[ "${PART_PREVIEW_PREBUILD_EXECUTE:-0}" != "1" ]]; then
  echo "Dry run only. Set PART_PREVIEW_PREBUILD_EXECUTE=1 and CONFIRM_DATABASE_TARGET to schedule the task."
  exit 0
fi
if [[ "${CONFIRM_DATABASE_TARGET:-}" != "${database_target}" ]]; then
  echo "error: CONFIRM_DATABASE_TARGET did not match; no task was scheduled" >&2
  exit 1
fi
prebuild_args=(--execute)
if [[ -n "${PART_LIBRARY_VERSION_ID:-}" ]]; then
  prebuild_args+=(--part-library-version-id "${PART_LIBRARY_VERSION_ID}")
fi
if [[ "${PART_PREVIEW_PREBUILD_FORCE:-0}" == "1" ]]; then
  prebuild_args+=(--force)
fi
go run ./cmd/part-preview-prebuild "${prebuild_args[@]}"
echo "Part Preview prebuild task scheduled. Keep the Go Worker with gltfpack running until the task finishes."
