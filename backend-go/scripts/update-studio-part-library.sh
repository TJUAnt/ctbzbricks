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

STUDIO_ROOT="${STUDIO_ROOT:-/Applications/Studio 2.0}"
STUDIO_MANIFEST_OUT_DIR="${STUDIO_MANIFEST_OUT_DIR:-${TMPDIR:-/tmp}/ctbzbricks-studio-manifest}"
SKIP_STUDIO_DRY_RUN="${SKIP_STUDIO_DRY_RUN:-0}"
STUDIO_COLLIDER_STORAGE="${STUDIO_COLLIDER_STORAGE:-metadata-only}"
FORCE_STUDIO_REIMPORT="${FORCE_STUDIO_REIMPORT:-0}"
# importer v4 会固化规范化描述和可解释标称尺寸；仅比较 manifest hash 会错误跳过这次可重建投影升级。
STUDIO_IMPORTER_VERSION="studio-part-library-importer-v4"

if [[ ! -d "${STUDIO_ROOT}" ]]; then
  echo "error: Studio root does not exist: ${STUDIO_ROOT}" >&2
  exit 1
fi
if ! command -v psql >/dev/null 2>&1; then
  echo "error: psql is required to identify and verify the target database" >&2
  exit 1
fi

database_target="$(psql "${DATABASE_URL}" -X -A -t -v ON_ERROR_STOP=1 \
  -c "SELECT current_database() || '@' || COALESCE(inet_server_addr()::text, 'local') || ':' || inet_server_port();")"

echo "Target database: ${database_target}"
echo "Studio source:   ${STUDIO_ROOT}"
echo "Manifest output: ${STUDIO_MANIFEST_OUT_DIR}"
echo "Collider mode:   ${STUDIO_COLLIDER_STORAGE}"

confirmation="${CONFIRM_DATABASE_TARGET:-}"
if [[ -z "${confirmation}" && -t 0 ]]; then
  read -r -p "Type the exact target database value to continue: " confirmation
fi
if [[ "${confirmation}" != "${database_target}" ]]; then
  echo "error: database confirmation did not match; no migration or import was run" >&2
  echo "For non-interactive use, set CONFIRM_DATABASE_TARGET='${database_target}'" >&2
  exit 1
fi

mkdir -p "${STUDIO_MANIFEST_OUT_DIR}"
cd "${GO_ROOT}"

go run ./cmd/studio-manifest \
  --studio-root "${STUDIO_ROOT}" \
  --out-dir "${STUDIO_MANIFEST_OUT_DIR}"

manifest_path="${STUDIO_MANIFEST_OUT_DIR}/studio_manifest.json"
manifest_hash="$(sed -n 's/.*"manifestSha256"[[:space:]]*:[[:space:]]*"\([0-9a-f]*\)".*/\1/p' "${manifest_path}" | head -n 1)"
if [[ -z "${manifest_hash}" ]]; then
  echo "error: generated manifest does not contain manifestSha256" >&2
  exit 1
fi

go run ./cmd/migrate up

active_state="$(psql "${DATABASE_URL}" -X -A -t -F '|' -v ON_ERROR_STOP=1 -c "
  SELECT source_hash, relation_ready::text, metadata->>'studioImporterVersion'
  FROM component_repo.part_library_versions
  WHERE status = 'active'
  ORDER BY created_at DESC, id DESC
  LIMIT 1;
")"
if [[ "${FORCE_STUDIO_REIMPORT}" != "1" && "${active_state}" == "${manifest_hash}|true|${STUDIO_IMPORTER_VERSION}" ]]; then
  echo "Part Library is already active and relation-ready for manifest ${manifest_hash}; no import is needed."
  echo "Set FORCE_STUDIO_REIMPORT=1 only for a deliberate rebuild."
  exit 0
fi

if [[ "${SKIP_STUDIO_DRY_RUN}" != "1" ]]; then
  go run ./cmd/studio-import \
    --manifest "${manifest_path}" \
    --collider-storage "${STUDIO_COLLIDER_STORAGE}" \
    --dry-run
fi

go run ./cmd/studio-import \
  --manifest "${manifest_path}" \
  --collider-storage "${STUDIO_COLLIDER_STORAGE}" \
  --status active

psql "${DATABASE_URL}" -X -P pager=off -v ON_ERROR_STOP=1 -c "
  SELECT id, source_name, source_hash, status,
         preview_ready, relation_ready,
         connector_count, collider_count,
         connector_parser_version, collider_parser_version,
         created_at
  FROM component_repo.part_library_versions
  ORDER BY (status = 'active') DESC, created_at DESC, id DESC;
"
