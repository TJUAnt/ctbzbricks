-- name: AcquireExclusiveComponentActivityLock :exec
-- Publish 与 Component 删除使用同一 Component 的独占事务锁；Feed 不再依赖事件时点订阅资格，
-- 但删除生命周期仍必须阻止并发 Watch 在目标失效后创建 active period。
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
