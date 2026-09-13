-- +goose Up

-- Feed entry 是发布事件的可变展示投影：领域事件保持不可变，图片任务达到终态后才允许进入公共流。
-- ready/fallback 都代表“可以展示”，pending 不参与列表，因此 API 请求无需等待或轮询 Worker。
CREATE TABLE component_repo.component_feed_entries (
    event_id uuid PRIMARY KEY REFERENCES component_repo.component_domain_events(id),
    component_id uuid NOT NULL REFERENCES component_repo.components(id),
    component_version_id uuid NOT NULL UNIQUE REFERENCES component_repo.component_versions(id),
    render_task_id uuid REFERENCES component_repo.tasks(id),
    render_profile text NOT NULL,
    renderer_version text NOT NULL,
    render_status text NOT NULL DEFAULT 'pending',
    image_artifact_id uuid REFERENCES component_repo.artifacts(id),
    available_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT component_feed_entries_task_unique UNIQUE (render_task_id),
    CONSTRAINT component_feed_entries_status_check CHECK (
        render_status IN ('pending', 'ready', 'fallback')
    ),
    CONSTRAINT component_feed_entries_terminal_check CHECK (
        (render_status = 'pending' AND available_at IS NULL AND image_artifact_id IS NULL)
        OR (render_status = 'ready' AND available_at IS NOT NULL AND image_artifact_id IS NOT NULL)
        OR (render_status = 'fallback' AND available_at IS NOT NULL AND image_artifact_id IS NULL)
    ),
    CONSTRAINT component_feed_entries_task_check CHECK (
        render_task_id IS NOT NULL OR render_status = 'fallback'
    )
);

-- 无限流从已经可展示的窄投影驱动；索引键与 API cursor 完全一致，pending 不增加读取路径体积。
CREATE INDEX component_feed_entries_available_idx
    ON component_repo.component_feed_entries (available_at DESC, event_id DESC)
    INCLUDE (component_version_id, render_status, image_artifact_id)
    WHERE render_status IN ('ready', 'fallback');

-- 任务终态是 Feed 准入的唯一触发点。失败、取消和重试耗尽都进入 fallback；发布状态从不被图片结果回滚。
-- available_at 只写一次，未来人工重建成功只能替换图片，不能让同一发布事件再次跳到流顶部。
-- +goose StatementBegin
CREATE FUNCTION component_repo.finalize_component_feed_entry()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.task_type = 'component.feed_render.materialize'
       AND NEW.status IN ('succeeded', 'failed', 'cancelled')
       AND OLD.status IS DISTINCT FROM NEW.status THEN
        UPDATE component_repo.component_feed_entries entry
        SET render_status = CASE
                WHEN NEW.status = 'succeeded' AND NEW.result_artifact_id IS NOT NULL THEN 'ready'
                ELSE 'fallback'
            END,
            image_artifact_id = CASE
                WHEN NEW.status = 'succeeded' THEN NEW.result_artifact_id
                ELSE NULL
            END,
            available_at = COALESCE(entry.available_at, NEW.finished_at, clock_timestamp()),
            updated_at = clock_timestamp()
        WHERE entry.render_task_id = NEW.id;
    END IF;
    RETURN NEW;
END;
$$;
-- +goose StatementEnd

CREATE TRIGGER tasks_finalize_component_feed_entry
AFTER UPDATE OF status ON component_repo.tasks
FOR EACH ROW EXECUTE FUNCTION component_repo.finalize_component_feed_entry();

-- v23 之前已经存在的发布事件没有对应渲染任务。迁移将其视为确定性 fallback，避免升级后历史 Feed 消失；
-- 后续若需要高质量图片，必须通过显式重建命令创建新任务，不能在 API/Worker 启动时偷偷回填。
INSERT INTO component_repo.component_feed_entries (
    event_id, component_id, component_version_id, render_task_id, render_profile,
    renderer_version, render_status, available_at
)
SELECT event.id, event.component_id, event.component_version_id, NULL,
       'feed_card_3x2', 'component-feed-renderer-v1', 'fallback', event.occurred_at
FROM component_repo.component_domain_events event
JOIN component_repo.components component ON component.id=event.component_id
WHERE event.event_type = 'component.version.published.v1'
  AND component.content_kind='user';

ALTER TABLE component_repo.component_feed_entries ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON component_repo.component_feed_entries FROM PUBLIC;

-- +goose Down

DROP TRIGGER tasks_finalize_component_feed_entry ON component_repo.tasks;
DROP FUNCTION component_repo.finalize_component_feed_entry();
DROP TABLE component_repo.component_feed_entries;
