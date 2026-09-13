-- name: ListComponentPublicFeed :many
-- 公共广场从全局发布事件索引取候选，不以当前 actor 的 Watch 关系限制成员资格。
-- 页面事件固定后才聚合 Star 和连接个人关系，避免为游标之后的全部历史事件做逐行计算。
WITH feed_page AS MATERIALIZED (
	SELECT source.event_id,
	       source.occurred_at,
	       entry.available_at,
	       entry.render_status,
	       entry.image_artifact_id,
	       source.component_version_id,
	       source.publisher_id,
	       source.version_label,
	       source.revision,
	       source.published_at,
	       source.release_note,
	       source.release_note_locale,
	       source.id,
	       source.owner_id,
	       source.content_kind,
	       source.content_locale,
	       source.name,
	       source.description,
	       source.tags,
	       source.category,
	       source.status,
	       source.current_version_id,
	       source.logical_width_stud,
	       source.logical_depth_stud,
	       source.logical_height_plate,
	       source.metadata,
	       source.created_at,
	       source.updated_at,
	       source.owned_by_actor
	FROM component_repo.component_feed_entries entry
	JOIN LATERAL (
		-- 单条 entry 的事件、版本和可见 Component 一次校验；OFFSET 0 防止优化器拆散后丢失 Feed 索引顺序。
		SELECT source_event.id AS event_id, source_event.occurred_at,
		       source_event.component_version_id, source_event.actor_id AS publisher_id,
		       version.version_label, version.revision, version.published_at,
		       version.release_note, version.release_note_locale,
		       component.id, component.owner_id, component.content_kind,
		       component.content_locale, component.name, component.description,
		       component.tags, component.category, component.status,
		       component.current_version_id, component.logical_width_stud,
		       component.logical_depth_stud, component.logical_height_plate,
		       component.metadata, component.created_at, component.updated_at,
		       COALESCE(component.owner_id = sqlc.arg(actor_id), false)::boolean AS owned_by_actor
		FROM component_repo.component_domain_events source_event
		JOIN component_repo.components component
		  ON component.id=entry.component_id
		 AND component.id=source_event.component_id
		 AND component.content_kind='user'
		 AND component.status='active'
		 AND component.deleted_at IS NULL
		JOIN component_repo.component_versions version
		  ON version.id=entry.component_version_id
		 AND version.id=source_event.component_version_id
		 AND version.component_id=component.id
		 AND version.deleted_at IS NULL
		WHERE source_event.id=entry.event_id
		  AND source_event.event_type='component.version.published.v1'
		  AND (
		      sqlc.arg(search_query)::text=''
		      OR component.name ILIKE '%' || sqlc.arg(search_query) || '%'
		      OR component.id::text=sqlc.arg(search_query)
		  )
		OFFSET 0
	) source ON true
	WHERE entry.render_status IN ('ready', 'fallback')
	  AND entry.available_at IS NOT NULL
	  AND (entry.available_at, entry.event_id) < (
	      COALESCE(sqlc.narg(cursor_available_at)::timestamptz, 'infinity'::timestamptz),
	      COALESCE(sqlc.narg(cursor_event_id)::uuid, 'ffffffff-ffff-ffff-ffff-ffffffffffff'::uuid)
	  )
	ORDER BY entry.available_at DESC, entry.event_id DESC
    LIMIT sqlc.arg(page_size)
), page_star_counts AS (
    SELECT aggregate_star.component_id, count(*)::bigint AS star_count
    FROM component_repo.component_stars aggregate_star
    JOIN (SELECT DISTINCT id FROM feed_page) page_component
      ON page_component.id = aggregate_star.component_id
    GROUP BY aggregate_star.component_id
)
SELECT page.event_id,
       page.occurred_at,
       page.available_at,
       CASE
           WHEN page.render_status = 'ready'
            AND feed_image.id IS NOT NULL THEN 'ready'
           ELSE 'fallback'
       END::text AS render_status,
       feed_image.id AS image_artifact_id,
       feed_image.storage_provider AS image_storage_provider,
       feed_image.storage_bucket AS image_storage_bucket,
       feed_image.storage_key AS image_storage_key,
       feed_image.sha256 AS image_sha256,
       feed_image.file_size AS image_file_size,
       feed_image.mime_type AS image_mime_type,
       page.component_version_id,
       page.publisher_id,
       page.version_label,
       page.revision,
       page.published_at,
       page.release_note,
       page.release_note_locale,
       page.id,
       page.owner_id,
       page.content_kind,
       page.content_locale,
       page.name,
       COALESCE(page.description, '')::text AS selected_description,
       (page.description IS NOT NULL)::boolean AS has_description,
       page.tags,
       page.category,
       page.status,
       page.current_version_id,
       COALESCE(current_version.logical_width_stud, page.logical_width_stud) AS logical_width_stud,
       COALESCE(current_version.logical_depth_stud, page.logical_depth_stud) AS logical_depth_stud,
       COALESCE(current_version.logical_height_plate, page.logical_height_plate) AS logical_height_plate,
       page.metadata,
       page.created_at,
       page.updated_at,
       page.owned_by_actor,
       EXISTS (
           SELECT 1
           FROM component_repo.component_stars actor_star
           WHERE actor_star.actor_id = sqlc.arg(actor_id)
             AND actor_star.component_id = page.id
       ) AS starred_by_actor,
       COALESCE(page_star_counts.star_count, 0)::bigint AS star_count,
       (active_watch.actor_id IS NOT NULL)::boolean AS watching_by_actor,
       active_watch.watch_level,
       active_watch.watched_at
FROM feed_page page
LEFT JOIN page_star_counts ON page_star_counts.component_id = page.id
LEFT JOIN component_repo.artifacts feed_image
  ON feed_image.id = page.image_artifact_id
 AND feed_image.artifact_type = 'component_feed_image'
 AND feed_image.source_kind = 'derived'
 AND feed_image.verification_status = 'verified'
 AND feed_image.deleted_at IS NULL
LEFT JOIN component_repo.component_versions current_version
  ON current_version.id = page.current_version_id
 AND current_version.component_id = page.id
 AND current_version.deleted_at IS NULL
LEFT JOIN component_repo.component_watch_periods active_watch
  ON active_watch.actor_id = sqlc.arg(actor_id)
 AND active_watch.component_id = page.id
 AND active_watch.ended_seq IS NULL
ORDER BY page.available_at DESC, page.event_id DESC;
