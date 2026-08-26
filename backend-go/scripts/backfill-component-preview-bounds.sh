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

confirmation="${CONFIRM_DATABASE_TARGET:-}"
if [[ -z "${confirmation}" && -t 0 ]]; then
  read -r -p "Type the exact target database value to continue: " confirmation
fi
if [[ "${confirmation}" != "${database_target}" ]]; then
  echo "error: database confirmation did not match; no migration or task was scheduled" >&2
  exit 1
fi

cd "${GO_ROOT}"
go run ./cmd/migrate up
backfill_args=(
  --batch-size "${PREVIEW_BOUNDS_BATCH_SIZE:-100}"
  --max-versions "${PREVIEW_BOUNDS_MAX_VERSIONS:-0}"
)
if [[ "${PREVIEW_BOUNDS_DRY_RUN:-0}" == "1" ]]; then
  backfill_args+=(--dry-run)
fi
go run ./cmd/preview-bounds-backfill "${backfill_args[@]}"

echo "Preview Box tasks were scheduled. Start or keep the v4 Go Worker running until they finish; do not use an older Worker."
