-- +goose Up

-- 发布事件是已发生的领域事实，不复用 Task outbox；WATCH-3 会以本表为输入建立独立的 fan-out 执行状态。
-- 迁移不回填历史 published Version，避免部署时把旧版本误解释为新的订阅事件。
CREATE TABLE component_repo.component_domain_events (
    id uuid PRIMARY KEY,
    event_type text NOT NULL,
    component_id uuid NOT NULL REFERENCES component_repo.components(id),
    component_version_id uuid NOT NULL REFERENCES component_repo.component_versions(id),
    actor_id uuid NOT NULL,
    event_seq bigint NOT NULL DEFAULT nextval('component_repo.component_activity_sequence'),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT component_domain_events_type_check CHECK (
        event_type IN ('component.version.published.v1')
    ),
    CONSTRAINT component_domain_events_payload_object_check CHECK (
        jsonb_typeof(payload) = 'object'
    ),
    CONSTRAINT component_domain_events_version_unique UNIQUE (event_type, component_version_id),
    CONSTRAINT component_domain_events_sequence_unique UNIQUE (event_seq)
);

-- 事件只能引用刚进入 published 状态且属于同一 Component 的 Version，阻止内部写路径制造伪事件。
-- +goose StatementBegin
CREATE FUNCTION component_repo.validate_component_domain_event()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM component_repo.component_versions version
        JOIN component_repo.components component
          ON component.id = version.component_id
         AND component.owner_id = NEW.actor_id
         AND component.deleted_at IS NULL
        WHERE version.id = NEW.component_version_id
          AND version.component_id = NEW.component_id
          AND version.status = 'published'
          AND version.deleted_at IS NULL
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'component domain event target is not a published version';
    END IF;
    RETURN NEW;
END;
$$;
-- +goose StatementEnd

CREATE TRIGGER component_domain_events_validate
BEFORE INSERT ON component_repo.component_domain_events
FOR EACH ROW EXECUTE FUNCTION component_repo.validate_component_domain_event();

-- 领域事实只允许追加；任何更正都必须写新版本事件，不能原地改变既有事件或删除审计边界。
-- +goose StatementBegin
CREATE FUNCTION component_repo.reject_component_domain_event_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION USING
        ERRCODE = '23514',
        MESSAGE = 'component domain event is immutable';
END;
$$;
-- +goose StatementEnd

CREATE TRIGGER component_domain_events_immutable
BEFORE UPDATE OR DELETE ON component_repo.component_domain_events
FOR EACH ROW EXECUTE FUNCTION component_repo.reject_component_domain_event_mutation();

ALTER TABLE component_repo.component_domain_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON component_repo.component_domain_events FROM PUBLIC;

-- +goose Down

DROP TRIGGER component_domain_events_immutable ON component_repo.component_domain_events;
DROP TRIGGER component_domain_events_validate ON component_repo.component_domain_events;
DROP FUNCTION component_repo.reject_component_domain_event_mutation();
DROP FUNCTION component_repo.validate_component_domain_event();
DROP TABLE component_repo.component_domain_events;
