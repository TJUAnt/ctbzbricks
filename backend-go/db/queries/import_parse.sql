-- name: GetImportParseInput :one
SELECT import_job.id, import_job.owner_id, import_job.source_artifact_id,
       import_job.exchange_artifact_id, import_job.target_component_id,
       import_job.base_version_id, import_job.status, import_job.parser_version,
       import_job.part_library_version_id, import_job.locale,
       import_job.timezone, import_job.created_by, import_job.parse_task_id,
       source_artifact.original_filename AS source_filename,
       source_artifact.storage_provider AS source_storage_provider,
       source_artifact.storage_bucket AS source_storage_bucket,
       source_artifact.storage_key AS source_storage_key,
       source_artifact.sha256 AS source_sha256,
       source_artifact.artifact_type AS source_artifact_type,
       source_artifact.verification_status AS source_verification_status,
       source_artifact.immutable AS source_immutable,
       source_artifact.deleted_at AS source_deleted_at,
       parse_artifact.id AS parse_artifact_id,
       parse_artifact.artifact_type AS parse_artifact_type,
       parse_artifact.original_filename AS parse_filename,
       parse_artifact.storage_key AS parse_storage_key,
       parse_artifact.sha256 AS parse_sha256,
       parse_artifact.verification_status AS parse_verification_status,
       parse_artifact.deleted_at AS parse_deleted_at
FROM component_repo.imports import_job
JOIN component_repo.artifacts source_artifact
  ON source_artifact.id = import_job.source_artifact_id
 AND source_artifact.owner_id = import_job.owner_id
JOIN component_repo.artifacts parse_artifact
  ON parse_artifact.id = COALESCE(import_job.exchange_artifact_id, import_job.source_artifact_id)
 AND parse_artifact.owner_id = import_job.owner_id
WHERE import_job.id = sqlc.arg(import_id)
  AND import_job.owner_id = sqlc.arg(owner_id)
  AND import_job.parse_task_id = sqlc.arg(parse_task_id);

-- name: LockImportForParse :one
SELECT id, owner_id, source_artifact_id, exchange_artifact_id,
       target_component_id, base_version_id, status, parser_version,
       part_library_version_id, locale, timezone, failure_code,
       failure_params, metadata, created_by, created_at, started_at,
       completed_at, upload_session_id, parse_task_id
FROM component_repo.imports
WHERE id = sqlc.arg(import_id)
FOR UPDATE;

-- name: GetExistingCandidateVersionForImport :one
SELECT candidate.id AS candidate_id,
       version.id AS version_id,
       version.component_id,
       version.scene_snapshot_id
FROM component_repo.candidates candidate
JOIN component_repo.component_versions version
  ON version.component_candidate_id = candidate.id
 AND version.deleted_at IS NULL
WHERE candidate.import_id = sqlc.arg(import_id)
  AND candidate.owner_id = sqlc.arg(owner_id)
ORDER BY candidate.created_at DESC, candidate.id
LIMIT 1;

-- name: CreateDerivedExchangeArtifact :exec
INSERT INTO component_repo.artifacts (
    id, owner_id, artifact_type, source_kind, original_filename,
    storage_provider, storage_bucket, storage_key, sha256, file_size,
    mime_type, immutable, verification_status, verified_at, uploaded_by,
    metadata, derived_from_artifact_id
) VALUES (
    sqlc.arg(id), sqlc.arg(owner_id), 'ldraw_ldr', 'derived',
    sqlc.arg(original_filename), sqlc.arg(storage_provider),
    sqlc.arg(storage_bucket), sqlc.arg(storage_key), sqlc.arg(sha256),
    sqlc.arg(file_size), 'text/plain', true, 'verified', now(),
    sqlc.arg(uploaded_by), sqlc.arg(metadata), sqlc.arg(derived_from_artifact_id)
)
ON CONFLICT (id) DO NOTHING;

-- name: CreateImportComponentForParse :exec
INSERT INTO component_repo.components (
    id, owner_id, content_kind, content_locale, name, status,
    metadata, created_by, created_at, updated_at
) VALUES (
    sqlc.arg(id), sqlc.arg(owner_id), 'user', sqlc.arg(content_locale),
    sqlc.arg(name), 'draft', '{}'::jsonb, sqlc.arg(created_by), now(), now()
)
ON CONFLICT (id) DO NOTHING;

-- name: MarkImportParseSucceeded :execrows
UPDATE component_repo.imports
SET target_component_id = sqlc.arg(target_component_id),
    exchange_artifact_id = sqlc.narg(exchange_artifact_id),
    status = 'succeeded',
    failure_code = NULL,
    failure_params = NULL,
    completed_at = now()
WHERE id = sqlc.arg(import_id)
  AND status = 'running';

-- name: CreateSceneSnapshotForParse :exec
INSERT INTO component_repo.scene_snapshots (
    id, import_id, schema_version, parser_version, root_model_id,
    document, bom, parse_issues, created_at
) VALUES (
    sqlc.arg(id), sqlc.arg(import_id), sqlc.arg(schema_version),
    sqlc.arg(parser_version), sqlc.narg(root_model_id), sqlc.arg(document),
    sqlc.arg(bom), sqlc.arg(parse_issues), now()
);

-- name: CreateCandidateForParse :exec
INSERT INTO component_repo.candidates (
    id, owner_id, import_id, scene_snapshot_id, status, summary,
    review_decisions, interface_signature, structure_hash, geometry_hash,
    created_at, updated_at
) VALUES (
    sqlc.arg(id), sqlc.arg(owner_id), sqlc.arg(import_id),
    sqlc.arg(scene_snapshot_id), 'pending_review', sqlc.arg(summary),
    sqlc.arg(review_decisions), sqlc.arg(interface_signature),
    sqlc.arg(structure_hash), sqlc.arg(geometry_hash), now(), now()
);

-- name: GetDraftVersionLabelForBase :one
SELECT version_label
FROM component_repo.component_versions
WHERE id = sqlc.arg(base_version_id)
  AND component_id = sqlc.arg(component_id)
  AND deleted_at IS NULL;

-- name: GetNextComponentVersionRevision :one
SELECT (COALESCE(max(revision), 0) + 1)::integer AS revision
FROM component_repo.component_versions
WHERE component_id = sqlc.arg(component_id)
  AND version_label = sqlc.arg(version_label);
