-- name: CreateComponentStar :one
INSERT INTO component_repo.component_stars (actor_id, component_id, source)
VALUES (sqlc.arg(actor_id), sqlc.arg(component_id), 'user_action')
ON CONFLICT (actor_id, component_id) DO UPDATE
SET starred_at = component_repo.component_stars.starred_at
RETURNING actor_id, component_id, starred_at, source;

-- name: DeleteComponentStar :one
DELETE FROM component_repo.component_stars
WHERE actor_id = sqlc.arg(actor_id) AND component_id = sqlc.arg(component_id)
RETURNING component_id;

-- name: DeleteComponentStarsForLifecycleBatch :many
-- Star 是当前收藏状态而不是审计账本；Worker 按 Component 索引和 actor 游标分批物理删除，重试天然幂等。
WITH batch AS MATERIALIZED (
    SELECT star.actor_id
    FROM component_repo.component_stars star
    WHERE star.component_id = sqlc.arg(component_id)
      AND star.actor_id >= sqlc.arg(after_actor_id)
    ORDER BY star.actor_id
    LIMIT sqlc.arg(batch_size)
    FOR UPDATE
)
DELETE FROM component_repo.component_stars star
USING batch
WHERE star.component_id = sqlc.arg(component_id)
  AND star.actor_id = batch.actor_id
RETURNING star.actor_id;

-- name: GetComponentStarTarget :one
-- 收藏资格检查只读取授权所需的最小投影；已有关系一并返回，以便幂等请求跳过写入和聚合计数。
SELECT component.id, component.owner_id, component.status,
       EXISTS (
           SELECT 1
           FROM component_repo.component_versions version
           WHERE version.component_id = component.id
             AND version.deleted_at IS NULL
             AND version.status <> 'draft'
       )::boolean AS public_version_available,
       existing_star.starred_at
FROM component_repo.components component
LEFT JOIN component_repo.component_stars existing_star
  ON existing_star.actor_id = sqlc.arg(actor_id)
 AND existing_star.component_id = component.id
WHERE component.id = sqlc.arg(component_id)
  AND component.deleted_at IS NULL
  AND (component.owner_id = sqlc.arg(actor_id) OR component.status = 'active');

-- name: CountStarredComponents :one
-- 先物化 actor 的有界权威关系集，再逐候选探测 Component 与可公开 Version；避免空/稀疏 actor 先构建全库哈希。
WITH actor_stars AS MATERIALIZED (
    SELECT star.component_id, star.starred_at
    FROM component_repo.component_stars star
    WHERE star.actor_id = sqlc.arg(actor_id)
)
SELECT count(*)::bigint AS total,
       (SELECT count(*)::bigint
        FROM actor_stars) AS relationship_total
FROM actor_stars star
JOIN component_repo.components component ON component.id = star.component_id
JOIN LATERAL (
    SELECT true AS available
    FROM component_repo.component_versions version
    WHERE version.component_id = component.id
      AND version.deleted_at IS NULL
      AND version.status <> 'draft'
    LIMIT 1
) public_version ON true
LEFT JOIN LATERAL (
    SELECT translation.id, translation.name
    FROM component_repo.component_translations translation
    WHERE component.content_kind = 'official'
      AND sqlc.arg(search_query)::text <> ''
      AND translation.component_id = component.id
      AND translation.locale = sqlc.arg(locale)
      AND translation.translation_status = 'reviewed'
    LIMIT 1
) translation ON true
WHERE component.deleted_at IS NULL
  AND component.status = 'active'
  AND (sqlc.arg(category_filter)::text = '' OR component.category = sqlc.arg(category_filter))
  AND (
      sqlc.arg(search_query)::text = ''
      OR CASE WHEN translation.id IS NULL THEN component.name ELSE translation.name END
         ILIKE '%' || sqlc.arg(search_query) || '%'
      OR component.id::text ILIKE '%' || sqlc.arg(search_query) || '%'
  )
  AND (
      sqlc.arg(size_dimension_count)::integer = 0
      OR COALESCE(
          (sqlc.arg(size_dimension_count)::integer = 3
           AND component.current_logical_size_a > sqlc.arg(size_a)::double precision - 1
           AND component.current_logical_size_a < sqlc.arg(size_a)::double precision + 1
           AND component.current_logical_size_b > sqlc.arg(size_b)::double precision - 1
           AND component.current_logical_size_b < sqlc.arg(size_b)::double precision + 1
           AND component.current_logical_size_c > sqlc.arg(size_c)::double precision - 1
           AND component.current_logical_size_c < sqlc.arg(size_c)::double precision + 1)
          OR
          (sqlc.arg(size_dimension_count)::integer = 2 AND (
              (component.current_logical_size_a > sqlc.arg(size_a)::double precision - 1
               AND component.current_logical_size_a < sqlc.arg(size_a)::double precision + 1
               AND component.current_logical_size_b > sqlc.arg(size_b)::double precision - 1
               AND component.current_logical_size_b < sqlc.arg(size_b)::double precision + 1)
              OR
              (component.current_logical_size_a > sqlc.arg(size_a)::double precision - 1
               AND component.current_logical_size_a < sqlc.arg(size_a)::double precision + 1
               AND component.current_logical_size_c > sqlc.arg(size_b)::double precision - 1
               AND component.current_logical_size_c < sqlc.arg(size_b)::double precision + 1)
              OR
              (component.current_logical_size_b > sqlc.arg(size_a)::double precision - 1
               AND component.current_logical_size_b < sqlc.arg(size_a)::double precision + 1
               AND component.current_logical_size_c > sqlc.arg(size_b)::double precision - 1
               AND component.current_logical_size_c < sqlc.arg(size_b)::double precision + 1)
          )), false)
  );

-- name: ListStarredComponents :many
-- 收藏列表只投影仍公开可见的 Component；归档/删除提交后立即隐藏，v17 Worker 最终物理删除关系且不恢复。
WITH actor_stars AS MATERIALIZED (
    -- 该候选集受当前产品每 actor 1,000 条 Star 包络约束；物化用于阻止规划器改从全 Component/Version 驱动。
    SELECT star.component_id, star.starred_at
    FROM component_repo.component_stars star
    WHERE star.actor_id = sqlc.arg(actor_id)
), page AS MATERIALIZED (
SELECT component.id, component.owner_id, component.content_kind,
       (CASE WHEN translation.id IS NULL THEN component.content_locale ELSE translation.locale END)::text AS selected_content_locale,
       (CASE WHEN translation.id IS NULL THEN component.name ELSE translation.name END)::text AS selected_name,
       COALESCE(CASE WHEN translation.id IS NULL THEN component.description ELSE translation.description END, '')::text AS selected_description,
       (CASE WHEN translation.id IS NULL THEN component.description ELSE translation.description END IS NOT NULL)::boolean AS has_description,
       (CASE WHEN translation.id IS NULL THEN component.tags ELSE translation.tags END)::text[] AS selected_tags,
       component.category, component.status, component.current_version_id,
       component.logical_width_stud, component.logical_depth_stud, component.logical_height_plate,
       component.metadata, component.created_at, component.updated_at,
       false::boolean AS owned_by_actor,
       (component.content_kind = 'official' AND component.content_locale <> sqlc.arg(locale)
        AND translation.id IS NULL)::boolean AS translation_missing,
       true::boolean AS starred_by_actor,
       star.starred_at
FROM actor_stars star
JOIN component_repo.components component ON component.id = star.component_id
JOIN LATERAL (
    SELECT true AS available
    FROM component_repo.component_versions version
    WHERE version.component_id = component.id
      AND version.deleted_at IS NULL
      AND version.status <> 'draft'
    LIMIT 1
) public_version ON true
LEFT JOIN LATERAL (
    SELECT item.id, item.locale, item.name, item.description, item.tags
    FROM component_repo.component_translations item
    WHERE component.content_kind = 'official'
      AND item.component_id = component.id
      AND item.locale = sqlc.arg(locale)
      AND item.translation_status = 'reviewed'
    LIMIT 1
) translation ON true
WHERE component.deleted_at IS NULL
  AND component.status = 'active'
  AND (sqlc.arg(category_filter)::text = '' OR component.category = sqlc.arg(category_filter))
  AND (
      sqlc.arg(search_query)::text = ''
      OR CASE WHEN translation.id IS NULL THEN component.name ELSE translation.name END
         ILIKE '%' || sqlc.arg(search_query) || '%'
      OR component.id::text ILIKE '%' || sqlc.arg(search_query) || '%'
  )
  AND (
      sqlc.arg(size_dimension_count)::integer = 0
      OR COALESCE(
          (sqlc.arg(size_dimension_count)::integer = 3
           AND component.current_logical_size_a > sqlc.arg(size_a)::double precision - 1
           AND component.current_logical_size_a < sqlc.arg(size_a)::double precision + 1
           AND component.current_logical_size_b > sqlc.arg(size_b)::double precision - 1
           AND component.current_logical_size_b < sqlc.arg(size_b)::double precision + 1
           AND component.current_logical_size_c > sqlc.arg(size_c)::double precision - 1
           AND component.current_logical_size_c < sqlc.arg(size_c)::double precision + 1)
          OR
          (sqlc.arg(size_dimension_count)::integer = 2 AND (
              (component.current_logical_size_a > sqlc.arg(size_a)::double precision - 1
               AND component.current_logical_size_a < sqlc.arg(size_a)::double precision + 1
               AND component.current_logical_size_b > sqlc.arg(size_b)::double precision - 1
               AND component.current_logical_size_b < sqlc.arg(size_b)::double precision + 1)
              OR
              (component.current_logical_size_a > sqlc.arg(size_a)::double precision - 1
               AND component.current_logical_size_a < sqlc.arg(size_a)::double precision + 1
               AND component.current_logical_size_c > sqlc.arg(size_b)::double precision - 1
               AND component.current_logical_size_c < sqlc.arg(size_b)::double precision + 1)
              OR
              (component.current_logical_size_b > sqlc.arg(size_a)::double precision - 1
               AND component.current_logical_size_b < sqlc.arg(size_a)::double precision + 1
               AND component.current_logical_size_c > sqlc.arg(size_b)::double precision - 1
               AND component.current_logical_size_c < sqlc.arg(size_b)::double precision + 1)
          )), false)
  )
ORDER BY star.starred_at DESC, component.id
LIMIT sqlc.arg(page_size) OFFSET sqlc.arg(page_offset)
), page_star_counts AS (
    -- 先固定当前页，再按 component_id 一次聚合，避免列表对每行执行一次 COUNT。
    SELECT aggregate_star.component_id, count(*)::bigint AS star_count
    FROM component_repo.component_stars aggregate_star
    JOIN page ON page.id = aggregate_star.component_id
    GROUP BY aggregate_star.component_id
)
SELECT page.id, page.owner_id, page.content_kind, page.selected_content_locale,
       page.selected_name, page.selected_description, page.has_description,
       page.selected_tags, page.category, page.status, page.current_version_id,
       COALESCE(display_version.logical_width_stud, page.logical_width_stud) AS logical_width_stud,
       COALESCE(display_version.logical_depth_stud, page.logical_depth_stud) AS logical_depth_stud,
       COALESCE(display_version.logical_height_plate, page.logical_height_plate) AS logical_height_plate,
       page.metadata, page.created_at, page.updated_at, page.owned_by_actor,
       page.translation_missing, page.starred_by_actor,
       COALESCE(page_star_counts.star_count, 0)::bigint AS star_count,
       page.starred_at
FROM page
LEFT JOIN LATERAL (
    -- 原始有方向尺寸仅服务最终展示；必须在 page 固定后读取，不能扩大到 actor 的全部候选。
    SELECT version.logical_width_stud, version.logical_depth_stud,
           version.logical_height_plate
    FROM component_repo.component_versions version
    WHERE version.component_id = page.id
      AND version.deleted_at IS NULL
      AND version.id = page.current_version_id
    LIMIT 1
) display_version ON true
LEFT JOIN page_star_counts ON page_star_counts.component_id = page.id
ORDER BY page.starred_at DESC, page.id;
