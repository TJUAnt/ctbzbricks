-- name: GetActivePartLibraryVersion :one
SELECT id
FROM component_repo.part_library_versions
WHERE status = 'active'
ORDER BY created_at DESC, id
LIMIT 1;

-- name: CreateComponentImport :one
INSERT INTO component_repo.imports (
    id, owner_id, source_artifact_id, exchange_artifact_id,
    target_component_id, base_version_id, status, parser_version,
    part_library_version_id, locale, timezone, metadata, created_by,
    upload_session_id, parse_task_id
) VALUES (
    sqlc.arg(id), sqlc.arg(owner_id), sqlc.arg(source_artifact_id),
    sqlc.narg(exchange_artifact_id), sqlc.narg(target_component_id),
    sqlc.narg(base_version_id), 'queued', sqlc.arg(parser_version),
    sqlc.narg(part_library_version_id), sqlc.arg(locale), sqlc.arg(timezone),
    sqlc.arg(metadata), sqlc.arg(created_by), sqlc.arg(upload_session_id),
    sqlc.arg(parse_task_id)
)
RETURNING id, owner_id, source_artifact_id, exchange_artifact_id,
          target_component_id, base_version_id, status, parser_version,
          part_library_version_id, locale, timezone, failure_code, failure_params,
          metadata, created_by, created_at, started_at, completed_at,
          upload_session_id, parse_task_id;

-- name: GetOwnedImport :one
SELECT import_job.id, import_job.owner_id, import_job.source_artifact_id,
       import_job.exchange_artifact_id, import_job.target_component_id,
       import_job.base_version_id, import_job.status, import_job.parser_version,
       import_job.part_library_version_id, import_job.locale, import_job.timezone,
       import_job.failure_code, import_job.failure_params, import_job.metadata,
       import_job.created_by, import_job.created_at, import_job.started_at,
       import_job.completed_at, import_job.upload_session_id,
       import_job.parse_task_id, candidate.id AS candidate_id,
       version.id AS draft_version_id,
       candidate.scene_snapshot_id,
       version.preview_task_id,
       version.preview_artifact_id,
       COALESCE(version.preview_status, '')::text AS preview_status,
       version.preview_failure_code,
       version.preview_failure_params,
       preview_task.status AS preview_task_status,
       preview_task.error_code AS preview_task_error_code,
       preview_task.error_params AS preview_task_error_params,
       preview_artifact.verification_status AS preview_artifact_verification_status
FROM component_repo.imports import_job
LEFT JOIN component_repo.candidates candidate
  ON candidate.import_id = import_job.id
LEFT JOIN LATERAL (
    SELECT version_record.id, version_record.component_id,
           version_record.preview_task_id, version_record.preview_artifact_id,
           version_record.preview_status,
           version_record.preview_failure_code,
           version_record.preview_failure_params
    FROM component_repo.component_versions version_record
    WHERE version_record.component_candidate_id = candidate.id
    -- Import 是审计历史：优先当前 Version，但 Version 软删除后仍保留最近的 Component 关联。
    ORDER BY (version_record.deleted_at IS NULL) DESC,
             version_record.created_at DESC, version_record.id DESC
    LIMIT 1
) version ON true
LEFT JOIN component_repo.tasks preview_task
  ON preview_task.id = version.preview_task_id
 AND preview_task.owner_id = import_job.owner_id
LEFT JOIN component_repo.artifacts preview_artifact
  ON preview_artifact.id = version.preview_artifact_id
 AND preview_artifact.owner_id = import_job.owner_id
 AND preview_artifact.deleted_at IS NULL
WHERE import_job.id = sqlc.arg(import_id)
  AND import_job.owner_id = sqlc.arg(actor_id);

-- name: GetOwnedImportByUploadSession :one
SELECT import_job.id, import_job.owner_id, import_job.source_artifact_id,
       import_job.exchange_artifact_id, import_job.target_component_id,
       import_job.base_version_id, import_job.status, import_job.parser_version,
       import_job.part_library_version_id, import_job.locale, import_job.timezone,
       import_job.failure_code, import_job.failure_params, import_job.metadata,
       import_job.created_by, import_job.created_at, import_job.started_at,
       import_job.completed_at, import_job.upload_session_id,
       import_job.parse_task_id
FROM component_repo.imports import_job
WHERE import_job.upload_session_id = sqlc.arg(upload_session_id)
  AND import_job.owner_id = sqlc.arg(actor_id);

-- name: ListOwnedImports :many
-- Import 状态是解析、Draft 与 Preview 制品的聚合结果；组件筛选同时覆盖“更新既有组件”和“导入后新建组件”两条关联路径。
WITH import_views AS (
    SELECT import_job.id, import_job.owner_id, import_job.source_artifact_id,
           import_job.exchange_artifact_id, import_job.target_component_id,
           import_job.base_version_id, import_job.status, import_job.parser_version,
           import_job.part_library_version_id, import_job.locale, import_job.timezone,
           import_job.failure_code, import_job.failure_params, import_job.metadata,
           import_job.created_by, import_job.created_at, import_job.started_at,
           import_job.completed_at, import_job.upload_session_id,
           import_job.parse_task_id, source_artifact.original_filename,
           source_artifact.file_size, source_artifact.mime_type,
           candidate.id AS candidate_id, candidate.scene_snapshot_id,
           version.id AS draft_version_id, version.component_id,
           version.preview_task_id, version.preview_artifact_id,
           COALESCE(version.preview_status, '')::text AS preview_status,
           version.preview_failure_code,
           version.preview_failure_params,
           preview_task.status AS preview_task_status,
           preview_task.error_code AS preview_task_error_code,
           preview_task.error_params AS preview_task_error_params,
           preview_artifact.verification_status AS preview_artifact_verification_status,
           CASE
               WHEN import_job.status IN ('failed', 'cancelled')
                 OR version.preview_status = 'failed'
                 OR preview_task.status IN ('failed', 'cancelled') THEN 'failed'
               WHEN import_job.status = 'succeeded'
                 AND candidate.id IS NOT NULL
                 AND version.id IS NOT NULL
                 AND candidate.scene_snapshot_id IS NOT NULL
                 AND version.preview_artifact_id IS NOT NULL
                 AND version.preview_status = 'ready'
                 AND preview_artifact.verification_status = 'verified' THEN 'ready'
               ELSE 'processing'
           END::text AS processing_status
    FROM component_repo.imports import_job
    JOIN component_repo.artifacts source_artifact
      ON source_artifact.id = import_job.source_artifact_id
     AND source_artifact.owner_id = import_job.owner_id
    LEFT JOIN component_repo.candidates candidate
      ON candidate.import_id = import_job.id
     AND candidate.owner_id = import_job.owner_id
    LEFT JOIN LATERAL (
        SELECT version_record.id, version_record.component_id,
               version_record.preview_task_id, version_record.preview_artifact_id,
               version_record.preview_status,
               version_record.preview_failure_code,
               version_record.preview_failure_params
        FROM component_repo.component_versions version_record
        WHERE version_record.component_candidate_id = candidate.id
        ORDER BY (version_record.deleted_at IS NULL) DESC,
                 version_record.created_at DESC, version_record.id DESC
        LIMIT 1
    ) version ON true
    LEFT JOIN component_repo.tasks preview_task
      ON preview_task.id = version.preview_task_id
     AND preview_task.owner_id = import_job.owner_id
    LEFT JOIN component_repo.artifacts preview_artifact
      ON preview_artifact.id = version.preview_artifact_id
     AND preview_artifact.owner_id = import_job.owner_id
     AND preview_artifact.deleted_at IS NULL
    WHERE import_job.owner_id = sqlc.arg(actor_id)
)
SELECT *
FROM import_views
WHERE (sqlc.narg(component_id)::uuid IS NULL
       OR COALESCE(target_component_id, component_id) = sqlc.narg(component_id)::uuid)
  AND (sqlc.arg(processing_status)::text = ''
       OR import_views.processing_status = sqlc.arg(processing_status)::text)
  AND (
      sqlc.arg(search_query)::text = ''
      OR original_filename ILIKE '%' || sqlc.arg(search_query)::text || '%'
      OR id::text ILIKE '%' || sqlc.arg(search_query)::text || '%'
  )
ORDER BY created_at DESC, id DESC
LIMIT sqlc.arg(page_size) OFFSET sqlc.arg(page_offset);

-- name: CountOwnedImportProcessingStatuses :many
-- 统计口径必须与列表的聚合状态一致，但不应用当前状态筛选，供前端切换筛选时保持完整计数。
WITH import_views AS (
    SELECT import_job.id, import_job.target_component_id,
           source_artifact.original_filename,
           version.component_id,
           CASE
               WHEN import_job.status IN ('failed', 'cancelled')
                 OR version.preview_status = 'failed'
                 OR preview_task.status IN ('failed', 'cancelled') THEN 'failed'
               WHEN import_job.status = 'succeeded'
                 AND candidate.id IS NOT NULL
                 AND version.id IS NOT NULL
                 AND candidate.scene_snapshot_id IS NOT NULL
                 AND version.preview_artifact_id IS NOT NULL
                 AND version.preview_status = 'ready'
                 AND preview_artifact.verification_status = 'verified' THEN 'ready'
               ELSE 'processing'
           END::text AS processing_status
    FROM component_repo.imports import_job
    JOIN component_repo.artifacts source_artifact
      ON source_artifact.id = import_job.source_artifact_id
     AND source_artifact.owner_id = import_job.owner_id
    LEFT JOIN component_repo.candidates candidate
      ON candidate.import_id = import_job.id
     AND candidate.owner_id = import_job.owner_id
    LEFT JOIN LATERAL (
        SELECT version_record.id, version_record.component_id,
               version_record.preview_task_id, version_record.preview_artifact_id,
               version_record.preview_status
        FROM component_repo.component_versions version_record
        WHERE version_record.component_candidate_id = candidate.id
        ORDER BY (version_record.deleted_at IS NULL) DESC,
                 version_record.created_at DESC, version_record.id DESC
        LIMIT 1
    ) version ON true
    LEFT JOIN component_repo.tasks preview_task
      ON preview_task.id = version.preview_task_id
     AND preview_task.owner_id = import_job.owner_id
    LEFT JOIN component_repo.artifacts preview_artifact
      ON preview_artifact.id = version.preview_artifact_id
     AND preview_artifact.owner_id = import_job.owner_id
     AND preview_artifact.deleted_at IS NULL
    WHERE import_job.owner_id = sqlc.arg(actor_id)
)
SELECT processing_status, count(*)::bigint AS import_count
FROM import_views
WHERE (sqlc.narg(component_id)::uuid IS NULL
       OR COALESCE(target_component_id, component_id) = sqlc.narg(component_id)::uuid)
  AND (
      sqlc.arg(search_query)::text = ''
      OR original_filename ILIKE '%' || sqlc.arg(search_query)::text || '%'
      OR id::text ILIKE '%' || sqlc.arg(search_query)::text || '%'
  )
GROUP BY processing_status
ORDER BY processing_status;

-- name: GetOwnedCandidate :one
SELECT candidate.id, candidate.owner_id, candidate.import_id,
       candidate.scene_snapshot_id, candidate.status, candidate.summary,
       candidate.review_decisions, candidate.interface_signature,
       candidate.structure_hash, candidate.geometry_hash,
       candidate.created_at, candidate.updated_at,
       snapshot.schema_version, snapshot.parser_version,
       snapshot.root_model_id, snapshot.document, snapshot.bom,
       snapshot.parse_issues, snapshot.created_at AS snapshot_created_at,
       version.id AS draft_version_id, version.component_id
FROM component_repo.candidates candidate
JOIN component_repo.scene_snapshots snapshot
  ON snapshot.id = candidate.scene_snapshot_id
 AND snapshot.import_id = candidate.import_id
LEFT JOIN component_repo.component_versions version
  ON version.component_candidate_id = candidate.id
 AND version.deleted_at IS NULL
WHERE candidate.id = sqlc.arg(candidate_id)
  AND candidate.owner_id = sqlc.arg(actor_id);
