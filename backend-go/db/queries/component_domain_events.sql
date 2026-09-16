-- name: CreateComponentVersionPublishedEvent :one
-- Version 首次发布和唯一事件同事务提交；event_seq 只保留发布审计顺序，不参与 read-time Feed 成员资格。
-- payload v1 保持空对象，避免复制用户文案或最终译文。
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
