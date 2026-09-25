//go:build integration

package partsearch_test

import (
	"context"
	"os"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const partSearchPlanLibraryID = "25000000-0000-0000-0000-000000000001"

// TestZZPartSearchQueryPlanEnvelope 用当前 Studio snapshot 的 24,954 条规划规模验证描述、标称/bbox 尺寸和深页查询形状；
// 该门禁只在显式开启时运行，输出的本机 warm-cache 时间不得解释为生产 SLO。
func TestZZPartSearchQueryPlanEnvelope(t *testing.T) {
	if os.Getenv("RUN_PART_SEARCH_PLAN_TEST") != "1" {
		t.Skip("set RUN_PART_SEARCH_PLAN_TEST=1 to run the Part Search plan gate")
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
	seedPartSearchPlanEnvelope(t, ctx, pool)
	searchParts := loadGeneratedQuery(t, "searchParts")
	countSearchableParts := loadGeneratedQuery(t, "countSearchableParts")

	for _, scenario := range []struct {
		name              string
		descriptionTokens []string
		partNumber        string
		hasWidth          bool
		hasDepth          bool
		hasHeight         bool
		width             float64
		depth             float64
		height            float64
		phrase            string
		offset            int32
	}{
		{name: "unfiltered-first-page"},
		{name: "selective-part-number", partNumber: "part-024953"},
		{name: "high-match-description", descriptionTokens: []string{"plate"}, phrase: "plate"},
		{name: "selective-nominal-size", hasWidth: true, hasDepth: true, hasHeight: true, width: 2, depth: 4, height: 1},
		{name: "selective-bbox-size", hasWidth: true, hasDepth: true, hasHeight: true, width: 7.3, depth: 5.4, height: 2.7},
		{name: "deepest-supported-page", offset: 24_934},
	} {
		descriptionPatterns := make([]string, 0, len(scenario.descriptionTokens))
		for _, token := range scenario.descriptionTokens {
			descriptionPatterns = append(descriptionPatterns, "%"+token+"%")
		}
		args := []any{
			"part-preview-ldraw-meshopt-glb-v2", partSearchPlanLibraryID, "en-US", scenario.phrase,
			descriptionPatterns, scenario.partNumber,
			scenario.hasWidth, scenario.hasDepth, scenario.hasHeight,
			scenario.width, scenario.depth, scenario.height,
			scenario.offset, int32(20),
		}
		// 先执行一次再采集计划，减少首次编译与磁盘读取对查询形状判断的干扰。
		if _, err := pool.Exec(ctx, searchParts, args...); err != nil {
			t.Fatalf("warm %s Part Search: %v", scenario.name, err)
		}
		plan := explainPartSearch(t, ctx, pool, searchParts, args...)
		spilled := strings.Contains(plan, "Sort Method: external") || strings.Contains(plan, "temp read=") || strings.Contains(plan, "temp written=")
		if spilled && scenario.name != "deepest-supported-page" {
			t.Fatalf("%s Part Search spilled to temporary storage:\n%s", scenario.name, plan)
		}
		if scenario.hasWidth && !strings.Contains(plan, "part_geometries_searchable_logical_size_idx") {
			t.Fatalf("%s did not use the searchable logical-size index:\n%s", scenario.name, plan)
		}
		if !strings.Contains(plan, "part_library_version_id") {
			t.Fatalf("%s did not retain the snapshot scope in its plan:\n%s", scenario.name, plan)
		}
		t.Logf("%s plan:\n%s", scenario.name, plan)
	}

	countArgs := []any{partSearchPlanLibraryID, []string{"%plate%"}, "", false, false, false, 0.0, 0.0, 0.0, "en-US"}
	countPlan := explainPartSearch(t, ctx, pool, countSearchableParts, countArgs...)
	if strings.Contains(countPlan, "temp read=") || strings.Contains(countPlan, "temp written=") {
		t.Fatalf("high-match exact count spilled to temporary storage:\n%s", countPlan)
	}
	t.Logf("high-match exact-count plan:\n%s", countPlan)

	var version, sharedBuffers, workMem, effectiveCacheSize string
	for query, destination := range map[string]*string{
		"SHOW server_version": &version, "SHOW shared_buffers": &sharedBuffers,
		"SHOW work_mem": &workMem, "SHOW effective_cache_size": &effectiveCacheSize,
	} {
		if err := pool.QueryRow(ctx, query).Scan(destination); err != nil {
			t.Fatal(err)
		}
	}
	t.Logf("PostgreSQL %s; shared_buffers=%s work_mem=%s effective_cache_size=%s; 24,954 Parts; warm-cache local evidence",
		version, sharedBuffers, workMem, effectiveCacheSize)
}

// TestZZLivePartSearchQueryPlanEnvelope 只读核对显式指定的真实 active snapshot；它不会造数、清表或改变业务数据。
// 该门禁用于部署验收，连接目标与 library ID 必须由操作者显式提供，输出时间只代表当次远程开发库观测值。
func TestZZLivePartSearchQueryPlanEnvelope(t *testing.T) {
	if os.Getenv("RUN_LIVE_PART_SEARCH_PLAN_TEST") != "1" {
		t.Skip("set RUN_LIVE_PART_SEARCH_PLAN_TEST=1 to run the live Part Search plan gate")
	}
	databaseURL := os.Getenv("DATABASE_URL")
	libraryID := os.Getenv("LIVE_PART_SEARCH_LIBRARY_ID")
	if databaseURL == "" || libraryID == "" {
		t.Fatal("DATABASE_URL and LIVE_PART_SEARCH_LIBRARY_ID are required")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	searchParts := loadGeneratedQuery(t, "searchParts")
	countSearchableParts := loadGeneratedQuery(t, "countSearchableParts")

	for _, scenario := range []struct {
		name              string
		locale            string
		descriptionTokens []string
		partNumber        string
		hasWidth          bool
		hasDepth          bool
		hasHeight         bool
		width             float64
		depth             float64
		height            float64
		phrase            string
		offset            int32
	}{
		{name: "unfiltered-first-page", locale: "en-US"},
		{name: "selective-part-number", locale: "en-US", partNumber: "3001"},
		{name: "high-match-description", locale: "en-US", descriptionTokens: []string{"plate"}, phrase: "plate"},
		{name: "combined-zh-fallback", locale: "zh-CN", descriptionTokens: []string{"plate"}, hasWidth: true, hasDepth: true, hasHeight: true, width: 2, depth: 4, height: 1, phrase: "plate"},
		{name: "selective-nominal-size", locale: "en-US", hasWidth: true, hasDepth: true, hasHeight: true, width: 2, depth: 4, height: 1},
		{name: "selective-bbox-size", locale: "en-US", hasWidth: true, hasDepth: true, hasHeight: true, width: 5.8, depth: 1, height: 0.031},
		{name: "deepest-supported-page", locale: "en-US", offset: 24_879},
	} {
		descriptionPatterns := make([]string, 0, len(scenario.descriptionTokens))
		for _, token := range scenario.descriptionTokens {
			descriptionPatterns = append(descriptionPatterns, "%"+token+"%")
		}
		args := []any{
			"part-preview-ldraw-meshopt-glb-v2", libraryID, scenario.locale, scenario.phrase,
			descriptionPatterns, scenario.partNumber,
			scenario.hasWidth, scenario.hasDepth, scenario.hasHeight,
			scenario.width, scenario.depth, scenario.height,
			scenario.offset, int32(20),
		}
		if _, err := pool.Exec(ctx, searchParts, args...); err != nil {
			t.Fatalf("warm %s live Part Search: %v", scenario.name, err)
		}
		plan := explainPartSearch(t, ctx, pool, searchParts, args...)
		// 托管库的 work_mem 与本地 fixture 不同；部署门禁记录真实 spill，而是否接受由容量包络和 PERF 清理项判断。
		spilled := strings.Contains(plan, "Sort Method: external") || strings.Contains(plan, "temp read=") || strings.Contains(plan, "temp written=")
		t.Logf("%s live plan spilled=%t", scenario.name, spilled)
		if scenario.hasWidth && !strings.Contains(plan, "part_geometries_searchable_logical_size_idx") {
			t.Fatalf("%s live Part Search did not use the searchable logical-size index:\n%s", scenario.name, plan)
		}
		t.Logf("%s live plan:\n%s", scenario.name, plan)
	}

	countArgs := []any{libraryID, []string{"%plate%"}, "", false, false, false, 0.0, 0.0, 0.0, "en-US"}
	countPlan := explainPartSearch(t, ctx, pool, countSearchableParts, countArgs...)
	if strings.Contains(countPlan, "temp read=") || strings.Contains(countPlan, "temp written=") {
		t.Fatalf("live high-match exact count spilled to temporary storage:\n%s", countPlan)
	}
	t.Logf("live high-match exact-count plan:\n%s", countPlan)

	var version, sharedBuffers, workMem, effectiveCacheSize string
	for query, destination := range map[string]*string{
		"SHOW server_version": &version, "SHOW shared_buffers": &sharedBuffers,
		"SHOW work_mem": &workMem, "SHOW effective_cache_size": &effectiveCacheSize,
	} {
		if err := pool.QueryRow(ctx, query).Scan(destination); err != nil {
			t.Fatal(err)
		}
	}
	t.Logf("PostgreSQL %s; shared_buffers=%s work_mem=%s effective_cache_size=%s; live library=%s; warm-cache remote evidence",
		version, sharedBuffers, workMem, effectiveCacheSize, libraryID)
}

// loadGeneratedQuery 从 sqlc 产物读取实际执行 SQL，使性能门禁验证生成后的查询且不修改生成文件。
func loadGeneratedQuery(t *testing.T, name string) string {
	t.Helper()
	source, err := os.ReadFile("../../../db/generated/parts.sql.go")
	if err != nil {
		t.Fatal(err)
	}
	prefix := "const " + name + " = `"
	start := strings.Index(string(source), prefix)
	if start < 0 {
		t.Fatalf("generated query %s not found", name)
	}
	remainder := string(source)[start+len(prefix):]
	end := strings.Index(remainder, "`")
	if end < 0 {
		t.Fatalf("generated query %s is not terminated", name)
	}
	return remainder[:end]
}

func seedPartSearchPlanEnvelope(t *testing.T, ctx context.Context, pool *pgxpool.Pool) {
	t.Helper()
	_, err := pool.Exec(ctx, `
		TRUNCATE component_repo.part_library_versions CASCADE;
		INSERT INTO component_repo.part_library_versions (
			id, source_name, source_hash, connector_count, status, created_by, preview_ready
		) VALUES (
			$1::uuid, 'part-search-plan', repeat('a', 64), 0, 'active',
			'25000000-0000-0000-0000-000000000002'::uuid, true
		);
		ALTER TABLE component_repo.parts DISABLE TRIGGER parts_create_preview_state;
		INSERT INTO component_repo.parts (
			part_library_version_id, ldraw_part_num, source_name, content_locale
		)
		SELECT $1::uuid,
		       'part-' || lpad(item::text, 6, '0') || '.dat',
		       CASE WHEN item % 10 = 0 THEN 'Plate 2 x 4 sample ' || item ELSE 'Brick 2 x 4 sample ' || item END,
		       'en-US'
		FROM generate_series(1, 24954) item;
		ALTER TABLE component_repo.parts ENABLE TRIGGER parts_create_preview_state;
		INSERT INTO component_repo.part_geometries (
			part_library_version_id, ldraw_part_num, source_relative_path, source_file_hash,
			bbox_min, bbox_max, logical_width_stud, logical_depth_stud, logical_height_plate,
			vertex_count, face_count, geometry_status, logical_size_derivation_status
		)
		SELECT $1::uuid,
		       'part-' || lpad(item::text, 6, '0') || '.dat',
		       'parts/part-' || lpad(item::text, 6, '0') || '.dat', repeat('b', 64),
		       ARRAY[0,0,0]::float8[], ARRAY[40,8,80]::float8[],
		       CASE WHEN item % 20 = 1 THEN 7.3 WHEN item % 100 = 0 THEN 2 ELSE 1 END,
		       CASE WHEN item % 20 = 1 THEN 5.4 WHEN item % 100 = 0 THEN 4 ELSE 2 END,
		       CASE WHEN item % 20 = 1 THEN 2.7 WHEN item % 10 = 0 THEN 1 ELSE 3 END,
		       24, 8, 'ready',
		       CASE WHEN item % 20 = 1 THEN 'derived_approximate' ELSE 'derived_exact' END
		FROM generate_series(1, 24954) item;
		INSERT INTO component_repo.part_translations (
			part_library_version_id, ldraw_part_num, locale, name,
			translation_status, reviewed_by, reviewed_at
		)
		SELECT $1::uuid, 'part-' || lpad(item::text, 6, '0') || '.dat', 'zh-CN',
		       '计划零件 ' || item, 'reviewed',
		       '25000000-0000-0000-0000-000000000002'::uuid, now()
		FROM generate_series(1000, 24000, 1000) item;
		ANALYZE component_repo.parts;
		ANALYZE component_repo.part_geometries;
		ANALYZE component_repo.part_translations;
	`, pgx.QueryExecModeSimpleProtocol, partSearchPlanLibraryID)
	if err != nil {
		t.Fatal(err)
	}
}

func explainPartSearch(t *testing.T, ctx context.Context, pool *pgxpool.Pool, query string, args ...any) string {
	t.Helper()
	rows, err := pool.Query(ctx, "EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT TEXT) "+query, args...)
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
