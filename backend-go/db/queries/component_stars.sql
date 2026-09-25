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
       component.public_version_available,
       existing_star.starred_at
FROM component_repo.component_catalog_candidates component
LEFT JOIN component_repo.component_stars existing_star
  ON existing_star.actor_id = sqlc.arg(actor_id)
 AND existing_star.component_id = component.id
WHERE component.id = sqlc.arg(component_id)
  AND (component.owner_id = sqlc.arg(actor_id) OR component.status = 'active');

-- name: ListStarredComponents :many
-- 收藏列表只维护一份可见性与筛选谓词，并在分页前用窗口计数固定 exact total；归档/删除提交后立即隐藏。
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
       star.starred_at,
       count(*) OVER ()::bigint AS total
FROM actor_stars star
JOIN component_repo.component_catalog_candidates component ON component.id = star.component_id
LEFT JOIN LATERAL (
    SELECT item.id, item.locale, item.name, item.description, item.tags
    FROM component_repo.component_reviewed_translations item
    WHERE component.content_kind = 'official'
      AND item.component_id = component.id
      AND item.locale = sqlc.arg(locale)
    LIMIT 1
) translation ON true
LEFT JOIN LATERAL (
    -- 只有尺寸筛选启用时才读取当前展示 Version；无尺寸条件时执行计划必须让该内层零循环。
    SELECT projection.logical_width_stud,
           projection.logical_depth_stud,
           projection.logical_height_plate
    FROM component_repo.component_catalog_projection projection
    WHERE (sqlc.arg(has_width)::boolean OR sqlc.arg(has_depth)::boolean OR sqlc.arg(has_height)::boolean)
      AND projection.id = component.id
) filter_size ON true
WHERE component.status = 'active'
  AND component.public_version_available
  AND (sqlc.arg(category_filter)::text = '' OR component.category = sqlc.arg(category_filter))
  AND lower(CASE WHEN translation.id IS NULL THEN component.name ELSE translation.name END)
      LIKE ALL(sqlc.arg(name_patterns)::text[])
  AND (
      sqlc.arg(component_id_filter)::text = ''
      OR position(sqlc.arg(component_id_filter)::text IN lower(component.id::text)) > 0
  )
  AND (
      (NOT sqlc.arg(has_width)::boolean AND NOT sqlc.arg(has_depth)::boolean)
      OR (
          sqlc.arg(has_width)::boolean AND sqlc.arg(has_depth)::boolean
          AND least(filter_size.logical_width_stud, filter_size.logical_depth_stud)
              BETWEEN least(sqlc.arg(width_stud)::double precision, sqlc.arg(depth_stud)::double precision) - 0.25
                  AND least(sqlc.arg(width_stud)::double precision, sqlc.arg(depth_stud)::double precision) + 0.25
          AND greatest(filter_size.logical_width_stud, filter_size.logical_depth_stud)
              BETWEEN greatest(sqlc.arg(width_stud)::double precision, sqlc.arg(depth_stud)::double precision) - 0.25
                  AND greatest(sqlc.arg(width_stud)::double precision, sqlc.arg(depth_stud)::double precision) + 0.25
      )
      OR (sqlc.arg(has_width)::boolean AND NOT sqlc.arg(has_depth)::boolean
          AND (filter_size.logical_width_stud BETWEEN sqlc.arg(width_stud)::double precision - 0.25 AND sqlc.arg(width_stud)::double precision + 0.25
               OR filter_size.logical_depth_stud BETWEEN sqlc.arg(width_stud)::double precision - 0.25 AND sqlc.arg(width_stud)::double precision + 0.25))
      OR (NOT sqlc.arg(has_width)::boolean AND sqlc.arg(has_depth)::boolean
          AND (filter_size.logical_width_stud BETWEEN sqlc.arg(depth_stud)::double precision - 0.25 AND sqlc.arg(depth_stud)::double precision + 0.25
               OR filter_size.logical_depth_stud BETWEEN sqlc.arg(depth_stud)::double precision - 0.25 AND sqlc.arg(depth_stud)::double precision + 0.25))
  )
  AND (
      NOT sqlc.arg(has_height)::boolean
      OR filter_size.logical_height_plate
          BETWEEN sqlc.arg(height_plate)::double precision - 0.625
              AND sqlc.arg(height_plate)::double precision + 0.625
  )
ORDER BY star.starred_at DESC, component.id
LIMIT sqlc.arg(page_size) OFFSET sqlc.arg(page_offset)
)
SELECT page.id, page.owner_id, page.content_kind, page.selected_content_locale,
       page.selected_name, page.selected_description, page.has_description,
       page.selected_tags, page.category, page.status, page.current_version_id,
       display_component.logical_width_stud, display_component.logical_depth_stud,
       display_component.logical_height_plate,
       page.metadata, page.created_at, page.updated_at, page.owned_by_actor,
       page.translation_missing, page.starred_by_actor,
       page_star_count.star_count,
       page.starred_at, page.total
FROM page
JOIN component_repo.component_catalog_projection display_component ON display_component.id = page.id
JOIN LATERAL (
    -- 页面先固定到最多 100 行，再按 component_id 索引逐页项聚合；禁止优化器为少量卡片扫描全部 Star。
    SELECT count(*)::bigint AS star_count
    FROM component_repo.component_stars aggregate_star
    WHERE aggregate_star.component_id = page.id
) page_star_count ON true
ORDER BY page.starred_at DESC, page.id;
