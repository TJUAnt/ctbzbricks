-- name: CreateComponentSubscription :one
INSERT INTO component_repo.component_subscriptions (owner_id, component_id)
VALUES (sqlc.arg(owner_id), sqlc.arg(component_id))
ON CONFLICT (owner_id, component_id) DO UPDATE
SET subscribed_at = component_repo.component_subscriptions.subscribed_at
RETURNING owner_id, component_id, subscribed_at;

-- name: DeleteComponentSubscription :one
DELETE FROM component_repo.component_subscriptions
WHERE owner_id = sqlc.arg(owner_id) AND component_id = sqlc.arg(component_id)
RETURNING component_id;
