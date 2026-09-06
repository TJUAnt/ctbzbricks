-- name: AcquireExclusiveComponentActivityLock :exec
-- Publish 使用同一 Component 的独占事务锁；必须在锁内分配 event_seq，固定 Watch period 的事件时点边界。
SELECT pg_advisory_xact_lock(sqlc.arg(lock_key)::bigint);

-- name: CreateComponentVersionPublishedEvent :one
-- Version 首次发布和唯一事件同事务提交；payload v1 保持空对象，避免复制用户文案或最终译文。
INSERT INTO component_repo.component_domain_events (
    id, event_type, component_id, component_version_id, actor_id, payload
) VALUES (
    sqlc.arg(id),
    'component.version.published.v1',
    sqlc.arg(component_id),
    sqlc.arg(component_version_id),
    sqlc.arg(actor_id),
    '{}'::jsonb
)
RETURNING event_seq;
