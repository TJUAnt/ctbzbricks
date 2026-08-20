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
       c.category, c.status, c.current_version_id, c.logical_width_stud,
       c.logical_depth_stud, c.logical_height_plate, c.metadata, c.created_by,
       c.created_at, c.updated_at,
       (c.content_kind = 'official' AND c.content_locale <> sqlc.arg(locale)
        AND translation.id IS NULL)::boolean AS translation_missing,
       EXISTS (
           SELECT 1 FROM component_repo.component_subscriptions subscription
           WHERE subscription.owner_id = sqlc.arg(actor_id)
             AND subscription.component_id = c.id
       ) AS subscribed
FROM component_repo.components c
LEFT JOIN LATERAL (
    SELECT t.id, t.locale, t.name, t.description, t.tags
    FROM component_repo.component_translations t
    WHERE t.component_id = c.id
      AND t.locale = sqlc.arg(locale)
      AND t.translation_status = 'reviewed'
    LIMIT 1
) translation ON c.content_kind = 'official'
WHERE c.id = sqlc.arg(component_id)
  AND c.deleted_at IS NULL
  AND (c.owner_id = sqlc.arg(actor_id) OR c.status = 'active');

-- name: ListVisibleComponents :many
SELECT c.id, c.owner_id, c.content_kind,
       (CASE WHEN translation.id IS NULL THEN c.content_locale ELSE translation.locale END)::text AS selected_content_locale,
       (CASE WHEN translation.id IS NULL THEN c.name ELSE translation.name END)::text AS selected_name,
       COALESCE(CASE WHEN translation.id IS NULL THEN c.description ELSE translation.description END, '')::text AS selected_description,
       (CASE WHEN translation.id IS NULL THEN c.description ELSE translation.description END IS NOT NULL)::boolean AS has_description,
       (CASE WHEN translation.id IS NULL THEN c.tags ELSE translation.tags END)::text[] AS selected_tags,
       c.category, c.status, c.current_version_id, c.logical_width_stud,
       c.logical_depth_stud, c.logical_height_plate, c.metadata, c.created_by,
       c.created_at, c.updated_at,
       (c.content_kind = 'official' AND c.content_locale <> sqlc.arg(locale)
        AND translation.id IS NULL)::boolean AS translation_missing,
       EXISTS (
           SELECT 1 FROM component_repo.component_subscriptions subscription
           WHERE subscription.owner_id = sqlc.arg(actor_id)
             AND subscription.component_id = c.id
       ) AS subscribed
FROM component_repo.components c
LEFT JOIN LATERAL (
    SELECT t.id, t.locale, t.name, t.description, t.tags
    FROM component_repo.component_translations t
    WHERE t.component_id = c.id
      AND t.locale = sqlc.arg(locale)
      AND t.translation_status = 'reviewed'
    LIMIT 1
) translation ON c.content_kind = 'official'
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
  )
ORDER BY c.updated_at DESC, c.id
LIMIT sqlc.arg(page_size) OFFSET sqlc.arg(page_offset);

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
UPDATE component_repo.components
SET current_version_id = sqlc.arg(version_id), status = 'active', updated_at = now()
WHERE id = sqlc.arg(component_id) AND owner_id = sqlc.arg(actor_id);

-- name: ComponentIsVisible :one
SELECT EXISTS (
    SELECT 1 FROM component_repo.components
    WHERE id = sqlc.arg(component_id)
      AND deleted_at IS NULL
      AND (owner_id = sqlc.arg(actor_id) OR status = 'active')
);
