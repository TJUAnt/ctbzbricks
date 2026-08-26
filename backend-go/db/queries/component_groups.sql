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
           SELECT count(*)::bigint
           FROM component_repo.components component
           WHERE component.deleted_at IS NULL
             AND (component.owner_id = sqlc.arg(owner_id) OR component.status = 'active')
             AND EXISTS (
                 SELECT 1
                 FROM component_repo.component_versions version
                 WHERE version.component_id = component.id
                   AND version.deleted_at IS NULL
                   AND (
                       component.owner_id = sqlc.arg(owner_id)
                       OR (component.status = 'active' AND version.status <> 'draft')
                   )
             )
       ) ELSE (
           SELECT count(*)::bigint
           FROM component_repo.component_group_memberships membership
           JOIN component_repo.components component ON component.id = membership.component_id
           WHERE membership.owner_id = sqlc.arg(owner_id)
             AND membership.group_id = group_tree.id
             AND component.deleted_at IS NULL
             AND (component.owner_id = sqlc.arg(owner_id) OR component.status = 'active')
             AND EXISTS (
                 SELECT 1
                 FROM component_repo.component_versions version
                 WHERE version.component_id = component.id
                   AND version.deleted_at IS NULL
                   AND (
                       component.owner_id = sqlc.arg(owner_id)
                       OR (component.status = 'active' AND version.status <> 'draft')
                   )
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
       c.metadata, c.created_at, c.updated_at,
       COALESCE(c.owner_id = sqlc.arg(owner_id), false)::boolean AS owned_by_actor,
       (c.content_kind = 'official' AND c.content_locale <> sqlc.arg(locale)
        AND translation.id IS NULL)::boolean AS translation_missing,
       EXISTS (
           SELECT 1 FROM component_repo.component_subscriptions subscription
           WHERE subscription.owner_id = sqlc.arg(owner_id)
             AND subscription.component_id = c.id
       ) AS subscribed,
       COALESCE(membership.added_at, c.created_at)::timestamptz AS added_at
FROM component_repo.component_groups g
JOIN component_repo.components c
  ON g.group_type = 'root'
  OR EXISTS (
      SELECT 1 FROM component_repo.component_group_memberships membership_filter
      WHERE membership_filter.owner_id = g.owner_id
        AND membership_filter.group_id = g.id
        AND membership_filter.component_id = c.id
  )
LEFT JOIN component_repo.component_group_memberships membership
  ON membership.owner_id = g.owner_id
 AND membership.group_id = g.id
 AND membership.component_id = c.id
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
    WHERE t.component_id = c.id
      AND t.locale = sqlc.arg(locale)
      AND t.translation_status = 'reviewed'
    LIMIT 1
) translation ON c.content_kind = 'official'
WHERE g.owner_id = sqlc.arg(owner_id)
  AND g.id = sqlc.arg(group_id)
  AND c.deleted_at IS NULL
  AND (c.owner_id = sqlc.arg(owner_id) OR c.status = 'active')
  AND EXISTS (
      SELECT 1
      FROM component_repo.component_versions version
      WHERE version.component_id = c.id
        AND version.deleted_at IS NULL
        AND (
            c.owner_id = sqlc.arg(owner_id)
            OR (c.status = 'active' AND version.status <> 'draft')
        )
  )
ORDER BY COALESCE(membership.added_at, c.created_at) DESC, c.id
LIMIT sqlc.arg(page_size) OFFSET sqlc.arg(page_offset);

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
       c.metadata, c.created_at, c.updated_at,
       COALESCE(c.owner_id = sqlc.arg(owner_id), false)::boolean AS owned_by_actor,
       (c.content_kind = 'official' AND c.content_locale <> sqlc.arg(locale)
        AND translation.id IS NULL)::boolean AS translation_missing,
       EXISTS (
           SELECT 1 FROM component_repo.component_subscriptions subscription
           WHERE subscription.owner_id = sqlc.arg(owner_id)
             AND subscription.component_id = c.id
       ) AS subscribed,
       count(*) OVER()::bigint AS total_count
FROM component_repo.component_groups group_record
JOIN component_repo.components c
  ON group_record.group_type = 'root'
  OR EXISTS (
      SELECT 1 FROM component_repo.component_group_memberships membership
      WHERE membership.owner_id = group_record.owner_id
        AND membership.group_id = group_record.id
        AND membership.component_id = c.id
  )
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
-- 尺寸搜索忽略 Box 轴方向：先把三个业务尺寸归一化为升序 a/b/c；任一尺寸缺失时不参与尺寸匹配。
LEFT JOIN LATERAL (
    SELECT LEAST(COALESCE(display_version.logical_width_stud, c.logical_width_stud),
                 COALESCE(display_version.logical_depth_stud, c.logical_depth_stud),
                 COALESCE(display_version.logical_height_plate, c.logical_height_plate))::double precision AS size_a,
           (COALESCE(display_version.logical_width_stud, c.logical_width_stud)
            + COALESCE(display_version.logical_depth_stud, c.logical_depth_stud)
            + COALESCE(display_version.logical_height_plate, c.logical_height_plate)
            - LEAST(COALESCE(display_version.logical_width_stud, c.logical_width_stud),
                    COALESCE(display_version.logical_depth_stud, c.logical_depth_stud),
                    COALESCE(display_version.logical_height_plate, c.logical_height_plate))
            - GREATEST(COALESCE(display_version.logical_width_stud, c.logical_width_stud),
                       COALESCE(display_version.logical_depth_stud, c.logical_depth_stud),
                       COALESCE(display_version.logical_height_plate, c.logical_height_plate)))::double precision AS size_b,
           GREATEST(COALESCE(display_version.logical_width_stud, c.logical_width_stud),
                    COALESCE(display_version.logical_depth_stud, c.logical_depth_stud),
                    COALESCE(display_version.logical_height_plate, c.logical_height_plate))::double precision AS size_c
    WHERE COALESCE(display_version.logical_width_stud, c.logical_width_stud) IS NOT NULL
      AND COALESCE(display_version.logical_depth_stud, c.logical_depth_stud) IS NOT NULL
      AND COALESCE(display_version.logical_height_plate, c.logical_height_plate) IS NOT NULL
) normalized_size ON true
LEFT JOIN LATERAL (
    SELECT translation_record.id, translation_record.locale, translation_record.name,
           translation_record.description, translation_record.tags
    FROM component_repo.component_translations translation_record
    WHERE translation_record.component_id = c.id
      AND translation_record.locale = sqlc.arg(locale)
      AND translation_record.translation_status = 'reviewed'
    LIMIT 1
) translation ON c.content_kind = 'official'
WHERE group_record.id = sqlc.arg(group_id)
  AND group_record.owner_id = sqlc.arg(owner_id)
  AND c.deleted_at IS NULL
  AND (c.owner_id = sqlc.arg(owner_id) OR c.status = 'active')
  AND EXISTS (
      SELECT 1
      FROM component_repo.component_versions version
      WHERE version.component_id = c.id
        AND version.deleted_at IS NULL
        AND (
            c.owner_id = sqlc.arg(owner_id)
            OR (c.status = 'active' AND version.status <> 'draft')
        )
  )
  AND (cardinality(sqlc.arg(status_filters)::text[]) = 0 OR c.status = ANY(sqlc.arg(status_filters)::text[]))
  -- 每个重复 query 都是独立条件；NOT EXISTS 反例使全部文字条件按 AND 组合。
  AND NOT EXISTS (
      SELECT 1
      FROM unnest(sqlc.arg(text_filters)::text[]) AS requested_text(value)
      WHERE NOT (
          CASE WHEN translation.id IS NULL THEN c.name ELSE translation.name END
              ILIKE '%' || requested_text.value || '%'
          OR c.id::text ILIKE '%' || requested_text.value || '%'
      )
  )
  -- 二维/三维条件也逐个满足；COALESCE(false) 确保缺少 Box 时不会被 SQL NULL 误判为通过。
  AND NOT EXISTS (
      SELECT 1
      FROM jsonb_to_recordset(sqlc.arg(size_filters)::jsonb)
          AS requested_size(dimension_count integer, size_a double precision,
                            size_b double precision, size_c double precision)
      WHERE NOT COALESCE((
          (
              requested_size.dimension_count = 3
              AND normalized_size.size_a > requested_size.size_a - 1
              AND normalized_size.size_a < requested_size.size_a + 1
              AND normalized_size.size_b > requested_size.size_b - 1
              AND normalized_size.size_b < requested_size.size_b + 1
              AND normalized_size.size_c > requested_size.size_c - 1
              AND normalized_size.size_c < requested_size.size_c + 1
          )
          OR (
              requested_size.dimension_count = 2
              AND (
                  (normalized_size.size_a > requested_size.size_a - 1
                   AND normalized_size.size_a < requested_size.size_a + 1
                   AND normalized_size.size_b > requested_size.size_b - 1
                   AND normalized_size.size_b < requested_size.size_b + 1)
                  OR
                  (normalized_size.size_a > requested_size.size_a - 1
                   AND normalized_size.size_a < requested_size.size_a + 1
                   AND normalized_size.size_c > requested_size.size_b - 1
                   AND normalized_size.size_c < requested_size.size_b + 1)
                  OR
                  (normalized_size.size_b > requested_size.size_a - 1
                   AND normalized_size.size_b < requested_size.size_a + 1
                   AND normalized_size.size_c > requested_size.size_b - 1
                   AND normalized_size.size_c < requested_size.size_b + 1)
              )
          )
      ), false)
  )
ORDER BY c.updated_at DESC, c.id
LIMIT sqlc.arg(page_size) OFFSET sqlc.arg(page_offset);

-- name: CountComponentGroupStatuses :many
SELECT c.status, count(*)::bigint AS component_count
FROM component_repo.component_groups group_record
JOIN component_repo.components c
  ON group_record.group_type = 'root'
  OR EXISTS (
      SELECT 1 FROM component_repo.component_group_memberships membership
      WHERE membership.owner_id = group_record.owner_id
        AND membership.group_id = group_record.id
        AND membership.component_id = c.id
      )
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
-- 状态统计必须复用与结果列表完全相同的尺寸归一化，否则分页总数和状态数量会发生漂移。
LEFT JOIN LATERAL (
    SELECT LEAST(COALESCE(display_version.logical_width_stud, c.logical_width_stud),
                 COALESCE(display_version.logical_depth_stud, c.logical_depth_stud),
                 COALESCE(display_version.logical_height_plate, c.logical_height_plate))::double precision AS size_a,
           (COALESCE(display_version.logical_width_stud, c.logical_width_stud)
            + COALESCE(display_version.logical_depth_stud, c.logical_depth_stud)
            + COALESCE(display_version.logical_height_plate, c.logical_height_plate)
            - LEAST(COALESCE(display_version.logical_width_stud, c.logical_width_stud),
                    COALESCE(display_version.logical_depth_stud, c.logical_depth_stud),
                    COALESCE(display_version.logical_height_plate, c.logical_height_plate))
            - GREATEST(COALESCE(display_version.logical_width_stud, c.logical_width_stud),
                       COALESCE(display_version.logical_depth_stud, c.logical_depth_stud),
                       COALESCE(display_version.logical_height_plate, c.logical_height_plate)))::double precision AS size_b,
           GREATEST(COALESCE(display_version.logical_width_stud, c.logical_width_stud),
                    COALESCE(display_version.logical_depth_stud, c.logical_depth_stud),
                    COALESCE(display_version.logical_height_plate, c.logical_height_plate))::double precision AS size_c
    WHERE COALESCE(display_version.logical_width_stud, c.logical_width_stud) IS NOT NULL
      AND COALESCE(display_version.logical_depth_stud, c.logical_depth_stud) IS NOT NULL
      AND COALESCE(display_version.logical_height_plate, c.logical_height_plate) IS NOT NULL
) normalized_size ON true
LEFT JOIN LATERAL (
    SELECT translation_record.id, translation_record.name
    FROM component_repo.component_translations translation_record
    WHERE translation_record.component_id = c.id
      AND translation_record.locale = sqlc.arg(locale)
      AND translation_record.translation_status = 'reviewed'
    LIMIT 1
) translation ON c.content_kind = 'official'
WHERE group_record.id = sqlc.arg(group_id)
  AND group_record.owner_id = sqlc.arg(owner_id)
  AND c.deleted_at IS NULL
  AND (c.owner_id = sqlc.arg(owner_id) OR c.status = 'active')
  AND EXISTS (
      SELECT 1
      FROM component_repo.component_versions version
      WHERE version.component_id = c.id
        AND version.deleted_at IS NULL
        AND (
            c.owner_id = sqlc.arg(owner_id)
            OR (c.status = 'active' AND version.status <> 'draft')
        )
  )
  AND NOT EXISTS (
      SELECT 1
      FROM unnest(sqlc.arg(text_filters)::text[]) AS requested_text(value)
      WHERE NOT (
          CASE WHEN translation.id IS NULL THEN c.name ELSE translation.name END
              ILIKE '%' || requested_text.value || '%'
          OR c.id::text ILIKE '%' || requested_text.value || '%'
      )
  )
  AND NOT EXISTS (
      SELECT 1
      FROM jsonb_to_recordset(sqlc.arg(size_filters)::jsonb)
          AS requested_size(dimension_count integer, size_a double precision,
                            size_b double precision, size_c double precision)
      WHERE NOT COALESCE((
          (
              requested_size.dimension_count = 3
              AND normalized_size.size_a > requested_size.size_a - 1
              AND normalized_size.size_a < requested_size.size_a + 1
              AND normalized_size.size_b > requested_size.size_b - 1
              AND normalized_size.size_b < requested_size.size_b + 1
              AND normalized_size.size_c > requested_size.size_c - 1
              AND normalized_size.size_c < requested_size.size_c + 1
          )
          OR (
              requested_size.dimension_count = 2
              AND (
                  (normalized_size.size_a > requested_size.size_a - 1
                   AND normalized_size.size_a < requested_size.size_a + 1
                   AND normalized_size.size_b > requested_size.size_b - 1
                   AND normalized_size.size_b < requested_size.size_b + 1)
                  OR
                  (normalized_size.size_a > requested_size.size_a - 1
                   AND normalized_size.size_a < requested_size.size_a + 1
                   AND normalized_size.size_c > requested_size.size_b - 1
                   AND normalized_size.size_c < requested_size.size_b + 1)
                  OR
                  (normalized_size.size_b > requested_size.size_a - 1
                   AND normalized_size.size_b < requested_size.size_a + 1
                   AND normalized_size.size_c > requested_size.size_b - 1
                   AND normalized_size.size_c < requested_size.size_b + 1)
              )
          )
      ), false)
  )
GROUP BY c.status
ORDER BY c.status;
