//go:build integration

package component_test

import (
	"context"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

// TestZZWatchListQueryPlanEnvelope 在显式门禁中分别构造 active 包络与 closed 重评点，验证历史增长不会改变在线查询边界。
func TestZZWatchListQueryPlanEnvelope(t *testing.T) {
	if os.Getenv("RUN_WATCH_LIST_PLAN_TEST") != "1" && os.Getenv("RUN_WATCH_FEED_PLAN_TEST") != "1" {
		t.Skip("set RUN_WATCH_LIST_PLAN_TEST=1 or RUN_WATCH_FEED_PLAN_TEST=1 to run the Watch plan gate")
	}
	databaseURL := os.Getenv("TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("TEST_DATABASE_URL is required")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()

	seedWatchListPlanEnvelope(t, ctx, pool)
	assertWatchLedgerEnvelope(t, ctx, pool)
	if os.Getenv("RUN_WATCH_FEED_PLAN_TEST") == "1" {
		assertWatchFeedPlans(t, ctx, pool)
	}
	actor := mustUUID(t, "16000000-0000-0000-0000-000000000001")
	firstCursorTime := time.Date(9999, 12, 31, 23, 59, 59, 0, time.UTC)
	firstCursorID := mustUUID(t, "ffffffff-ffff-ffff-ffff-ffffffffffff")

	for _, scenario := range []struct {
		name     string
		locale   string
		query    string
		category string
	}{
		{name: "unfiltered", locale: "en-US"},
		{name: "selective", locale: "en-US", query: "Watch filter 1000", category: "vehicle"},
		{name: "high-match", locale: "en-US", query: "Watch filter"},
		{name: "reviewed-translation", locale: "zh-CN", query: "订阅筛选 1000", category: "vehicle"},
	} {
		// 第一次执行只用于填充测试机缓存；记录的第二次计划仍只代表本机查询形状，不作为生产 SLO。
		_ = explainWatchList(t, ctx, pool, actor, firstCursorTime, firstCursorID, scenario.locale, scenario.query, scenario.category)
		plan := explainWatchList(t, ctx, pool, actor, firstCursorTime, firstCursorID, scenario.locale, scenario.query, scenario.category)
		assertWatchActorDrivenPlan(t, scenario.name, plan)
		if scenario.name == "unfiltered" && !strings.Contains(plan, "One-Time Filter: false") {
			t.Fatalf("unfiltered plan did not gate the candidate translation probe:\n%s", plan)
		}
		t.Logf("%s %s", scenario.name, explainTiming(plan))
	}

	var deepTime time.Time
	var deepID pgtype.UUID
	if err := pool.QueryRow(ctx, `
		SELECT watched_at, component_id
		FROM component_repo.component_watch_periods
		WHERE actor_id=$1 AND ended_seq IS NULL
		ORDER BY watched_at DESC, component_id DESC
		OFFSET 979 LIMIT 1`, actor).Scan(&deepTime, &deepID); err != nil {
		t.Fatalf("read deepest supported Watch cursor: %v", err)
	}
	_ = explainWatchList(t, ctx, pool, actor, deepTime, deepID, "en-US", "", "")
	deepPlan := explainWatchList(t, ctx, pool, actor, deepTime, deepID, "en-US", "", "")
	assertWatchActorDrivenPlan(t, "deep-cursor", deepPlan)
	if !strings.Contains(deepPlan, "component_watch_periods_actor_active_time_idx") {
		t.Fatalf("deep cursor did not enter the actor time index condition:\n%s", deepPlan)
	}
	if strings.Contains(deepPlan, "Rows Removed by Filter: 979") {
		t.Fatalf("deep cursor skipped prior Watch rows instead of entering the index condition:\n%s", deepPlan)
	}
	t.Logf("deep-cursor %s", explainTiming(deepPlan))

	emptyActor := mustUUID(t, "16000000-0000-0000-0000-000000000999")
	_ = explainWatchList(t, ctx, pool, emptyActor, firstCursorTime, firstCursorID, "en-US", "", "")
	emptyPlan := explainWatchList(t, ctx, pool, emptyActor, firstCursorTime, firstCursorID, "en-US", "", "")
	assertWatchActorDrivenPlan(t, "empty-actor", emptyPlan)
	t.Logf("empty-actor %s", explainTiming(emptyPlan))
	explainWatchRewatchMutation(t, ctx, pool, actor)

	var version, sharedBuffers, workMem, effectiveCacheSize string
	for setting, target := range map[string]*string{
		"server_version":       &version,
		"shared_buffers":       &sharedBuffers,
		"work_mem":             &workMem,
		"effective_cache_size": &effectiveCacheSize,
	} {
		if err := pool.QueryRow(ctx, "SHOW "+setting).Scan(target); err != nil {
			t.Fatal(err)
		}
	}
	t.Logf("PostgreSQL %s; shared_buffers=%s work_mem=%s effective_cache_size=%s; plans are warm-cache local evidence",
		version, sharedBuffers, workMem, effectiveCacheSize)
}

// assertWatchLedgerEnvelope 固定 active 与 closed 两个独立容量维度，并记录本地物理大小供未来同版本重评。
func assertWatchLedgerEnvelope(t *testing.T, ctx context.Context, pool *pgxpool.Pool) {
	t.Helper()
	var activeCount, closedCount int64
	if err := pool.QueryRow(ctx, `
		SELECT count(*) FILTER (WHERE watch.ended_seq IS NULL),
		       count(*) FILTER (WHERE watch.ended_seq IS NOT NULL)
		FROM component_repo.component_watch_periods watch
		JOIN component_repo.components component ON component.id = watch.component_id
		WHERE component.name LIKE 'Watch filter %'`).Scan(&activeCount, &closedCount); err != nil {
		t.Fatal(err)
	}
	if activeCount != 1_000_000 || closedCount != 1_000_000 {
		t.Fatalf("unexpected Watch envelope: active=%d closed=%d", activeCount, closedCount)
	}

	var totalBytes, heapBytes, primaryBytes, activeUniqueBytes, activeTimeBytes int64
	if err := pool.QueryRow(ctx, `
		SELECT pg_total_relation_size('component_repo.component_watch_periods'::regclass),
		       pg_relation_size('component_repo.component_watch_periods'::regclass),
		       pg_relation_size('component_repo.component_watch_periods_pkey'::regclass),
		       pg_relation_size('component_repo.component_watch_periods_active_unique_idx'::regclass),
		       pg_relation_size('component_repo.component_watch_periods_actor_active_time_idx'::regclass)`).Scan(
		&totalBytes, &heapBytes, &primaryBytes, &activeUniqueBytes, &activeTimeBytes,
	); err != nil {
		t.Fatal(err)
	}
	t.Logf("Watch ledger rows active=%d closed=%d; local bytes total=%d heap=%d primary=%d active_unique=%d active_time=%d",
		activeCount, closedCount, totalBytes, heapBytes, primaryBytes, activeUniqueBytes, activeTimeBytes,
	)
}

// assertWatchFeedPlans 验证读取时 Feed 只由当前 actor 的 active Watch 和事件时间索引驱动，
// 百万 closed 历史不得参与执行；首屏、窄时间窗、高命中、空 actor 与深 cursor 都不得退化为关系全扫描。
func assertWatchFeedPlans(t *testing.T, ctx context.Context, pool *pgxpool.Pool) {
	t.Helper()
	actor := mustUUID(t, "16000000-0000-0000-0000-000000000001")
	firstCursorTime := time.Date(9999, 12, 31, 23, 59, 59, 0, time.UTC)
	firstCursorID := mustUUID(t, "ffffffff-ffff-ffff-ffff-ffffffffffff")
	for _, scenario := range []struct {
		name        string
		windowStart time.Time
	}{
		{name: "selective-window", windowStart: time.Now().UTC().Add(-25 * time.Hour)},
		{name: "high-match-window", windowStart: time.Now().UTC().Add(-31 * 24 * time.Hour)},
		{name: "90-day-window", windowStart: time.Now().UTC().Add(-90 * 24 * time.Hour)},
	} {
		_ = explainWatchFeed(t, ctx, pool, actor, scenario.windowStart, firstCursorTime, firstCursorID)
		plan := explainWatchFeed(t, ctx, pool, actor, scenario.windowStart, firstCursorTime, firstCursorID)
		assertWatchFeedPlan(t, scenario.name, plan)
		t.Logf("feed-%s %s", scenario.name, explainTiming(plan))
	}

	var deepTime time.Time
	var deepEventID pgtype.UUID
	if err := pool.QueryRow(ctx, `
		SELECT event.occurred_at, event.id
		FROM component_repo.component_watch_periods watch
		JOIN component_repo.component_domain_events event ON event.component_id = watch.component_id
		WHERE watch.actor_id=$1 AND watch.ended_seq IS NULL
		  AND event.occurred_at >= clock_timestamp() - interval '31 days'
		ORDER BY event.occurred_at, event.id OFFSET 20 LIMIT 1`, actor).Scan(&deepTime, &deepEventID); err != nil {
		t.Fatalf("read deepest Feed cursor: %v", err)
	}
	deepPlan := explainWatchFeed(t, ctx, pool, actor, time.Now().UTC().Add(-31*24*time.Hour), deepTime, deepEventID)
	assertWatchFeedPlan(t, "deep-cursor", deepPlan)
	t.Logf("feed-deep-cursor %s", explainTiming(deepPlan))

	emptyActor := mustUUID(t, "16000000-0000-0000-0000-000000000999")
	emptyPlan := explainWatchFeed(t, ctx, pool, emptyActor, time.Now().UTC().Add(-31*24*time.Hour), firstCursorTime, firstCursorID)
	assertWatchFeedPlan(t, "empty-actor", emptyPlan)
	t.Logf("feed-empty-actor %s", explainTiming(emptyPlan))
}

func explainWatchFeed(
	t *testing.T,
	ctx context.Context,
	pool *pgxpool.Pool,
	actor pgtype.UUID,
	windowStart time.Time,
	cursorTime time.Time,
	cursorEventID pgtype.UUID,
) string {
	t.Helper()
	// 直接读取 sqlc 的手写查询，确保门禁包含真实页内 Version、删除过滤和 reviewed translation 投影。
	// 不维护简化 SQL 副本，否则业务查询变更后性能测试可能仍错误地通过。
	data, err := os.ReadFile("../../../db/queries/component_watches.sql")
	if err != nil {
		t.Fatalf("read authoritative Watch SQL: %v", err)
	}
	_, query, ok := strings.Cut(string(data), "-- name: ListCurrentComponentWatchFeed :many")
	if !ok {
		t.Fatal("authoritative Feed query not found")
	}
	query = strings.NewReplacer(
		"sqlc.arg(actor_id)", "$1",
		"sqlc.arg(window_start)", "$2",
		"sqlc.narg(cursor_occurred_at)", "$3",
		"sqlc.narg(cursor_event_id)", "$4",
		"sqlc.arg(locale)", "$5",
		"sqlc.arg(page_size)", "$6",
	).Replace(query)
	return collectExplain(t, ctx, pool, "EXPLAIN (ANALYZE, BUFFERS, SETTINGS)\n"+query,
		actor, windowStart, cursorTime, cursorEventID, "zh-CN", int32(21))
}

func assertWatchFeedPlan(t *testing.T, name, plan string) {
	t.Helper()
	// 发布验收保留完整执行节点与 buffers/settings，不能只记录计时或索引名称。
	t.Logf("%s full Feed plan:\n%s", name, plan)
	if strings.Contains(plan, "Seq Scan on component_watch_periods") {
		t.Fatalf("%s scanned the complete Watch ledger:\n%s", name, plan)
	}
	if strings.Contains(plan, "Seq Scan on component_feed_entries") {
		t.Fatalf("%s scanned the complete terminal Feed projection:\n%s", name, plan)
	}
	if !strings.Contains(plan, "component_watch_periods_active_unique_idx") &&
		!strings.Contains(plan, "component_watch_periods_actor_active_time_idx") {
		t.Fatalf("%s did not use an actor-scoped active Watch index:\n%s", name, plan)
	}
	if !strings.Contains(plan, "component_domain_events_component_feed_idx") {
		t.Fatalf("%s did not use the Component/time Feed event index:\n%s", name, plan)
	}
	if strings.Contains(plan, "temp read=") || strings.Contains(plan, "temp written=") ||
		strings.Contains(plan, "Sort Method: external") {
		t.Fatalf("%s spilled Feed paging to temporary storage:\n%s", name, plan)
	}
}

// explainWatchRewatchMutation 在回滚事务内关闭并重新追加一个 period，确保百万 closed 历史不进入点操作候选集。
func explainWatchRewatchMutation(t *testing.T, ctx context.Context, pool *pgxpool.Pool, actor pgtype.UUID) {
	t.Helper()
	var componentID pgtype.UUID
	if err := pool.QueryRow(ctx, "SELECT md5('watch-list-component-1')::uuid").Scan(&componentID); err != nil {
		t.Fatal(err)
	}
	tx, err := pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	closePlan := collectWatchExplainTx(t, ctx, tx, `
		EXPLAIN (ANALYZE, BUFFERS, SETTINGS)
		UPDATE component_repo.component_watch_periods
		SET ended_seq = nextval('component_repo.component_activity_sequence'),
		    unwatched_at = clock_timestamp(),
		    ended_reason = 'user_unwatched'
		WHERE actor_id = $1 AND component_id = $2 AND ended_seq IS NULL`, actor, componentID)
	if strings.Contains(closePlan, "Seq Scan on component_watch_periods") ||
		(!strings.Contains(closePlan, "component_watch_periods_active_unique_idx") &&
			!strings.Contains(closePlan, "component_watch_periods_component_active_idx")) {
		t.Fatalf("Unwatch did not use the active relationship index with closed history present:\n%s", closePlan)
	}
	t.Logf("million-closed unwatch %s", explainTiming(closePlan))

	rewatchPlan := collectWatchExplainTx(t, ctx, tx, `
		EXPLAIN (ANALYZE, BUFFERS, SETTINGS)
		INSERT INTO component_repo.component_watch_periods (actor_id, component_id, watch_level)
		VALUES ($1, $2, 'releases_only')
		ON CONFLICT (actor_id, component_id) WHERE ended_seq IS NULL DO NOTHING`, actor, componentID)
	if !strings.Contains(rewatchPlan, "Conflict Arbiter Indexes: component_watch_periods_active_unique_idx") {
		t.Fatalf("Rewatch did not arbitrate through the active partial unique index:\n%s", rewatchPlan)
	}
	t.Logf("million-closed rewatch %s", explainTiming(rewatchPlan))
}

func collectWatchExplainTx(t *testing.T, ctx context.Context, tx pgx.Tx, query string, args ...any) string {
	t.Helper()
	rows, err := tx.Query(ctx, query, args...)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	lines := make([]string, 0, 32)
	for rows.Next() {
		var line string
		if err := rows.Scan(&line); err != nil {
			t.Fatal(err)
		}
		lines = append(lines, line)
	}
	if err := rows.Err(); err != nil {
		t.Fatal(err)
	}
	return strings.Join(lines, "\n")
}

func assertWatchActorDrivenPlan(t *testing.T, name, plan string) {
	t.Helper()
	if strings.Contains(plan, "Seq Scan on component_watch_periods") {
		t.Fatalf("%s plan scanned the complete Watch ledger:\n%s", name, plan)
	}
	if !strings.Contains(plan, "component_watch_periods_actor_active_time_idx") &&
		!strings.Contains(plan, "component_watch_periods_active_unique_idx") {
		t.Fatalf("%s plan did not start from an actor-scoped active Watch index:\n%s", name, plan)
	}
	if strings.Contains(plan, "Seq Scan on component_versions") {
		t.Fatalf("%s plan scanned all Versions instead of probing actor candidates:\n%s", name, plan)
	}
	if strings.Contains(plan, "temp read=") || strings.Contains(plan, "temp written=") ||
		strings.Contains(plan, "Sort Method: external") {
		t.Fatalf("%s plan spilled page work to temporary storage:\n%s", name, plan)
	}
}

func explainTiming(plan string) string {
	for _, line := range strings.Split(plan, "\n") {
		if trimmed := strings.TrimSpace(line); strings.HasPrefix(trimmed, "Execution Time:") {
			return trimmed
		}
	}
	return "Execution Time: unavailable"
}

func seedWatchListPlanEnvelope(t *testing.T, ctx context.Context, pool *pgxpool.Pool) {
	t.Helper()
	_, err := pool.Exec(ctx, `
		INSERT INTO component_repo.artifacts (
			id, owner_id, artifact_type, source_kind, original_filename,
			storage_provider, storage_bucket, storage_key, sha256, file_size,
			mime_type, verification_status, verified_at, uploaded_by
		) VALUES (
			'16000000-0000-0000-0000-000000000010',
			'16000000-0000-0000-0000-000000000002', 'component_source', 'source', 'watch-perf.ldr',
			'test', 'test', 'watch-list/perf.ldr', repeat('a',64), 1,
			'text/plain', 'verified', now(), '16000000-0000-0000-0000-000000000002'
		);
		INSERT INTO component_repo.upload_sessions (
			id, owner_id, status, locale, timezone, created_by, expires_at, completed_at
		) VALUES (
			'16000000-0000-0000-0000-000000000013',
			'16000000-0000-0000-0000-000000000002', 'completed', 'en-US', 'UTC',
			'16000000-0000-0000-0000-000000000002', now() + interval '1 hour', now()
		);
		INSERT INTO component_repo.tasks (id, owner_id, task_type, payload, locale, timezone, created_by)
		VALUES
			('16000000-0000-0000-0000-000000000014', '16000000-0000-0000-0000-000000000002',
			 'component.artifact.verify', '{"artifactId":"16000000-0000-0000-0000-000000000010"}',
			 'en-US', 'UTC', '16000000-0000-0000-0000-000000000002'),
			('16000000-0000-0000-0000-000000000015', '16000000-0000-0000-0000-000000000002',
			 'component.import.parse', '{"importId":"16000000-0000-0000-0000-000000000011","parserVersion":"perf-v1"}',
			 'en-US', 'UTC', '16000000-0000-0000-0000-000000000002');
		INSERT INTO component_repo.task_dependencies (task_id, prerequisite_task_id, owner_id)
		VALUES ('16000000-0000-0000-0000-000000000015', '16000000-0000-0000-0000-000000000014',
		        '16000000-0000-0000-0000-000000000002');
		INSERT INTO component_repo.imports (
			id, owner_id, source_artifact_id, status, parser_version, locale, timezone, created_by,
			upload_session_id, parse_task_id
		) VALUES (
			'16000000-0000-0000-0000-000000000011', '16000000-0000-0000-0000-000000000002',
			'16000000-0000-0000-0000-000000000010', 'succeeded', 'perf-v1', 'en-US', 'UTC',
			'16000000-0000-0000-0000-000000000002', '16000000-0000-0000-0000-000000000013',
			'16000000-0000-0000-0000-000000000015'
		);
		INSERT INTO component_repo.scene_snapshots (id, import_id, schema_version, parser_version, document, bom, parse_issues)
		VALUES ('16000000-0000-0000-0000-000000000012', '16000000-0000-0000-0000-000000000011',
		        'perf-v1', 'perf-v1', '{}', '{}', '[]');
		INSERT INTO component_repo.components (id, owner_id, content_kind, content_locale, name, category, status, created_by)
		SELECT md5('watch-list-component-' || item)::uuid,
		       CASE WHEN item % 10 = 0 THEN NULL ELSE '16000000-0000-0000-0000-000000000002'::uuid END,
		       CASE WHEN item % 10 = 0 THEN 'official' ELSE 'user' END,
		       'en-US', 'Watch filter ' || item,
		       CASE WHEN item % 10 = 0 THEN 'vehicle' ELSE 'building' END,
		       'active', '16000000-0000-0000-0000-000000000002'
		FROM generate_series(1, 1000) item;
		-- 性能 fixture 只验证 Watch/Feed 查询形状，不重复构造十万条 Import/Candidate 来源链；
		-- 临时停用 Version 来源触发器，事务结束前恢复，发布事件自己的 owner/published 校验仍保持启用。
		ALTER TABLE component_repo.component_versions DISABLE TRIGGER component_versions_require_source_integrity;
		INSERT INTO component_repo.component_versions (
			id, component_id, version_label, status, source_artifact_id, scene_snapshot_id,
			parser_version, interface_signature, structure_hash, geometry_hash, created_by, published_at
		)
		SELECT md5('watch-list-version-' || item)::uuid, md5('watch-list-component-' || item)::uuid,
		       '1.0.0', 'published', '16000000-0000-0000-0000-000000000010',
		       '16000000-0000-0000-0000-000000000012', 'perf-v1', repeat('1',64), repeat('2',64),
		       repeat('3',64), '16000000-0000-0000-0000-000000000002', now()
		FROM generate_series(1, 1000) item;
		UPDATE component_repo.components component
		SET current_version_id = md5('watch-list-version-' || item)::uuid
		FROM generate_series(1, 1000) item
		WHERE component.id = md5('watch-list-component-' || item)::uuid;
		INSERT INTO component_repo.component_translations (
			component_id, locale, name, translation_status, reviewed_by, reviewed_at
		)
		SELECT md5('watch-list-component-' || item)::uuid, 'zh-CN', '订阅筛选 ' || item,
		       'reviewed', '16000000-0000-0000-0000-000000000002', now()
		FROM generate_series(10, 1000, 10) item;
		-- 一百万 closed period 表示每个当前关系曾完成一次 Rewatch；它们不得进入 active partial index。
		INSERT INTO component_repo.component_watch_periods (
			actor_id, component_id, watch_level, started_seq, ended_seq, watched_at, unwatched_at, ended_reason
		)
		SELECT CASE WHEN actor = 1
		            THEN '16000000-0000-0000-0000-000000000001'::uuid
		            ELSE md5('watch-list-actor-' || actor)::uuid END,
		       md5('watch-list-component-1')::uuid, 'releases_only',
		       actor::bigint * 3000 + item::bigint * 3,
		       actor::bigint * 3000 + item::bigint * 3 + 1,
		       '2025-09-04 00:00:00+00'::timestamptz - make_interval(secs => item),
		       '2025-09-05 00:00:00+00'::timestamptz - make_interval(secs => item),
		       'user_unwatched'
		FROM generate_series(1, 1000) actor
		CROSS JOIN generate_series(1, 1000) item;
		INSERT INTO component_repo.component_watch_periods (
			actor_id, component_id, watch_level, started_seq, watched_at
		)
		SELECT CASE WHEN actor = 1
		            THEN '16000000-0000-0000-0000-000000000001'::uuid
		            ELSE md5('watch-list-actor-' || actor)::uuid END,
		       md5('watch-list-component-' || item)::uuid, 'releases_only',
		       actor::bigint * 3000 + item::bigint * 3 + 2,
		       '2026-09-04 00:00:00+00'::timestamptz - make_interval(secs => item)
		FROM generate_series(1, 1000) actor
		CROSS JOIN generate_series(1, 1000) item;
		-- Feed 表保留约九万条窗口外事件，并为 900 个可发布的用户 Component 各准备三条窗口内事件。
		-- 这让计划必须同时证明时间谓词和 Component 谓词进入复合事件索引，不能依赖测试表过小。
		INSERT INTO component_repo.component_versions (
			id, component_id, version_label, status, source_artifact_id, scene_snapshot_id,
			parser_version, interface_signature, structure_hash, geometry_hash, created_by, published_at
		)
		SELECT md5('watch-feed-old-version-' || component_item || '-' || event_item)::uuid,
		       md5('watch-list-component-' || component_item)::uuid,
		       'old-' || event_item, 'published', '16000000-0000-0000-0000-000000000010',
		       '16000000-0000-0000-0000-000000000012', 'perf-v1', repeat('4',64), repeat('5',64),
		       repeat('6',64), '16000000-0000-0000-0000-000000000002',
		       clock_timestamp() - make_interval(days => 40 + event_item)
		FROM generate_series(1, 1000) component_item
		CROSS JOIN generate_series(1, 100) event_item
		WHERE component_item % 10 <> 0;
		INSERT INTO component_repo.component_domain_events (
			id, event_type, component_id, component_version_id, actor_id, occurred_at
		)
		SELECT md5('watch-feed-old-event-' || component_item || '-' || event_item)::uuid,
		       'component.version.published.v1', md5('watch-list-component-' || component_item)::uuid,
		       md5('watch-feed-old-version-' || component_item || '-' || event_item)::uuid,
		       '16000000-0000-0000-0000-000000000002',
		       clock_timestamp() - make_interval(days => 40 + event_item)
		FROM generate_series(1, 1000) component_item
		CROSS JOIN generate_series(1, 100) event_item
		WHERE component_item % 10 <> 0;
		INSERT INTO component_repo.component_versions (
			id, component_id, version_label, status, source_artifact_id, scene_snapshot_id,
			parser_version, interface_signature, structure_hash, geometry_hash, created_by, published_at
		)
		SELECT md5('watch-feed-recent-version-' || component_item || '-' || event_item)::uuid,
		       md5('watch-list-component-' || component_item)::uuid,
		       'recent-' || event_item, 'published', '16000000-0000-0000-0000-000000000010',
		       '16000000-0000-0000-0000-000000000012', 'perf-v1', repeat('7',64), repeat('8',64),
		       repeat('9',64), '16000000-0000-0000-0000-000000000002',
		       clock_timestamp() - make_interval(hours => event_item * 24) + make_interval(secs => component_item)
		FROM generate_series(1, 1000) component_item
		CROSS JOIN generate_series(1, 3) event_item
		WHERE component_item % 10 <> 0;
		ALTER TABLE component_repo.component_versions ENABLE TRIGGER component_versions_require_source_integrity;
		INSERT INTO component_repo.component_domain_events (
			id, event_type, component_id, component_version_id, actor_id, occurred_at
		)
		SELECT md5('watch-feed-recent-event-' || component_item || '-' || event_item)::uuid,
		       'component.version.published.v1', md5('watch-list-component-' || component_item)::uuid,
		       md5('watch-feed-recent-version-' || component_item || '-' || event_item)::uuid,
		       '16000000-0000-0000-0000-000000000002',
		       clock_timestamp() - make_interval(hours => event_item * 24) + make_interval(secs => component_item)
		FROM generate_series(1, 1000) component_item
		CROSS JOIN generate_series(1, 3) event_item
		WHERE component_item % 10 <> 0;
		-- 个人订阅卡片与公共卡片共用终态准入；性能 fixture 同时覆盖 92,700 条 Feed entry，
		-- 防止测试因缺少派生投影而让图片连接成为 never executed 的假阳性。
		INSERT INTO component_repo.component_feed_entries (
			event_id, component_id, component_version_id, render_profile, renderer_version,
			render_status, available_at
		)
		SELECT event.id, event.component_id, event.component_version_id,
		       'feed_card_3x2', 'component-feed-renderer-v4', 'fallback', event.occurred_at
		FROM component_repo.component_domain_events event
		JOIN component_repo.components component ON component.id=event.component_id
		WHERE component.name LIKE 'Watch filter %';
		SELECT setval('component_repo.component_activity_sequence', 4000000, true);
		ANALYZE component_repo.component_watch_periods;
		ANALYZE component_repo.components;
		ANALYZE component_repo.component_versions;
		ANALYZE component_repo.component_translations;
		ANALYZE component_repo.component_domain_events;
		ANALYZE component_repo.component_feed_entries;
	`)
	if err != nil {
		t.Fatalf("seed Watch list capacity envelope: %v", err)
	}
}

func explainWatchList(
	t *testing.T,
	ctx context.Context,
	pool *pgxpool.Pool,
	actor pgtype.UUID,
	cursorTime time.Time,
	cursorID pgtype.UUID,
	locale, query, category string,
) string {
	t.Helper()
	return collectExplain(t, ctx, pool, `
		EXPLAIN (ANALYZE, BUFFERS, SETTINGS)
		WITH actor_watches AS MATERIALIZED (
		    SELECT watch.component_id, watch.watch_level, watch.watched_at
		    FROM component_repo.component_watch_periods watch
		    WHERE watch.actor_id = $1
		      AND watch.ended_seq IS NULL
		      AND (watch.watched_at, watch.component_id) < ($2::timestamptz, $3::uuid)
		), watch_page AS MATERIALIZED (
		    SELECT watch.component_id, watch.watch_level, watch.watched_at
		    FROM actor_watches watch
		    JOIN component_repo.components component ON component.id = watch.component_id
		    JOIN LATERAL (
		        SELECT true AS available
		        FROM component_repo.component_versions public_version
		        WHERE public_version.component_id = component.id
		          AND public_version.deleted_at IS NULL AND public_version.status <> 'draft'
		        LIMIT 1
		    ) public_version ON true
		    LEFT JOIN LATERAL (
		        SELECT item.id, item.name
		        FROM component_repo.component_translations item
		        WHERE $6::text <> '' AND component.content_kind = 'official'
		          AND item.component_id = component.id AND item.locale = $4
		          AND item.translation_status = 'reviewed'
		        LIMIT 1
		    ) search_translation ON true
		    WHERE component.deleted_at IS NULL AND component.status = 'active'
		      AND ($5::text = '' OR component.category = $5)
		      AND ($6::text = ''
		           OR CASE WHEN search_translation.id IS NULL THEN component.name ELSE search_translation.name END
		              ILIKE '%' || $6 || '%'
		           OR component.id::text ILIKE '%' || $6 || '%')
		    ORDER BY watch.watched_at DESC, watch.component_id DESC
		    LIMIT 21
		)
		SELECT page.component_id,
		       CASE WHEN translation.id IS NULL THEN component.name ELSE translation.name END AS selected_name,
		       current_version.version_label, page.watched_at
		FROM watch_page page
		JOIN component_repo.components component ON component.id = page.component_id
		LEFT JOIN component_repo.component_versions current_version
		  ON current_version.id = component.current_version_id AND current_version.deleted_at IS NULL
		LEFT JOIN LATERAL (
		    SELECT item.id, item.name
		    FROM component_repo.component_translations item
		    WHERE component.content_kind = 'official' AND item.component_id = component.id
		      AND item.locale = $4 AND item.translation_status = 'reviewed'
		    LIMIT 1
		) translation ON true
		ORDER BY page.watched_at DESC, page.component_id DESC`,
		actor, cursorTime, cursorID, locale, category, query)
}
