//go:build integration

package db

import (
	"context"
	"os"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const partSearchPlanLibraryID = "25000000-0000-0000-0000-000000000001"

// TestZZPartSearchQueryPlanEnvelope 用当前 Studio snapshot 的 24,426 条规划规模验证描述、尺寸和深页查询形状；
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
		{name: "selective-part-number", partNumber: "part-024425"},
		{name: "high-match-description", descriptionTokens: []string{"plate"}, phrase: "plate"},
		{name: "selective-exact-size", hasWidth: true, hasDepth: true, hasHeight: true, width: 2, depth: 4, height: 1},
		{name: "deepest-supported-page", offset: 24_406},
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
		if scenario.hasWidth && !strings.Contains(plan, "part_geometries_exact_logical_size_idx") {
			t.Fatalf("%s did not use the exact logical-size index:\n%s", scenario.name, plan)
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
	t.Logf("PostgreSQL %s; shared_buffers=%s work_mem=%s effective_cache_size=%s; 24,426 Parts; warm-cache local evidence",
		version, sharedBuffers, workMem, effectiveCacheSize)
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
		FROM generate_series(1, 24426) item;
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
		       CASE WHEN item % 100 = 0 THEN 2 ELSE 1 END,
		       CASE WHEN item % 100 = 0 THEN 4 ELSE 2 END,
		       CASE WHEN item % 10 = 0 THEN 1 ELSE 3 END,
		       24, 8, 'ready',
		       CASE WHEN item % 20 = 1 THEN 'derived_approximate' ELSE 'derived_exact' END
		FROM generate_series(1, 24426) item;
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
