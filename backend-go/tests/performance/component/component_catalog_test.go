//go:build integration

package component_test

import (
	"context"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

// TestZZZComponentCatalogQueryPlanEnvelope 用十万条 Component 验证目录首屏、筛选和深游标的执行边界。
func TestZZZComponentCatalogQueryPlanEnvelope(t *testing.T) {
	if os.Getenv("RUN_COMPONENT_LIST_PLAN_TEST") != "1" {
		t.Skip("set RUN_COMPONENT_LIST_PLAN_TEST=1 to run the Component catalog plan gate")
	}
	databaseURL := os.Getenv("TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("TEST_DATABASE_URL is required")
	}
	ctx := context.Background()
	poolConfig, err := pgxpool.ParseConfig(databaseURL)
	if err != nil {
		t.Fatal(err)
	}
	// 性能 fixture 使用多条 DDL/DML 的隔离批次，显式 simple protocol 仅作用于该临时测试连接。
	poolConfig.ConnConfig.DefaultQueryExecMode = pgx.QueryExecModeSimpleProtocol
	pool, err := pgxpool.NewWithConfig(ctx, poolConfig)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	resetComponentRepo(t, pool)
	seedComponentCatalogPlanEnvelope(t, ctx, pool)

	actor := mustUUID(t, "18000000-0000-0000-0000-000000000001")
	firstTime := time.Date(9999, 12, 31, 23, 59, 59, 0, time.UTC)
	firstID := mustUUID(t, "ffffffff-ffff-ffff-ffff-ffffffffffff")
	exactIDText := ""
	if err := pool.QueryRow(ctx, `SELECT md5('catalog-component-50000')::uuid::text`).Scan(&exactIDText); err != nil {
		t.Fatal(err)
	}
	exactID, err := uuidutil.Parse(exactIDText)
	if err != nil {
		t.Fatal(err)
	}

	for _, scenario := range []struct {
		name, locale, query, category, status string
		hasExact                              bool
		exact                                 pgtype.UUID
	}{
		{name: "unfiltered", locale: "en-US"},
		{name: "selective-category", locale: "en-US", category: "vehicle"},
		{name: "selective-name", locale: "en-US", query: "Catalog item 89999"},
		{name: "high-match-name", locale: "en-US", query: "Catalog item"},
		{name: "reviewed-translation-selective", locale: "zh-CN", query: "目录翻译 89980"},
		{name: "reviewed-translation-high", locale: "zh-CN", query: "目录翻译"},
		{name: "exact-id", locale: "en-US", hasExact: true, exact: exactID},
	} {
		// 第一次只用于填充本机缓存；第二次计划用于审查执行节点，计时不代表生产 SLO。
		_ = explainComponentCatalog(t, ctx, pool, actor, firstTime, firstID, scenario.locale,
			scenario.query, scenario.category, scenario.status, scenario.hasExact, scenario.exact)
		plan := explainComponentCatalog(t, ctx, pool, actor, firstTime, firstID, scenario.locale,
			scenario.query, scenario.category, scenario.status, scenario.hasExact, scenario.exact)
		assertComponentCatalogPlan(t, scenario.name, plan)
		if scenario.name == "selective-name" &&
			!strings.Contains(plan, "components_name_trgm_idx") && !strings.Contains(plan, "components_id_text_trgm_idx") {
			t.Fatalf("selective source search did not use a trigram index:\n%s", plan)
		}
		if scenario.name == "reviewed-translation-selective" &&
			!strings.Contains(plan, "component_translations_reviewed_name_trgm_idx") {
			t.Fatalf("reviewed translation search did not use its trigram index:\n%s", plan)
		}
		if scenario.name == "unfiltered" && planExecutesNode(plan, "Seq Scan on component_translations") {
			t.Fatalf("unfiltered catalog executed the optional translation search source:\n%s", plan)
		}
		t.Logf("component-catalog-%s %s", scenario.name, explainTiming(plan))
	}

	var deepTime time.Time
	var deepID pgtype.UUID
	if err := pool.QueryRow(ctx, `
		SELECT component.updated_at, component.id
		FROM component_repo.component_catalog_projection component
		WHERE (component.owner_id=$1 AND component.version_available)
		   OR (component.owner_id IS DISTINCT FROM $1 AND component.status='active' AND component.public_version_available)
		ORDER BY component.updated_at DESC, component.id DESC
		OFFSET 80000 LIMIT 1`, actor).Scan(&deepTime, &deepID); err != nil {
		t.Fatalf("read deep Component cursor: %v", err)
	}
	deepPlan := explainComponentCatalog(t, ctx, pool, actor, deepTime, deepID, "en-US", "", "", "", false, pgtype.UUID{})
	assertComponentCatalogPlan(t, "deep-cursor", deepPlan)
	if strings.Contains(deepPlan, "Rows Removed by Filter: 80000") {
		t.Fatalf("deep cursor skipped prior rows instead of entering an index condition:\n%s", deepPlan)
	}
	t.Logf("component-catalog-deep-cursor %s", explainTiming(deepPlan))

	emptyActor := mustUUID(t, "18000000-0000-0000-0000-000000000999")
	emptyPlan := explainComponentCatalog(t, ctx, pool, emptyActor, firstTime, firstID, "en-US", "", "", "", false, pgtype.UUID{})
	assertComponentCatalogPlan(t, "empty-actor", emptyPlan)
	t.Logf("component-catalog-empty-actor %s", explainTiming(emptyPlan))

	var total, active, official, reviewed int64
	if err := pool.QueryRow(ctx, `
		SELECT count(*), count(*) FILTER (WHERE status='active'),
		       count(*) FILTER (WHERE content_kind='official')
		FROM component_repo.components WHERE name LIKE 'Catalog item %'`).Scan(&total, &active, &official); err != nil {
		t.Fatal(err)
	}
	if err := pool.QueryRow(ctx, `SELECT count(*) FROM component_repo.component_reviewed_translations`).Scan(&reviewed); err != nil {
		t.Fatal(err)
	}
	if total != 100_000 || active != 90_000 || official != 10_000 || reviewed != 5_000 {
		t.Fatalf("unexpected catalog dataset: total=%d active=%d official=%d reviewed=%d", total, active, official, reviewed)
	}
	var version, sharedBuffers, workMem, effectiveCacheSize string
	for setting, target := range map[string]*string{
		"server_version": &version, "shared_buffers": &sharedBuffers,
		"work_mem": &workMem, "effective_cache_size": &effectiveCacheSize,
	} {
		if err := pool.QueryRow(ctx, "SHOW "+setting).Scan(target); err != nil {
			t.Fatal(err)
		}
	}
	t.Logf("PostgreSQL %s; shared_buffers=%s work_mem=%s effective_cache_size=%s; warm-cache local plan evidence",
		version, sharedBuffers, workMem, effectiveCacheSize)
}

func seedComponentCatalogPlanEnvelope(t *testing.T, ctx context.Context, pool *pgxpool.Pool) {
	t.Helper()
	actor := mustUUID(t, "18000000-0000-0000-0000-000000000001")
	_, err := pool.Exec(ctx, `
		INSERT INTO component_repo.components (
			id, owner_id, content_kind, content_locale, name, category, status, created_by, updated_at,
			logical_width_stud, logical_depth_stud, logical_height_plate,
			current_logical_size_a, current_logical_size_b, current_logical_size_c,
			version_available, public_version_available
		)
		SELECT md5('catalog-component-' || item)::uuid,
		       CASE WHEN item % 10 = 0 THEN NULL
		            WHEN item <= 1111 THEN $1::uuid
		            ELSE md5('catalog-owner-' || (item % 20))::uuid END,
		       CASE WHEN item % 10 = 0 THEN 'official' ELSE 'user' END,
		       'en-US', 'Catalog item ' || item,
		       CASE WHEN item % 1000 = 0 THEN 'vehicle' ELSE 'building' END,
		       CASE WHEN item <= 90000 THEN 'active' ELSE 'archived' END,
		       $1, '2026-09-13 00:00:00+00'::timestamptz - make_interval(secs => item),
		       2, 4, 3, 2, 3, 4, true, true
		FROM generate_series(1, 100000) item;

		INSERT INTO component_repo.component_translations (
			component_id, locale, name, tags, translation_status, reviewed_by, reviewed_at
		)
		SELECT md5('catalog-component-' || item)::uuid, 'zh-CN', '目录翻译 ' || item, ARRAY[]::text[],
		       CASE WHEN item % 20 = 0 THEN 'reviewed' ELSE 'draft' END,
		       CASE WHEN item % 20 = 0 THEN $1::uuid END,
		       CASE WHEN item % 20 = 0 THEN now() END
		FROM generate_series(10, 100000, 10) item;
		ANALYZE component_repo.components;
		ANALYZE component_repo.component_translations;`, actor)
	if err != nil {
		t.Fatalf("seed Component catalog capacity envelope: %v", err)
	}
}

func explainComponentCatalog(
	t *testing.T, ctx context.Context, pool *pgxpool.Pool,
	actor pgtype.UUID, cursorTime time.Time, cursorID pgtype.UUID,
	locale, query, category, status string, hasExact bool, exactID pgtype.UUID,
) string {
	t.Helper()
	data, err := os.ReadFile("../../../db/queries/components.sql")
	if err != nil {
		t.Fatalf("read authoritative Component SQL: %v", err)
	}
	_, querySQL, ok := strings.Cut(string(data), "-- name: ListVisibleComponents :many")
	if !ok {
		t.Fatal("authoritative Component list query not found")
	}
	querySQL, _, ok = strings.Cut(querySQL, "-- name: UpdateOwnedComponent :one")
	if !ok {
		t.Fatal("authoritative Component list query end not found")
	}
	querySQL = strings.NewReplacer(
		"sqlc.arg(locale)", "$1", "sqlc.arg(actor_id)", "$2",
		"sqlc.narg(cursor_updated_at)", "$3", "sqlc.narg(cursor_component_id)", "$4",
		"sqlc.arg(status_filter)", "$5", "sqlc.arg(category_filter)", "$6",
		"sqlc.arg(has_search_component_id)", "$7", "sqlc.narg(search_component_id)", "$8",
		"sqlc.arg(search_query)", "$9", "sqlc.arg(page_size)", "$10",
	).Replace(querySQL)
	return collectExplain(t, ctx, pool, "EXPLAIN (ANALYZE, BUFFERS, SETTINGS)\n"+querySQL,
		locale, actor, cursorTime, cursorID, status, category, hasExact, exactID, query, int32(21))
}

func assertComponentCatalogPlan(t *testing.T, name, plan string) {
	t.Helper()
	t.Logf("%s full Component catalog plan:\n%s", name, plan)
	for _, line := range strings.Split(plan, "\n") {
		if strings.Contains(line, "(never executed)") {
			continue
		}
		// 高命中搜索允许规划器在 100k 包络内选择顺序扫描；选择性与无筛选路径必须使用索引。
		if strings.Contains(line, "Seq Scan on components") && !strings.Contains(name, "high") {
			t.Fatalf("%s scanned the complete Component relation:\n%s", name, plan)
		}
		if strings.Contains(line, "Seq Scan on component_versions") {
			t.Fatalf("%s scanned the complete Version relation for per-Component eligibility:\n%s", name, plan)
		}
	}
	if strings.Contains(plan, "Sort Method: external") || strings.Contains(plan, "temp read=") || strings.Contains(plan, "temp written=") {
		t.Fatalf("%s spilled Component paging to temporary storage:\n%s", name, plan)
	}
	if !strings.Contains(plan, "Limit") {
		t.Fatalf("%s did not fix the page before enrichment:\n%s", name, plan)
	}
}

func planExecutesNode(plan, node string) bool {
	for _, line := range strings.Split(plan, "\n") {
		if strings.Contains(line, node) && !strings.Contains(line, "(never executed)") {
			return true
		}
	}
	return false
}
