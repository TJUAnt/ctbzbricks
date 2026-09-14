-- name: AcquireSharedComponentActivityLock :exec
-- Watch/Unwatch 使用同一 Component 的共享事务锁；Publish 与 Component 删除使用独占锁冻结各自顺序边界。
SELECT pg_advisory_xact_lock_shared(sqlc.arg(lock_key)::bigint);

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
-- Component 删除事务只分配一次公共边界并把它冻结进持久任务；回滚产生的 sequence 空洞没有业务含义。
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
-- Component 翻译与 Version 展示字段，closed Watch 历史不参与任何执行节点。
WITH active_watches AS MATERIALIZED (
    SELECT watch.component_id
    FROM component_repo.component_watch_periods watch
    WHERE watch.actor_id = sqlc.arg(actor_id)
      AND watch.ended_seq IS NULL
), feed_page AS MATERIALIZED (
    SELECT event.id AS event_id,
           event.event_type,
           event.component_id,
           event.component_version_id,
           event.occurred_at
    FROM active_watches watch
    JOIN component_repo.component_catalog_candidates component
      ON component.id = watch.component_id
     AND component.status = 'active'
     AND component.public_version_available
    -- 全局一页不可能包含同一 Component 排名超过 page_size 的事件；先对每个 active Watch
    -- 截断到一页保持结果等价，同时强制历史增长时仍按 Component/time 索引做有界探测。
    JOIN LATERAL (
        SELECT item.id, item.event_type, item.component_id, item.component_version_id, item.occurred_at
        FROM component_repo.component_domain_events item
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
       page.component_id,
       component.content_kind,
       (CASE WHEN translation.id IS NULL THEN component.content_locale ELSE translation.locale END)::text
           AS selected_content_locale,
       (CASE WHEN translation.id IS NULL THEN component.name ELSE translation.name END)::text AS selected_name,
       component.category,
       page.component_version_id,
       version.version_label,
       version.revision,
       version.published_at,
       version.release_note,
       version.release_note_locale,
       (component.content_kind = 'official' AND component.content_locale <> sqlc.arg(locale)
        AND translation.id IS NULL)::boolean AS translation_missing
FROM feed_page page
JOIN component_repo.component_catalog_projection component ON component.id = page.component_id
JOIN component_repo.component_versions version
  ON version.id = page.component_version_id
 AND version.deleted_at IS NULL
LEFT JOIN LATERAL (
    SELECT item.id, item.locale, item.name
    FROM component_repo.component_reviewed_translations item
    WHERE component.content_kind = 'official'
      AND item.component_id = component.id
      AND item.locale = sqlc.arg(locale)
    LIMIT 1
) translation ON true
ORDER BY page.occurred_at DESC, page.event_id DESC;
