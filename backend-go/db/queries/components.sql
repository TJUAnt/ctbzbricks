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
       c.logical_width_stud, c.logical_depth_stud, c.logical_height_plate,
       c.metadata, c.created_by, c.created_at, c.updated_at,
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
FROM component_repo.component_catalog_projection c
LEFT JOIN LATERAL (
    SELECT t.id, t.locale, t.name, t.description, t.tags
    FROM component_repo.component_reviewed_translations t
    WHERE c.content_kind = 'official'
      AND t.component_id = c.id
      AND t.locale = sqlc.arg(locale)
    LIMIT 1
) translation ON true
LEFT JOIN component_repo.component_watch_periods active_watch
  ON active_watch.actor_id = sqlc.arg(actor_id)
 AND active_watch.component_id = c.id
 AND active_watch.ended_seq IS NULL
WHERE c.id = sqlc.arg(component_id)
  AND (
      c.owner_id = sqlc.arg(actor_id)
      OR c.status = 'active'
  );

-- name: ListVisibleComponents :many
-- 无文本搜索时从 owner/active 排序索引驱动；文本搜索先用 trigram 产生来源候选。
-- 每个互斥来源最多保留一页，跨源重复只在有界集合中去重；cursor 与 ORDER BY 使用相同双降序键。
WITH owner_candidates AS MATERIALIZED (
    SELECT c.id, c.updated_at
    FROM component_repo.component_catalog_candidates c
    WHERE c.owner_id = sqlc.arg(actor_id)
      AND c.version_available
      AND (sqlc.arg(search_query)::text = '' OR sqlc.arg(has_search_component_id)::boolean)
      AND (c.updated_at, c.id) < (
          COALESCE(sqlc.narg(cursor_updated_at)::timestamptz, 'infinity'::timestamptz),
          COALESCE(sqlc.narg(cursor_component_id)::uuid, 'ffffffff-ffff-ffff-ffff-ffffffffffff'::uuid)
      )
      AND (sqlc.arg(status_filter)::text = '' OR c.status = sqlc.arg(status_filter))
      AND (sqlc.arg(category_filter)::text = '' OR c.category = sqlc.arg(category_filter))
      AND (NOT sqlc.arg(has_search_component_id)::boolean
           OR c.id = sqlc.narg(search_component_id)::uuid)
    ORDER BY c.updated_at DESC, c.id DESC
    LIMIT sqlc.arg(page_size)
), public_candidates AS MATERIALIZED (
    SELECT c.id, c.updated_at
    FROM component_repo.component_catalog_candidates c
    WHERE c.owner_id IS DISTINCT FROM sqlc.arg(actor_id)
      AND c.status = 'active'
      AND c.public_version_available
      AND (sqlc.arg(search_query)::text = '' OR sqlc.arg(has_search_component_id)::boolean)
      AND (c.updated_at, c.id) < (
          COALESCE(sqlc.narg(cursor_updated_at)::timestamptz, 'infinity'::timestamptz),
          COALESCE(sqlc.narg(cursor_component_id)::uuid, 'ffffffff-ffff-ffff-ffff-ffffffffffff'::uuid)
      )
      AND (sqlc.arg(status_filter)::text = '' OR c.status = sqlc.arg(status_filter))
      AND (sqlc.arg(category_filter)::text = '' OR c.category = sqlc.arg(category_filter))
      AND (NOT sqlc.arg(has_search_component_id)::boolean
           OR c.id = sqlc.narg(search_component_id)::uuid)
    ORDER BY c.updated_at DESC, c.id DESC
    LIMIT sqlc.arg(page_size)
), name_owner_candidates AS MATERIALIZED (
    -- 名称与 ID 分开驱动，让 PostgreSQL 可分别选择 trigram 或稳定排序索引。
    SELECT c.id, c.updated_at
    FROM component_repo.component_catalog_candidates c
    WHERE sqlc.arg(search_query)::text <> ''
      AND NOT sqlc.arg(has_search_component_id)::boolean
      AND c.name ILIKE '%' || sqlc.arg(search_query) || '%'
      AND c.owner_id = sqlc.arg(actor_id)
      AND c.version_available
      AND (c.updated_at, c.id) < (
          COALESCE(sqlc.narg(cursor_updated_at)::timestamptz, 'infinity'::timestamptz),
          COALESCE(sqlc.narg(cursor_component_id)::uuid, 'ffffffff-ffff-ffff-ffff-ffffffffffff'::uuid)
      )
      AND (sqlc.arg(status_filter)::text = '' OR c.status = sqlc.arg(status_filter))
      AND (sqlc.arg(category_filter)::text = '' OR c.category = sqlc.arg(category_filter))
    ORDER BY c.updated_at DESC, c.id DESC
    LIMIT sqlc.arg(page_size)
), name_public_candidates AS MATERIALIZED (
    SELECT c.id, c.updated_at
    FROM component_repo.component_catalog_candidates c
    WHERE sqlc.arg(search_query)::text <> ''
      AND NOT sqlc.arg(has_search_component_id)::boolean
      AND c.name ILIKE '%' || sqlc.arg(search_query) || '%'
      AND c.owner_id IS DISTINCT FROM sqlc.arg(actor_id)
      AND c.status = 'active'
      AND c.public_version_available
      AND (c.updated_at, c.id) < (
          COALESCE(sqlc.narg(cursor_updated_at)::timestamptz, 'infinity'::timestamptz),
          COALESCE(sqlc.narg(cursor_component_id)::uuid, 'ffffffff-ffff-ffff-ffff-ffffffffffff'::uuid)
      )
      AND (sqlc.arg(status_filter)::text = '' OR c.status = sqlc.arg(status_filter))
      AND (sqlc.arg(category_filter)::text = '' OR c.category = sqlc.arg(category_filter))
    ORDER BY c.updated_at DESC, c.id DESC
    LIMIT sqlc.arg(page_size)
), id_owner_candidates AS MATERIALIZED (
    SELECT c.id, c.updated_at
    FROM component_repo.component_catalog_candidates c
    WHERE sqlc.arg(search_query)::text <> ''
      AND NOT sqlc.arg(has_search_component_id)::boolean
      AND c.id::text ILIKE '%' || sqlc.arg(search_query) || '%'
      AND c.owner_id = sqlc.arg(actor_id)
      AND c.version_available
      AND (c.updated_at, c.id) < (
          COALESCE(sqlc.narg(cursor_updated_at)::timestamptz, 'infinity'::timestamptz),
          COALESCE(sqlc.narg(cursor_component_id)::uuid, 'ffffffff-ffff-ffff-ffff-ffffffffffff'::uuid)
      )
      AND (sqlc.arg(status_filter)::text = '' OR c.status = sqlc.arg(status_filter))
      AND (sqlc.arg(category_filter)::text = '' OR c.category = sqlc.arg(category_filter))
    ORDER BY c.updated_at DESC, c.id DESC
    LIMIT sqlc.arg(page_size)
), id_public_candidates AS MATERIALIZED (
    SELECT c.id, c.updated_at
    FROM component_repo.component_catalog_candidates c
    WHERE sqlc.arg(search_query)::text <> ''
      AND NOT sqlc.arg(has_search_component_id)::boolean
      AND c.id::text ILIKE '%' || sqlc.arg(search_query) || '%'
      AND c.owner_id IS DISTINCT FROM sqlc.arg(actor_id)
      AND c.status = 'active'
      AND c.public_version_available
      AND (c.updated_at, c.id) < (
          COALESCE(sqlc.narg(cursor_updated_at)::timestamptz, 'infinity'::timestamptz),
          COALESCE(sqlc.narg(cursor_component_id)::uuid, 'ffffffff-ffff-ffff-ffff-ffffffffffff'::uuid)
      )
      AND (sqlc.arg(status_filter)::text = '' OR c.status = sqlc.arg(status_filter))
      AND (sqlc.arg(category_filter)::text = '' OR c.category = sqlc.arg(category_filter))
    ORDER BY c.updated_at DESC, c.id DESC
    LIMIT sqlc.arg(page_size)
), translation_owner_candidates AS MATERIALIZED (
    SELECT c.id, c.updated_at
    FROM component_repo.component_reviewed_translations translation
    JOIN component_repo.component_catalog_candidates c ON c.id = translation.component_id
    WHERE sqlc.arg(search_query)::text <> ''
      AND NOT sqlc.arg(has_search_component_id)::boolean
      AND translation.locale = sqlc.arg(locale)
      AND translation.name ILIKE '%' || sqlc.arg(search_query) || '%'
      AND c.owner_id = sqlc.arg(actor_id)
      AND c.version_available
      AND (c.updated_at, c.id) < (
          COALESCE(sqlc.narg(cursor_updated_at)::timestamptz, 'infinity'::timestamptz),
          COALESCE(sqlc.narg(cursor_component_id)::uuid, 'ffffffff-ffff-ffff-ffff-ffffffffffff'::uuid)
      )
      AND (sqlc.arg(status_filter)::text = '' OR c.status = sqlc.arg(status_filter))
      AND (sqlc.arg(category_filter)::text = '' OR c.category = sqlc.arg(category_filter))
    ORDER BY c.updated_at DESC, c.id DESC
    LIMIT sqlc.arg(page_size)
), translation_public_candidates AS MATERIALIZED (
    SELECT c.id, c.updated_at
    FROM component_repo.component_reviewed_translations translation
    JOIN component_repo.component_catalog_candidates c ON c.id = translation.component_id
    WHERE sqlc.arg(search_query)::text <> ''
      AND NOT sqlc.arg(has_search_component_id)::boolean
      AND translation.locale = sqlc.arg(locale)
      AND translation.name ILIKE '%' || sqlc.arg(search_query) || '%'
      AND c.owner_id IS DISTINCT FROM sqlc.arg(actor_id)
      AND c.status = 'active'
      AND c.public_version_available
      AND (c.updated_at, c.id) < (
          COALESCE(sqlc.narg(cursor_updated_at)::timestamptz, 'infinity'::timestamptz),
          COALESCE(sqlc.narg(cursor_component_id)::uuid, 'ffffffff-ffff-ffff-ffff-ffffffffffff'::uuid)
      )
      AND (sqlc.arg(status_filter)::text = '' OR c.status = sqlc.arg(status_filter))
      AND (sqlc.arg(category_filter)::text = '' OR c.category = sqlc.arg(category_filter))
    ORDER BY c.updated_at DESC, c.id DESC
    LIMIT sqlc.arg(page_size)
), candidate_components AS MATERIALIZED (
    -- 每个来源先截到一页，搜索时合并集合最多处理 6 * page_size 行。
    SELECT owner.id, owner.updated_at FROM owner_candidates owner
    UNION ALL
    SELECT public_item.id, public_item.updated_at FROM public_candidates public_item
    UNION ALL
    SELECT name_owner.id, name_owner.updated_at FROM name_owner_candidates name_owner
    UNION ALL
    SELECT name_public.id, name_public.updated_at FROM name_public_candidates name_public
    UNION ALL
    SELECT id_owner.id, id_owner.updated_at FROM id_owner_candidates id_owner
    UNION ALL
    SELECT id_public.id, id_public.updated_at FROM id_public_candidates id_public
    UNION ALL
    SELECT translation_owner.id, translation_owner.updated_at FROM translation_owner_candidates translation_owner
    UNION ALL
    SELECT translation_public.id, translation_public.updated_at FROM translation_public_candidates translation_public
), deduplicated_candidates AS MATERIALIZED (
    SELECT candidate.id, max(candidate.updated_at)::timestamptz AS updated_at
    FROM candidate_components candidate
    GROUP BY candidate.id
), page AS MATERIALIZED (
    SELECT candidate.id, candidate.updated_at
    FROM deduplicated_candidates candidate
    ORDER BY candidate.updated_at DESC, candidate.id DESC
    LIMIT sqlc.arg(page_size)
), page_rows AS MATERIALIZED (
    -- 展示翻译、actor Star 和共享尺寸只作用于已经固定的页面。
    SELECT c.id, c.owner_id, c.content_kind,
           (CASE WHEN translation.id IS NULL THEN c.content_locale ELSE translation.locale END)::text AS selected_content_locale,
           (CASE WHEN translation.id IS NULL THEN c.name ELSE translation.name END)::text AS selected_name,
           COALESCE(CASE WHEN translation.id IS NULL THEN c.description ELSE translation.description END, '')::text AS selected_description,
           (CASE WHEN translation.id IS NULL THEN c.description ELSE translation.description END IS NOT NULL)::boolean AS has_description,
           (CASE WHEN translation.id IS NULL THEN c.tags ELSE translation.tags END)::text[] AS selected_tags,
           c.category, c.status, c.current_version_id,
           c.logical_width_stud, c.logical_depth_stud, c.logical_height_plate,
           c.metadata, c.created_by, c.created_at, c.updated_at,
           COALESCE(c.owner_id = sqlc.arg(actor_id), false)::boolean AS owned_by_actor,
           (c.content_kind = 'official' AND c.content_locale <> sqlc.arg(locale)
            AND translation.id IS NULL)::boolean AS translation_missing,
           EXISTS (
               SELECT 1 FROM component_repo.component_stars star
               WHERE star.actor_id = sqlc.arg(actor_id)
                 AND star.component_id = c.id
           ) AS starred_by_actor
    FROM page
    JOIN component_repo.component_catalog_projection c ON c.id = page.id
    LEFT JOIN LATERAL (
        SELECT t.id, t.locale, t.name, t.description, t.tags
        FROM component_repo.component_reviewed_translations t
        WHERE c.content_kind = 'official'
          AND t.component_id = c.id
          AND t.locale = sqlc.arg(locale)
        LIMIT 1
    ) translation ON true
), page_star_counts AS (
    SELECT aggregate_star.component_id, count(*)::bigint AS star_count
    FROM component_repo.component_stars aggregate_star
    JOIN page ON page.id = aggregate_star.component_id
    GROUP BY aggregate_star.component_id
)
SELECT page_rows.id, page_rows.owner_id, page_rows.content_kind,
       page_rows.selected_content_locale, page_rows.selected_name,
       page_rows.selected_description, page_rows.has_description,
       page_rows.selected_tags, page_rows.category, page_rows.status,
       page_rows.current_version_id, page_rows.logical_width_stud,
       page_rows.logical_depth_stud, page_rows.logical_height_plate,
       page_rows.metadata, page_rows.created_by, page_rows.created_at,
       page_rows.updated_at, page_rows.owned_by_actor,
       page_rows.translation_missing, page_rows.starred_by_actor,
       (active_watch.actor_id IS NOT NULL)::boolean AS watching_by_actor,
       active_watch.watch_level, active_watch.watched_at,
       COALESCE(page_star_counts.star_count, 0)::bigint AS star_count
FROM page_rows
LEFT JOIN page_star_counts ON page_star_counts.component_id = page_rows.id
LEFT JOIN component_repo.component_watch_periods active_watch
  ON active_watch.actor_id = sqlc.arg(actor_id)
 AND active_watch.component_id = page_rows.id
 AND active_watch.ended_seq IS NULL
ORDER BY page_rows.updated_at DESC, page_rows.id DESC;

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
    SELECT 1 FROM component_repo.component_catalog_projection
    WHERE id = sqlc.arg(component_id)
      AND (
          owner_id = sqlc.arg(actor_id)
          OR status = 'active'
      )
);
