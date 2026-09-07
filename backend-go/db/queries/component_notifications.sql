-- name: ClaimComponentEventDelivery :one
-- Worker 只从 pending/retry_wait partial index 领取可执行 Delivery；终态历史永不进入 claim 候选。
WITH candidate AS (
    SELECT delivery.event_id
    FROM component_repo.component_event_deliveries delivery
    WHERE delivery.status IN ('pending', 'retry_wait')
      AND delivery.available_at <= sqlc.arg(claimed_at)
    ORDER BY delivery.available_at, delivery.event_id
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
UPDATE component_repo.component_event_deliveries delivery
SET status = 'processing',
    attempts = delivery.attempts + 1,
    lease_owner = sqlc.arg(lease_owner),
    lease_expires_at = sqlc.arg(lease_expires_at),
    last_error_code = NULL,
    last_error_params = '{}'::jsonb,
    started_at = COALESCE(delivery.started_at, sqlc.arg(claimed_at)),
    updated_at = sqlc.arg(claimed_at)
FROM candidate
JOIN component_repo.component_domain_events event ON event.id = candidate.event_id
WHERE delivery.event_id = candidate.event_id
RETURNING delivery.event_id, delivery.status, delivery.cursor_actor_id, delivery.cursor_period_id,
          delivery.attempts, delivery.max_attempts, delivery.available_at, delivery.lease_owner,
          delivery.lease_expires_at, delivery.last_error_code, delivery.last_error_params,
          delivery.started_at, delivery.completed_at, delivery.dead_lettered_at,
          delivery.dead_letter_acknowledged_at, delivery.dead_letter_acknowledged_by,
          delivery.created_at, delivery.updated_at, event.occurred_at;

-- name: RecoverExpiredComponentEventDelivery :one
-- 过期 processing lease 每次只恢复一行；达到最大尝试后进入 dead letter，否则重新进入可领取队列。
WITH candidate AS (
    SELECT delivery.event_id
    FROM component_repo.component_event_deliveries delivery
    WHERE delivery.status = 'processing'
      AND delivery.lease_expires_at <= sqlc.arg(recovered_at)
    ORDER BY delivery.lease_expires_at, delivery.event_id
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
UPDATE component_repo.component_event_deliveries delivery
SET status = CASE WHEN delivery.attempts >= delivery.max_attempts THEN 'dead_lettered' ELSE 'retry_wait' END,
    available_at = sqlc.arg(recovered_at),
    lease_owner = NULL,
    lease_expires_at = NULL,
    last_error_code = 'notification.delivery.lease_expired',
    last_error_params = '{}'::jsonb,
    dead_lettered_at = CASE
        WHEN delivery.attempts >= delivery.max_attempts THEN sqlc.arg(recovered_at)
        ELSE NULL
    END,
    updated_at = sqlc.arg(recovered_at)
FROM candidate
JOIN component_repo.component_domain_events event ON event.id = candidate.event_id
WHERE delivery.event_id = candidate.event_id
RETURNING delivery.event_id, delivery.status, delivery.cursor_actor_id, delivery.cursor_period_id,
          delivery.attempts, delivery.max_attempts, delivery.available_at, delivery.lease_owner,
          delivery.lease_expires_at, delivery.last_error_code, delivery.last_error_params,
          delivery.started_at, delivery.completed_at, delivery.dead_lettered_at,
          delivery.dead_letter_acknowledged_at, delivery.dead_letter_acknowledged_by,
          delivery.created_at, delivery.updated_at, event.occurred_at;

-- name: HeartbeatComponentEventDelivery :execrows
-- attempt 是 fencing token；旧进程即使恢复执行，也不能延长或提交新 owner 已接管的 lease。
UPDATE component_repo.component_event_deliveries
SET lease_expires_at = sqlc.arg(lease_expires_at),
    updated_at = sqlc.arg(heartbeat_at)
WHERE event_id = sqlc.arg(event_id)
  AND status = 'processing'
  AND lease_owner = sqlc.arg(lease_owner)
  AND attempts = sqlc.arg(claimed_attempt)
  AND lease_expires_at > sqlc.arg(heartbeat_at);

-- name: GetClaimedComponentEventDelivery :one
-- 每个批次在事务内锁住并复核 lease fence，同时取得不可变事件和 tombstone 状态。
SELECT delivery.event_id, delivery.cursor_actor_id, delivery.cursor_period_id,
       delivery.attempts, delivery.max_attempts,
       event.event_type, event.component_id, event.component_version_id, event.event_seq,
       event.occurred_at,
       (component.deleted_at IS NOT NULL OR component.status <> 'active')::boolean AS tombstone
FROM component_repo.component_event_deliveries delivery
JOIN component_repo.component_domain_events event ON event.id = delivery.event_id
JOIN component_repo.components component ON component.id = event.component_id
WHERE delivery.event_id = sqlc.arg(event_id)
  AND delivery.status = 'processing'
  AND delivery.lease_owner = sqlc.arg(lease_owner)
  AND delivery.attempts = sqlc.arg(claimed_attempt)
  AND delivery.lease_expires_at > sqlc.arg(checked_at)
FOR UPDATE OF delivery;

-- name: ListEligibleComponentWatchRecipients :many
-- active 与 closed 使用各自的权威索引，避免无界 active range 污染 GiST 选择性；合并后只对最多
-- 当前单事件 recipient 包络内的命中集合按 actor/period 做 keyset 和 250 条分页。
WITH eligible AS (
    (
        SELECT watch.id AS period_id, watch.actor_id,
               watch.notification_locale, watch.notification_timezone,
               watch.notification_catalog_version
        FROM component_repo.component_watch_periods watch
        WHERE watch.component_id = sqlc.arg(component_id)
          AND watch.ended_seq IS NULL
          AND watch.started_seq <= sqlc.arg(event_seq)::bigint
          AND (watch.actor_id, watch.id) > (
              COALESCE(sqlc.narg(cursor_actor_id)::uuid, '00000000-0000-0000-0000-000000000000'::uuid),
              COALESCE(sqlc.narg(cursor_period_id)::bigint, 0::bigint)
          )
        ORDER BY watch.actor_id, watch.id
        LIMIT sqlc.arg(batch_size)
    )
    UNION ALL
    (
        SELECT watch.id AS period_id, watch.actor_id,
               watch.notification_locale, watch.notification_timezone,
               watch.notification_catalog_version
        FROM component_repo.component_watch_periods watch
        WHERE watch.component_id = sqlc.arg(component_id)
          AND watch.ended_seq IS NOT NULL
          AND int8range(watch.started_seq, watch.ended_seq, '[)') @> sqlc.arg(event_seq)::bigint
          AND (watch.actor_id, watch.id) > (
              COALESCE(sqlc.narg(cursor_actor_id)::uuid, '00000000-0000-0000-0000-000000000000'::uuid),
              COALESCE(sqlc.narg(cursor_period_id)::bigint, 0::bigint)
          )
        ORDER BY watch.actor_id, watch.id
        LIMIT sqlc.arg(batch_size)
    )
)
SELECT period_id, actor_id, notification_locale, notification_timezone,
       notification_catalog_version
FROM eligible
ORDER BY actor_id, period_id
LIMIT sqlc.arg(batch_size);

-- name: InsertComponentVersionNotifications :many
-- 固定页面后一次批量写入；唯一键把 crash/retry 收敛为用户可见 exactly-once，返回值只用于 created/deduplicated 指标。
WITH proposed AS (
    SELECT item.notification_id,
           (sqlc.arg(recipient_ids)::uuid[])[item.ordinality] AS recipient_id,
           (sqlc.arg(source_watch_period_ids)::bigint[])[item.ordinality] AS source_watch_period_id,
           (sqlc.arg(locales)::text[])[item.ordinality] AS locale,
           (sqlc.arg(timezones)::text[])[item.ordinality] AS timezone,
           (sqlc.arg(resource_catalog_versions)::text[])[item.ordinality] AS resource_catalog_version
    FROM unnest(sqlc.arg(notification_ids)::uuid[]) WITH ORDINALITY AS item(notification_id, ordinality)
)
INSERT INTO component_repo.user_notifications (
    id, recipient_id, event_id, source_watch_period_id, notification_type,
    code, params, component_id, component_version_id,
    locale, timezone, resource_catalog_version, tombstone
)
SELECT proposed.notification_id, proposed.recipient_id, sqlc.arg(event_id), proposed.source_watch_period_id,
       'component.version.published.v1', sqlc.arg(notification_code), sqlc.arg(notification_params),
       sqlc.arg(component_id), sqlc.arg(component_version_id),
       proposed.locale, proposed.timezone, proposed.resource_catalog_version, sqlc.arg(tombstone)
FROM proposed
ON CONFLICT (recipient_id, event_id, notification_type) DO NOTHING
RETURNING recipient_id;

-- name: AdvanceComponentEventDeliveryCursor :execrows
-- 通知写入与 cursor 推进使用同一事务；attempt fence 阻止过期 Worker 跨 lease 提交页面。
UPDATE component_repo.component_event_deliveries
SET cursor_actor_id = sqlc.arg(cursor_actor_id),
    cursor_period_id = sqlc.arg(cursor_period_id),
    updated_at = sqlc.arg(updated_at)
WHERE event_id = sqlc.arg(event_id)
  AND status = 'processing'
  AND lease_owner = sqlc.arg(lease_owner)
  AND attempts = sqlc.arg(claimed_attempt)
  AND lease_expires_at > sqlc.arg(updated_at);

-- name: CompleteComponentEventDelivery :execrows
-- 只有 cursor 之后已不存在 recipient 的空页面才能完成 Delivery。
UPDATE component_repo.component_event_deliveries
SET status = 'completed',
    lease_owner = NULL,
    lease_expires_at = NULL,
    last_error_code = NULL,
    last_error_params = '{}'::jsonb,
    completed_at = sqlc.arg(completed_at),
    updated_at = sqlc.arg(completed_at)
WHERE event_id = sqlc.arg(event_id)
  AND status = 'processing'
  AND lease_owner = sqlc.arg(lease_owner)
  AND attempts = sqlc.arg(claimed_attempt)
  AND lease_expires_at > sqlc.arg(completed_at);

-- name: RetryComponentEventDelivery :execrows
UPDATE component_repo.component_event_deliveries
SET status = 'retry_wait',
    available_at = sqlc.arg(available_at),
    lease_owner = NULL,
    lease_expires_at = NULL,
    last_error_code = sqlc.arg(error_code),
    last_error_params = sqlc.arg(error_params),
    updated_at = sqlc.arg(failed_at)
WHERE event_id = sqlc.arg(event_id)
  AND status = 'processing'
  AND lease_owner = sqlc.arg(lease_owner)
  AND attempts = sqlc.arg(claimed_attempt)
  AND attempts < max_attempts
  AND lease_expires_at > sqlc.arg(failed_at);

-- name: DeadLetterComponentEventDelivery :execrows
UPDATE component_repo.component_event_deliveries
SET status = 'dead_lettered',
    lease_owner = NULL,
    lease_expires_at = NULL,
    last_error_code = sqlc.arg(error_code),
    last_error_params = sqlc.arg(error_params),
    dead_lettered_at = sqlc.arg(failed_at),
    updated_at = sqlc.arg(failed_at)
WHERE event_id = sqlc.arg(event_id)
  AND status = 'processing'
  AND lease_owner = sqlc.arg(lease_owner)
  AND attempts = sqlc.arg(claimed_attempt)
  AND lease_expires_at > sqlc.arg(failed_at);

-- name: GetComponentNotificationBacklog :one
-- Gauge 只扫描非终态和未确认 dead-letter partial indexes；永久完成历史不参与周期采样。
WITH pending AS (
    SELECT count(*)::bigint AS event_count,
           COALESCE(EXTRACT(EPOCH FROM (clock_timestamp() - min(event.occurred_at))), 0)::double precision
               AS oldest_age_seconds
    FROM component_repo.component_event_deliveries delivery
    JOIN component_repo.component_domain_events event ON event.id = delivery.event_id
    WHERE delivery.status IN ('pending', 'processing', 'retry_wait')
), unresolved_dead AS (
    SELECT count(*)::bigint AS event_count,
           COALESCE(EXTRACT(EPOCH FROM (clock_timestamp() - min(delivery.dead_lettered_at))), 0)::double precision
               AS oldest_age_seconds
    FROM component_repo.component_event_deliveries delivery
    WHERE delivery.status = 'dead_lettered'
      AND delivery.dead_letter_acknowledged_at IS NULL
)
SELECT pending.event_count AS pending_events,
       pending.oldest_age_seconds AS oldest_pending_seconds,
       unresolved_dead.event_count AS unresolved_dead_letters,
       unresolved_dead.oldest_age_seconds AS oldest_dead_letter_seconds
FROM pending CROSS JOIN unresolved_dead;
