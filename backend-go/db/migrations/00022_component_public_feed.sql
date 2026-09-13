-- +goose Up

-- 公共广场按全局发布时间倒序读取事件；部分索引只维护广场使用的发布事件，键顺序与
-- (occurred_at, id) keyset 游标完全一致，INCLUDE 字段避免候选页回表取得关联标识。
CREATE INDEX component_domain_events_public_feed_idx
    ON component_repo.component_domain_events (occurred_at DESC, id DESC)
    INCLUDE (component_id, component_version_id, actor_id)
    WHERE event_type = 'component.version.published.v1';

-- +goose Down

DROP INDEX component_repo.component_domain_events_public_feed_idx;
