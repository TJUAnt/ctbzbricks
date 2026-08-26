#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${GO_ROOT}/.." && pwd)"

# shellcheck source=../../scripts/dev-env.sh
source "${PROJECT_ROOT}/scripts/dev-env.sh"
ctbz_load_dev_environment
ctbz_require_database_url

if ! command -v psql >/dev/null 2>&1; then
  echo "error: psql is required" >&2
  exit 1
fi

database_target="$(psql "${DATABASE_URL}" -X -A -t -v ON_ERROR_STOP=1 \
  -c "SELECT current_database() || '@' || COALESCE(inet_server_addr()::text, 'local') || ':' || inet_server_port();")"

echo "Target database: ${database_target}"
echo "Cleanup scope: public.connector_instances, public.ldraw_part_geometry, public.xref_part_numbers"
echo "Blocked parents are intentionally preserved: public.part_connector_definitions, public.ldraw_files, public.ldraw_parts, public.ldraw_shadow_meta_raw, public.ldraw_shadow_files"

# 默认只盘点。该查询同时证明 Go active Part Library 已具备 Parts、geometry 与 connector 数据，
# 避免在迁移目标不完整时清空 legacy 来源。
psql "${DATABASE_URL}" -X -v ON_ERROR_STOP=1 -P pager=off \
  -c "SELECT pg_size_pretty(pg_database_size(current_database())) AS database_size, pg_database_size(current_database()) AS database_bytes;" \
  -c "SELECT id, status, source_name FROM component_repo.part_library_versions WHERE status = 'active';" \
  -c "SELECT 'public.connector_instances' AS relation, count(*) AS rows, pg_size_pretty(pg_total_relation_size('public.connector_instances')) AS total_size FROM public.connector_instances UNION ALL SELECT 'public.ldraw_part_geometry', count(*), pg_size_pretty(pg_total_relation_size('public.ldraw_part_geometry')) FROM public.ldraw_part_geometry UNION ALL SELECT 'public.xref_part_numbers', count(*), pg_size_pretty(pg_total_relation_size('public.xref_part_numbers')) FROM public.xref_part_numbers;"

if [[ "${PUBLIC_PART_SOURCE_CLEANUP_EXECUTE:-0}" != "1" ]]; then
  echo "Dry run only. Set PUBLIC_PART_SOURCE_CLEANUP_EXECUTE=1 and CONFIRM_DATABASE_TARGET to execute."
  exit 0
fi
if [[ "${CONFIRM_DATABASE_TARGET:-}" != "${database_target}" ]]; then
  echo "error: CONFIRM_DATABASE_TARGET did not match; no data was changed" >&2
  exit 1
fi

backup_dir="${PUBLIC_PART_SOURCE_CLEANUP_BACKUP_DIR:-${TMPDIR:-/tmp}/brickbuilder-public-part-source-$(date -u +%Y%m%dT%H%M%SZ)}"
if [[ "${backup_dir}" != /* || "${backup_dir}" == *"'"* ]]; then
  echo "error: backup directory must be an absolute path without a single quote" >&2
  exit 1
fi
if [[ -e "${backup_dir}" && "${PUBLIC_PART_SOURCE_CLEANUP_REUSE_BACKUP:-0}" != "1" ]]; then
  echo "error: backup directory already exists: ${backup_dir}" >&2
  exit 1
fi

# TRUNCATE 会立即释放表页；先用客户端 COPY 保存带列头的 CSV。Supabase Pooler 会中断较长的
# 单次 COPY，因此按稳定 bigint 主键排序并分片，每片使用独立短连接；分片总行数必须与清理前一致。
backup_manifest="${backup_dir}/MANIFEST.csv"

backup_table() {
  local table_name="$1"
  local chunk_size=2000
  local expected_rows
  local copied_rows=0
  local chunk_number=0
  local copy_output
  local current_rows
  local backup_file

  expected_rows="$(psql "${DATABASE_URL}" -X -A -t -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM public.${table_name};")"
  while (( copied_rows < expected_rows )); do
    chunk_number=$((chunk_number + 1))
    backup_file="${backup_dir}/${table_name}-$(printf '%04d' "${chunk_number}").csv"
    copy_output="$(psql "${DATABASE_URL}" -X -v ON_ERROR_STOP=1 \
      -c "\copy (SELECT * FROM public.${table_name} ORDER BY id OFFSET ${copied_rows} LIMIT ${chunk_size}) TO '${backup_file}' WITH (FORMAT csv, HEADER true)")"
    current_rows="$(printf '%s\n' "${copy_output}" | awk '$1 == "COPY" {print $2}')"
    if [[ ! "${current_rows}" =~ ^[1-9][0-9]*$ ]]; then
      echo "error: invalid COPY row count for public.${table_name}: ${copy_output}" >&2
      exit 1
    fi
    copied_rows=$((copied_rows + current_rows))
  done
  if (( copied_rows != expected_rows )); then
    echo "error: backup row count mismatch for public.${table_name}: expected=${expected_rows} copied=${copied_rows}" >&2
    exit 1
  fi
  printf '%s,%s,%s\n' "${table_name}" "${expected_rows}" "${chunk_number}" >> "${backup_manifest}"
}

if [[ "${PUBLIC_PART_SOURCE_CLEANUP_REUSE_BACKUP:-0}" == "1" ]]; then
  if [[ ! -d "${backup_dir}" || ! -s "${backup_manifest}" ]]; then
    echo "error: reusable backup manifest is missing: ${backup_manifest}" >&2
    exit 1
  fi
  echo "Reusing completed backup shards: ${backup_dir}"
else
  mkdir "${backup_dir}"
  printf 'table,rows,chunks\n' > "${backup_manifest}"
  backup_table connector_instances
  backup_table ldraw_part_geometry
  backup_table xref_part_numbers
fi

validate_backup_table() {
  local table_name="$1"
  local current_rows
  local manifest_rows
  local manifest_chunks
  local actual_chunks

  current_rows="$(psql "${DATABASE_URL}" -X -A -t -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM public.${table_name};")"
  manifest_rows="$(awk -F, -v table_name="${table_name}" '$1 == table_name {print $2}' "${backup_manifest}")"
  manifest_chunks="$(awk -F, -v table_name="${table_name}" '$1 == table_name {print $3}' "${backup_manifest}")"
  actual_chunks="$(find "${backup_dir}" -maxdepth 1 -type f -name "${table_name}-*.csv" | wc -l | tr -d ' ')"
  if [[ "${manifest_rows}" != "${current_rows}" || "${manifest_chunks}" != "${actual_chunks}" ]]; then
    echo "error: reusable backup mismatch for public.${table_name}: current=${current_rows} manifest=${manifest_rows} chunks=${manifest_chunks}/${actual_chunks}" >&2
    exit 1
  fi
}

validate_backup_table connector_instances
validate_backup_table ldraw_part_geometry
validate_backup_table xref_part_numbers

for backup_file in "${backup_dir}"/*.csv; do
  if [[ ! -s "${backup_file}" ]]; then
    echo "error: backup file is empty: ${backup_file}" >&2
    exit 1
  fi
done
(cd "${backup_dir}" && LC_ALL=C shasum -a 256 ./*.csv > SHA256SUMS)
echo "Recovery backup: ${backup_dir}"

psql "${DATABASE_URL}" -X -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
SELECT pg_advisory_xact_lock(hashtext('brickbuilder.public_part_source_cleanup'));

DO $cleanup$
DECLARE
  active_library_count bigint;
  active_part_count bigint;
  active_geometry_count bigint;
  active_connector_count bigint;
  unexpected_dependents text;
BEGIN
  SELECT count(*) INTO active_library_count
  FROM component_repo.part_library_versions
  WHERE status = 'active';

  SELECT count(*) INTO active_part_count
  FROM component_repo.parts p
  JOIN component_repo.part_library_versions v ON v.id = p.part_library_version_id
  WHERE v.status = 'active';

  SELECT count(*) INTO active_geometry_count
  FROM component_repo.part_geometries g
  JOIN component_repo.part_library_versions v ON v.id = g.part_library_version_id
  WHERE v.status = 'active';

  SELECT count(*) INTO active_connector_count
  FROM component_repo.part_connector_definitions d
  JOIN component_repo.part_library_versions v ON v.id = d.part_library_version_id
  WHERE v.status = 'active';

  IF active_library_count <> 1 OR active_part_count = 0 OR active_geometry_count = 0 OR active_connector_count = 0 THEN
    RAISE EXCEPTION 'Go active Part Library invariant failed; cleanup aborted';
  END IF;

  -- 不使用 CASCADE；如果未来出现新的外键子表，维护命令必须停止并重新审计影响范围。
  SELECT string_agg(format('%I.%I', tc.table_schema, tc.table_name), ', ' ORDER BY tc.table_schema, tc.table_name)
  INTO unexpected_dependents
  FROM information_schema.table_constraints tc
  JOIN information_schema.referential_constraints rc
    ON rc.constraint_schema = tc.constraint_schema
   AND rc.constraint_name = tc.constraint_name
  JOIN information_schema.constraint_column_usage ccu
    ON ccu.constraint_schema = rc.unique_constraint_schema
   AND ccu.constraint_name = rc.unique_constraint_name
  WHERE tc.constraint_type = 'FOREIGN KEY'
    AND ccu.table_schema = 'public'
    AND ccu.table_name IN ('connector_instances', 'ldraw_part_geometry', 'xref_part_numbers');

  IF unexpected_dependents IS NOT NULL THEN
    RAISE EXCEPTION 'Unexpected dependent tables: %; cleanup aborted', unexpected_dependents;
  END IF;
END
$cleanup$;

TRUNCATE TABLE
  public.connector_instances,
  public.ldraw_part_geometry,
  public.xref_part_numbers;
COMMIT;
SQL

psql "${DATABASE_URL}" -X -v ON_ERROR_STOP=1 -P pager=off \
  -c "SELECT pg_size_pretty(pg_database_size(current_database())) AS database_size, pg_database_size(current_database()) AS database_bytes;" \
  -c "SELECT 'public.connector_instances' AS relation, count(*) AS rows FROM public.connector_instances UNION ALL SELECT 'public.ldraw_part_geometry', count(*) FROM public.ldraw_part_geometry UNION ALL SELECT 'public.xref_part_numbers', count(*) FROM public.xref_part_numbers;"

echo "Cleanup completed. The five blocked parent tables and all out-of-scope child tables were preserved."
