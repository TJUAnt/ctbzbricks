-- name: AcquireSharedComponentActivityLock :exec
-- Watch/Unwatch/Star 使用同一 Component 的共享事务锁；Publish 与 Component 删除使用独占锁冻结生命周期边界。
SELECT pg_advisory_xact_lock_shared(sqlc.arg(lock_key)::bigint);

-- name: AcquireExclusiveComponentActivityLock :exec
-- Publish 与 Component 删除使用同一 Component 的独占事务锁；Feed 不依赖事件时点订阅资格，
-- 但独占锁仍阻止并发关系写入越过发布或删除的事务边界。
SELECT pg_advisory_xact_lock(sqlc.arg(lock_key)::bigint);
