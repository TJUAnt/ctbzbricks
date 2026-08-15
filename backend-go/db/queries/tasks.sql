-- name: CreateTaskJob :one
INSERT INTO component_repo.task_jobs (
    id, owner_id, task_type, logical_key, input_hash, created_by
) VALUES (
    sqlc.arg(id), sqlc.arg(owner_id), sqlc.arg(task_type),
    sqlc.arg(logical_key), sqlc.arg(input_hash), sqlc.arg(created_by)
)
ON CONFLICT (owner_id, task_type, logical_key, input_hash) DO NOTHING
RETURNING id, owner_id, task_type, logical_key, input_hash, execution_count,
          latest_task_id, successful_task_id, created_by, created_at, updated_at;

-- name: LockTaskJobByIdentity :one
SELECT id, owner_id, task_type, logical_key, input_hash, execution_count,
       latest_task_id, successful_task_id, created_by, created_at, updated_at
FROM component_repo.task_jobs
WHERE owner_id = sqlc.arg(owner_id)
  AND task_type = sqlc.arg(task_type)
  AND logical_key = sqlc.arg(logical_key)
  AND input_hash = sqlc.arg(input_hash)
FOR UPDATE;

-- name: CreateTask :one
INSERT INTO component_repo.tasks (
    id, owner_id, task_type, status, payload, locale, timezone, created_by, max_attempts, available_at, task_job_id,
    execution_number, retry_of_task_id
) VALUES (
    sqlc.arg(id), sqlc.arg(owner_id), sqlc.arg(task_type), 'queued',
    sqlc.arg(payload), sqlc.arg(locale), sqlc.arg(timezone), sqlc.arg(created_by),
    sqlc.arg(max_attempts), sqlc.arg(available_at)
    , sqlc.arg(task_job_id), sqlc.arg(execution_number), sqlc.narg(retry_of_task_id)
)
RETURNING id, owner_id, task_type, status, payload, result, result_artifact_id,
          locale, timezone, created_by, attempts, max_attempts,
          available_at, lease_owner, lease_expires_at, progress_code,
          progress_params, progress_percent, error_code, error_params, created_at,
          started_at, finished_at, cancel_requested_at, cancel_requested_by, updated_at,
          task_job_id, execution_number, retry_of_task_id;

-- name: GetOwnedTask :one
SELECT id, owner_id, task_type, status, payload, result, result_artifact_id,
       locale, timezone, created_by, attempts, max_attempts,
       available_at, lease_owner, lease_expires_at, progress_code,
       progress_params, progress_percent, error_code, error_params, created_at,
       started_at, finished_at, cancel_requested_at, cancel_requested_by, updated_at,
       task_job_id, execution_number, retry_of_task_id
FROM component_repo.tasks
WHERE id = sqlc.arg(task_id) AND owner_id = sqlc.arg(actor_id);

-- name: CreateTaskDependency :exec
INSERT INTO component_repo.task_dependencies (
    task_id, prerequisite_task_id, owner_id
) VALUES (
    sqlc.arg(task_id), sqlc.arg(prerequisite_task_id), sqlc.arg(owner_id)
)
ON CONFLICT (task_id, prerequisite_task_id) DO NOTHING;

-- name: LockOwnedTask :one
SELECT id, owner_id, task_type, status, payload, result, result_artifact_id,
       locale, timezone, created_by, attempts, max_attempts,
       available_at, lease_owner, lease_expires_at, progress_code,
       progress_params, progress_percent, error_code, error_params, created_at,
       started_at, finished_at, cancel_requested_at, cancel_requested_by, updated_at,
       task_job_id, execution_number, retry_of_task_id
FROM component_repo.tasks
WHERE id = sqlc.arg(task_id) AND owner_id = sqlc.arg(actor_id)
FOR UPDATE;

-- name: ClaimAvailableTask :one
WITH candidate AS (
    SELECT id
    FROM component_repo.tasks
    WHERE status = 'queued'
      AND available_at <= sqlc.arg(claimed_at)
      AND attempts < max_attempts
      AND task_type = ANY(sqlc.arg(task_types)::text[])
      AND NOT EXISTS (
          SELECT 1
          FROM component_repo.task_dependencies dependency
          JOIN component_repo.tasks prerequisite
            ON prerequisite.id = dependency.prerequisite_task_id
          WHERE dependency.task_id = tasks.id
            AND prerequisite.status <> 'succeeded'
      )
    ORDER BY available_at, created_at, id
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
UPDATE component_repo.tasks task
SET status = 'running', attempts = task.attempts + 1,
    lease_owner = sqlc.arg(lease_owner), lease_expires_at = sqlc.arg(lease_expires_at),
    started_at = COALESCE(task.started_at, sqlc.arg(claimed_at)),
    error_code = NULL, error_params = NULL, updated_at = sqlc.arg(claimed_at)
FROM candidate
WHERE task.id = candidate.id
RETURNING task.id, task.owner_id, task.task_type, task.status, task.payload,
          task.result, task.result_artifact_id, task.locale, task.timezone,
          task.created_by, task.attempts, task.max_attempts,
          task.available_at, task.lease_owner, task.lease_expires_at,
          task.progress_code, task.progress_params, task.progress_percent,
          task.error_code, task.error_params, task.created_at, task.started_at,
          task.finished_at, task.cancel_requested_at, task.cancel_requested_by,
          task.updated_at, task.task_job_id, task.execution_number,
          task.retry_of_task_id;

-- name: FailTasksWithTerminalDependencies :many
WITH blocked AS (
    SELECT dependent.id, prerequisite.status AS prerequisite_status,
           prerequisite.error_code, prerequisite.error_params
    FROM component_repo.tasks dependent
    JOIN LATERAL (
        SELECT prerequisite.status, prerequisite.error_code, prerequisite.error_params
        FROM component_repo.task_dependencies dependency
        JOIN component_repo.tasks prerequisite
          ON prerequisite.id = dependency.prerequisite_task_id
        WHERE dependency.task_id = dependent.id
          AND prerequisite.status IN ('failed', 'cancelled')
        ORDER BY CASE prerequisite.status WHEN 'failed' THEN 0 ELSE 1 END,
                 prerequisite.finished_at, prerequisite.id
        LIMIT 1
    ) prerequisite ON true
    WHERE dependent.status = 'queued'
    FOR UPDATE OF dependent SKIP LOCKED
)
UPDATE component_repo.tasks task
SET status = CASE blocked.prerequisite_status
        WHEN 'cancelled' THEN 'cancelled'
        ELSE 'failed'
    END,
    error_code = CASE blocked.prerequisite_status
        WHEN 'failed' THEN COALESCE(blocked.error_code, 'common.internal_error')
        ELSE NULL
    END,
    error_params = CASE blocked.prerequisite_status
        WHEN 'failed' THEN COALESCE(blocked.error_params, '{}'::jsonb)
        ELSE NULL
    END,
    finished_at = sqlc.arg(finished_at), updated_at = sqlc.arg(finished_at)
FROM blocked
WHERE task.id = blocked.id
RETURNING task.id, task.owner_id, task.task_type, task.status, task.payload,
          task.result, task.result_artifact_id, task.locale, task.timezone,
          task.created_by, task.attempts, task.max_attempts,
          task.available_at, task.lease_owner, task.lease_expires_at,
          task.progress_code, task.progress_params, task.progress_percent,
          task.error_code, task.error_params, task.created_at, task.started_at,
          task.finished_at, task.cancel_requested_at, task.cancel_requested_by,
          task.updated_at, task.task_job_id, task.execution_number,
          task.retry_of_task_id;

-- name: HeartbeatTask :one
UPDATE component_repo.tasks
SET lease_expires_at = sqlc.arg(lease_expires_at), updated_at = sqlc.arg(heartbeat_at)
WHERE id = sqlc.arg(task_id)
  AND status = 'running'
  AND lease_owner = sqlc.arg(lease_owner)
  AND attempts = sqlc.arg(claimed_attempt)
  AND lease_expires_at > sqlc.arg(heartbeat_at)
RETURNING cancel_requested_at;

-- name: UpdateTaskProgress :one
UPDATE component_repo.tasks
SET progress_code = sqlc.narg(progress_code),
    progress_params = sqlc.narg(progress_params),
    progress_percent = sqlc.narg(progress_percent),
    updated_at = sqlc.arg(updated_at)
WHERE id = sqlc.arg(task_id)
  AND status = 'running'
  AND lease_owner = sqlc.arg(lease_owner)
  AND attempts = sqlc.arg(claimed_attempt)
  AND lease_expires_at > sqlc.arg(updated_at)
  AND cancel_requested_at IS NULL
RETURNING id, owner_id, task_type, status, payload, result, result_artifact_id,
          locale, timezone, created_by, attempts, max_attempts,
          available_at, lease_owner, lease_expires_at, progress_code,
          progress_params, progress_percent, error_code, error_params, created_at,
          started_at, finished_at, cancel_requested_at, cancel_requested_by, updated_at,
          task_job_id, execution_number, retry_of_task_id;

-- name: CompleteTask :one
UPDATE component_repo.tasks
SET status = 'succeeded', result = sqlc.arg(result),
    result_artifact_id = sqlc.narg(result_artifact_id),
    lease_owner = NULL, lease_expires_at = NULL,
    progress_percent = 100, error_code = NULL, error_params = NULL,
    finished_at = sqlc.arg(finished_at), updated_at = sqlc.arg(finished_at)
WHERE id = sqlc.arg(task_id)
  AND status = 'running'
  AND lease_owner = sqlc.arg(lease_owner)
  AND attempts = sqlc.arg(claimed_attempt)
  AND lease_expires_at > sqlc.arg(finished_at)
  AND cancel_requested_at IS NULL
RETURNING id, owner_id, task_type, status, payload, result, result_artifact_id,
          locale, timezone, created_by, attempts, max_attempts,
          available_at, lease_owner, lease_expires_at, progress_code,
          progress_params, progress_percent, error_code, error_params, created_at,
          started_at, finished_at, cancel_requested_at, cancel_requested_by, updated_at,
          task_job_id, execution_number, retry_of_task_id;

-- name: RetryTask :one
UPDATE component_repo.tasks
SET status = 'queued', available_at = sqlc.arg(available_at),
    lease_owner = NULL, lease_expires_at = NULL,
    progress_code = NULL, progress_params = NULL, progress_percent = NULL,
    error_code = sqlc.arg(error_code), error_params = sqlc.arg(error_params),
    updated_at = sqlc.arg(updated_at)
WHERE id = sqlc.arg(task_id)
  AND status = 'running'
  AND lease_owner = sqlc.arg(lease_owner)
  AND attempts = sqlc.arg(claimed_attempt)
  AND lease_expires_at > sqlc.arg(updated_at)
  AND cancel_requested_at IS NULL
  AND attempts < max_attempts
RETURNING id, owner_id, task_type, status, payload, result, result_artifact_id,
          locale, timezone, created_by, attempts, max_attempts,
          available_at, lease_owner, lease_expires_at, progress_code,
          progress_params, progress_percent, error_code, error_params, created_at,
          started_at, finished_at, cancel_requested_at, cancel_requested_by, updated_at,
          task_job_id, execution_number, retry_of_task_id;

-- name: FailTask :one
UPDATE component_repo.tasks
SET status = 'failed', lease_owner = NULL, lease_expires_at = NULL,
    error_code = sqlc.arg(error_code), error_params = sqlc.arg(error_params),
    finished_at = sqlc.arg(finished_at), updated_at = sqlc.arg(finished_at)
WHERE id = sqlc.arg(task_id)
  AND status = 'running'
  AND lease_owner = sqlc.arg(lease_owner)
  AND attempts = sqlc.arg(claimed_attempt)
  AND lease_expires_at > sqlc.arg(finished_at)
  AND cancel_requested_at IS NULL
RETURNING id, owner_id, task_type, status, payload, result, result_artifact_id,
          locale, timezone, created_by, attempts, max_attempts,
          available_at, lease_owner, lease_expires_at, progress_code,
          progress_params, progress_percent, error_code, error_params, created_at,
          started_at, finished_at, cancel_requested_at, cancel_requested_by, updated_at,
          task_job_id, execution_number, retry_of_task_id;

-- name: CancelClaimedTask :one
UPDATE component_repo.tasks
SET status = 'cancelled', lease_owner = NULL, lease_expires_at = NULL,
    finished_at = sqlc.arg(finished_at), updated_at = sqlc.arg(finished_at)
WHERE id = sqlc.arg(task_id)
  AND status = 'running'
  AND lease_owner = sqlc.arg(lease_owner)
  AND attempts = sqlc.arg(claimed_attempt)
  AND lease_expires_at > sqlc.arg(finished_at)
  AND cancel_requested_at IS NOT NULL
RETURNING id, owner_id, task_type, status, payload, result, result_artifact_id,
          locale, timezone, created_by, attempts, max_attempts,
          available_at, lease_owner, lease_expires_at, progress_code,
          progress_params, progress_percent, error_code, error_params, created_at,
          started_at, finished_at, cancel_requested_at, cancel_requested_by, updated_at,
          task_job_id, execution_number, retry_of_task_id;

-- name: CancelQueuedTask :one
UPDATE component_repo.tasks
SET status = 'cancelled', cancel_requested_at = sqlc.arg(cancelled_at),
    cancel_requested_by = sqlc.arg(actor_id), finished_at = sqlc.arg(cancelled_at),
    updated_at = sqlc.arg(cancelled_at)
WHERE id = sqlc.arg(task_id) AND owner_id = sqlc.arg(actor_id) AND status = 'queued'
RETURNING id, owner_id, task_type, status, payload, result, result_artifact_id,
          locale, timezone, created_by, attempts, max_attempts,
          available_at, lease_owner, lease_expires_at, progress_code,
          progress_params, progress_percent, error_code, error_params, created_at,
          started_at, finished_at, cancel_requested_at, cancel_requested_by, updated_at,
          task_job_id, execution_number, retry_of_task_id;

-- name: RequestRunningTaskCancellation :one
UPDATE component_repo.tasks
SET cancel_requested_at = COALESCE(cancel_requested_at, sqlc.arg(requested_at)),
    cancel_requested_by = COALESCE(cancel_requested_by, sqlc.arg(actor_id)),
    updated_at = sqlc.arg(requested_at)
WHERE id = sqlc.arg(task_id) AND owner_id = sqlc.arg(actor_id) AND status = 'running'
RETURNING id, owner_id, task_type, status, payload, result, result_artifact_id,
          locale, timezone, created_by, attempts, max_attempts,
          available_at, lease_owner, lease_expires_at, progress_code,
          progress_params, progress_percent, error_code, error_params, created_at,
          started_at, finished_at, cancel_requested_at, cancel_requested_by, updated_at,
          task_job_id, execution_number, retry_of_task_id;

-- name: RecoverExpiredTask :one
WITH candidate AS (
    SELECT id
    FROM component_repo.tasks
    WHERE status = 'running' AND lease_expires_at <= sqlc.arg(recovered_at)
    ORDER BY lease_expires_at, id
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
UPDATE component_repo.tasks task
SET status = CASE
        WHEN task.cancel_requested_at IS NOT NULL THEN 'cancelled'
        WHEN task.attempts < task.max_attempts THEN 'queued'
        ELSE 'failed'
    END,
    available_at = CASE
        WHEN task.cancel_requested_at IS NULL AND task.attempts < task.max_attempts
            THEN sqlc.arg(recovered_at)
        ELSE task.available_at
    END,
    lease_owner = NULL,
    lease_expires_at = NULL,
    progress_code = CASE
        WHEN task.cancel_requested_at IS NULL AND task.attempts < task.max_attempts
            THEN NULL
        ELSE task.progress_code
    END,
    progress_params = CASE
        WHEN task.cancel_requested_at IS NULL AND task.attempts < task.max_attempts
            THEN NULL
        ELSE task.progress_params
    END,
    progress_percent = CASE
        WHEN task.cancel_requested_at IS NULL AND task.attempts < task.max_attempts
            THEN NULL
        ELSE task.progress_percent
    END,
    error_code = CASE
        WHEN task.cancel_requested_at IS NULL AND task.attempts >= task.max_attempts
            THEN 'common.internal_error'
        ELSE task.error_code
    END,
    error_params = CASE
        WHEN task.cancel_requested_at IS NULL AND task.attempts >= task.max_attempts
            THEN '{}'::jsonb
        ELSE task.error_params
    END,
    finished_at = CASE
        WHEN task.cancel_requested_at IS NOT NULL OR task.attempts >= task.max_attempts
            THEN sqlc.arg(recovered_at)
        ELSE NULL
    END,
    updated_at = sqlc.arg(recovered_at)
FROM candidate
WHERE task.id = candidate.id
RETURNING task.id, task.owner_id, task.task_type, task.status, task.payload,
          task.result, task.result_artifact_id, task.locale, task.timezone,
          task.created_by, task.attempts, task.max_attempts,
          task.available_at, task.lease_owner, task.lease_expires_at,
          task.progress_code, task.progress_params, task.progress_percent,
          task.error_code, task.error_params, task.created_at, task.started_at,
          task.finished_at, task.cancel_requested_at, task.cancel_requested_by,
          task.updated_at, task.task_job_id, task.execution_number,
          task.retry_of_task_id;

-- name: CreateTaskEvent :one
INSERT INTO component_repo.task_events (
    task_id, status, code, params, progress_percent
) VALUES (
    sqlc.arg(task_id), sqlc.arg(status), sqlc.narg(code),
    sqlc.narg(params), sqlc.narg(progress_percent)
)
RETURNING id, task_id, status, code, params, progress_percent, created_at;

-- name: ListOwnedTaskEvents :many
SELECT event.id, event.task_id, event.status, event.code, event.params,
       event.progress_percent, event.created_at
FROM component_repo.task_events event
JOIN component_repo.tasks task ON task.id = event.task_id
WHERE event.task_id = sqlc.arg(task_id) AND task.owner_id = sqlc.arg(actor_id)
ORDER BY event.created_at, event.id;

-- name: CreateOutboxEvent :execrows
INSERT INTO component_repo.outbox_events (
    id, aggregate_type, aggregate_id, topic, event_key, payload,
    max_attempts, available_at
) VALUES (
    sqlc.arg(id), sqlc.arg(aggregate_type), sqlc.arg(aggregate_id),
    sqlc.arg(topic), sqlc.arg(event_key), sqlc.arg(payload),
    sqlc.arg(max_attempts), sqlc.arg(available_at)
)
ON CONFLICT (topic, event_key) DO NOTHING;

-- name: ClaimOutboxEvent :one
WITH candidate AS (
    SELECT id
    FROM component_repo.outbox_events
    WHERE published_at IS NULL
      AND attempts < max_attempts
      AND available_at <= sqlc.arg(claimed_at)
      AND (lease_owner IS NULL OR lease_expires_at <= sqlc.arg(claimed_at))
    ORDER BY available_at, created_at, id
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
UPDATE component_repo.outbox_events event
SET attempts = event.attempts + 1, lease_owner = sqlc.arg(lease_owner),
    lease_expires_at = sqlc.arg(lease_expires_at), updated_at = sqlc.arg(claimed_at)
FROM candidate
WHERE event.id = candidate.id
RETURNING event.id, event.aggregate_type, event.aggregate_id, event.topic,
          event.event_key, event.payload, event.attempts, event.available_at,
          event.published_at, event.last_error_code, event.last_error_params,
          event.created_at, event.max_attempts, event.lease_owner,
          event.lease_expires_at, event.updated_at;

-- name: MarkOutboxPublished :one
UPDATE component_repo.outbox_events
SET published_at = sqlc.arg(published_at), lease_owner = NULL,
    lease_expires_at = NULL, last_error_code = NULL, last_error_params = NULL,
    updated_at = sqlc.arg(published_at)
WHERE id = sqlc.arg(event_id) AND published_at IS NULL
  AND lease_owner = sqlc.arg(lease_owner)
  AND lease_expires_at > sqlc.arg(published_at)
RETURNING id, aggregate_type, aggregate_id, topic, event_key, payload, attempts,
          available_at, published_at, last_error_code, last_error_params,
          created_at, max_attempts, lease_owner, lease_expires_at, updated_at;

-- name: RetryOutboxEvent :one
UPDATE component_repo.outbox_events
SET available_at = sqlc.arg(available_at), lease_owner = NULL, lease_expires_at = NULL,
    last_error_code = sqlc.arg(error_code), last_error_params = sqlc.arg(error_params),
    updated_at = sqlc.arg(updated_at)
WHERE id = sqlc.arg(event_id) AND published_at IS NULL
  AND lease_owner = sqlc.arg(lease_owner)
RETURNING id, aggregate_type, aggregate_id, topic, event_key, payload, attempts,
          available_at, published_at, last_error_code, last_error_params,
          created_at, max_attempts, lease_owner, lease_expires_at, updated_at;
