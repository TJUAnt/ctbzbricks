-- +goose Up

DROP INDEX component_repo.tasks_type_idempotency_unique;
CREATE UNIQUE INDEX tasks_owner_type_idempotency_unique
    ON component_repo.tasks (owner_id, task_type, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

ALTER TABLE component_repo.tasks
    ADD COLUMN cancel_requested_at timestamptz,
    ADD COLUMN cancel_requested_by uuid,
    ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now(),
    ADD CONSTRAINT tasks_type_check CHECK (task_type <> '' AND task_type = btrim(task_type)),
    ADD CONSTRAINT tasks_payload_object_check CHECK (jsonb_typeof(payload) = 'object'),
    ADD CONSTRAINT tasks_result_object_check CHECK (result IS NULL OR jsonb_typeof(result) = 'object'),
    ADD CONSTRAINT tasks_progress_params_object_check CHECK (
        progress_params IS NULL OR jsonb_typeof(progress_params) = 'object'
    ),
    ADD CONSTRAINT tasks_error_params_object_check CHECK (
        error_params IS NULL OR jsonb_typeof(error_params) = 'object'
    ),
    ADD CONSTRAINT tasks_cancel_request_check CHECK (
        (cancel_requested_at IS NULL AND cancel_requested_by IS NULL)
        OR (cancel_requested_at IS NOT NULL AND cancel_requested_by IS NOT NULL)
    ),
    ADD CONSTRAINT tasks_state_fields_check CHECK (
        (status = 'queued' AND lease_owner IS NULL AND lease_expires_at IS NULL AND finished_at IS NULL)
        OR (status = 'running' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL AND finished_at IS NULL)
        OR (status IN ('succeeded', 'failed', 'cancelled')
            AND lease_owner IS NULL AND lease_expires_at IS NULL AND finished_at IS NOT NULL)
    ),
    ADD CONSTRAINT tasks_result_state_check CHECK (
        (result IS NULL AND result_artifact_id IS NULL) OR status = 'succeeded'
    ),
    ADD CONSTRAINT tasks_result_artifact_owner_fk
        FOREIGN KEY (result_artifact_id, owner_id)
        REFERENCES component_repo.artifacts(id, owner_id);

ALTER TABLE component_repo.task_events
    DROP CONSTRAINT task_events_status_check,
    ADD CONSTRAINT task_events_status_check CHECK (
        status IN (
            'queued', 'running', 'succeeded', 'failed', 'cancelled',
            'retrying', 'cancel_requested'
        )
    ),
    ADD CONSTRAINT task_events_params_object_check CHECK (
        params IS NULL OR jsonb_typeof(params) = 'object'
    );

ALTER TABLE component_repo.outbox_events
    ADD COLUMN max_attempts integer NOT NULL DEFAULT 10,
    ADD COLUMN lease_owner text,
    ADD COLUMN lease_expires_at timestamptz,
    ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now(),
    ADD CONSTRAINT outbox_events_max_attempts_check CHECK (
        max_attempts > 0 AND attempts <= max_attempts
    ),
    ADD CONSTRAINT outbox_events_payload_object_check CHECK (jsonb_typeof(payload) = 'object'),
    ADD CONSTRAINT outbox_events_lease_check CHECK (
        (lease_owner IS NULL AND lease_expires_at IS NULL)
        OR (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
    ),
    ADD CONSTRAINT outbox_events_published_lease_check CHECK (
        published_at IS NULL OR (lease_owner IS NULL AND lease_expires_at IS NULL)
    );

DROP INDEX component_repo.outbox_events_publish_idx;
CREATE INDEX outbox_events_publish_idx
    ON component_repo.outbox_events (available_at, created_at, id)
    WHERE published_at IS NULL AND attempts < max_attempts;
CREATE INDEX outbox_events_lease_expiry_idx
    ON component_repo.outbox_events (lease_expires_at, id)
    WHERE published_at IS NULL AND lease_owner IS NOT NULL;

-- +goose StatementBegin
CREATE FUNCTION component_repo.protect_task_transition()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'queued' OR NEW.attempts <> 0 THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'task must start queued';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.status IN ('succeeded', 'failed', 'cancelled') THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'terminal task is immutable';
    END IF;

    IF NOT (
        NEW.status = OLD.status
        OR (OLD.status = 'queued' AND NEW.status IN ('running', 'cancelled'))
        OR (OLD.status = 'running' AND NEW.status IN ('queued', 'succeeded', 'failed', 'cancelled'))
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'invalid task status transition';
    END IF;

    IF OLD.status = 'queued' AND NEW.status = 'running' THEN
        IF NEW.attempts <> OLD.attempts + 1 THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'task claim must increment attempts';
        END IF;
    ELSIF NEW.attempts <> OLD.attempts THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'task attempts may only change on claim';
    END IF;

    RETURN NEW;
END;
$$;
-- +goose StatementEnd

CREATE TRIGGER tasks_protect_transition
BEFORE INSERT OR UPDATE ON component_repo.tasks
FOR EACH ROW EXECUTE FUNCTION component_repo.protect_task_transition();

-- +goose Down

DROP TRIGGER IF EXISTS tasks_protect_transition ON component_repo.tasks;
DROP FUNCTION IF EXISTS component_repo.protect_task_transition();

DROP INDEX IF EXISTS component_repo.outbox_events_lease_expiry_idx;
DROP INDEX IF EXISTS component_repo.outbox_events_publish_idx;
CREATE INDEX outbox_events_publish_idx
    ON component_repo.outbox_events (available_at, created_at, id)
    WHERE published_at IS NULL;

ALTER TABLE component_repo.outbox_events
    DROP CONSTRAINT IF EXISTS outbox_events_published_lease_check,
    DROP CONSTRAINT IF EXISTS outbox_events_lease_check,
    DROP CONSTRAINT IF EXISTS outbox_events_payload_object_check,
    DROP CONSTRAINT IF EXISTS outbox_events_max_attempts_check,
    DROP COLUMN IF EXISTS updated_at,
    DROP COLUMN IF EXISTS lease_expires_at,
    DROP COLUMN IF EXISTS lease_owner,
    DROP COLUMN IF EXISTS max_attempts;

ALTER TABLE component_repo.task_events
    DROP CONSTRAINT IF EXISTS task_events_params_object_check,
    DROP CONSTRAINT IF EXISTS task_events_status_check,
    ADD CONSTRAINT task_events_status_check CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'retrying')
    );

ALTER TABLE component_repo.tasks
    DROP CONSTRAINT IF EXISTS tasks_result_artifact_owner_fk,
    DROP CONSTRAINT IF EXISTS tasks_result_state_check,
    DROP CONSTRAINT IF EXISTS tasks_state_fields_check,
    DROP CONSTRAINT IF EXISTS tasks_cancel_request_check,
    DROP CONSTRAINT IF EXISTS tasks_error_params_object_check,
    DROP CONSTRAINT IF EXISTS tasks_progress_params_object_check,
    DROP CONSTRAINT IF EXISTS tasks_result_object_check,
    DROP CONSTRAINT IF EXISTS tasks_payload_object_check,
    DROP CONSTRAINT IF EXISTS tasks_type_check,
    DROP COLUMN IF EXISTS updated_at,
    DROP COLUMN IF EXISTS cancel_requested_by,
    DROP COLUMN IF EXISTS cancel_requested_at;

DROP INDEX IF EXISTS component_repo.tasks_owner_type_idempotency_unique;
CREATE UNIQUE INDEX tasks_type_idempotency_unique
    ON component_repo.tasks (task_type, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
