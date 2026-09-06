-- +goose Up

-- Watch period 和后续发布事件共享这一顺序域。CACHE 1 保证 nextval 分配顺序可作为并发边界，
-- 回滚产生的空洞没有业务含义，任何调用方都不得假设序号连续。
CREATE SEQUENCE component_repo.component_activity_sequence AS bigint CACHE 1;
REVOKE ALL ON SEQUENCE component_repo.component_activity_sequence FROM PUBLIC;

-- 每次重新 Watch 都追加新 period；关闭后只能写入一次结束边界，不能覆盖或重新打开历史区间。
CREATE TABLE component_repo.component_watch_periods (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_id uuid NOT NULL,
    component_id uuid NOT NULL REFERENCES component_repo.components(id) ON DELETE CASCADE,
    watch_level text NOT NULL,
    started_seq bigint NOT NULL DEFAULT nextval('component_repo.component_activity_sequence'),
    ended_seq bigint,
    watched_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    unwatched_at timestamptz,
    CONSTRAINT component_watch_periods_level_check CHECK (watch_level IN ('releases_only')),
    CONSTRAINT component_watch_periods_end_state_check CHECK (
        (ended_seq IS NULL AND unwatched_at IS NULL)
        OR (
            ended_seq IS NOT NULL
            AND unwatched_at IS NOT NULL
            AND ended_seq > started_seq
            AND unwatched_at >= watched_at
        )
    )
);

-- 同一 actor/Component 同时只允许一个未关闭 period；并发首次 Watch 由数据库唯一性收敛。
CREATE UNIQUE INDEX component_watch_periods_active_unique_idx
    ON component_repo.component_watch_periods (actor_id, component_id)
    WHERE ended_seq IS NULL;

-- “我的订阅”按订阅时间和 Component ID 双倒序做 row-value keyset；只索引 active period。
CREATE INDEX component_watch_periods_actor_active_time_idx
    ON component_repo.component_watch_periods (actor_id, watched_at DESC, component_id DESC)
    INCLUDE (watch_level)
    WHERE ended_seq IS NULL;

-- WATCH-3 的 event-time fan-out 查询与数据分布尚未冻结，本阶段不提前添加推测性 Component 索引。
ALTER TABLE component_repo.component_watch_periods ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON component_repo.component_watch_periods FROM PUBLIC;

-- +goose Down

DROP TABLE component_repo.component_watch_periods;
DROP SEQUENCE component_repo.component_activity_sequence;
