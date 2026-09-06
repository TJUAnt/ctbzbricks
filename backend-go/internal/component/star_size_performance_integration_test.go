//go:build integration

package component

import (
	"context"
	"os"
	"strings"
	"testing"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/jackc/pgx/v5/pgtype"
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
		dimensionCount int32
		sizeA          float64
		sizeB          float64
		sizeC          float64
	}{
		{name: "unfiltered"},
		{name: "selective", dimensionCount: 3, sizeA: 4, sizeB: 5, sizeC: 6},
		{name: "high-match", dimensionCount: 3, sizeA: 1, sizeB: 2, sizeC: 3},
		{name: "zero-match", dimensionCount: 3, sizeA: 20, sizeB: 21, sizeC: 22},
	} {
		params := db.CountStarredComponentsParams{
			Locale: "en-US", ActorID: actor, SizeDimensionCount: scenario.dimensionCount,
			SizeA: scenario.sizeA, SizeB: scenario.sizeB, SizeC: scenario.sizeC,
		}
		if _, err := queries.CountStarredComponents(ctx, params); err != nil {
			t.Fatalf("warm %s Star count: %v", scenario.name, err)
		}
		plan := explainStarSizeCount(t, ctx, pool, actor, scenario.dimensionCount, scenario.sizeA, scenario.sizeB, scenario.sizeC)
		if strings.Contains(plan, "Seq Scan on component_stars") {
			t.Fatalf("%s plan did not start from the actor relationship index:\n%s", scenario.name, plan)
		}
		if strings.Contains(plan, "Seq Scan on component_versions") {
			t.Fatalf("%s plan scanned all Versions instead of probing actor candidates:\n%s", scenario.name, plan)
		}
		if scenario.dimensionCount != 0 && !strings.Contains(plan, "current_logical_size_a") {
			t.Fatalf("%s plan did not filter through the persisted projection:\n%s", scenario.name, plan)
		}
		t.Logf("%s plan:\n%s", scenario.name, plan)
	}
	emptyActor := mustUUID(t, "15000000-0000-0000-0000-000000000999")
	if _, err := queries.CountStarredComponents(ctx, db.CountStarredComponentsParams{
		Locale: "en-US", ActorID: emptyActor,
	}); err != nil {
		t.Fatalf("warm empty-actor Star count: %v", err)
	}
	emptyPlan := explainStarSizeCount(t, ctx, pool, emptyActor, 0, 0, 0, 0)
	if strings.Contains(emptyPlan, "Seq Scan on component_stars") {
		t.Fatalf("empty-actor plan scanned the complete relationship table:\n%s", emptyPlan)
	}
	if strings.Contains(emptyPlan, "Seq Scan on component_versions") {
		t.Fatalf("empty-actor plan scanned Versions before proving the actor candidate set was empty:\n%s", emptyPlan)
	}
	t.Logf("empty-actor plan:\n%s", emptyPlan)

	for _, page := range []struct {
		name   string
		offset int32
	}{{name: "first-page"}, {name: "deepest-page", offset: 980}} {
		plan := explainStarSizePage(t, ctx, pool, actor, page.offset)
		if strings.Contains(plan, "Seq Scan on component_stars") {
			t.Fatalf("%s plan did not use the actor relationship index:\n%s", page.name, plan)
		}
		if strings.Contains(plan, "Seq Scan on component_versions") {
			t.Fatalf("%s plan scanned all Versions instead of probing page candidates:\n%s", page.name, plan)
		}
		t.Logf("%s plan:\n%s", page.name, plan)
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
			id, content_kind, content_locale, name, status, created_by,
			current_logical_size_a, current_logical_size_b, current_logical_size_c
		)
		SELECT md5('star-size-component-' || item)::uuid, 'official', 'en-US',
		       'Star size ' || item, 'active', '15000000-0000-0000-0000-000000000002',
		       CASE WHEN item % 100 = 0 THEN 4 ELSE 1 END,
		       CASE WHEN item % 100 = 0 THEN 5 ELSE 2 END,
		       CASE WHEN item % 100 = 0 THEN 6 ELSE 3 END
		FROM generate_series(1, 1000) item;
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
		UPDATE component_repo.components component
		SET current_version_id = md5('star-size-version-' || item)::uuid
		FROM generate_series(1, 1000) item
		WHERE component.id = md5('star-size-component-' || item)::uuid;
		INSERT INTO component_repo.component_stars (actor_id, component_id, starred_at)
		SELECT CASE WHEN actor = 1
		            THEN '15000000-0000-0000-0000-000000000001'::uuid
		            ELSE md5('star-size-actor-' || actor)::uuid END,
		       md5('star-size-component-' || item)::uuid,
		       now() - make_interval(secs => item)
		FROM generate_series(1, 1000) actor
		CROSS JOIN generate_series(1, 1000) item;
		ANALYZE component_repo.component_stars;
		ANALYZE component_repo.components;
		ANALYZE component_repo.component_versions;
	`)
	if err != nil {
		t.Fatalf("seed Star size capacity envelope: %v", err)
	}
}

func explainStarSizeCount(
	t *testing.T,
	ctx context.Context,
	pool *pgxpool.Pool,
	actor pgtype.UUID,
	dimensionCount int32,
	sizeA, sizeB, sizeC float64,
) string {
	t.Helper()
	return collectExplain(t, ctx, pool, `
		EXPLAIN (ANALYZE, BUFFERS, SETTINGS)
		WITH actor_stars AS MATERIALIZED (
		    SELECT star.component_id
		    FROM component_repo.component_stars star
		    WHERE star.actor_id = $1
		)
		SELECT count(*)::bigint
		FROM actor_stars star
		JOIN component_repo.components component ON component.id = star.component_id
		JOIN LATERAL (
		    SELECT true AS available FROM component_repo.component_versions version
		    WHERE version.component_id = component.id
		      AND version.deleted_at IS NULL AND version.status <> 'draft'
		    LIMIT 1
		) public_version ON true
		WHERE component.deleted_at IS NULL
		  AND component.status = 'active'
		  AND ($2::integer = 0 OR COALESCE(
		      ($2::integer = 3
		       AND component.current_logical_size_a > $3::double precision - 1
		       AND component.current_logical_size_a < $3::double precision + 1
		       AND component.current_logical_size_b > $4::double precision - 1
		       AND component.current_logical_size_b < $4::double precision + 1
		       AND component.current_logical_size_c > $5::double precision - 1
		       AND component.current_logical_size_c < $5::double precision + 1), false))`,
		actor, dimensionCount, sizeA, sizeB, sizeC)
}

func explainStarSizePage(t *testing.T, ctx context.Context, pool *pgxpool.Pool, actor pgtype.UUID, offset int32) string {
	t.Helper()
	return collectExplain(t, ctx, pool, `
		EXPLAIN (ANALYZE, BUFFERS, SETTINGS)
		WITH actor_stars AS MATERIALIZED (
		    SELECT star.component_id, star.starred_at
		    FROM component_repo.component_stars star
		    WHERE star.actor_id = $1
		)
		SELECT component.id
		FROM actor_stars star
		JOIN component_repo.components component ON component.id = star.component_id
		JOIN LATERAL (
		    SELECT true AS available FROM component_repo.component_versions version
		    WHERE version.component_id = component.id
		      AND version.deleted_at IS NULL AND version.status <> 'draft'
		    LIMIT 1
		) public_version ON true
		WHERE component.deleted_at IS NULL
		  AND component.status = 'active'
		  AND component.current_logical_size_a > 0
		  AND component.current_logical_size_a < 2
		  AND component.current_logical_size_b > 1
		  AND component.current_logical_size_b < 3
		  AND component.current_logical_size_c > 2
		  AND component.current_logical_size_c < 4
		ORDER BY star.starred_at DESC, component.id
		LIMIT 20 OFFSET $2`, actor, offset)
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
