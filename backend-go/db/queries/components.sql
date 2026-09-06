-- name: CreateComponent :one
INSERT INTO component_repo.components (
    id, owner_id, content_kind, content_locale, name, description, tags, category,
    status, created_by
) VALUES (
    sqlc.arg(id), sqlc.arg(owner_id), 'user', sqlc.arg(content_locale), sqlc.arg(name),
    sqlc.narg(description), sqlc.arg(tags), sqlc.narg(category), 'draft', sqlc.arg(created_by)
)
RETURNING id, owner_id, content_kind, content_locale, name, description, tags,
          category, status, current_version_id, logical_width_stud,
          logical_depth_stud, logical_height_plate, metadata, created_by,
          created_at, updated_at, deleted_at, deleted_by;

-- name: GetVisibleComponent :one
SELECT c.id, c.owner_id, c.content_kind,
       (CASE WHEN translation.id IS NULL THEN c.content_locale ELSE translation.locale END)::text AS selected_content_locale,
       (CASE WHEN translation.id IS NULL THEN c.name ELSE translation.name END)::text AS selected_name,
       COALESCE(CASE WHEN translation.id IS NULL THEN c.description ELSE translation.description END, '')::text AS selected_description,
       (CASE WHEN translation.id IS NULL THEN c.description ELSE translation.description END IS NOT NULL)::boolean AS has_description,
       (CASE WHEN translation.id IS NULL THEN c.tags ELSE translation.tags END)::text[] AS selected_tags,
       c.category, c.status, c.current_version_id,
       COALESCE(display_version.logical_width_stud, c.logical_width_stud) AS logical_width_stud,
       COALESCE(display_version.logical_depth_stud, c.logical_depth_stud) AS logical_depth_stud,
       COALESCE(display_version.logical_height_plate, c.logical_height_plate) AS logical_height_plate,
       c.metadata, c.created_by,
       c.created_at, c.updated_at,
       COALESCE(c.owner_id = sqlc.arg(actor_id), false)::boolean AS owned_by_actor,
       (c.content_kind = 'official' AND c.content_locale <> sqlc.arg(locale)
        AND translation.id IS NULL)::boolean AS translation_missing,
       EXISTS (
           SELECT 1 FROM component_repo.component_stars star
           WHERE star.actor_id = sqlc.arg(actor_id)
             AND star.component_id = c.id
       ) AS starred_by_actor,
       (active_watch.actor_id IS NOT NULL)::boolean AS watching_by_actor,
       active_watch.watch_level,
       active_watch.watched_at,
       (SELECT count(*)::bigint
        FROM component_repo.component_stars aggregate_star
        WHERE aggregate_star.component_id = c.id)::bigint AS star_count
FROM component_repo.components c
LEFT JOIN LATERAL (
    SELECT version.logical_width_stud, version.logical_depth_stud,
           version.logical_height_plate
    FROM component_repo.component_versions version
    WHERE version.component_id = c.id
      AND version.deleted_at IS NULL
      AND (
          version.id = c.current_version_id
          OR (c.current_version_id IS NULL AND version.status = 'draft')
      )
    ORDER BY (version.id = c.current_version_id) DESC,
             version.created_at DESC, version.id DESC
    LIMIT 1
) display_version ON true
LEFT JOIN LATERAL (
    SELECT t.id, t.locale, t.name, t.description, t.tags
    FROM component_repo.component_translations t
    WHERE c.content_kind = 'official'
      AND t.component_id = c.id
      AND t.locale = sqlc.arg(locale)
      AND t.translation_status = 'reviewed'
    LIMIT 1
) translation ON true
LEFT JOIN component_repo.component_watch_periods active_watch
  ON active_watch.actor_id = sqlc.arg(actor_id)
 AND active_watch.component_id = c.id
 AND active_watch.ended_seq IS NULL
WHERE c.id = sqlc.arg(component_id)
  AND c.deleted_at IS NULL
  AND (c.owner_id = sqlc.arg(actor_id) OR c.status = 'active');

-- name: ListVisibleComponents :many
WITH page AS MATERIALIZED (
SELECT c.id, c.owner_id, c.content_kind,
       (CASE WHEN translation.id IS NULL THEN c.content_locale ELSE translation.locale END)::text AS selected_content_locale,
       (CASE WHEN translation.id IS NULL THEN c.name ELSE translation.name END)::text AS selected_name,
       COALESCE(CASE WHEN translation.id IS NULL THEN c.description ELSE translation.description END, '')::text AS selected_description,
       (CASE WHEN translation.id IS NULL THEN c.description ELSE translation.description END IS NOT NULL)::boolean AS has_description,
       (CASE WHEN translation.id IS NULL THEN c.tags ELSE translation.tags END)::text[] AS selected_tags,
       c.category, c.status, c.current_version_id,
       COALESCE(display_version.logical_width_stud, c.logical_width_stud) AS logical_width_stud,
       COALESCE(display_version.logical_depth_stud, c.logical_depth_stud) AS logical_depth_stud,
       COALESCE(display_version.logical_height_plate, c.logical_height_plate) AS logical_height_plate,
       c.metadata, c.created_by,
       c.created_at, c.updated_at,
       COALESCE(c.owner_id = sqlc.arg(actor_id), false)::boolean AS owned_by_actor,
       (c.content_kind = 'official' AND c.content_locale <> sqlc.arg(locale)
        AND translation.id IS NULL)::boolean AS translation_missing,
       EXISTS (
           SELECT 1 FROM component_repo.component_stars star
           WHERE star.actor_id = sqlc.arg(actor_id)
             AND star.component_id = c.id
       ) AS starred_by_actor
FROM component_repo.components c
LEFT JOIN LATERAL (
    SELECT version.logical_width_stud, version.logical_depth_stud,
           version.logical_height_plate
    FROM component_repo.component_versions version
    WHERE version.component_id = c.id
      AND version.deleted_at IS NULL
      AND (
          version.id = c.current_version_id
          OR (c.current_version_id IS NULL AND version.status = 'draft')
      )
    ORDER BY (version.id = c.current_version_id) DESC,
             version.created_at DESC, version.id DESC
    LIMIT 1
) display_version ON true
LEFT JOIN LATERAL (
    SELECT t.id, t.locale, t.name, t.description, t.tags
    FROM component_repo.component_translations t
    WHERE c.content_kind = 'official'
      AND t.component_id = c.id
      AND t.locale = sqlc.arg(locale)
      AND t.translation_status = 'reviewed'
    LIMIT 1
) translation ON true
WHERE c.deleted_at IS NULL
  AND (c.owner_id = sqlc.arg(actor_id) OR c.status = 'active')
  AND EXISTS (
      SELECT 1
      FROM component_repo.component_versions version
      WHERE version.component_id = c.id
        AND version.deleted_at IS NULL
        AND (
            c.owner_id = sqlc.arg(actor_id)
            OR (c.status = 'active' AND version.status <> 'draft')
        )
  )
  AND (sqlc.arg(status_filter)::text = '' OR c.status = sqlc.arg(status_filter))
  AND (sqlc.arg(category_filter)::text = '' OR c.category = sqlc.arg(category_filter))
  AND (
      sqlc.arg(search_query)::text = ''
      OR CASE WHEN translation.id IS NULL THEN c.name ELSE translation.name END
         ILIKE '%' || sqlc.arg(search_query) || '%'
      OR c.id::text ILIKE '%' || sqlc.arg(search_query) || '%'
  )
ORDER BY c.updated_at DESC, c.id
LIMIT sqlc.arg(page_size) OFFSET sqlc.arg(page_offset)
), page_star_counts AS (
    -- 列表先分页再聚合当前页 Star，避免关系规模增长后出现逐行 COUNT 放大。
    SELECT aggregate_star.component_id, count(*)::bigint AS star_count
    FROM component_repo.component_stars aggregate_star
    JOIN page ON page.id = aggregate_star.component_id
    GROUP BY aggregate_star.component_id
)
SELECT page.id, page.owner_id, page.content_kind, page.selected_content_locale,
       page.selected_name, page.selected_description, page.has_description,
       page.selected_tags, page.category, page.status, page.current_version_id,
       page.logical_width_stud, page.logical_depth_stud, page.logical_height_plate,
       page.metadata, page.created_by, page.created_at, page.updated_at,
       page.owned_by_actor, page.translation_missing, page.starred_by_actor,
       (active_watch.actor_id IS NOT NULL)::boolean AS watching_by_actor,
       active_watch.watch_level, active_watch.watched_at,
       COALESCE(page_star_counts.star_count, 0)::bigint AS star_count
FROM page
LEFT JOIN page_star_counts ON page_star_counts.component_id = page.id
LEFT JOIN component_repo.component_watch_periods active_watch
  ON active_watch.actor_id = sqlc.arg(actor_id)
 AND active_watch.component_id = page.id
 AND active_watch.ended_seq IS NULL
ORDER BY page.updated_at DESC, page.id;

-- name: CountVisibleComponents :one
-- 公开目录总数必须复用列表的可见性和过滤条件，避免分页元数据泄露不可见 Component。
SELECT count(*)::bigint
FROM component_repo.components c
LEFT JOIN LATERAL (
    SELECT t.id, t.name
    FROM component_repo.component_translations t
    WHERE c.content_kind = 'official'
      AND sqlc.arg(search_query)::text <> ''
      AND t.component_id = c.id
      AND t.locale = sqlc.arg(locale)
      AND t.translation_status = 'reviewed'
    LIMIT 1
) translation ON true
WHERE c.deleted_at IS NULL
  AND (c.owner_id = sqlc.arg(actor_id) OR c.status = 'active')
  AND EXISTS (
      SELECT 1
      FROM component_repo.component_versions version
      WHERE version.component_id = c.id
        AND version.deleted_at IS NULL
        AND (
            c.owner_id = sqlc.arg(actor_id)
            OR (c.status = 'active' AND version.status <> 'draft')
        )
  )
  AND (sqlc.arg(status_filter)::text = '' OR c.status = sqlc.arg(status_filter))
  AND (sqlc.arg(category_filter)::text = '' OR c.category = sqlc.arg(category_filter))
  AND (
      sqlc.arg(search_query)::text = ''
      OR CASE WHEN translation.id IS NULL THEN c.name ELSE translation.name END
         ILIKE '%' || sqlc.arg(search_query) || '%'
      OR c.id::text ILIKE '%' || sqlc.arg(search_query) || '%'
  );

-- name: UpdateOwnedComponent :one
UPDATE component_repo.components
SET name = CASE WHEN sqlc.arg(set_name)::boolean THEN sqlc.arg(name)::text ELSE name END,
    description = CASE WHEN sqlc.arg(set_description)::boolean THEN sqlc.narg(description)::text ELSE description END,
    tags = CASE WHEN sqlc.arg(set_tags)::boolean THEN sqlc.arg(tags)::text[] ELSE tags END,
    category = CASE WHEN sqlc.arg(set_category)::boolean THEN sqlc.narg(category)::text ELSE category END,
    content_locale = CASE WHEN sqlc.arg(set_content_locale)::boolean THEN sqlc.arg(content_locale)::text ELSE content_locale END,
    updated_at = now()
WHERE id = sqlc.arg(component_id)
  AND owner_id = sqlc.arg(actor_id)
  AND content_kind = 'user'
  AND deleted_at IS NULL
RETURNING id, owner_id, content_kind, content_locale, name, description, tags,
          category, status, current_version_id, logical_width_stud,
          logical_depth_stud, logical_height_plate, metadata, created_by,
          created_at, updated_at, deleted_at, deleted_by;

-- name: SoftDeleteOwnedComponent :one
UPDATE component_repo.components
SET status = 'archived', deleted_at = now(), deleted_by = sqlc.arg(actor_id), updated_at = now()
WHERE id = sqlc.arg(component_id)
  AND owner_id = sqlc.arg(actor_id)
  AND content_kind = 'user'
  AND deleted_at IS NULL
RETURNING id;

-- name: LockOwnedComponent :one
SELECT id, current_version_id, status
FROM component_repo.components
WHERE id = sqlc.arg(component_id)
  AND owner_id = sqlc.arg(actor_id)
  AND content_kind = 'user'
  AND deleted_at IS NULL
FOR UPDATE;

-- name: SetComponentCurrentVersion :exec
-- 发布事务切换 current Version 时同步维护规范化尺寸，避免 Star 筛选读取 Version 后逐行计算。
WITH projection_source AS (
    SELECT version.id AS version_id, version.component_id,
           COALESCE(version.logical_width_stud, component.logical_width_stud) AS size_x,
           COALESCE(version.logical_depth_stud, component.logical_depth_stud) AS size_y,
           COALESCE(version.logical_height_plate, component.logical_height_plate) AS size_z
    FROM component_repo.component_versions version
    JOIN component_repo.components component ON component.id = version.component_id
    WHERE version.id = sqlc.arg(version_id)
      AND version.component_id = sqlc.arg(component_id)
      AND version.status = 'published'
      AND version.deleted_at IS NULL
      AND component.owner_id = sqlc.arg(actor_id)
), normalized AS (
    SELECT version_id, component_id,
           CASE WHEN size_x IS NOT NULL AND size_y IS NOT NULL AND size_z IS NOT NULL
                THEN LEAST(size_x, size_y, size_z) END AS size_a,
           CASE WHEN size_x IS NOT NULL AND size_y IS NOT NULL AND size_z IS NOT NULL
                THEN size_x + size_y + size_z - LEAST(size_x, size_y, size_z) - GREATEST(size_x, size_y, size_z) END AS size_b,
           CASE WHEN size_x IS NOT NULL AND size_y IS NOT NULL AND size_z IS NOT NULL
                THEN GREATEST(size_x, size_y, size_z) END AS size_c
    FROM projection_source
)
UPDATE component_repo.components component
SET current_version_id = normalized.version_id,
    status = 'active',
    current_logical_size_a = normalized.size_a,
    current_logical_size_b = normalized.size_b,
    current_logical_size_c = normalized.size_c,
    updated_at = now()
FROM normalized
WHERE component.id = normalized.component_id
  AND component.owner_id = sqlc.arg(actor_id);

-- name: ComponentIsVisible :one
SELECT EXISTS (
    SELECT 1 FROM component_repo.components
    WHERE id = sqlc.arg(component_id)
      AND deleted_at IS NULL
      AND (owner_id = sqlc.arg(actor_id) OR status = 'active')
);
