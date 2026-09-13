-- name: CreateComponentFeedEntry :one
-- 发布事务在事件与渲染任务均已创建后写入 pending 投影；终态只能由 tasks trigger 推进。
INSERT INTO component_repo.component_feed_entries (
    event_id, component_id, component_version_id, render_task_id, render_profile, renderer_version
) VALUES (
    sqlc.arg(event_id), sqlc.arg(component_id), sqlc.arg(component_version_id), sqlc.arg(render_task_id),
    sqlc.arg(render_profile), sqlc.arg(renderer_version)
)
RETURNING event_id, component_id, component_version_id, render_task_id, render_profile,
          renderer_version, render_status, image_artifact_id, available_at,
          created_at, updated_at;

-- name: GetComponentFeedRenderInput :one
-- Worker 只接受任务自身绑定的发布版本，并读取已经验证的 GLB；发布人的 owner 边界来自不可变事件。
SELECT entry.event_id,
       entry.component_version_id,
       entry.render_profile,
       entry.renderer_version,
       preview.id AS preview_artifact_id,
       preview.storage_key AS preview_storage_key,
       preview.sha256 AS preview_sha256,
       preview.file_size AS preview_file_size
FROM component_repo.component_feed_entries entry
JOIN component_repo.component_domain_events event
  ON event.id = entry.event_id
 AND event.component_version_id = entry.component_version_id
 AND event.actor_id = sqlc.arg(owner_id)
JOIN component_repo.component_versions version
  ON version.id = entry.component_version_id
 AND version.preview_status = 'ready'
 AND version.preview_artifact_id IS NOT NULL
JOIN component_repo.artifacts preview
  ON preview.id = version.preview_artifact_id
 AND preview.owner_id = event.actor_id
 AND preview.artifact_type = 'component_preview_glb'
 AND preview.source_kind = 'derived'
 AND preview.verification_status = 'verified'
 AND preview.deleted_at IS NULL
WHERE entry.render_task_id = sqlc.arg(task_id)
  AND entry.render_status = 'pending';

-- name: UpsertComponentFeedImageArtifact :one
-- Feed PNG 是可重建派生资产，并明确追溯到实际读取的不可变 GLB Artifact。
INSERT INTO component_repo.artifacts (
    id, owner_id, artifact_type, source_kind, original_filename,
    storage_provider, storage_bucket, storage_key, sha256, file_size,
    mime_type, immutable, verification_status, verified_at, uploaded_by,
    metadata, derived_from_artifact_id
) VALUES (
    sqlc.arg(id), sqlc.arg(owner_id), 'component_feed_image', 'derived',
    sqlc.arg(original_filename), sqlc.arg(storage_provider), sqlc.arg(storage_bucket),
    sqlc.arg(storage_key), sqlc.arg(sha256), sqlc.arg(file_size), 'image/png',
    true, 'verified', now(), sqlc.arg(uploaded_by), sqlc.arg(metadata),
    sqlc.arg(derived_from_artifact_id)
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
