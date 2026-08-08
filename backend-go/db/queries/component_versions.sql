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
          published_at, deleted_at, deleted_by;

-- name: VersionInputsOwnedByActor :one
SELECT (
    EXISTS (
        SELECT 1 FROM component_repo.artifacts artifact
        WHERE artifact.id = sqlc.arg(source_artifact_id)
          AND artifact.owner_id = sqlc.arg(actor_id)
          AND artifact.deleted_at IS NULL
    )
    AND (
        sqlc.narg(exchange_artifact_id)::uuid IS NULL
        OR EXISTS (
            SELECT 1 FROM component_repo.artifacts artifact
            WHERE artifact.id = sqlc.narg(exchange_artifact_id)
              AND artifact.owner_id = sqlc.arg(actor_id)
              AND artifact.deleted_at IS NULL
        )
    )
    AND EXISTS (
        SELECT 1
        FROM component_repo.scene_snapshots snapshot
        JOIN component_repo.imports import_job ON import_job.id = snapshot.import_id
        WHERE snapshot.id = sqlc.arg(scene_snapshot_id)
          AND import_job.owner_id = sqlc.arg(actor_id)
    )
    AND (
        sqlc.narg(component_candidate_id)::uuid IS NULL
        OR EXISTS (
            SELECT 1 FROM component_repo.candidates candidate
            WHERE candidate.id = sqlc.narg(component_candidate_id)
              AND candidate.owner_id = sqlc.arg(actor_id)
              AND candidate.scene_snapshot_id = sqlc.arg(scene_snapshot_id)
        )
    )
)::boolean AS owned;

-- name: GetVisibleComponentVersion :one
SELECT v.id, v.component_id, v.component_candidate_id, v.version_label, v.revision,
       v.status, v.source_artifact_id, v.exchange_artifact_id, v.scene_snapshot_id,
       v.parser_version, v.part_library_version_id, v.validation_report_id,
       v.interface_signature, v.structure_hash, v.geometry_hash,
       v.preview_artifact_id, v.preview_status, v.preview_generator_version,
       v.preview_failure_code, v.preview_failure_params, v.release_note,
       v.release_note_locale, v.metadata, v.created_by, v.created_at,
       v.published_at, v.deleted_at, v.deleted_by
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
       v.published_at, v.deleted_at, v.deleted_by
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
