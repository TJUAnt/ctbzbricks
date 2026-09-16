-- name: GetComponentWatchTarget :one
-- Watch 资格检查只读取目标可用性与当前 actor 的关系；不加载 Component 详情、翻译或聚合。
SELECT component.id, component.owner_id, component.status,
       component.public_version_available,
       existing_watch.watch_level,
       existing_watch.id AS watch_period_id,
       existing_watch.started_seq,
       existing_watch.watched_at
FROM component_repo.component_catalog_candidates component
LEFT JOIN component_repo.component_watch_periods existing_watch
  ON existing_watch.actor_id = sqlc.arg(actor_id)
 AND existing_watch.component_id = component.id
 AND existing_watch.ended_seq IS NULL
WHERE component.id = sqlc.arg(component_id)
  AND (component.owner_id = sqlc.arg(actor_id) OR component.status = 'active');

-- name: CreateActiveComponentWatchPeriod :one
-- 没有 active period 时追加新周期；并发重复 PUT 命中部分唯一索引时不更新任何既有行，由 Service 重试读取。
INSERT INTO component_repo.component_watch_periods (actor_id, component_id, watch_level)
VALUES (sqlc.arg(actor_id), sqlc.arg(component_id), sqlc.arg(watch_level))
ON CONFLICT (actor_id, component_id) WHERE ended_seq IS NULL DO NOTHING
RETURNING id, actor_id, component_id, watch_level, started_seq, ended_seq, watched_at, unwatched_at;

-- name: CloseActiveComponentWatchPeriod :execrows
-- 用户主动 Unwatch 仅关闭仍处于 active 生命周期的 Component；结束序号与时间在同一条语句中只写一次。
-- started_seq/ended_seq 是不可变关系审计与生命周期顺序，不参与 read-time Feed 成员资格判断。
UPDATE component_repo.component_watch_periods
SET ended_seq = nextval('component_repo.component_activity_sequence'),
    unwatched_at = clock_timestamp(),
    ended_reason = 'user_unwatched'
WHERE actor_id = sqlc.arg(actor_id)
  AND component_id = sqlc.arg(component_id)
  AND ended_seq IS NULL
  -- Component 生命周期结束后由持久清理任务写统一边界；延迟到达的 Unwatch 只能幂等成功，不能覆盖该边界。
  AND EXISTS (
      SELECT 1
      FROM component_repo.components component
      WHERE component.id = component_watch_periods.component_id
        AND component.deleted_at IS NULL
        AND component.status = 'active'
  );

-- name: CreateComponentRelationshipEndBoundary :one
-- Component 删除事务只分配一次公共生命周期边界并把它冻结进持久任务；所有 active Watch 共用该值。
-- sequence 只保证相对顺序并允许回滚空洞，不是 Feed cursor、recipient 或连续业务编号。
SELECT nextval('component_repo.component_activity_sequence')::bigint AS ended_seq,
       clock_timestamp()::timestamptz AS ended_at;

-- name: CloseActiveComponentWatchesForLifecycleBatch :many
-- Worker 按 Component active 索引和 actor 闭区间游标分批关闭周期；游标避免每批从索引起点重复跳过已关闭项。
WITH batch AS MATERIALIZED (
    SELECT watch.id, watch.actor_id
    FROM component_repo.component_watch_periods watch
    WHERE watch.component_id = sqlc.arg(component_id)
      AND watch.ended_seq IS NULL
      AND watch.actor_id >= sqlc.arg(after_actor_id)
    ORDER BY watch.actor_id
    LIMIT sqlc.arg(batch_size)
    FOR UPDATE
)
UPDATE component_repo.component_watch_periods watch
SET ended_seq = sqlc.arg(ended_seq)::bigint,
    unwatched_at = sqlc.arg(ended_at)::timestamptz,
    ended_reason = sqlc.arg(ended_reason)::text
FROM batch
WHERE watch.id = batch.id
  AND watch.ended_seq IS NULL
RETURNING watch.actor_id;

-- name: ListActiveComponentWatches :many
-- actor 关系索引先限定有界候选；筛选后固定一页，再读取 Component 展示和当前发布版本。
-- 搜索翻译仅在 search_query 非空时探测，普通列表不会在分页前逐行读取翻译。
WITH actor_watches AS MATERIALIZED (
    SELECT watch.component_id, watch.watch_level, watch.watched_at
    FROM component_repo.component_watch_periods watch
    WHERE watch.actor_id = sqlc.arg(actor_id)
      AND watch.ended_seq IS NULL
      -- NULL cursor 使用正无穷哨兵；深页使用双 DESC row comparison，确保边界进入复合索引 Index Cond。
      AND (watch.watched_at, watch.component_id) < (
          COALESCE(sqlc.narg(cursor_watched_at)::timestamptz, 'infinity'::timestamptz),
          COALESCE(sqlc.narg(cursor_component_id)::uuid, 'ffffffff-ffff-ffff-ffff-ffffffffffff'::uuid)
      )
), watch_page AS MATERIALIZED (
    SELECT watch.component_id, watch.watch_level, watch.watched_at
    FROM actor_watches watch
    JOIN component_repo.component_catalog_candidates component ON component.id = watch.component_id
    LEFT JOIN LATERAL (
        SELECT item.id, item.name
        FROM component_repo.component_reviewed_translations item
        WHERE sqlc.arg(search_query)::text <> ''
          AND component.content_kind = 'official'
          AND item.component_id = component.id
          AND item.locale = sqlc.arg(locale)
        LIMIT 1
    ) search_translation ON true
    WHERE component.status = 'active'
      AND component.public_version_available
      AND (sqlc.arg(category_filter)::text = '' OR component.category = sqlc.arg(category_filter))
      -- leading-wildcard 搜索只运行在当前 actor 的有界 Watch 候选集内，不依赖普通 B-tree。
      AND (
          sqlc.arg(search_query)::text = ''
          OR CASE WHEN search_translation.id IS NULL THEN component.name ELSE search_translation.name END
             ILIKE '%' || sqlc.arg(search_query) || '%'
          OR component.id::text ILIKE '%' || sqlc.arg(search_query) || '%'
      )
    ORDER BY watch.watched_at DESC, watch.component_id DESC
    LIMIT sqlc.arg(page_size)
)
SELECT page.component_id,
       component.content_kind,
       (CASE WHEN translation.id IS NULL THEN component.content_locale ELSE translation.locale END)::text AS selected_content_locale,
       (CASE WHEN translation.id IS NULL THEN component.name ELSE translation.name END)::text AS selected_name,
       component.category,
       component.current_version_id,
       current_version.version_label,
       current_version.revision,
       current_version.published_at,
       page.watch_level,
       page.watched_at,
       (component.content_kind = 'official' AND component.content_locale <> sqlc.arg(locale)
        AND translation.id IS NULL)::boolean AS translation_missing
FROM watch_page page
JOIN component_repo.component_catalog_projection component ON component.id = page.component_id
LEFT JOIN component_repo.component_versions current_version
  ON current_version.id = component.current_version_id
 AND current_version.deleted_at IS NULL
LEFT JOIN LATERAL (
    SELECT item.id, item.locale, item.name
    FROM component_repo.component_reviewed_translations item
    WHERE component.content_kind = 'official'
      AND item.component_id = component.id
      AND item.locale = sqlc.arg(locale)
    LIMIT 1
) translation ON true
ORDER BY page.watched_at DESC, page.component_id DESC;

-- name: ListCurrentComponentWatchFeed :many
-- Feed 成员资格在读取时按当前 active Watch 计算：发布早于 Watch 也可出现，Unwatch 后立即消失。
-- actor-scoped active partial index 先把候选限定为当前规划的最多 1,000 个 Component；页面固定后才读取
-- Component 翻译、Star 和终态图片投影，closed Watch 历史不参与任何执行节点。
WITH active_watches AS MATERIALIZED (
    SELECT watch.component_id, watch.watch_level, watch.watched_at
    FROM component_repo.component_watch_periods watch
    WHERE watch.actor_id = sqlc.arg(actor_id)
      AND watch.ended_seq IS NULL
), feed_page AS MATERIALIZED (
    SELECT event.id AS event_id,
           event.event_type,
           event.component_id,
           event.component_version_id,
           event.actor_id AS publisher_id,
           event.occurred_at,
           event.available_at,
           event.render_status,
           event.image_artifact_id,
           watch.watch_level,
           watch.watched_at
    FROM active_watches watch
    JOIN component_repo.component_catalog_candidates component
      ON component.id = watch.component_id
     AND component.status = 'active'
     AND component.public_version_available
    -- 全局一页不可能包含同一 Component 排名超过 page_size 的事件；先对每个 active Watch
    -- 截断到一页保持结果等价，同时强制历史增长时仍按 Component/time 索引做有界探测。
    JOIN LATERAL (
        SELECT item.id, item.event_type, item.component_id, item.component_version_id, item.actor_id,
               item.occurred_at, entry.available_at, entry.render_status, entry.image_artifact_id
        FROM component_repo.component_domain_events item
        JOIN component_repo.component_feed_entries entry
          ON entry.event_id = item.id
         AND entry.component_id = item.component_id
         AND entry.component_version_id = item.component_version_id
         AND entry.render_status IN ('ready', 'fallback')
         AND entry.available_at IS NOT NULL
        WHERE item.component_id = watch.component_id
          AND item.occurred_at >= sqlc.arg(window_start)::timestamptz
          AND (item.occurred_at, item.id) < (
              COALESCE(sqlc.narg(cursor_occurred_at)::timestamptz, 'infinity'::timestamptz),
              COALESCE(sqlc.narg(cursor_event_id)::uuid, 'ffffffff-ffff-ffff-ffff-ffffffffffff'::uuid)
          )
        ORDER BY item.occurred_at DESC, item.id DESC
        LIMIT sqlc.arg(page_size)
    ) event ON true
    ORDER BY event.occurred_at DESC, event.id DESC
    LIMIT sqlc.arg(page_size)
)
SELECT page.event_id,
       page.event_type,
       page.occurred_at,
       page.available_at,
       CASE
           WHEN page.render_status = 'ready' AND feed_image.id IS NOT NULL THEN 'ready'
           ELSE 'fallback'
       END::text AS render_status,
       feed_image.id AS image_artifact_id,
       feed_image.storage_provider AS image_storage_provider,
       feed_image.storage_bucket AS image_storage_bucket,
       feed_image.storage_key AS image_storage_key,
       feed_image.sha256 AS image_sha256,
       feed_image.file_size AS image_file_size,
       page.component_id,
       component.owner_id,
       component.content_kind,
       (CASE WHEN translation.id IS NULL THEN component.content_locale ELSE translation.locale END)::text
           AS selected_content_locale,
       (CASE WHEN translation.id IS NULL THEN component.name ELSE translation.name END)::text AS selected_name,
       COALESCE(CASE WHEN translation.id IS NULL THEN component.description ELSE translation.description END, '')::text
           AS selected_description,
       (CASE WHEN translation.id IS NULL THEN component.description IS NOT NULL ELSE translation.description IS NOT NULL END)::boolean
           AS has_description,
       (CASE WHEN translation.id IS NULL THEN component.tags ELSE translation.tags END)::text[] AS selected_tags,
       component.category,
       component.status,
       component.current_version_id,
       component.logical_width_stud,
       component.logical_depth_stud,
       component.logical_height_plate,
       component.metadata,
       component.created_at,
       component.updated_at,
       page.component_version_id,
       page.publisher_id,
       version.version_label,
       version.revision,
       version.published_at,
       version.release_note,
       version.release_note_locale,
       false::boolean AS owned_by_actor,
       EXISTS (
           SELECT 1
           FROM component_repo.component_stars actor_star
           WHERE actor_star.actor_id = sqlc.arg(actor_id)
             AND actor_star.component_id = page.component_id
       ) AS starred_by_actor,
       page_star_count.star_count,
       page.watch_level,
       page.watched_at,
       (component.content_kind = 'official' AND component.content_locale <> sqlc.arg(locale)
        AND translation.id IS NULL)::boolean AS translation_missing
FROM feed_page page
JOIN component_repo.component_catalog_projection component ON component.id = page.component_id
JOIN component_repo.component_versions version
  ON version.id = page.component_version_id
 AND version.deleted_at IS NULL
LEFT JOIN LATERAL (
    SELECT item.id, item.locale, item.name, item.description, item.tags
    FROM component_repo.component_reviewed_translations item
    WHERE component.content_kind = 'official'
      AND item.component_id = component.id
      AND item.locale = sqlc.arg(locale)
    LIMIT 1
) translation ON true
-- 聚合只对已经固定的一页 Component 做索引探测，禁止优化器为少量卡片扫描全部 Star 关系。
JOIN LATERAL (
    SELECT count(*)::bigint AS star_count
    FROM component_repo.component_stars aggregate_star
    WHERE aggregate_star.component_id = page.component_id
    OFFSET 0
) page_star_count ON true
LEFT JOIN component_repo.artifacts feed_image
  ON feed_image.id = page.image_artifact_id
 AND feed_image.artifact_type = 'component_feed_image'
 AND feed_image.source_kind = 'derived'
 AND feed_image.verification_status = 'verified'
 AND feed_image.deleted_at IS NULL
ORDER BY page.occurred_at DESC, page.event_id DESC;
