-- name: GetPreviewActivePartLibraryVersion :one
SELECT id, source_name, source_hash, status,
       preview_ready, relation_ready, connector_count, collider_count,
       created_at
FROM component_repo.part_library_versions
WHERE status = 'active'
ORDER BY created_at DESC, id DESC
LIMIT 1;

-- name: CountSearchableParts :one
-- 零件搜索只读取指定的不可变 Part Library；描述 token、编号和每个尺寸条件全部按 AND 组合。
-- 宽/深是可旋转的平面轴，高度单位为 plate 且绝不参与换轴；每个物理轴允许含边界的 ±2mm。
WITH requested_translations AS MATERIALIZED (
    SELECT source.part_library_version_id, source.ldraw_part_num, source.name, source.locale
    FROM component_repo.part_translations source
    WHERE source.part_library_version_id = sqlc.arg(part_library_version_id)
      AND source.locale = sqlc.arg(locale)
      AND source.translation_status = 'reviewed'
)
SELECT count(*)::bigint
FROM component_repo.parts part
JOIN component_repo.part_geometries geometry
  ON geometry.part_library_version_id = part.part_library_version_id
 AND geometry.ldraw_part_num = part.ldraw_part_num
LEFT JOIN requested_translations translation
  ON translation.part_library_version_id = part.part_library_version_id
 AND translation.ldraw_part_num = part.ldraw_part_num
WHERE part.part_library_version_id = sqlc.arg(part_library_version_id)
  AND geometry.geometry_status = 'ready'
  AND lower(part.source_name || ' ' || COALESCE(translation.name, ''))
      LIKE ALL(sqlc.arg(description_patterns)::text[])
  AND (
      sqlc.arg(part_number)::text = ''
      OR position(sqlc.arg(part_number)::text IN lower(part.ldraw_part_num)) > 0
  )
  AND (
      NOT (sqlc.arg(has_width)::boolean OR sqlc.arg(has_depth)::boolean OR sqlc.arg(has_height)::boolean)
      OR geometry.logical_size_derivation_status IN ('derived_exact', 'derived_approximate')
  )
  AND (
      (NOT sqlc.arg(has_width)::boolean AND NOT sqlc.arg(has_depth)::boolean)
      OR (
          sqlc.arg(has_width)::boolean AND sqlc.arg(has_depth)::boolean
          AND least(geometry.logical_width_stud, geometry.logical_depth_stud)
              BETWEEN least(sqlc.arg(width_stud)::double precision, sqlc.arg(depth_stud)::double precision) - 0.25
                  AND least(sqlc.arg(width_stud)::double precision, sqlc.arg(depth_stud)::double precision) + 0.25
          AND greatest(geometry.logical_width_stud, geometry.logical_depth_stud)
              BETWEEN greatest(sqlc.arg(width_stud)::double precision, sqlc.arg(depth_stud)::double precision) - 0.25
                  AND greatest(sqlc.arg(width_stud)::double precision, sqlc.arg(depth_stud)::double precision) + 0.25
      )
      OR (sqlc.arg(has_width)::boolean AND NOT sqlc.arg(has_depth)::boolean
          AND (geometry.logical_width_stud BETWEEN sqlc.arg(width_stud)::double precision - 0.25 AND sqlc.arg(width_stud)::double precision + 0.25
               OR geometry.logical_depth_stud BETWEEN sqlc.arg(width_stud)::double precision - 0.25 AND sqlc.arg(width_stud)::double precision + 0.25))
      OR (NOT sqlc.arg(has_width)::boolean AND sqlc.arg(has_depth)::boolean
          AND (geometry.logical_width_stud BETWEEN sqlc.arg(depth_stud)::double precision - 0.25 AND sqlc.arg(depth_stud)::double precision + 0.25
               OR geometry.logical_depth_stud BETWEEN sqlc.arg(depth_stud)::double precision - 0.25 AND sqlc.arg(depth_stud)::double precision + 0.25))
  )
  AND (
      NOT sqlc.arg(has_height)::boolean
      OR geometry.logical_height_plate
          BETWEEN sqlc.arg(height_plate)::double precision - 0.625
              AND sqlc.arg(height_plate)::double precision + 0.625
  );

-- name: SearchParts :many
-- 先固定排序后的页面，再关联 preview/artifact；候选集不会因 Storage 投影产生逐行放大。
-- reviewed translation 既参与请求 locale 的描述检索，也作为展示名；无 reviewed 行时回退源描述。
WITH requested_translations AS MATERIALIZED (
    SELECT source.part_library_version_id, source.ldraw_part_num, source.name, source.locale
    FROM component_repo.part_translations source
    WHERE source.part_library_version_id = sqlc.arg(part_library_version_id)
      AND source.locale = sqlc.arg(locale)
      AND source.translation_status = 'reviewed'
), filtered AS (
    SELECT part.part_library_version_id, part.ldraw_part_num,
           COALESCE(translation.name, part.source_name) AS display_name,
           COALESCE(translation.locale, part.content_locale) AS display_locale,
           CASE WHEN translation.name IS NULL THEN 'source' ELSE 'reviewed' END AS translation_status,
           geometry.logical_width_stud, geometry.logical_depth_stud, geometry.logical_height_plate,
           geometry.logical_size_derivation_status,
           lower(part.source_name) AS source_sort,
           CASE
               WHEN sqlc.arg(description_phrase)::text <> ''
                AND lower(COALESCE(translation.name, part.source_name)) = sqlc.arg(description_phrase)::text THEN 0
               WHEN sqlc.arg(description_phrase)::text <> ''
                AND position(sqlc.arg(description_phrase)::text IN lower(COALESCE(translation.name, part.source_name))) > 0 THEN 1
               ELSE 2
           END AS relevance_rank
    FROM component_repo.parts part
    JOIN component_repo.part_geometries geometry
      ON geometry.part_library_version_id = part.part_library_version_id
     AND geometry.ldraw_part_num = part.ldraw_part_num
    LEFT JOIN requested_translations translation
      ON translation.part_library_version_id = part.part_library_version_id
     AND translation.ldraw_part_num = part.ldraw_part_num
    WHERE part.part_library_version_id = sqlc.arg(part_library_version_id)
      AND geometry.geometry_status = 'ready'
      AND lower(part.source_name || ' ' || COALESCE(translation.name, ''))
          LIKE ALL(sqlc.arg(description_patterns)::text[])
      AND (
          sqlc.arg(part_number)::text = ''
          OR position(sqlc.arg(part_number)::text IN lower(part.ldraw_part_num)) > 0
      )
      AND (
          NOT (sqlc.arg(has_width)::boolean OR sqlc.arg(has_depth)::boolean OR sqlc.arg(has_height)::boolean)
          OR geometry.logical_size_derivation_status IN ('derived_exact', 'derived_approximate')
      )
      AND (
          (NOT sqlc.arg(has_width)::boolean AND NOT sqlc.arg(has_depth)::boolean)
          OR (
              sqlc.arg(has_width)::boolean AND sqlc.arg(has_depth)::boolean
              AND least(geometry.logical_width_stud, geometry.logical_depth_stud)
                  BETWEEN least(sqlc.arg(width_stud)::double precision, sqlc.arg(depth_stud)::double precision) - 0.25
                      AND least(sqlc.arg(width_stud)::double precision, sqlc.arg(depth_stud)::double precision) + 0.25
              AND greatest(geometry.logical_width_stud, geometry.logical_depth_stud)
                  BETWEEN greatest(sqlc.arg(width_stud)::double precision, sqlc.arg(depth_stud)::double precision) - 0.25
                      AND greatest(sqlc.arg(width_stud)::double precision, sqlc.arg(depth_stud)::double precision) + 0.25
          )
          OR (sqlc.arg(has_width)::boolean AND NOT sqlc.arg(has_depth)::boolean
              AND (geometry.logical_width_stud BETWEEN sqlc.arg(width_stud)::double precision - 0.25 AND sqlc.arg(width_stud)::double precision + 0.25
                   OR geometry.logical_depth_stud BETWEEN sqlc.arg(width_stud)::double precision - 0.25 AND sqlc.arg(width_stud)::double precision + 0.25))
          OR (NOT sqlc.arg(has_width)::boolean AND sqlc.arg(has_depth)::boolean
              AND (geometry.logical_width_stud BETWEEN sqlc.arg(depth_stud)::double precision - 0.25 AND sqlc.arg(depth_stud)::double precision + 0.25
                   OR geometry.logical_depth_stud BETWEEN sqlc.arg(depth_stud)::double precision - 0.25 AND sqlc.arg(depth_stud)::double precision + 0.25))
      )
      AND (
          NOT sqlc.arg(has_height)::boolean
          OR geometry.logical_height_plate
              BETWEEN sqlc.arg(height_plate)::double precision - 0.625
                  AND sqlc.arg(height_plate)::double precision + 0.625
      )
    ORDER BY relevance_rank, source_sort, part.ldraw_part_num
    LIMIT sqlc.arg(page_size)
    OFFSET sqlc.arg(page_offset)
)
SELECT filtered.part_library_version_id, filtered.ldraw_part_num, filtered.display_name,
       filtered.display_locale, filtered.translation_status,
       filtered.logical_width_stud, filtered.logical_depth_stud, filtered.logical_height_plate,
       filtered.logical_size_derivation_status, preview.artifact_id AS preview_artifact_id,
       artifact.storage_key AS preview_storage_key, artifact.sha256 AS preview_sha256,
       artifact.file_size AS preview_file_size
FROM filtered
LEFT JOIN component_repo.part_previews preview
  ON preview.part_library_version_id = filtered.part_library_version_id
 AND preview.ldraw_part_num = filtered.ldraw_part_num
 AND preview.status = 'ready'
 AND preview.generator_version = sqlc.arg(generator_version)
LEFT JOIN component_repo.artifacts artifact
  ON artifact.id = preview.artifact_id
 AND artifact.artifact_type = 'part_preview_glb'
 AND artifact.verification_status = 'verified'
 AND artifact.deleted_at IS NULL
ORDER BY
    filtered.relevance_rank,
    filtered.source_sort,
    filtered.ldraw_part_num;

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
-- 显式指定版本时允许预生成 building 快照；默认入口仍只选择 active，避免新库未完成前提前切换在线搜索。
SELECT id, source_hash, created_by
FROM component_repo.part_library_versions
WHERE id = sqlc.arg(part_library_version_id)
  AND status IN ('active', 'building');

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
-- 每次只读取已经绑定本次 task/generator 的一小批 pending 行；远程 pooler 不承载 2.5 万行单次结果。
SELECT preview.ldraw_part_num, preview.generation,
       geometry.source_relative_path, geometry.source_file_hash, geometry.face_count
FROM component_repo.part_previews preview
JOIN component_repo.part_geometries geometry
  ON geometry.part_library_version_id = preview.part_library_version_id
 AND geometry.ldraw_part_num = preview.ldraw_part_num
WHERE preview.part_library_version_id = sqlc.arg(part_library_version_id)
  AND preview.task_id = sqlc.arg(task_id)
  AND preview.generator_version = sqlc.arg(generator_version)
  AND preview.status = 'pending'
  AND geometry.geometry_status = 'ready'
ORDER BY geometry.face_count, preview.ldraw_part_num
LIMIT sqlc.arg(batch_size);

-- name: MarkPartPreviewPrebuildFailed :execrows
UPDATE component_repo.part_previews
SET status = 'failed', failure_code = sqlc.arg(failure_code),
    failure_params = sqlc.arg(failure_params), updated_at = now()
WHERE part_library_version_id = sqlc.arg(part_library_version_id)
  AND ldraw_part_num = sqlc.arg(ldraw_part_num)
  AND task_id = sqlc.arg(task_id)
  AND generation = sqlc.arg(generation)
  AND status IN ('pending', 'running');

-- name: IsVerifiedPartPreviewArtifactReusable :one
-- 全库换代时允许复用完全相同的内容寻址 Artifact；逐字段校验避免把同 UUID 下的漂移 metadata 绑定到新 Part。
SELECT EXISTS (
  SELECT 1
  FROM component_repo.artifacts artifact
  WHERE artifact.id = sqlc.arg(artifact_id)
    AND artifact.owner_id IS NULL
    AND artifact.artifact_type = 'part_preview_glb'
    AND artifact.source_kind = 'derived'
    AND artifact.storage_provider = sqlc.arg(storage_provider)
    AND artifact.storage_bucket = sqlc.arg(storage_bucket)
    AND artifact.storage_key = sqlc.arg(storage_key)
    AND artifact.sha256 = sqlc.arg(sha256)
    AND artifact.file_size = sqlc.arg(file_size)
    AND artifact.mime_type = 'model/gltf-binary'
    AND artifact.immutable
    AND artifact.verification_status = 'verified'
    AND artifact.deleted_at IS NULL
) AS reusable;

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
