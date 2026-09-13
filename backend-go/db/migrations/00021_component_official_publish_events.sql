-- +goose Up

-- 用户 Component 的发布事件 actor 必须是 owner；official Component 没有 owner，改由不可变 Version 的
-- created_by 证明发布来源。事件仍只能引用同 Component 的已发布、未删除 Version。
-- +goose StatementBegin
CREATE OR REPLACE FUNCTION component_repo.validate_component_domain_event()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM component_repo.component_versions version
        JOIN component_repo.components component
          ON component.id = version.component_id
         AND component.deleted_at IS NULL
        WHERE version.id = NEW.component_version_id
          AND version.component_id = NEW.component_id
          AND version.status = 'published'
          AND version.deleted_at IS NULL
          AND (
              (component.content_kind = 'user' AND component.owner_id = NEW.actor_id)
              OR (component.content_kind = 'official' AND version.created_by = NEW.actor_id)
          )
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'component domain event target is not an authorized published version';
    END IF;
    RETURN NEW;
END;
$$;
-- +goose StatementEnd

-- +goose Down

-- 回退到 v16 的 user-owner 约束；已追加的领域事件仍保持不可变，不在回退中删除历史。
-- +goose StatementBegin
CREATE OR REPLACE FUNCTION component_repo.validate_component_domain_event()
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
