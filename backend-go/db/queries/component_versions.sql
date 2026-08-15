-- name: CreateComponentVersion :one
INSERT INTO component_repo.component_versions (
    id, component_id, component_candidate_id, version_label, revision, status,
    source_artifact_id, exchange_artifact_id, scene_snapshot_id, parser_version,
    part_library_version_id, interface_signature, structure_hash, geometry_hash,
    release_note, release_note_locale, metadata, created_by
) VALUES (
    sqlc.arg(id), sqlc.arg(component_id), sqlc.narg(component_candidate_id),
    sqlc.arg(version_label), sqlc.arg(revision), 'draft', sqlc.arg(source_artifact_id),
    sqlc.narg(exchange_artifact_id), sqlc.arg(scene_snapshot_id), sqlc.arg(parser_version),
    sqlc.narg(part_library_version_id), sqlc.arg(interface_signature),
    sqlc.arg(structure_hash), sqlc.arg(geometry_hash), sqlc.narg(release_note),
    sqlc.narg(release_note_locale), sqlc.arg(metadata), sqlc.arg(created_by)
)
RETURNING id, component_id, component_candidate_id, version_label, revision, status,
          source_artifact_id, exchange_artifact_id, scene_snapshot_id, parser_version,
          part_library_version_id, validation_report_id, interface_signature,
          structure_hash, geometry_hash, preview_artifact_id, preview_status,
          preview_generator_version, preview_failure_code, preview_failure_params,
          release_note, release_note_locale, metadata, created_by, created_at,
          published_at, deleted_at, deleted_by, preview_task_id, preview_generation;

-- name: GetOwnedVersionCandidateSource :one
SELECT candidate.id AS component_candidate_id,
       import_job.source_artifact_id,
       import_job.exchange_artifact_id,
       snapshot.id AS scene_snapshot_id,
       snapshot.parser_version,
       import_job.part_library_version_id,
       COALESCE(candidate.interface_signature, '')::text AS interface_signature,
       COALESCE(candidate.structure_hash, '')::text AS structure_hash,
       COALESCE(candidate.geometry_hash, '')::text AS geometry_hash
FROM component_repo.candidates candidate
JOIN component_repo.scene_snapshots snapshot
  ON snapshot.id = candidate.scene_snapshot_id
 AND snapshot.import_id = candidate.import_id
JOIN component_repo.imports import_job
  ON import_job.id = candidate.import_id
 AND import_job.owner_id = candidate.owner_id
JOIN component_repo.artifacts source_artifact
  ON source_artifact.id = import_job.source_artifact_id
 AND source_artifact.owner_id = candidate.owner_id
LEFT JOIN component_repo.artifacts exchange_artifact
  ON exchange_artifact.id = import_job.exchange_artifact_id
 AND exchange_artifact.owner_id = candidate.owner_id
WHERE candidate.id = sqlc.arg(candidate_id)
  AND candidate.owner_id = sqlc.arg(actor_id)
  AND candidate.status IN ('pending_review', 'accepted')
  AND import_job.status = 'succeeded'
  AND import_job.target_component_id = sqlc.arg(component_id)
  AND import_job.parser_version = snapshot.parser_version
  AND candidate.interface_signature IS NOT NULL
  AND candidate.structure_hash IS NOT NULL
  AND candidate.geometry_hash IS NOT NULL
  AND source_artifact.source_kind = 'source'
  AND source_artifact.immutable
  AND source_artifact.verification_status = 'verified'
  AND source_artifact.deleted_at IS NULL
  AND (
      import_job.exchange_artifact_id IS NULL
      OR (
          exchange_artifact.immutable
          AND exchange_artifact.verification_status = 'verified'
          AND exchange_artifact.deleted_at IS NULL
          AND (
              exchange_artifact.source_kind = 'source'
              OR (
                  exchange_artifact.source_kind = 'derived'
                  AND exchange_artifact.derived_from_artifact_id = source_artifact.id
              )
          )
      )
  );

-- name: GetVisibleComponentVersion :one
SELECT v.id, v.component_id, v.component_candidate_id, v.version_label, v.revision,
       v.status, v.source_artifact_id, v.exchange_artifact_id, v.scene_snapshot_id,
       v.parser_version, v.part_library_version_id, v.validation_report_id,
       v.interface_signature, v.structure_hash, v.geometry_hash,
       v.preview_artifact_id, v.preview_status, v.preview_generator_version,
       v.preview_failure_code, v.preview_failure_params, v.release_note,
       v.release_note_locale, v.metadata, v.created_by, v.created_at,
       v.published_at, v.deleted_at, v.deleted_by, v.preview_task_id,
       v.preview_generation
FROM component_repo.component_versions v
JOIN component_repo.components c ON c.id = v.component_id
WHERE v.id = sqlc.arg(version_id)
  AND v.deleted_at IS NULL
  AND c.deleted_at IS NULL
  AND (c.owner_id = sqlc.arg(actor_id) OR (c.status = 'active' AND v.status <> 'draft'));

-- name: ListVisibleComponentVersions :many
SELECT v.id, v.component_id, v.component_candidate_id, v.version_label, v.revision,
       v.status, v.source_artifact_id, v.exchange_artifact_id, v.scene_snapshot_id,
       v.parser_version, v.part_library_version_id, v.validation_report_id,
       v.interface_signature, v.structure_hash, v.geometry_hash,
       v.preview_artifact_id, v.preview_status, v.preview_generator_version,
       v.preview_failure_code, v.preview_failure_params, v.release_note,
       v.release_note_locale, v.metadata, v.created_by, v.created_at,
       v.published_at, v.deleted_at, v.deleted_by, v.preview_task_id,
       v.preview_generation
FROM component_repo.component_versions v
JOIN component_repo.components c ON c.id = v.component_id
WHERE v.component_id = sqlc.arg(component_id)
  AND v.deleted_at IS NULL
  AND c.deleted_at IS NULL
  AND (c.owner_id = sqlc.arg(actor_id) OR (c.status = 'active' AND v.status <> 'draft'))
ORDER BY v.created_at DESC, v.id
LIMIT sqlc.arg(page_size) OFFSET sqlc.arg(page_offset);

-- name: LockOwnedComponentVersion :one
SELECT v.id, v.component_id, v.status
FROM component_repo.component_versions v
JOIN component_repo.components c ON c.id = v.component_id
WHERE v.id = sqlc.arg(version_id)
  AND v.deleted_at IS NULL
  AND c.owner_id = sqlc.arg(actor_id)
  AND c.content_kind = 'user'
  AND c.deleted_at IS NULL
FOR UPDATE OF v;

-- name: UpdateOwnedDraftComponentVersion :one
UPDATE component_repo.component_versions version
SET version_label = CASE WHEN sqlc.arg(set_version_label)::boolean THEN sqlc.arg(version_label)::text ELSE version_label END,
    revision = CASE WHEN sqlc.arg(set_revision)::boolean THEN sqlc.arg(revision)::integer ELSE revision END,
    release_note = CASE WHEN sqlc.arg(set_release_note)::boolean THEN sqlc.narg(release_note)::text ELSE release_note END,
    release_note_locale = CASE WHEN sqlc.arg(set_release_note)::boolean THEN sqlc.narg(release_note_locale)::text ELSE release_note_locale END
FROM component_repo.components component
WHERE version.id = sqlc.arg(version_id)
  AND version.component_id = component.id
  AND component.owner_id = sqlc.arg(actor_id)
  AND component.content_kind = 'user'
  AND component.deleted_at IS NULL
  AND version.deleted_at IS NULL
  AND version.status = 'draft'
RETURNING version.id, version.component_id, version.component_candidate_id,
          version.version_label, version.revision, version.status,
          version.source_artifact_id, version.exchange_artifact_id,
          version.scene_snapshot_id, version.parser_version,
          version.part_library_version_id, version.validation_report_id,
          version.interface_signature, version.structure_hash, version.geometry_hash,
          version.preview_artifact_id, version.preview_status,
          version.preview_generator_version, version.preview_failure_code,
          version.preview_failure_params, version.release_note,
          version.release_note_locale, version.metadata, version.created_by,
          version.created_at, version.published_at, version.deleted_at,
          version.deleted_by, version.preview_task_id, version.preview_generation;

-- name: PublishComponentVersion :one
UPDATE component_repo.component_versions
SET status = 'published', published_at = COALESCE(published_at, now())
WHERE id = sqlc.arg(version_id) AND status = 'draft' AND deleted_at IS NULL
RETURNING id;

-- name: DeprecateOtherPublishedVersions :exec
UPDATE component_repo.component_versions
SET status = 'deprecated'
WHERE component_id = sqlc.arg(component_id)
  AND id <> sqlc.arg(version_id)
  AND status = 'published'
  AND deleted_at IS NULL;

-- name: TransitionOwnedComponentVersion :one
UPDATE component_repo.component_versions v
SET status = sqlc.arg(target_status)::text
FROM component_repo.components c
WHERE v.id = sqlc.arg(version_id)
  AND c.id = v.component_id
  AND c.owner_id = sqlc.arg(actor_id)
  AND c.content_kind = 'user'
  AND c.deleted_at IS NULL
  AND v.deleted_at IS NULL
  AND (
      (v.status = 'published' AND sqlc.arg(target_status)::text IN ('deprecated', 'archived'))
      OR (v.status = 'deprecated' AND sqlc.arg(target_status)::text = 'archived')
  )
RETURNING v.id;

-- name: SoftDeleteOwnedDraftVersion :one
UPDATE component_repo.component_versions v
SET deleted_at = now(), deleted_by = sqlc.arg(actor_id)
FROM component_repo.components c
WHERE v.id = sqlc.arg(version_id)
  AND c.id = v.component_id
  AND c.owner_id = sqlc.arg(actor_id)
  AND c.content_kind = 'user'
  AND v.status = 'draft'
  AND v.deleted_at IS NULL
  AND c.current_version_id IS DISTINCT FROM v.id
RETURNING v.id;
