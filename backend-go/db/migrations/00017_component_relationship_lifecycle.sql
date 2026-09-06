-- +goose Up

-- Watch 历史需要区分用户主动退订和 Component 生命周期终止；已有关闭周期均来自旧 Unwatch 路径。
ALTER TABLE component_repo.component_watch_periods
    ADD COLUMN ended_reason text;

UPDATE component_repo.component_watch_periods
SET ended_reason = 'user_unwatched'
WHERE ended_seq IS NOT NULL;

ALTER TABLE component_repo.component_watch_periods
    DROP CONSTRAINT component_watch_periods_end_state_check,
    ADD CONSTRAINT component_watch_periods_end_state_check CHECK (
        (ended_seq IS NULL AND unwatched_at IS NULL AND ended_reason IS NULL)
        OR (
            ended_seq IS NOT NULL
            AND unwatched_at IS NOT NULL
            AND ended_reason IS NOT NULL
            AND ended_seq > started_seq
            AND unwatched_at >= watched_at
        )
    ),
    ADD CONSTRAINT component_watch_periods_end_reason_check CHECK (
        ended_reason IS NULL OR ended_reason IN (
            'user_unwatched',
            'component_archived',
            'component_deleted'
        )
    );

-- Component 退出公开生命周期时按 Component 定位全部 active watcher；actor_id 保持索引键稳定并为后续
-- recipient 查询保留确定顺序，但本迁移不实现 fan-out。
CREATE INDEX component_watch_periods_component_active_idx
    ON component_repo.component_watch_periods (component_id, actor_id)
    WHERE ended_seq IS NULL;

-- +goose Down

DROP INDEX component_repo.component_watch_periods_component_active_idx;

ALTER TABLE component_repo.component_watch_periods
    DROP CONSTRAINT component_watch_periods_end_reason_check,
    DROP CONSTRAINT component_watch_periods_end_state_check,
    ADD CONSTRAINT component_watch_periods_end_state_check CHECK (
        (ended_seq IS NULL AND unwatched_at IS NULL)
        OR (
            ended_seq IS NOT NULL
            AND unwatched_at IS NOT NULL
            AND ended_seq > started_seq
            AND unwatched_at >= watched_at
        )
    ),
    DROP COLUMN ended_reason;
