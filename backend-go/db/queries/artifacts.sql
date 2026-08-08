-- name: CreateUploadSession :one
INSERT INTO component_repo.upload_sessions (
    id, owner_id, status, target_component_id, base_version_id,
    locale, timezone, metadata, created_by, expires_at
) VALUES (
    sqlc.arg(id), sqlc.arg(owner_id), 'pending', sqlc.narg(target_component_id),
    sqlc.narg(base_version_id), sqlc.arg(locale), sqlc.arg(timezone),
    sqlc.arg(metadata), sqlc.arg(created_by), sqlc.arg(expires_at)
)
RETURNING *;

-- name: CreateUploadSessionFile :one
INSERT INTO component_repo.upload_session_files (
    id, upload_session_id, ordinal, artifact_type, original_filename,
    expected_size, expected_sha256, storage_provider, storage_bucket, storage_key
) VALUES (
    sqlc.arg(id), sqlc.arg(upload_session_id), sqlc.arg(ordinal),
    sqlc.arg(artifact_type), sqlc.arg(original_filename), sqlc.arg(expected_size),
    sqlc.arg(expected_sha256), sqlc.arg(storage_provider), sqlc.arg(storage_bucket),
    sqlc.arg(storage_key)
)
RETURNING *;

-- name: GetOwnedUploadSession :one
SELECT *
FROM component_repo.upload_sessions
WHERE id = sqlc.arg(session_id) AND owner_id = sqlc.arg(actor_id);

-- name: LockOwnedUploadSession :one
SELECT *
FROM component_repo.upload_sessions
WHERE id = sqlc.arg(session_id) AND owner_id = sqlc.arg(actor_id)
FOR UPDATE;

-- name: ListUploadSessionFiles :many
SELECT *
FROM component_repo.upload_session_files
WHERE upload_session_id = sqlc.arg(session_id)
ORDER BY ordinal, id;

-- name: CreateSourceArtifact :one
INSERT INTO component_repo.artifacts (
    id, owner_id, artifact_type, source_kind, original_filename,
    storage_provider, storage_bucket, storage_key, sha256, file_size,
    mime_type, immutable, verification_status, uploaded_by, metadata
) VALUES (
    sqlc.arg(id), sqlc.arg(owner_id), sqlc.arg(artifact_type), 'source',
    sqlc.arg(original_filename), sqlc.arg(storage_provider), sqlc.arg(storage_bucket),
    sqlc.arg(storage_key), sqlc.arg(sha256), sqlc.arg(file_size), sqlc.arg(mime_type),
    true, 'pending', sqlc.arg(uploaded_by), sqlc.arg(metadata)
)
RETURNING *;

-- name: MarkUploadSessionFileUploaded :one
UPDATE component_repo.upload_session_files
SET artifact_id = sqlc.arg(artifact_id), status = 'uploaded', completed_at = now()
WHERE id = sqlc.arg(file_id)
  AND upload_session_id = sqlc.arg(session_id)
  AND status = 'pending'
RETURNING *;

-- name: CompleteUploadSession :one
UPDATE component_repo.upload_sessions
SET status = 'completed', completed_at = now(), failure_code = NULL,
    failure_params = NULL, metadata = sqlc.arg(metadata)
WHERE id = sqlc.arg(session_id) AND owner_id = sqlc.arg(actor_id) AND status = 'pending'
RETURNING *;

-- name: GetOwnedArtifact :one
SELECT *
FROM component_repo.artifacts
WHERE id = sqlc.arg(artifact_id)
  AND owner_id = sqlc.arg(actor_id)
  AND deleted_at IS NULL;

-- name: GetVisibleVersionSourceArtifact :one
SELECT a.*
FROM component_repo.component_versions v
JOIN component_repo.components c ON c.id = v.component_id
JOIN component_repo.artifacts a ON a.id = v.source_artifact_id
WHERE v.id = sqlc.arg(version_id)
  AND v.deleted_at IS NULL
  AND c.deleted_at IS NULL
  AND a.deleted_at IS NULL
  AND (
      c.owner_id = sqlc.arg(actor_id)
      OR (c.status = 'active' AND v.status <> 'draft')
  );

-- name: MarkArtifactVerified :one
UPDATE component_repo.artifacts
SET verification_status = 'verified', verified_at = now(), metadata = sqlc.arg(metadata)
WHERE id = sqlc.arg(artifact_id) AND verification_status = 'pending' AND deleted_at IS NULL
RETURNING *;

-- name: MarkArtifactFailed :one
UPDATE component_repo.artifacts
SET verification_status = 'failed', verified_at = NULL, metadata = sqlc.arg(metadata)
WHERE id = sqlc.arg(artifact_id) AND verification_status = 'pending' AND deleted_at IS NULL
RETURNING *;

-- name: MarkUploadSessionFileVerified :exec
UPDATE component_repo.upload_session_files
SET status = 'verified', completed_at = COALESCE(completed_at, now())
WHERE artifact_id = sqlc.arg(artifact_id) AND status = 'uploaded';

-- name: MarkUploadSessionFileFailed :exec
UPDATE component_repo.upload_session_files
SET status = 'failed', completed_at = COALESCE(completed_at, now())
WHERE artifact_id = sqlc.arg(artifact_id) AND status IN ('pending', 'uploaded');

-- name: FailUploadSession :exec
UPDATE component_repo.upload_sessions
SET status = 'failed', failure_code = sqlc.arg(failure_code),
    failure_params = sqlc.arg(failure_params)
WHERE id = sqlc.arg(session_id) AND owner_id = sqlc.arg(actor_id) AND status = 'pending';

-- name: FailUploadSessionFiles :exec
UPDATE component_repo.upload_session_files
SET status = 'failed', completed_at = now()
WHERE upload_session_id = sqlc.arg(session_id) AND status = 'pending';

-- name: ListExpiredUploadSessions :many
SELECT *
FROM component_repo.upload_sessions
WHERE status = 'pending' AND expires_at <= sqlc.arg(expired_before)
ORDER BY expires_at, id
LIMIT sqlc.arg(batch_size);

-- name: ExpireUploadSession :execrows
UPDATE component_repo.upload_sessions
SET status = 'expired', failure_code = 'component_repo.upload_session_complete_failed',
    failure_params = jsonb_build_object('uploadSessionId', id::text)
WHERE id = sqlc.arg(session_id) AND status = 'pending' AND expires_at <= now();
