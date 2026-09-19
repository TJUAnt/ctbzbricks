//go:build integration

package workbench

import (
	"context"
	"os"
	"strconv"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"
)

// TestZZVersionPartsPreviewPlanEnvelope 验证 BOM 固定候选后才点查名称、几何和 ready Preview。
func TestZZVersionPartsPreviewPlanEnvelope(t *testing.T) {
	if os.Getenv("RUN_VERSION_PARTS_PLAN_TEST") != "1" {
		t.Skip("set RUN_VERSION_PARTS_PLAN_TEST=1 to run the Version Parts plan gate")
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
	seedVersionPartsPlanEnvelope(t, ctx, pool)

	refs := make([]string, 1_000)
	for index := range refs {
		refs[index] = partPlanNumber(index + 1)
	}
	for _, scenario := range []struct {
		name       string
		readyCount int
	}{
		{name: "no-preview"},
		{name: "partial-preview", readyCount: 500},
		{name: "all-preview", readyCount: 1_000},
	} {
		if scenario.readyCount > 0 {
			markVersionPartsPlanPreviewsReady(t, ctx, pool, scenario.readyCount)
		}
		plan := explainVersionParts(t, ctx, pool, refs)
		assertVersionPartsPlan(t, scenario.name, plan)
		t.Logf("%s plan:\n%s", scenario.name, plan)
	}

	missingRefs := make([]string, 1_000)
	for index := range missingRefs {
		missingRefs[index] = partPlanNumber(24_001 + index)
	}
	missingPlan := explainVersionParts(t, ctx, pool, missingRefs)
	assertVersionPartsPlan(t, "missing-parts", missingPlan)
	t.Logf("missing-parts plan:\n%s", missingPlan)

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

func seedVersionPartsPlanEnvelope(t *testing.T, ctx context.Context, pool *pgxpool.Pool) {
	t.Helper()
	_, err := pool.Exec(ctx, `
		INSERT INTO component_repo.part_library_versions (
			id, source_name, source_hash, connector_count, status, created_by
		) VALUES (
			'19000000-0000-0000-0000-000000000001', 'Version Parts plan', repeat('1',64), 0,
			'retired', '19000000-0000-0000-0000-000000000002'
		);
		INSERT INTO component_repo.parts (
			part_library_version_id, ldraw_part_num, source_name, content_locale
		)
		SELECT '19000000-0000-0000-0000-000000000001',
		       'plan-' || lpad(item::text, 5, '0') || '.dat', 'Plan Part ' || item, 'en-US'
		FROM generate_series(1, 24000) item;
		INSERT INTO component_repo.part_geometries (
			part_library_version_id, ldraw_part_num, source_relative_path, source_file_hash,
			bbox_min, bbox_max, logical_width_stud, logical_depth_stud, logical_height_plate,
			vertex_count, face_count
		)
		SELECT '19000000-0000-0000-0000-000000000001',
		       'plan-' || lpad(item::text, 5, '0') || '.dat',
		       'parts/plan-' || lpad(item::text, 5, '0') || '.dat', repeat('2',64),
		       ARRAY[0,0,0]::float8[], ARRAY[20,20,24]::float8[], 1, 1, 3, 8, 12
		FROM generate_series(1, 24000) item;
		INSERT INTO component_repo.part_translations (
			part_library_version_id, ldraw_part_num, locale, name, translation_status, reviewed_by, reviewed_at
		)
		SELECT '19000000-0000-0000-0000-000000000001',
		       'plan-' || lpad(item::text, 5, '0') || '.dat', 'zh-CN', '计划零件 ' || item,
		       'reviewed', '19000000-0000-0000-0000-000000000002', now()
		FROM generate_series(1, 1000) item;
		INSERT INTO component_repo.artifacts (
			id, artifact_type, source_kind, original_filename, storage_provider, storage_bucket,
			storage_key, sha256, file_size, mime_type, verification_status, verified_at, uploaded_by
		)
		SELECT md5('version-parts-plan-artifact-' || item)::uuid,
		       CASE WHEN item <= 1000 THEN 'part_preview_glb' ELSE 'component_preview_glb' END,
		       'derived', 'plan-' || item || '.glb', 'test', 'test', 'plan/' || item || '.glb',
		       md5(item::text) || md5('sha-' || item), 1024, 'model/gltf-binary', 'verified', now(),
		       '19000000-0000-0000-0000-000000000002'
		FROM generate_series(1, 24000) item;
		ANALYZE component_repo.parts;
		ANALYZE component_repo.part_geometries;
		ANALYZE component_repo.part_translations;
		ANALYZE component_repo.part_previews;
		ANALYZE component_repo.artifacts;
	`)
	if err != nil {
		t.Fatalf("seed Version Parts plan envelope: %v", err)
	}
}

func markVersionPartsPlanPreviewsReady(t *testing.T, ctx context.Context, pool *pgxpool.Pool, readyCount int) {
	t.Helper()
	_, err := pool.Exec(ctx, `
		UPDATE component_repo.part_previews preview
		SET status='ready', generator_version=$2,
		    artifact_id=md5('version-parts-plan-artifact-' || item)::uuid
		FROM generate_series(1, $1::integer) item
		WHERE preview.part_library_version_id='19000000-0000-0000-0000-000000000001'
		  AND preview.ldraw_part_num='plan-' || lpad(item::text, 5, '0') || '.dat'
	`, readyCount, PartPreviewGeneratorVersion)
	if err != nil {
		t.Fatalf("mark %d Version Parts previews ready: %v", readyCount, err)
	}
	if _, err := pool.Exec(ctx, `ANALYZE component_repo.part_previews`); err != nil {
		t.Fatalf("analyze Version Parts previews: %v", err)
	}
}

func explainVersionParts(t *testing.T, ctx context.Context, pool *pgxpool.Pool, refs []string) string {
	t.Helper()
	data, err := os.ReadFile("../../db/queries/workbench.sql")
	if err != nil {
		t.Fatalf("read authoritative Workbench SQL: %v", err)
	}
	_, query, ok := strings.Cut(string(data), "-- name: ListLocalizedParts :many")
	if !ok {
		t.Fatal("authoritative Version Parts enrichment query not found")
	}
	query = strings.NewReplacer(
		"sqlc.arg(ldraw_part_nums)", "$1",
		"sqlc.arg(part_library_version_id)", "$2",
		"sqlc.arg(locale)", "$3",
		"sqlc.arg(generator_version)", "$4",
	).Replace(query)
	rows, err := pool.Query(ctx, "EXPLAIN (ANALYZE, BUFFERS, SETTINGS)\n"+query,
		refs, "19000000-0000-0000-0000-000000000001", "zh-CN", PartPreviewGeneratorVersion)
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

func assertVersionPartsPlan(t *testing.T, name, plan string) {
	t.Helper()
	for _, relation := range []string{"parts", "part_geometries", "part_translations", "part_previews", "artifacts"} {
		if strings.Contains(plan, "Seq Scan on "+relation) {
			t.Fatalf("%s scanned the complete %s relation instead of probing fixed BOM candidates:\n%s", name, relation, plan)
		}
	}
	if strings.Contains(plan, "Sort Method: external") || strings.Contains(plan, "temp read=") || strings.Contains(plan, "temp written=") {
		t.Fatalf("%s spilled BOM enrichment to temporary storage:\n%s", name, plan)
	}
}

func partPlanNumber(value int) string {
	return "plan-" + leftPadFive(value) + ".dat"
}

func leftPadFive(value int) string {
	text := "00000" + strconv.Itoa(value)
	return text[len(text)-5:]
}
