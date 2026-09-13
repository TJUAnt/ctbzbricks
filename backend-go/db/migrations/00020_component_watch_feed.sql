-- +goose Up

-- WATCH-3 改为读取时聚合：先从 actor 的 active Watch 限定候选 Component，再按每个 Component
-- 的发布时间范围读取不可变事件。closed period 只承担历史审计，不进入 Feed 热路径。
CREATE INDEX component_domain_events_component_feed_idx
    ON component_repo.component_domain_events (component_id, occurred_at DESC, id DESC)
    INCLUDE (event_type, component_version_id);

-- +goose Down

DROP INDEX component_repo.component_domain_events_component_feed_idx;
