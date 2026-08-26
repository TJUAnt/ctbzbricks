-- name: GetPreviewActivePartLibraryVersion :one
SELECT id, source_name, source_hash, status,
       preview_ready, relation_ready, connector_count, collider_count,
       created_at
FROM component_repo.part_library_versions
WHERE status = 'active'
ORDER BY created_at DESC, id DESC
LIMIT 1;

-- name: CountSearchableParts :one
-- 零件搜索只读取指定的不可变 Part Library；名称/编号关键词按“至少命中一个”组合，
-- 尺寸片段也按候选集合组合，但关键词集合与尺寸集合之间必须同时满足。
SELECT count(*)::bigint
FROM component_repo.parts part
JOIN component_repo.part_geometries geometry
  ON geometry.part_library_version_id = part.part_library_version_id
 AND geometry.ldraw_part_num = part.ldraw_part_num
WHERE part.part_library_version_id = sqlc.arg(part_library_version_id)
  AND geometry.geometry_status = 'ready'
  AND position('sticker' IN lower(part.source_name)) = 0
  AND position('decal' IN lower(part.source_name)) = 0
  AND (
      cardinality(sqlc.arg(keywords)::text[]) = 0
      OR EXISTS (
          SELECT 1
          FROM unnest(sqlc.arg(keywords)::text[]) keyword(value)
          WHERE position(keyword.value IN lower(part.source_name)) > 0
             OR position(keyword.value IN lower(part.ldraw_part_num)) > 0
      )
  )
  AND (
      jsonb_array_length(sqlc.arg(dimensions)::jsonb) = 0
      OR EXISTS (
          SELECT 1
          FROM jsonb_array_elements(sqlc.arg(dimensions)::jsonb) dimension(value)
          WHERE geometry.logical_width_stud IS NOT NULL
            AND geometry.logical_depth_stud IS NOT NULL
            AND (
                (
                    jsonb_array_length(dimension.value) = 2
                    AND least(geometry.logical_width_stud, geometry.logical_depth_stud) = (dimension.value ->> 0)::double precision
                    AND greatest(geometry.logical_width_stud, geometry.logical_depth_stud) = (dimension.value ->> 1)::double precision
                )
                OR (
                    jsonb_array_length(dimension.value) = 3
                    AND geometry.logical_height_plate IS NOT NULL
                    AND least(geometry.logical_width_stud, geometry.logical_depth_stud, geometry.logical_height_plate) = (dimension.value ->> 0)::double precision
                    AND geometry.logical_width_stud + geometry.logical_depth_stud + geometry.logical_height_plate
                        - least(geometry.logical_width_stud, geometry.logical_depth_stud, geometry.logical_height_plate)
                        - greatest(geometry.logical_width_stud, geometry.logical_depth_stud, geometry.logical_height_plate) = (dimension.value ->> 1)::double precision
                    AND greatest(geometry.logical_width_stud, geometry.logical_depth_stud, geometry.logical_height_plate) = (dimension.value ->> 2)::double precision
                )
            )
      )
  );

-- name: SearchParts :many
-- 排序先按命中的名称/编号关键词数量，再按源名称和 LDraw 编号稳定排序；分页不会依赖本地化文案。
-- 当前 generator 的 ready Artifact 作为可选只读投影返回，Search 不创建任务，也不读取对象正文。
SELECT part.part_library_version_id, part.ldraw_part_num, part.source_name,
       part.content_locale, geometry.logical_width_stud,
       geometry.logical_depth_stud, geometry.logical_height_plate,
       geometry.logical_size_derivation_status, preview.artifact_id AS preview_artifact_id,
       artifact.storage_key AS preview_storage_key, artifact.sha256 AS preview_sha256,
       artifact.file_size AS preview_file_size,
       (
           SELECT count(*)::integer
           FROM unnest(sqlc.arg(keywords)::text[]) keyword(value)
           WHERE position(keyword.value IN lower(part.source_name)) > 0
              OR position(keyword.value IN lower(part.ldraw_part_num)) > 0
       ) AS matched_keyword_count
FROM component_repo.parts part
JOIN component_repo.part_geometries geometry
  ON geometry.part_library_version_id = part.part_library_version_id
 AND geometry.ldraw_part_num = part.ldraw_part_num
LEFT JOIN component_repo.part_previews preview
  ON preview.part_library_version_id = part.part_library_version_id
 AND preview.ldraw_part_num = part.ldraw_part_num
 AND preview.status = 'ready'
 AND preview.generator_version = sqlc.arg(generator_version)
LEFT JOIN component_repo.artifacts artifact
  ON artifact.id = preview.artifact_id
 AND artifact.artifact_type = 'part_preview_glb'
 AND artifact.verification_status = 'verified'
 AND artifact.deleted_at IS NULL
WHERE part.part_library_version_id = sqlc.arg(part_library_version_id)
  AND geometry.geometry_status = 'ready'
  AND position('sticker' IN lower(part.source_name)) = 0
  AND position('decal' IN lower(part.source_name)) = 0
  AND (
      cardinality(sqlc.arg(keywords)::text[]) = 0
      OR EXISTS (
          SELECT 1
          FROM unnest(sqlc.arg(keywords)::text[]) keyword(value)
          WHERE position(keyword.value IN lower(part.source_name)) > 0
             OR position(keyword.value IN lower(part.ldraw_part_num)) > 0
      )
  )
  AND (
      jsonb_array_length(sqlc.arg(dimensions)::jsonb) = 0
      OR EXISTS (
          SELECT 1
          FROM jsonb_array_elements(sqlc.arg(dimensions)::jsonb) dimension(value)
          WHERE geometry.logical_width_stud IS NOT NULL
            AND geometry.logical_depth_stud IS NOT NULL
            AND (
                (
                    jsonb_array_length(dimension.value) = 2
                    AND least(geometry.logical_width_stud, geometry.logical_depth_stud) = (dimension.value ->> 0)::double precision
                    AND greatest(geometry.logical_width_stud, geometry.logical_depth_stud) = (dimension.value ->> 1)::double precision
                )
                OR (
                    jsonb_array_length(dimension.value) = 3
                    AND geometry.logical_height_plate IS NOT NULL
                    AND least(geometry.logical_width_stud, geometry.logical_depth_stud, geometry.logical_height_plate) = (dimension.value ->> 0)::double precision
                    AND geometry.logical_width_stud + geometry.logical_depth_stud + geometry.logical_height_plate
                        - least(geometry.logical_width_stud, geometry.logical_depth_stud, geometry.logical_height_plate)
                        - greatest(geometry.logical_width_stud, geometry.logical_depth_stud, geometry.logical_height_plate) = (dimension.value ->> 1)::double precision
                    AND greatest(geometry.logical_width_stud, geometry.logical_depth_stud, geometry.logical_height_plate) = (dimension.value ->> 2)::double precision
                )
            )
      )
  )
ORDER BY matched_keyword_count DESC, lower(part.source_name), part.ldraw_part_num
LIMIT sqlc.arg(page_size)
OFFSET sqlc.arg(page_offset);

-- name: GetPartPreview :one
SELECT library.id AS part_library_version_id, library.source_hash AS part_library_source_hash,
       part.ldraw_part_num, part.source_name, part.content_locale,
       translation.name AS translated_name, translation.locale AS translated_locale,
       geometry.source_relative_path, geometry.source_file_hash,
       geometry.bbox_min, geometry.bbox_max,
       geometry.logical_width_stud, geometry.logical_depth_stud,
       geometry.logical_height_plate, geometry.logical_size_derivation_status,
       geometry.vertex_count, geometry.face_count,
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

-- name: GetPartPreviewPrebuildLibrary :one
SELECT id, source_hash, created_by
FROM component_repo.part_library_versions
WHERE id = sqlc.arg(part_library_version_id)
  AND status = 'active';

-- name: GetActivePartPreviewPrebuildLibrary :one
SELECT id, source_hash, created_by
FROM component_repo.part_library_versions
WHERE status = 'active'
ORDER BY created_at DESC, id DESC
LIMIT 1;

-- name: CountPartPreviewPrebuildCandidates :one
SELECT count(*)::bigint
FROM component_repo.part_previews preview
JOIN component_repo.part_geometries geometry
  ON geometry.part_library_version_id = preview.part_library_version_id
 AND geometry.ldraw_part_num = preview.ldraw_part_num
WHERE preview.part_library_version_id = sqlc.arg(part_library_version_id)
  AND geometry.geometry_status = 'ready'
  AND (preview.status <> 'ready'
       OR preview.generator_version IS DISTINCT FROM sqlc.arg(generator_version));

-- name: PreparePartPreviewPrebuildCandidateBatch :execrows
-- 分批冻结 generation/task 归属，避免 Supabase pooler 对大 UPDATE 触发 statement/response 限制。
WITH candidate AS (
  SELECT preview.part_library_version_id, preview.ldraw_part_num
  FROM component_repo.part_previews preview
  JOIN component_repo.part_geometries geometry
    ON geometry.part_library_version_id = preview.part_library_version_id
   AND geometry.ldraw_part_num = preview.ldraw_part_num
  WHERE preview.part_library_version_id = sqlc.arg(part_library_version_id)
    AND geometry.geometry_status = 'ready'
    AND preview.status <> 'ready'
    AND (preview.task_id IS DISTINCT FROM sqlc.arg(task_id)
         OR preview.generator_version IS DISTINCT FROM sqlc.arg(generator_version)
         OR preview.status = 'failed')
  ORDER BY preview.ldraw_part_num
  FOR UPDATE OF preview SKIP LOCKED
  LIMIT sqlc.arg(batch_size)
)
UPDATE component_repo.part_previews preview
SET task_id = sqlc.arg(task_id), status = 'pending',
    generator_version = sqlc.arg(generator_version),
    generation = CASE
      WHEN preview.task_id IS DISTINCT FROM sqlc.arg(task_id)
        OR preview.generator_version IS DISTINCT FROM sqlc.arg(generator_version)
      THEN preview.generation + 1
      ELSE preview.generation
    END,
    artifact_id = NULL, failure_code = NULL, failure_params = NULL, updated_at = now()
FROM candidate
WHERE preview.part_library_version_id = candidate.part_library_version_id
  AND preview.ldraw_part_num = candidate.ldraw_part_num;

-- name: ListPreparedPartPreviewPrebuildCandidates :many
-- 只读取已经绑定本次 task/generator 的非 ready 行；任务重试不会重新解释 active library。
SELECT preview.ldraw_part_num, preview.generation,
       geometry.source_relative_path, geometry.source_file_hash, geometry.face_count
FROM component_repo.part_previews preview
JOIN component_repo.part_geometries geometry
  ON geometry.part_library_version_id = preview.part_library_version_id
 AND geometry.ldraw_part_num = preview.ldraw_part_num
WHERE preview.part_library_version_id = sqlc.arg(part_library_version_id)
  AND preview.task_id = sqlc.arg(task_id)
  AND preview.generator_version = sqlc.arg(generator_version)
  AND preview.status <> 'ready'
  AND geometry.geometry_status = 'ready';

-- name: MarkPartPreviewPrebuildFailed :execrows
UPDATE component_repo.part_previews
SET status = 'failed', failure_code = sqlc.arg(failure_code),
    failure_params = sqlc.arg(failure_params), updated_at = now()
WHERE part_library_version_id = sqlc.arg(part_library_version_id)
  AND ldraw_part_num = sqlc.arg(ldraw_part_num)
  AND task_id = sqlc.arg(task_id)
  AND generation = sqlc.arg(generation)
  AND status IN ('pending', 'running');

-- name: FinalizePartPreviewArtifact :one
-- Artifact upsert 与 Part 绑定必须同语句原子提交；全局 Artifact 为 NULL owner，Task owner 只记 uploaded_by。
WITH artifact AS (
  INSERT INTO component_repo.artifacts (
      id, owner_id, artifact_type, source_kind, original_filename,
      storage_provider, storage_bucket, storage_key, sha256, file_size,
      mime_type, immutable, verification_status, verified_at, uploaded_by, metadata
  ) VALUES (
      sqlc.arg(artifact_id), NULL, 'part_preview_glb', 'derived',
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
  RETURNING id
)
UPDATE component_repo.part_previews preview
SET artifact_id = artifact.id, status = 'ready',
    generator_version = sqlc.arg(generator_version),
    failure_code = NULL, failure_params = NULL, updated_at = now()
FROM artifact
WHERE preview.part_library_version_id = sqlc.arg(part_library_version_id)
  AND preview.ldraw_part_num = sqlc.arg(ldraw_part_num)
  AND preview.task_id = sqlc.arg(task_id)
  AND preview.generation = sqlc.arg(generation)
  AND preview.status IN ('pending', 'running')
RETURNING preview.generation;
