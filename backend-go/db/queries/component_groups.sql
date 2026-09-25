-- name: EnsureComponentRootGroup :one
INSERT INTO component_repo.component_groups (
    id, owner_id, group_type, sort_order
) VALUES (
    sqlc.arg(id), sqlc.arg(owner_id), 'root', 0
)
ON CONFLICT (owner_id) WHERE group_type = 'root'
DO UPDATE SET owner_id = EXCLUDED.owner_id
RETURNING id, owner_id, parent_group_id, group_type, name, normalized_name,
          content_locale, sort_order, created_at, updated_at;

-- name: ListOwnedComponentGroups :many
WITH RECURSIVE group_tree AS (
    SELECT g.id, g.owner_id, g.parent_group_id, g.group_type, g.name,
           g.normalized_name, g.content_locale, g.sort_order, g.created_at,
           g.updated_at, 0::integer AS depth
    FROM component_repo.component_groups g
    WHERE g.owner_id = sqlc.arg(owner_id) AND g.group_type = 'root'
    UNION ALL
    SELECT child.id, child.owner_id, child.parent_group_id, child.group_type,
           child.name, child.normalized_name, child.content_locale,
           child.sort_order, child.created_at, child.updated_at, parent.depth + 1
    FROM component_repo.component_groups child
    JOIN group_tree parent
      ON parent.id = child.parent_group_id AND parent.owner_id = child.owner_id
)
SELECT id, owner_id, parent_group_id, group_type, name, normalized_name,
       content_locale, sort_order, created_at, updated_at, depth,
       (CASE WHEN group_type = 'root' THEN (
           -- root 明确表示“我的组件”，只走 owner 复合索引；收藏由独立 Star 视图承载。
           SELECT count(*)::bigint
           FROM component_repo.component_catalog_candidates component
           WHERE component.owner_id = sqlc.arg(owner_id)
             AND component.version_available
       ) ELSE (
           SELECT count(*)::bigint
           FROM component_repo.component_group_memberships membership
           JOIN component_repo.component_catalog_candidates component ON component.id = membership.component_id
           WHERE membership.owner_id = sqlc.arg(owner_id)
             AND membership.group_id = group_tree.id
             AND (
                 (component.owner_id = sqlc.arg(owner_id) AND component.version_available)
                 OR (component.status = 'active' AND component.public_version_available)
             )
       ) END)::bigint AS direct_component_count
FROM group_tree
ORDER BY depth, parent_group_id NULLS FIRST, sort_order, id;

-- name: GetOwnedComponentGroup :one
SELECT id, owner_id, parent_group_id, group_type, name, normalized_name,
       content_locale, sort_order, created_at, updated_at
FROM component_repo.component_groups
WHERE id = sqlc.arg(group_id) AND owner_id = sqlc.arg(owner_id);

-- name: CreateComponentGroup :one
INSERT INTO component_repo.component_groups (
    id, owner_id, parent_group_id, group_type, name, normalized_name,
    content_locale, sort_order
) VALUES (
    sqlc.arg(id), sqlc.arg(owner_id), sqlc.arg(parent_group_id), 'custom',
    sqlc.arg(name), sqlc.arg(normalized_name), sqlc.arg(content_locale),
    sqlc.arg(sort_order)
)
RETURNING id, owner_id, parent_group_id, group_type, name, normalized_name,
          content_locale, sort_order, created_at, updated_at;

-- name: UpdateOwnedComponentGroup :one
UPDATE component_repo.component_groups
SET name = CASE WHEN sqlc.arg(set_name)::boolean THEN sqlc.arg(name)::text ELSE name END,
    normalized_name = CASE WHEN sqlc.arg(set_name)::boolean THEN sqlc.arg(normalized_name)::text ELSE normalized_name END,
    content_locale = CASE WHEN sqlc.arg(set_content_locale)::boolean THEN sqlc.arg(content_locale)::text ELSE content_locale END,
    sort_order = CASE WHEN sqlc.arg(set_sort_order)::boolean THEN sqlc.arg(sort_order)::integer ELSE sort_order END,
    updated_at = now()
WHERE id = sqlc.arg(group_id)
  AND owner_id = sqlc.arg(owner_id)
  AND group_type = 'custom'
RETURNING id, owner_id, parent_group_id, group_type, name, normalized_name,
          content_locale, sort_order, created_at, updated_at;

-- name: MoveOwnedComponentGroup :one
UPDATE component_repo.component_groups
SET parent_group_id = sqlc.arg(parent_group_id),
    sort_order = sqlc.arg(sort_order),
    updated_at = now()
WHERE id = sqlc.arg(group_id)
  AND owner_id = sqlc.arg(owner_id)
  AND group_type = 'custom'
RETURNING id, owner_id, parent_group_id, group_type, name, normalized_name,
          content_locale, sort_order, created_at, updated_at;

-- name: DeleteOwnedComponentGroup :one
DELETE FROM component_repo.component_groups
WHERE id = sqlc.arg(group_id)
  AND owner_id = sqlc.arg(owner_id)
  AND group_type = 'custom'
RETURNING id;

-- name: ComponentGroupDepth :one
WITH RECURSIVE ancestors AS (
    SELECT child.id, child.parent_group_id, 0::integer AS depth
    FROM component_repo.component_groups child
    WHERE child.id = sqlc.arg(group_id) AND child.owner_id = sqlc.arg(owner_id)
    UNION ALL
    SELECT parent.id, parent.parent_group_id, child.depth + 1
    FROM component_repo.component_groups parent
    JOIN ancestors child ON child.parent_group_id = parent.id
    WHERE parent.owner_id = sqlc.arg(owner_id)
)
SELECT COALESCE(max(depth), -1)::integer AS depth FROM ancestors;

-- name: ComponentGroupSubtreeDepth :one
WITH RECURSIVE descendants AS (
    SELECT root.id, 0::integer AS depth
    FROM component_repo.component_groups root
    WHERE root.id = sqlc.arg(group_id) AND root.owner_id = sqlc.arg(owner_id)
    UNION ALL
    SELECT child.id, parent.depth + 1
    FROM component_repo.component_groups child
    JOIN descendants parent ON child.parent_group_id = parent.id
    WHERE child.owner_id = sqlc.arg(owner_id)
)
SELECT COALESCE(max(depth), -1)::integer AS depth FROM descendants;

-- name: ListComponentGroupDescendantIDs :many
WITH RECURSIVE descendants AS (
    SELECT root.id
    FROM component_repo.component_groups root
    WHERE root.id = sqlc.arg(group_id) AND root.owner_id = sqlc.arg(owner_id)
    UNION ALL
    SELECT child.id
    FROM component_repo.component_groups child
    JOIN descendants parent ON child.parent_group_id = parent.id
    WHERE child.owner_id = sqlc.arg(owner_id)
)
SELECT id FROM descendants;

-- name: AddComponentGroupMembership :one
INSERT INTO component_repo.component_group_memberships (
    owner_id, group_id, component_id, added_by
) VALUES (
    sqlc.arg(owner_id), sqlc.arg(group_id), sqlc.arg(component_id), sqlc.arg(added_by)
)
ON CONFLICT (group_id, component_id) DO NOTHING
RETURNING group_id;

-- name: RemoveComponentGroupMembership :one
DELETE FROM component_repo.component_group_memberships
WHERE owner_id = sqlc.arg(owner_id)
  AND group_id = sqlc.arg(group_id)
  AND component_id = sqlc.arg(component_id)
RETURNING group_id;

-- name: ListComponentGroupMembers :many
WITH group_record AS MATERIALIZED (
    SELECT group_item.id, group_item.owner_id, group_item.group_type
    FROM component_repo.component_groups group_item
    WHERE group_item.id = sqlc.arg(group_id)
      AND group_item.owner_id = sqlc.arg(owner_id)
), candidate_components AS MATERIALIZED (
    -- root 只表示 actor 自有 Component；custom 只读取显式 membership，二者都避免扫描公开全集。
    SELECT component.id AS component_id, component.created_at AS added_at
    FROM group_record
    JOIN component_repo.component_catalog_candidates component ON component.owner_id = group_record.owner_id
    WHERE group_record.group_type = 'root'
    UNION ALL
    SELECT membership.component_id, membership.added_at
    FROM group_record
    JOIN component_repo.component_group_memberships membership
      ON membership.owner_id = group_record.owner_id
     AND membership.group_id = group_record.id
    WHERE group_record.group_type = 'custom'
), page AS MATERIALIZED (
SELECT c.id, c.owner_id, c.content_kind,
       (CASE WHEN translation.id IS NULL THEN c.content_locale ELSE translation.locale END)::text AS selected_content_locale,
       (CASE WHEN translation.id IS NULL THEN c.name ELSE translation.name END)::text AS selected_name,
       COALESCE(CASE WHEN translation.id IS NULL THEN c.description ELSE translation.description END, '')::text AS selected_description,
       (CASE WHEN translation.id IS NULL THEN c.description ELSE translation.description END IS NOT NULL)::boolean AS has_description,
       (CASE WHEN translation.id IS NULL THEN c.tags ELSE translation.tags END)::text[] AS selected_tags,
       c.category, c.status, c.current_version_id,
       c.logical_width_stud, c.logical_depth_stud, c.logical_height_plate,
       c.metadata, c.created_at, c.updated_at,
       COALESCE(c.owner_id = sqlc.arg(owner_id), false)::boolean AS owned_by_actor,
       (c.content_kind = 'official' AND c.content_locale <> sqlc.arg(locale)
        AND translation.id IS NULL)::boolean AS translation_missing,
       EXISTS (
           SELECT 1 FROM component_repo.component_stars star
           WHERE star.actor_id = sqlc.arg(owner_id)
             AND star.component_id = c.id
       ) AS starred_by_actor,
       candidate_components.added_at
FROM candidate_components
JOIN component_repo.component_catalog_candidates c ON c.id = candidate_components.component_id
LEFT JOIN LATERAL (
    SELECT t.id, t.locale, t.name, t.description, t.tags
    FROM component_repo.component_reviewed_translations t
    WHERE c.content_kind = 'official'
      AND t.component_id = c.id
      AND t.locale = sqlc.arg(locale)
    LIMIT 1
) translation ON true
WHERE (
    (c.owner_id = sqlc.arg(owner_id) AND c.version_available)
    OR (c.status = 'active' AND c.public_version_available)
)
ORDER BY candidate_components.added_at DESC, c.id
LIMIT sqlc.arg(page_size) OFFSET sqlc.arg(page_offset)
), page_star_counts AS (
    SELECT aggregate_star.component_id, count(*)::bigint AS star_count
    FROM component_repo.component_stars aggregate_star
    JOIN page ON page.id = aggregate_star.component_id
    GROUP BY aggregate_star.component_id
)
SELECT page.id, page.owner_id, page.content_kind, page.selected_content_locale,
       page.selected_name, page.selected_description, page.has_description,
       page.selected_tags, page.category, page.status, page.current_version_id,
       display_component.logical_width_stud, display_component.logical_depth_stud,
       display_component.logical_height_plate,
       page.metadata, page.created_at, page.updated_at, page.owned_by_actor,
       page.translation_missing, page.starred_by_actor,
       COALESCE(page_star_counts.star_count, 0)::bigint AS star_count,
       page.added_at
FROM page
JOIN component_repo.component_catalog_projection display_component ON display_component.id = page.id
LEFT JOIN page_star_counts ON page_star_counts.component_id = page.id
ORDER BY page.added_at DESC, page.id;

-- name: ListOwnedComponentGroupIDsForComponent :many
SELECT membership.group_id
FROM component_repo.component_group_memberships membership
JOIN component_repo.component_groups group_record
  ON group_record.id = membership.group_id
 AND group_record.owner_id = membership.owner_id
WHERE membership.owner_id = sqlc.arg(owner_id)
  AND membership.component_id = sqlc.arg(component_id)
  AND group_record.group_type = 'custom'
ORDER BY group_record.sort_order, group_record.created_at, group_record.id;

-- name: SearchComponentGroupComponents :many
WITH group_record AS MATERIALIZED (
    SELECT group_item.id, group_item.owner_id, group_item.group_type
    FROM component_repo.component_groups group_item
    WHERE group_item.id = sqlc.arg(group_id)
      AND group_item.owner_id = sqlc.arg(owner_id)
), candidate_component_ids AS MATERIALIZED (
    SELECT component.id AS component_id
    FROM group_record
    JOIN component_repo.component_catalog_candidates component ON component.owner_id = group_record.owner_id
    WHERE group_record.group_type = 'root'
    UNION ALL
    SELECT membership.component_id
    FROM group_record
    JOIN component_repo.component_group_memberships membership
      ON membership.owner_id = group_record.owner_id
     AND membership.group_id = group_record.id
    WHERE group_record.group_type = 'custom'
), page AS MATERIALIZED (
SELECT c.id, c.owner_id, c.content_kind,
       (CASE WHEN translation.id IS NULL THEN c.content_locale ELSE translation.locale END)::text AS selected_content_locale,
       (CASE WHEN translation.id IS NULL THEN c.name ELSE translation.name END)::text AS selected_name,
       COALESCE(CASE WHEN translation.id IS NULL THEN c.description ELSE translation.description END, '')::text AS selected_description,
       (CASE WHEN translation.id IS NULL THEN c.description ELSE translation.description END IS NOT NULL)::boolean AS has_description,
       (CASE WHEN translation.id IS NULL THEN c.tags ELSE translation.tags END)::text[] AS selected_tags,
       c.category, c.status, c.current_version_id,
       c.logical_width_stud, c.logical_depth_stud, c.logical_height_plate,
       c.metadata, c.created_at, c.updated_at,
       COALESCE(c.owner_id = sqlc.arg(owner_id), false)::boolean AS owned_by_actor,
       (c.content_kind = 'official' AND c.content_locale <> sqlc.arg(locale)
        AND translation.id IS NULL)::boolean AS translation_missing,
       EXISTS (
           SELECT 1 FROM component_repo.component_stars star
           WHERE star.actor_id = sqlc.arg(owner_id)
             AND star.component_id = c.id
       ) AS starred_by_actor,
       count(*) OVER()::bigint AS total_count
FROM candidate_component_ids
JOIN component_repo.component_catalog_candidates c ON c.id = candidate_component_ids.component_id
LEFT JOIN LATERAL (
    SELECT translation_record.id, translation_record.locale, translation_record.name,
           translation_record.description, translation_record.tags
    FROM component_repo.component_reviewed_translations translation_record
    WHERE c.content_kind = 'official'
      AND translation_record.component_id = c.id
      AND translation_record.locale = sqlc.arg(locale)
    LIMIT 1
) translation ON true
LEFT JOIN LATERAL (
    -- 只有尺寸筛选启用时才读取当前展示 Version；无尺寸条件时执行计划必须让该内层零循环。
    SELECT projection.logical_width_stud,
           projection.logical_depth_stud,
           projection.logical_height_plate
    FROM component_repo.component_catalog_projection projection
    WHERE (sqlc.arg(has_width)::boolean OR sqlc.arg(has_depth)::boolean OR sqlc.arg(has_height)::boolean)
      AND projection.id = c.id
) filter_size ON true
WHERE (
    (c.owner_id = sqlc.arg(owner_id) AND c.version_available)
    OR (c.status = 'active' AND c.public_version_available)
)
  AND (cardinality(sqlc.arg(status_filters)::text[]) = 0 OR c.status = ANY(sqlc.arg(status_filters)::text[]))
  AND lower(CASE WHEN translation.id IS NULL THEN c.name ELSE translation.name END)
      LIKE ALL(sqlc.arg(name_patterns)::text[])
  AND (
      sqlc.arg(component_id_filter)::text = ''
      OR position(sqlc.arg(component_id_filter)::text IN lower(c.id::text)) > 0
  )
  -- 宽深允许平面旋转；单轴宽/深命中任一水平轴。误差窗与 Part Search 一致并包含边界。
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
ORDER BY c.updated_at DESC, c.id
LIMIT sqlc.arg(page_size) OFFSET sqlc.arg(page_offset)
), page_star_counts AS (
    SELECT aggregate_star.component_id, count(*)::bigint AS star_count
    FROM component_repo.component_stars aggregate_star
    JOIN page ON page.id = aggregate_star.component_id
    GROUP BY aggregate_star.component_id
)
SELECT page.id, page.owner_id, page.content_kind, page.selected_content_locale,
       page.selected_name, page.selected_description, page.has_description,
       page.selected_tags, page.category, page.status, page.current_version_id,
       display_component.logical_width_stud, display_component.logical_depth_stud,
       display_component.logical_height_plate,
       page.metadata, page.created_at, page.updated_at, page.owned_by_actor,
       page.translation_missing, page.starred_by_actor,
       COALESCE(page_star_counts.star_count, 0)::bigint AS star_count,
       page.total_count
FROM page
JOIN component_repo.component_catalog_projection display_component ON display_component.id = page.id
LEFT JOIN page_star_counts ON page_star_counts.component_id = page.id
ORDER BY page.updated_at DESC, page.id;

-- name: CountComponentGroupStatuses :many
WITH group_record AS MATERIALIZED (
    SELECT group_item.id, group_item.owner_id, group_item.group_type
    FROM component_repo.component_groups group_item
    WHERE group_item.id = sqlc.arg(group_id)
      AND group_item.owner_id = sqlc.arg(owner_id)
), candidate_component_ids AS MATERIALIZED (
    SELECT component.id AS component_id
    FROM group_record
    JOIN component_repo.component_catalog_candidates component ON component.owner_id = group_record.owner_id
    WHERE group_record.group_type = 'root'
    UNION ALL
    SELECT membership.component_id
    FROM group_record
    JOIN component_repo.component_group_memberships membership
      ON membership.owner_id = group_record.owner_id
     AND membership.group_id = group_record.id
    WHERE group_record.group_type = 'custom'
)
SELECT c.status, count(*)::bigint AS component_count
FROM candidate_component_ids
JOIN component_repo.component_catalog_candidates c ON c.id = candidate_component_ids.component_id
LEFT JOIN LATERAL (
    SELECT translation_record.id, translation_record.name
    FROM component_repo.component_reviewed_translations translation_record
    WHERE c.content_kind = 'official'
      AND cardinality(sqlc.arg(name_patterns)::text[]) > 0
      AND translation_record.component_id = c.id
      AND translation_record.locale = sqlc.arg(locale)
    LIMIT 1
) translation ON true
LEFT JOIN LATERAL (
    -- 状态统计与列表复用同一展示尺寸和启用门控，确保总数语义不漂移。
    SELECT projection.logical_width_stud,
           projection.logical_depth_stud,
           projection.logical_height_plate
    FROM component_repo.component_catalog_projection projection
    WHERE (sqlc.arg(has_width)::boolean OR sqlc.arg(has_depth)::boolean OR sqlc.arg(has_height)::boolean)
      AND projection.id = c.id
) filter_size ON true
WHERE (
    (c.owner_id = sqlc.arg(owner_id) AND c.version_available)
    OR (c.status = 'active' AND c.public_version_available)
)
  AND lower(CASE WHEN translation.id IS NULL THEN c.name ELSE translation.name END)
      LIKE ALL(sqlc.arg(name_patterns)::text[])
  AND (
      sqlc.arg(component_id_filter)::text = ''
      OR position(sqlc.arg(component_id_filter)::text IN lower(c.id::text)) > 0
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
GROUP BY c.status
ORDER BY c.status;
