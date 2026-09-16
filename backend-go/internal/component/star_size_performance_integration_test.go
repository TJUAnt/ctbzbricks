//go:build integration

package component

import (
	"context"
	"os"
	"strings"
	"testing"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/jackc/pgx/v5/pgxpool"
)

// TestZZStarSizeQueryPlanEnvelope 只在显式性能门禁中构造当前产品容量包络，避免普通测试隐式承担百万行成本。
func TestZZStarSizeQueryPlanEnvelope(t *testing.T) {
	if os.Getenv("RUN_STAR_SIZE_PLAN_TEST") != "1" {
		t.Skip("set RUN_STAR_SIZE_PLAN_TEST=1 to run the Star size plan gate")
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

	seedStarSizePlanEnvelope(t, ctx, pool)
	actor := mustUUID(t, "15000000-0000-0000-0000-000000000001")
	queries := db.New(pool)
	for _, scenario := range []struct {
		name           string
		locale         string
		query          string
		dimensionCount int32
		sizeA          float64
		sizeB          float64
		sizeC          float64
	}{
		{name: "unfiltered", locale: "en-US"},
		{name: "selective-size", locale: "en-US", dimensionCount: 3, sizeA: 4, sizeB: 5, sizeC: 6},
		{name: "high-match-size", locale: "en-US", dimensionCount: 3, sizeA: 1, sizeB: 2, sizeC: 3},
		{name: "zero-match-size", locale: "en-US", dimensionCount: 3, sizeA: 20, sizeB: 21, sizeC: 22},
		{name: "reviewed-translation-selective", locale: "zh-CN", query: "收藏翻译 1000"},
		{name: "reviewed-translation-high", locale: "zh-CN", query: "收藏翻译"},
	} {
		params := db.ListStarredComponentsParams{
			Locale: scenario.locale, ActorID: actor, SearchQuery: scenario.query,
			SizeDimensionCount: scenario.dimensionCount, SizeA: scenario.sizeA, SizeB: scenario.sizeB, SizeC: scenario.sizeC,
			PageSize: 20,
		}
		if _, err := queries.ListStarredComponents(ctx, params); err != nil {
			t.Fatalf("warm %s Star page: %v", scenario.name, err)
		}
		plan := explainStarPage(t, ctx, pool, params)
		if strings.Contains(plan, "Seq Scan on component_stars") {
			t.Fatalf("%s plan did not start from the actor relationship index:\n%s", scenario.name, plan)
		}
		if strings.Contains(plan, "Seq Scan on component_versions") {
			t.Fatalf("%s plan scanned all Versions instead of probing actor candidates:\n%s", scenario.name, plan)
		}
		if strings.Contains(plan, "Seq Scan on components") {
			t.Fatalf("%s plan scanned the complete Component relation instead of probing actor candidates:\n%s", scenario.name, plan)
		}
		if scenario.dimensionCount != 0 && !strings.Contains(plan, "current_logical_size_a") {
			t.Fatalf("%s plan did not filter through the persisted projection:\n%s", scenario.name, plan)
		}
		if !strings.Contains(scenario.name, "zero-match") && !strings.Contains(plan, "WindowAgg") {
			t.Fatalf("%s plan did not compute exact total before pagination:\n%s", scenario.name, plan)
		}
		if strings.Contains(plan, "Sort Method: external") || strings.Contains(plan, "temp read=") || strings.Contains(plan, "temp written=") {
			t.Fatalf("%s plan spilled Star pagination to temporary storage:\n%s", scenario.name, plan)
		}
		if !strings.Contains(scenario.name, "zero-match") && !strings.Contains(plan, "component_stars_component_idx") {
			t.Fatalf("%s plan did not aggregate page star counts through the component index:\n%s", scenario.name, plan)
		}
		t.Logf("%s plan:\n%s", scenario.name, plan)
		t.Logf("star-%s %s", scenario.name, explainTiming(plan))
	}
	emptyActor := mustUUID(t, "15000000-0000-0000-0000-000000000999")
	emptyParams := db.ListStarredComponentsParams{Locale: "en-US", ActorID: emptyActor, PageSize: 20}
	if _, err := queries.ListStarredComponents(ctx, emptyParams); err != nil {
		t.Fatalf("warm empty-actor Star page: %v", err)
	}
	emptyPlan := explainStarPage(t, ctx, pool, emptyParams)
	if strings.Contains(emptyPlan, "Seq Scan on component_stars") {
		t.Fatalf("empty-actor plan scanned the complete relationship table:\n%s", emptyPlan)
	}
	if strings.Contains(emptyPlan, "Seq Scan on component_versions") {
		t.Fatalf("empty-actor plan scanned Versions before proving the actor candidate set was empty:\n%s", emptyPlan)
	}
	if strings.Contains(emptyPlan, "Seq Scan on components") {
		t.Fatalf("empty-actor plan scanned Components before proving the actor candidate set was empty:\n%s", emptyPlan)
	}
	t.Logf("empty-actor plan:\n%s", emptyPlan)

	for _, page := range []struct {
		name   string
		offset int32
	}{{name: "first-page"}, {name: "deepest-page", offset: 980}} {
		plan := explainStarPage(t, ctx, pool, db.ListStarredComponentsParams{
			Locale: "en-US", ActorID: actor, SizeDimensionCount: 3,
			SizeA: 1, SizeB: 2, SizeC: 3, PageOffset: page.offset, PageSize: 20,
		})
		if strings.Contains(plan, "Seq Scan on component_stars") {
			t.Fatalf("%s plan did not use the actor relationship index:\n%s", page.name, plan)
		}
		if strings.Contains(plan, "Seq Scan on component_versions") {
			t.Fatalf("%s plan scanned all Versions instead of probing page candidates:\n%s", page.name, plan)
		}
		if strings.Contains(plan, "Seq Scan on components") {
			t.Fatalf("%s plan scanned the complete Component relation instead of probing actor candidates:\n%s", page.name, plan)
		}
		t.Logf("%s plan:\n%s", page.name, plan)
		t.Logf("star-%s %s", page.name, explainTiming(plan))
	}

	var version, sharedBuffers, workMem, effectiveCacheSize string
	if err := pool.QueryRow(ctx, "SHOW server_version").Scan(&version); err != nil {
		t.Fatal(err)
	}
	if err := pool.QueryRow(ctx, "SHOW shared_buffers").Scan(&sharedBuffers); err != nil {
		t.Fatal(err)
	}
	if err := pool.QueryRow(ctx, "SHOW work_mem").Scan(&workMem); err != nil {
		t.Fatal(err)
	}
	if err := pool.QueryRow(ctx, "SHOW effective_cache_size").Scan(&effectiveCacheSize); err != nil {
		t.Fatal(err)
	}
	t.Logf("PostgreSQL %s; shared_buffers=%s work_mem=%s effective_cache_size=%s; plans are warm-cache local evidence",
		version, sharedBuffers, workMem, effectiveCacheSize)
}

func seedStarSizePlanEnvelope(t *testing.T, ctx context.Context, pool *pgxpool.Pool) {
	t.Helper()
	_, err := pool.Exec(ctx, `
		INSERT INTO component_repo.artifacts (
			id, owner_id, artifact_type, source_kind, original_filename,
			storage_provider, storage_bucket, storage_key, sha256, file_size,
			mime_type, verification_status, verified_at, uploaded_by
		) VALUES (
			'15000000-0000-0000-0000-000000000010',
			'15000000-0000-0000-0000-000000000002', 'component_source', 'source', 'perf.ldr',
			'test', 'test', 'star-size/perf.ldr', repeat('a',64), 1,
			'text/plain', 'verified', now(), '15000000-0000-0000-0000-000000000002'
		);
		INSERT INTO component_repo.upload_sessions (
			id, owner_id, status, locale, timezone, created_by, expires_at, completed_at
		) VALUES (
			'15000000-0000-0000-0000-000000000013',
			'15000000-0000-0000-0000-000000000002', 'completed', 'en-US', 'UTC',
			'15000000-0000-0000-0000-000000000002', now() + interval '1 hour', now()
		);
		INSERT INTO component_repo.tasks (
			id, owner_id, task_type, payload, locale, timezone, created_by
		) VALUES
			(
				'15000000-0000-0000-0000-000000000014',
				'15000000-0000-0000-0000-000000000002', 'component.artifact.verify',
				'{"artifactId":"15000000-0000-0000-0000-000000000010"}', 'en-US', 'UTC',
				'15000000-0000-0000-0000-000000000002'
			),
			(
				'15000000-0000-0000-0000-000000000015',
				'15000000-0000-0000-0000-000000000002', 'component.import.parse',
				'{"importId":"15000000-0000-0000-0000-000000000011","parserVersion":"perf-v1"}',
				'en-US', 'UTC', '15000000-0000-0000-0000-000000000002'
			);
		INSERT INTO component_repo.task_dependencies (task_id, prerequisite_task_id, owner_id)
		VALUES (
			'15000000-0000-0000-0000-000000000015',
			'15000000-0000-0000-0000-000000000014',
			'15000000-0000-0000-0000-000000000002'
		);
		INSERT INTO component_repo.imports (
			id, owner_id, source_artifact_id, status, parser_version, locale, timezone, created_by,
			upload_session_id, parse_task_id
		) VALUES (
			'15000000-0000-0000-0000-000000000011',
			'15000000-0000-0000-0000-000000000002',
			'15000000-0000-0000-0000-000000000010', 'succeeded', 'perf-v1', 'en-US', 'UTC',
			'15000000-0000-0000-0000-000000000002',
			'15000000-0000-0000-0000-000000000013',
			'15000000-0000-0000-0000-000000000015'
		);
		INSERT INTO component_repo.scene_snapshots (
			id, import_id, schema_version, parser_version, document, bom, parse_issues
		) VALUES (
			'15000000-0000-0000-0000-000000000012',
			'15000000-0000-0000-0000-000000000011', 'perf-v1', 'perf-v1', '{}', '{}', '[]'
		);
		INSERT INTO component_repo.components (
			id, owner_id, content_kind, content_locale, name, status, created_by,
			current_logical_size_a, current_logical_size_b, current_logical_size_c
		)
		SELECT md5('star-size-component-' || item)::uuid,
		       CASE WHEN item % 10 = 0 THEN NULL ELSE '15000000-0000-0000-0000-000000000002'::uuid END,
		       CASE WHEN item % 10 = 0 THEN 'official' ELSE 'user' END, 'en-US',
		       'Star size ' || item, 'active', '15000000-0000-0000-0000-000000000002',
		       CASE WHEN item % 100 = 0 THEN 4 ELSE 1 END,
		       CASE WHEN item % 100 = 0 THEN 5 ELSE 2 END,
		       CASE WHEN item % 100 = 0 THEN 6 ELSE 3 END
		FROM generate_series(1, 1000) item;
		-- 性能 fixture 只验证 Star 查询的 actor 候选、翻译和分页形状，不为 900 个 user Component 重建导入来源链。
		-- 临时停用来源完整性触发器，并在批量 Version 写入后立即恢复；生产迁移与运行时约束不受影响。
		ALTER TABLE component_repo.component_versions DISABLE TRIGGER component_versions_require_source_integrity;
		INSERT INTO component_repo.component_versions (
			id, component_id, version_label, status, source_artifact_id, scene_snapshot_id,
			parser_version, interface_signature, structure_hash, geometry_hash, created_by, published_at
		)
		SELECT md5('star-size-version-' || item)::uuid,
		       md5('star-size-component-' || item)::uuid, '1.0.0', 'published',
		       '15000000-0000-0000-0000-000000000010',
		       '15000000-0000-0000-0000-000000000012', 'perf-v1',
		       repeat('1',64), repeat('2',64), repeat('3',64),
		       '15000000-0000-0000-0000-000000000002', now()
		FROM generate_series(1, 1000) item;
		ALTER TABLE component_repo.component_versions ENABLE TRIGGER component_versions_require_source_integrity;
		UPDATE component_repo.components component
		SET current_version_id = md5('star-size-version-' || item)::uuid
		FROM generate_series(1, 1000) item
		WHERE component.id = md5('star-size-component-' || item)::uuid;
		INSERT INTO component_repo.component_translations (
			component_id, locale, name, translation_status, reviewed_by, reviewed_at
		)
		SELECT md5('star-size-component-' || item)::uuid, 'zh-CN', '收藏翻译 ' || item,
		       'reviewed', '15000000-0000-0000-0000-000000000002', now()
		FROM generate_series(10, 1000, 10) item;
		INSERT INTO component_repo.component_stars (actor_id, component_id, starred_at)
		SELECT CASE WHEN actor = 1
		            THEN '15000000-0000-0000-0000-000000000001'::uuid
		            ELSE md5('star-size-actor-' || actor)::uuid END,
		       md5('star-size-component-' || item)::uuid,
		       now() - make_interval(secs => item)
		FROM generate_series(1, 1000) actor
		CROSS JOIN generate_series(1, 1000) item;
		-- 额外 Component 让 actor 的 1,000 条 Star 只是全目录的小候选集，防止小表计划掩盖反向全表驱动。
		INSERT INTO component_repo.components (
			id, content_kind, content_locale, name, status, created_by
		)
		SELECT md5('star-size-unrelated-component-' || item)::uuid,
		       'official', 'en-US', 'Unrelated Star size ' || item, 'archived',
		       '15000000-0000-0000-0000-000000000002'
		FROM generate_series(1001, 100000) item;
		ANALYZE component_repo.component_stars;
		ANALYZE component_repo.components;
		ANALYZE component_repo.component_versions;
		ANALYZE component_repo.component_translations;
	`)
	if err != nil {
		t.Fatalf("seed Star size capacity envelope: %v", err)
	}
}

func explainStarPage(t *testing.T, ctx context.Context, pool *pgxpool.Pool, params db.ListStarredComponentsParams) string {
	t.Helper()
	data, err := os.ReadFile("../../db/queries/component_stars.sql")
	if err != nil {
		t.Fatalf("read authoritative Star SQL: %v", err)
	}
	_, querySQL, ok := strings.Cut(string(data), "-- name: ListStarredComponents :many")
	if !ok {
		t.Fatal("authoritative Star list query not found")
	}
	querySQL = strings.NewReplacer(
		"sqlc.arg(actor_id)", "$1", "sqlc.arg(locale)", "$2",
		"sqlc.arg(category_filter)", "$3", "sqlc.arg(search_query)", "$4",
		"sqlc.arg(size_dimension_count)", "$5", "sqlc.arg(size_a)", "$6",
		"sqlc.arg(size_b)", "$7", "sqlc.arg(size_c)", "$8",
		"sqlc.arg(page_offset)", "$9", "sqlc.arg(page_size)", "$10",
	).Replace(querySQL)
	return collectExplain(t, ctx, pool, "EXPLAIN (ANALYZE, BUFFERS, SETTINGS)\n"+querySQL,
		params.ActorID, params.Locale, params.CategoryFilter, params.SearchQuery,
		params.SizeDimensionCount, params.SizeA, params.SizeB, params.SizeC,
		params.PageOffset, params.PageSize)
}

func collectExplain(t *testing.T, ctx context.Context, pool *pgxpool.Pool, query string, args ...any) string {
	t.Helper()
	rows, err := pool.Query(ctx, query, args...)
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
