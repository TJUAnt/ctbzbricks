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
       version.id AS draft_version_id
FROM component_repo.imports import_job
LEFT JOIN component_repo.candidates candidate
  ON candidate.import_id = import_job.id
LEFT JOIN component_repo.component_versions version
  ON version.component_candidate_id = candidate.id
 AND version.deleted_at IS NULL
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
