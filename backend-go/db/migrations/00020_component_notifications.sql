-- +goose Up

-- WATCH-3 在订阅建立时冻结通知上下文；既有 v15～v19 周期没有该信息，迁移使用当时产品默认
-- zh-CN/UTC 与当前 catalog 作为显式基线，后续 Rewatch 会保存浏览器提交的新上下文。
ALTER TABLE component_repo.component_watch_periods
    ADD COLUMN notification_locale text NOT NULL DEFAULT 'zh-CN',
    ADD COLUMN notification_timezone text NOT NULL DEFAULT 'UTC',
    ADD COLUMN notification_catalog_version text NOT NULL DEFAULT 'frontend-2026.09.06.1',
    ADD CONSTRAINT component_watch_periods_notification_locale_check CHECK (
        notification_locale IN ('zh-CN', 'en-US')
    ),
    ADD CONSTRAINT component_watch_periods_notification_timezone_check CHECK (
        notification_timezone <> '' AND notification_timezone = btrim(notification_timezone)
    ),
    ADD CONSTRAINT component_watch_periods_notification_catalog_check CHECK (
        notification_catalog_version <> ''
        AND notification_catalog_version = btrim(notification_catalog_version)
        AND length(notification_catalog_version) <= 128
    );

-- event-time 查询把 active 与 closed 拆成互斥分支。active 索引同时覆盖稳定顺序和冻结通知上下文，
-- 在目标 Component 的历史占比很高时仍可按顺序读取有限页面；它也继续服务生命周期批量关闭。
DROP INDEX component_repo.component_watch_periods_component_active_idx;
CREATE INDEX component_watch_periods_component_active_idx
    ON component_repo.component_watch_periods (component_id, actor_id, id)
    INCLUDE (started_seq, notification_locale, notification_timezone, notification_catalog_version)
    WHERE ended_seq IS NULL;
-- closed 才使用区间 GiST，避免无界 active range 污染区间选择性估算。
CREATE INDEX component_watch_periods_closed_event_range_idx
    ON component_repo.component_watch_periods
    USING gist (int8range(started_seq, ended_seq, '[)'))
    WHERE ended_seq IS NOT NULL;
-- 表级 component_id 频率会被高密度 closed 历史放大；联合统计让规划器识别同一 Component 在 active
-- 分支中的真实占比，避免即使存在 partial index 仍错误选择并行全表扫描。
CREATE STATISTICS component_repo.component_watch_periods_component_end_stats (dependencies, mcv)
    ON component_id, ended_seq
    FROM component_repo.component_watch_periods;
ANALYZE component_repo.component_watch_periods (component_id, ended_seq);

-- Delivery 是 Component 发布事件的专属持久执行状态。它不属于 owner-scoped Task，也不复用 outbox_events。
CREATE TABLE component_repo.component_event_deliveries (
    event_id uuid PRIMARY KEY REFERENCES component_repo.component_domain_events(id),
    status text NOT NULL DEFAULT 'pending',
    cursor_actor_id uuid,
    cursor_period_id bigint,
    attempts smallint NOT NULL DEFAULT 0,
    max_attempts smallint NOT NULL DEFAULT 8,
    available_at timestamptz NOT NULL DEFAULT now(),
    lease_owner text,
    lease_expires_at timestamptz,
    last_error_code text,
    last_error_params jsonb NOT NULL DEFAULT '{}'::jsonb,
    started_at timestamptz,
    completed_at timestamptz,
    dead_lettered_at timestamptz,
    dead_letter_acknowledged_at timestamptz,
    dead_letter_acknowledged_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT component_event_deliveries_status_check CHECK (
        status IN ('pending', 'processing', 'retry_wait', 'completed', 'dead_lettered')
    ),
    CONSTRAINT component_event_deliveries_attempts_check CHECK (
        attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts
    ),
    CONSTRAINT component_event_deliveries_cursor_check CHECK (
        (cursor_actor_id IS NULL) = (cursor_period_id IS NULL)
    ),
    CONSTRAINT component_event_deliveries_error_params_check CHECK (
        jsonb_typeof(last_error_params) = 'object'
    ),
    CONSTRAINT component_event_deliveries_lease_check CHECK (
        (status = 'processing' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR (status <> 'processing' AND lease_owner IS NULL AND lease_expires_at IS NULL)
    ),
    CONSTRAINT component_event_deliveries_terminal_time_check CHECK (
        (status = 'completed' AND completed_at IS NOT NULL AND dead_lettered_at IS NULL)
        OR (status = 'dead_lettered' AND dead_lettered_at IS NOT NULL AND completed_at IS NULL)
        OR (status NOT IN ('completed', 'dead_lettered') AND completed_at IS NULL AND dead_lettered_at IS NULL)
    ),
    CONSTRAINT component_event_deliveries_retry_error_check CHECK (
        status <> 'retry_wait' OR last_error_code IS NOT NULL
    ),
    CONSTRAINT component_event_deliveries_dead_error_check CHECK (
        status <> 'dead_lettered' OR last_error_code IS NOT NULL
    ),
    CONSTRAINT component_event_deliveries_ack_check CHECK (
        (dead_letter_acknowledged_at IS NULL AND dead_letter_acknowledged_by IS NULL)
        OR (
            status = 'dead_lettered'
            AND dead_letter_acknowledged_at IS NOT NULL
            AND dead_letter_acknowledged_by IS NOT NULL
        )
    )
);

-- Claim 与过期 lease 恢复分别使用精确 partial index，避免可执行 Delivery 增长后扫描永久终态历史。
CREATE INDEX component_event_deliveries_claim_idx
    ON component_repo.component_event_deliveries (available_at, event_id)
    WHERE status IN ('pending', 'retry_wait');
CREATE INDEX component_event_deliveries_expired_lease_idx
    ON component_repo.component_event_deliveries (lease_expires_at, event_id)
    WHERE status = 'processing';
CREATE INDEX component_event_deliveries_unresolved_dead_idx
    ON component_repo.component_event_deliveries (dead_lettered_at, event_id)
    WHERE status = 'dead_lettered' AND dead_letter_acknowledged_at IS NULL;

-- 通知正文不在 Worker 中翻译；code/params 与冻结上下文用于 WATCH-4 展示和未来渠道审计。
CREATE TABLE component_repo.user_notifications (
    id uuid PRIMARY KEY,
    recipient_id uuid NOT NULL,
    event_id uuid NOT NULL REFERENCES component_repo.component_domain_events(id),
    source_watch_period_id bigint NOT NULL REFERENCES component_repo.component_watch_periods(id),
    notification_type text NOT NULL,
    code text NOT NULL,
    params jsonb NOT NULL DEFAULT '{}'::jsonb,
    component_id uuid NOT NULL REFERENCES component_repo.components(id),
    component_version_id uuid NOT NULL REFERENCES component_repo.component_versions(id),
    locale text NOT NULL,
    timezone text NOT NULL,
    resource_catalog_version text NOT NULL,
    tombstone boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    read_at timestamptz,
    deleted_at timestamptz,
    CONSTRAINT user_notifications_type_check CHECK (
        notification_type IN ('component.version.published.v1')
    ),
    CONSTRAINT user_notifications_code_check CHECK (
        code IN (
            'component_repo.notification.version_published',
            'component_repo.notification.version_published_unavailable'
        )
    ),
    CONSTRAINT user_notifications_params_check CHECK (jsonb_typeof(params) = 'object'),
    CONSTRAINT user_notifications_locale_check CHECK (locale IN ('zh-CN', 'en-US')),
    CONSTRAINT user_notifications_timezone_check CHECK (
        timezone <> '' AND timezone = btrim(timezone)
    ),
    CONSTRAINT user_notifications_catalog_check CHECK (
        resource_catalog_version <> ''
        AND resource_catalog_version = btrim(resource_catalog_version)
        AND length(resource_catalog_version) <= 128
    ),
    CONSTRAINT user_notifications_tombstone_code_check CHECK (
        (tombstone AND code = 'component_repo.notification.version_published_unavailable')
        OR (NOT tombstone AND code = 'component_repo.notification.version_published')
    ),
    CONSTRAINT user_notifications_recipient_event_unique UNIQUE (
        recipient_id, event_id, notification_type
    )
);

ALTER TABLE component_repo.component_event_deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE component_repo.user_notifications ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON component_repo.component_event_deliveries FROM PUBLIC;
REVOKE ALL ON component_repo.user_notifications FROM PUBLIC;

-- +goose Down

DROP TABLE component_repo.user_notifications;
DROP TABLE component_repo.component_event_deliveries;
DROP STATISTICS component_repo.component_watch_periods_component_end_stats;
DROP INDEX component_repo.component_watch_periods_closed_event_range_idx;
DROP INDEX component_repo.component_watch_periods_component_active_idx;
CREATE INDEX component_watch_periods_component_active_idx
    ON component_repo.component_watch_periods (component_id, actor_id)
    WHERE ended_seq IS NULL;
ALTER TABLE component_repo.component_watch_periods
    DROP CONSTRAINT component_watch_periods_notification_catalog_check,
    DROP CONSTRAINT component_watch_periods_notification_timezone_check,
    DROP CONSTRAINT component_watch_periods_notification_locale_check,
    DROP COLUMN notification_catalog_version,
    DROP COLUMN notification_timezone,
    DROP COLUMN notification_locale;
