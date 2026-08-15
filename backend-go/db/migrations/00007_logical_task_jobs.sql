-- +goose Up

CREATE TABLE component_repo.task_jobs (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL,
    task_type text NOT NULL,
    logical_key text NOT NULL,
    input_hash text NOT NULL,
    execution_count integer NOT NULL DEFAULT 0,
    latest_task_id uuid,
    successful_task_id uuid,
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT task_jobs_identity_unique
        UNIQUE (owner_id, task_type, logical_key, input_hash),
    CONSTRAINT task_jobs_id_owner_type_unique UNIQUE (id, owner_id, task_type),
    CONSTRAINT task_jobs_logical_key_check CHECK (
        logical_key <> '' AND logical_key = btrim(logical_key)
        AND length(logical_key) <= 300
    ),
    CONSTRAINT task_jobs_input_hash_check CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT task_jobs_type_check CHECK (task_type <> '' AND task_type = btrim(task_type)),
    CONSTRAINT task_jobs_execution_count_check CHECK (execution_count >= 0),
    CONSTRAINT task_jobs_task_refs_check CHECK (
        (execution_count = 0 AND latest_task_id IS NULL AND successful_task_id IS NULL)
        OR (execution_count > 0 AND latest_task_id IS NOT NULL)
    )
);

ALTER TABLE component_repo.tasks
    ADD COLUMN task_job_id uuid,
    ADD COLUMN execution_number integer,
    ADD COLUMN retry_of_task_id uuid;

INSERT INTO component_repo.task_jobs (
    id, owner_id, task_type, logical_key, input_hash, execution_count,
    latest_task_id, successful_task_id, created_by, created_at, updated_at
)
SELECT task.id, task.owner_id, task.task_type,
       COALESCE(task.idempotency_key, task.id::text),
       md5(task.id::text) || md5(task.id::text), 1, task.id,
       CASE WHEN task.status = 'succeeded' THEN task.id END,
       task.created_by, task.created_at, task.updated_at
FROM component_repo.tasks task;

UPDATE component_repo.tasks
SET task_job_id = id, execution_number = 1;

ALTER TABLE component_repo.tasks
    ALTER COLUMN task_job_id SET NOT NULL,
    ALTER COLUMN execution_number SET NOT NULL,
    ADD CONSTRAINT tasks_job_identity_fk
        FOREIGN KEY (task_job_id, owner_id, task_type)
        REFERENCES component_repo.task_jobs(id, owner_id, task_type),
    ADD CONSTRAINT tasks_job_execution_unique UNIQUE (task_job_id, execution_number),
    ADD CONSTRAINT tasks_id_job_unique UNIQUE (id, task_job_id),
    ADD CONSTRAINT tasks_execution_number_check CHECK (execution_number > 0),
    ADD CONSTRAINT tasks_retry_execution_fk
        FOREIGN KEY (retry_of_task_id, task_job_id)
        REFERENCES component_repo.tasks(id, task_job_id),
    ADD CONSTRAINT tasks_retry_not_self_check CHECK (retry_of_task_id IS NULL OR retry_of_task_id <> id);

ALTER TABLE component_repo.task_jobs
    ADD CONSTRAINT task_jobs_latest_task_fk
        FOREIGN KEY (latest_task_id, id)
        REFERENCES component_repo.tasks(id, task_job_id),
    ADD CONSTRAINT task_jobs_successful_task_fk
        FOREIGN KEY (successful_task_id, id)
        REFERENCES component_repo.tasks(id, task_job_id);

DROP INDEX component_repo.tasks_owner_type_idempotency_unique;
ALTER TABLE component_repo.tasks DROP COLUMN idempotency_key;

CREATE INDEX task_jobs_logical_idx
    ON component_repo.task_jobs (owner_id, task_type, logical_key, created_at DESC, id);
CREATE INDEX tasks_job_created_idx
    ON component_repo.tasks (task_job_id, execution_number DESC);

-- +goose StatementBegin
CREATE FUNCTION component_repo.assign_task_execution()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    job component_repo.task_jobs%ROWTYPE;
BEGIN
    IF NEW.task_job_id IS NULL THEN
        NEW.task_job_id := NEW.id;
        NEW.execution_number := 1;
        INSERT INTO component_repo.task_jobs (
            id, owner_id, task_type, logical_key, input_hash, created_by
        ) VALUES (
            NEW.task_job_id, NEW.owner_id, NEW.task_type,
            NEW.id::text,
            md5(NEW.id::text) || md5(NEW.id::text), NEW.created_by
        );
    END IF;

    SELECT * INTO job
    FROM component_repo.task_jobs
    WHERE id = NEW.task_job_id
    FOR UPDATE;

    IF job.id IS NULL
       OR job.owner_id <> NEW.owner_id
       OR job.task_type <> NEW.task_type
       OR NEW.execution_number IS DISTINCT FROM job.execution_count + 1
       OR (job.latest_task_id IS NULL) <> (NEW.retry_of_task_id IS NULL)
       OR (job.latest_task_id IS NOT NULL AND NEW.retry_of_task_id <> job.latest_task_id) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'task execution identity is invalid';
    END IF;
    RETURN NEW;
END;
$$;
-- +goose StatementEnd

CREATE TRIGGER tasks_assign_execution
BEFORE INSERT ON component_repo.tasks
FOR EACH ROW EXECUTE FUNCTION component_repo.assign_task_execution();

-- +goose StatementBegin
CREATE FUNCTION component_repo.advance_task_job()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE component_repo.task_jobs
    SET execution_count = NEW.execution_number,
        latest_task_id = NEW.id,
        updated_at = NEW.created_at
    WHERE id = NEW.task_job_id;
    RETURN NEW;
END;
$$;
-- +goose StatementEnd

CREATE TRIGGER tasks_advance_job
AFTER INSERT ON component_repo.tasks
FOR EACH ROW EXECUTE FUNCTION component_repo.advance_task_job();

-- +goose StatementBegin
CREATE FUNCTION component_repo.validate_task_job_state()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    latest_execution integer;
    successful_status text;
BEGIN
    IF NEW.execution_count = 0 THEN
        RETURN NEW;
    END IF;

    SELECT task.execution_number
    INTO latest_execution
    FROM component_repo.tasks task
    WHERE task.id = NEW.latest_task_id
      AND task.task_job_id = NEW.id;

    IF latest_execution IS DISTINCT FROM NEW.execution_count THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'task job latest execution is invalid';
    END IF;

    IF NEW.successful_task_id IS NOT NULL THEN
        SELECT task.status
        INTO successful_status
        FROM component_repo.tasks task
        WHERE task.id = NEW.successful_task_id
          AND task.task_job_id = NEW.id;
        IF successful_status IS DISTINCT FROM 'succeeded' THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'task job successful execution is invalid';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
-- +goose StatementEnd

CREATE TRIGGER task_jobs_validate_state
BEFORE UPDATE OF execution_count, latest_task_id, successful_task_id
ON component_repo.task_jobs
FOR EACH ROW EXECUTE FUNCTION component_repo.validate_task_job_state();

-- +goose StatementBegin
CREATE FUNCTION component_repo.sync_task_job_success()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.status = 'succeeded' AND OLD.status IS DISTINCT FROM 'succeeded' THEN
        UPDATE component_repo.task_jobs
        SET successful_task_id = NEW.id, updated_at = NEW.updated_at
        WHERE id = NEW.task_job_id
          AND latest_task_id = NEW.id;
    END IF;
    RETURN NEW;
END;
$$;
-- +goose StatementEnd

CREATE TRIGGER tasks_sync_task_job_success
AFTER UPDATE OF status ON component_repo.tasks
FOR EACH ROW EXECUTE FUNCTION component_repo.sync_task_job_success();

ALTER TABLE component_repo.task_jobs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON component_repo.task_jobs FROM PUBLIC;

-- +goose Down

DROP TRIGGER IF EXISTS tasks_sync_task_job_success ON component_repo.tasks;
DROP FUNCTION IF EXISTS component_repo.sync_task_job_success();
DROP TRIGGER IF EXISTS task_jobs_validate_state ON component_repo.task_jobs;
DROP FUNCTION IF EXISTS component_repo.validate_task_job_state();
DROP TRIGGER IF EXISTS tasks_advance_job ON component_repo.tasks;
DROP FUNCTION IF EXISTS component_repo.advance_task_job();
DROP TRIGGER IF EXISTS tasks_assign_execution ON component_repo.tasks;
DROP FUNCTION IF EXISTS component_repo.assign_task_execution();
DROP INDEX IF EXISTS component_repo.tasks_job_created_idx;
DROP INDEX IF EXISTS component_repo.task_jobs_logical_idx;

ALTER TABLE component_repo.task_jobs
    DROP CONSTRAINT IF EXISTS task_jobs_successful_task_fk,
    DROP CONSTRAINT IF EXISTS task_jobs_latest_task_fk;

ALTER TABLE component_repo.tasks ADD COLUMN idempotency_key text;
UPDATE component_repo.tasks task
SET idempotency_key = job.id::text || ':' || task.execution_number::text
FROM component_repo.task_jobs job
WHERE job.id = task.task_job_id;

ALTER TABLE component_repo.tasks
    DROP CONSTRAINT IF EXISTS tasks_retry_execution_fk,
    DROP CONSTRAINT IF EXISTS tasks_retry_not_self_check,
    DROP CONSTRAINT IF EXISTS tasks_execution_number_check,
    DROP CONSTRAINT IF EXISTS tasks_id_job_unique,
    DROP CONSTRAINT IF EXISTS tasks_job_execution_unique,
    DROP CONSTRAINT IF EXISTS tasks_job_identity_fk,
    DROP COLUMN IF EXISTS retry_of_task_id,
    DROP COLUMN IF EXISTS execution_number,
    DROP COLUMN IF EXISTS task_job_id;

CREATE UNIQUE INDEX tasks_owner_type_idempotency_unique
    ON component_repo.tasks (owner_id, task_type, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

DROP TABLE IF EXISTS component_repo.task_jobs;
