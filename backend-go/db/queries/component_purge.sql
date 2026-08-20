-- name: GetOwnedComponentForPurge :one
SELECT id, name
FROM component_repo.components
WHERE id = sqlc.arg(component_id)
  AND owner_id = sqlc.arg(actor_id)
  AND content_kind = 'user';

-- name: ListComponentPurgeStorageObjects :many
WITH RECURSIVE version_ids AS (
    SELECT version.id
    FROM component_repo.component_versions version
    WHERE version.component_id = sqlc.arg(target_component_id)
), candidate_ids AS (
    SELECT DISTINCT candidate.id
    FROM component_repo.candidates candidate
    WHERE candidate.id IN (
        SELECT version.component_candidate_id
        FROM component_repo.component_versions version
        WHERE version.component_id = sqlc.arg(target_component_id)
          AND version.component_candidate_id IS NOT NULL
    )
), import_ids AS (
    SELECT DISTINCT import_job.id
    FROM component_repo.imports import_job
    WHERE import_job.owner_id = sqlc.arg(actor_id)
      AND (
          import_job.target_component_id = sqlc.arg(target_component_id)
          OR import_job.base_version_id IN (SELECT id FROM version_ids)
          OR import_job.id IN (
              SELECT candidate.import_id
              FROM component_repo.candidates candidate
              WHERE candidate.id IN (SELECT id FROM candidate_ids)
          )
      )
), upload_session_ids AS (
    SELECT upload_session.id
    FROM component_repo.upload_sessions upload_session
    WHERE upload_session.owner_id = sqlc.arg(actor_id)
      AND (
          upload_session.target_component_id = sqlc.arg(target_component_id)
          OR upload_session.base_version_id IN (SELECT id FROM version_ids)
      )
), base_artifacts AS (
    SELECT version.source_artifact_id AS id
    FROM component_repo.component_versions version
    WHERE version.id IN (SELECT id FROM version_ids)
    UNION
    SELECT version.exchange_artifact_id
    FROM component_repo.component_versions version
    WHERE version.id IN (SELECT id FROM version_ids)
      AND version.exchange_artifact_id IS NOT NULL
    UNION
    SELECT version.preview_artifact_id
    FROM component_repo.component_versions version
    WHERE version.id IN (SELECT id FROM version_ids)
      AND version.preview_artifact_id IS NOT NULL
    UNION
    SELECT import_job.source_artifact_id
    FROM component_repo.imports import_job
    WHERE import_job.id IN (SELECT id FROM import_ids)
    UNION
    SELECT import_job.exchange_artifact_id
    FROM component_repo.imports import_job
    WHERE import_job.id IN (SELECT id FROM import_ids)
      AND import_job.exchange_artifact_id IS NOT NULL
    UNION
    SELECT upload_file.artifact_id
    FROM component_repo.upload_session_files upload_file
    WHERE upload_file.upload_session_id IN (SELECT id FROM upload_session_ids)
      AND upload_file.artifact_id IS NOT NULL
), artifact_tree AS (
    SELECT artifact.id, artifact.storage_provider, artifact.storage_bucket, artifact.storage_key
    FROM component_repo.artifacts artifact
    JOIN base_artifacts base ON base.id = artifact.id
    WHERE artifact.owner_id = sqlc.arg(actor_id)
    UNION
    SELECT child.id, child.storage_provider, child.storage_bucket, child.storage_key
    FROM component_repo.artifacts child
    JOIN artifact_tree parent ON child.derived_from_artifact_id = parent.id
    WHERE child.owner_id = sqlc.arg(actor_id)
), upload_file_objects AS (
    SELECT upload_file.storage_provider, upload_file.storage_bucket, upload_file.storage_key
    FROM component_repo.upload_session_files upload_file
    WHERE upload_file.upload_session_id IN (SELECT id FROM upload_session_ids)
)
SELECT DISTINCT storage_provider, storage_bucket, storage_key
FROM artifact_tree tree
WHERE NOT EXISTS (
    SELECT 1
    FROM component_repo.component_versions version
    WHERE version.component_id <> sqlc.arg(target_component_id)
      AND version.deleted_at IS NULL
      AND (
          version.source_artifact_id = tree.id
          OR version.exchange_artifact_id = tree.id
          OR version.preview_artifact_id = tree.id
      )
)
AND NOT EXISTS (
    SELECT 1
    FROM component_repo.imports import_job
    WHERE import_job.id NOT IN (SELECT id FROM import_ids)
      AND (
          import_job.source_artifact_id = tree.id
          OR import_job.exchange_artifact_id = tree.id
      )
)
AND NOT EXISTS (
    SELECT 1
    FROM component_repo.upload_session_files upload_file
    WHERE upload_file.upload_session_id NOT IN (SELECT id FROM upload_session_ids)
      AND upload_file.artifact_id = tree.id
)
UNION
SELECT DISTINCT storage_provider, storage_bucket, storage_key
FROM upload_file_objects
ORDER BY storage_provider, storage_bucket, storage_key;

-- name: RedactOwnedComponent :one
SELECT result.component_redacted::boolean AS component_redacted,
       result.versions_redacted::integer AS versions_redacted,
       result.artifacts_tombstoned::integer AS artifacts_tombstoned,
       result.related_tasks_redacted::integer AS related_tasks_redacted
FROM component_repo.redact_owned_component(
    sqlc.arg(actor_id), sqlc.arg(component_id), sqlc.arg(current_task_id)
) AS result;

-- name: RedactComponentPurgeTaskPayload :exec
UPDATE component_repo.tasks
SET payload = jsonb_build_object('componentId', sqlc.arg(component_id)::text, 'purged', true),
    updated_at = now()
WHERE id = sqlc.arg(task_id)
  AND owner_id = sqlc.arg(actor_id)
  AND task_type = 'component.purge';
