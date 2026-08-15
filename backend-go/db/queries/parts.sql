-- name: GetPreviewActivePartLibraryVersion :one
SELECT id, source_name, source_hash, status, created_at
FROM component_repo.part_library_versions
WHERE status = 'active'
ORDER BY created_at DESC, id DESC
LIMIT 1;

-- name: GetPartPreview :one
SELECT library.id AS part_library_version_id, library.source_hash AS part_library_source_hash,
       part.ldraw_part_num, part.source_name, part.content_locale,
       translation.name AS translated_name, translation.locale AS translated_locale,
       geometry.source_relative_path, geometry.source_file_hash,
       geometry.bbox_min, geometry.bbox_max,
       geometry.logical_width_stud, geometry.logical_depth_stud,
       geometry.logical_height_plate, geometry.vertex_count, geometry.face_count,
       geometry.geometry_status, geometry.geometry_error_code, geometry.geometry_error_params,
       preview.status AS preview_status, preview.generator_version,
       preview.artifact_id, preview.task_id, preview.generation,
       preview.failure_code, preview.failure_params,
       artifact.sha256, artifact.file_size, artifact.storage_key
FROM component_repo.part_library_versions library
JOIN component_repo.parts part ON part.part_library_version_id = library.id
LEFT JOIN component_repo.part_translations translation
  ON translation.part_library_version_id = part.part_library_version_id
 AND translation.ldraw_part_num = part.ldraw_part_num
 AND translation.locale = sqlc.arg(locale)
 AND translation.translation_status = 'reviewed'
LEFT JOIN component_repo.part_geometries geometry
  ON geometry.part_library_version_id = part.part_library_version_id
 AND geometry.ldraw_part_num = part.ldraw_part_num
JOIN component_repo.part_previews preview
  ON preview.part_library_version_id = part.part_library_version_id
 AND preview.ldraw_part_num = part.ldraw_part_num
LEFT JOIN component_repo.artifacts artifact
  ON artifact.id = preview.artifact_id AND artifact.deleted_at IS NULL
WHERE library.id = sqlc.arg(part_library_version_id)
  AND part.ldraw_part_num = sqlc.arg(ldraw_part_num);

-- name: LockPartPreviewState :one
SELECT library.id AS part_library_version_id, library.source_hash AS part_library_source_hash,
       part.ldraw_part_num, part.content_locale,
       geometry.source_file_hash, geometry.geometry_status,
       preview.status AS preview_status, preview.generator_version,
       preview.artifact_id, preview.task_id, preview.generation
FROM component_repo.part_library_versions library
JOIN component_repo.parts part ON part.part_library_version_id = library.id
LEFT JOIN component_repo.part_geometries geometry
  ON geometry.part_library_version_id = part.part_library_version_id
 AND geometry.ldraw_part_num = part.ldraw_part_num
JOIN component_repo.part_previews preview
  ON preview.part_library_version_id = part.part_library_version_id
 AND preview.ldraw_part_num = part.ldraw_part_num
WHERE library.id = sqlc.arg(part_library_version_id)
  AND part.ldraw_part_num = sqlc.arg(ldraw_part_num)
FOR UPDATE OF preview;

-- name: SetPartPreviewTask :exec
UPDATE component_repo.part_previews
SET task_id = sqlc.arg(task_id), status = 'pending',
    generator_version = sqlc.arg(generator_version), generation = sqlc.arg(generation),
    failure_code = NULL, failure_params = NULL, updated_at = now()
WHERE part_library_version_id = sqlc.arg(part_library_version_id)
  AND ldraw_part_num = sqlc.arg(ldraw_part_num);

-- name: GetPartPreviewTaskInput :one
SELECT library.source_hash AS part_library_source_hash,
       geometry.source_relative_path, geometry.source_file_hash,
       geometry.geometry_status, preview.status AS preview_status,
       preview.generator_version, preview.artifact_id, preview.generation
FROM component_repo.part_previews preview
JOIN component_repo.part_library_versions library
  ON library.id = preview.part_library_version_id
JOIN component_repo.part_geometries geometry
  ON geometry.part_library_version_id = preview.part_library_version_id
 AND geometry.ldraw_part_num = preview.ldraw_part_num
WHERE preview.part_library_version_id = sqlc.arg(part_library_version_id)
  AND preview.ldraw_part_num = sqlc.arg(ldraw_part_num)
  AND preview.task_id = sqlc.arg(task_id);

-- name: MarkPartPreviewRunning :execrows
UPDATE component_repo.part_previews
SET status = 'running', updated_at = now()
WHERE part_library_version_id = sqlc.arg(part_library_version_id)
  AND ldraw_part_num = sqlc.arg(ldraw_part_num)
  AND task_id = sqlc.arg(task_id)
  AND status IN ('pending', 'running');

-- name: MarkPartPreviewReady :execrows
UPDATE component_repo.part_previews
SET artifact_id = sqlc.arg(artifact_id), status = 'ready',
    generator_version = sqlc.arg(generator_version),
    failure_code = NULL, failure_params = NULL, updated_at = now()
WHERE part_library_version_id = sqlc.arg(part_library_version_id)
  AND ldraw_part_num = sqlc.arg(ldraw_part_num)
  AND task_id = sqlc.arg(task_id)
  AND generation = sqlc.arg(generation)
  AND status = 'running';

-- name: UpsertPartPreviewArtifact :one
INSERT INTO component_repo.artifacts (
    id, owner_id, artifact_type, source_kind, original_filename,
    storage_provider, storage_bucket, storage_key, sha256, file_size,
    mime_type, immutable, verification_status, verified_at, uploaded_by, metadata
) VALUES (
    sqlc.arg(id), sqlc.arg(owner_id), 'part_preview_glb', 'derived',
    sqlc.arg(original_filename), sqlc.arg(storage_provider), sqlc.arg(storage_bucket),
    sqlc.arg(storage_key), sqlc.arg(sha256), sqlc.arg(file_size), 'model/gltf-binary',
    true, 'verified', now(), sqlc.arg(uploaded_by), sqlc.arg(metadata)
)
ON CONFLICT (id) DO UPDATE SET
    storage_key = EXCLUDED.storage_key,
    sha256 = EXCLUDED.sha256,
    file_size = EXCLUDED.file_size,
    verification_status = 'verified',
    verified_at = now(),
    metadata = EXCLUDED.metadata,
    deleted_at = NULL
RETURNING id, owner_id, artifact_type, source_kind, original_filename,
          storage_provider, storage_bucket, storage_key, sha256, file_size,
          mime_type, immutable, verification_status, verified_at, uploaded_by,
          uploaded_at, metadata, deleted_at, derived_from_artifact_id;
