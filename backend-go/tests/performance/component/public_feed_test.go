//go:build integration

package component_test

import (
	"context"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

// TestZZZPublicFeedQueryPlanEnvelope 以十万条发布事件验证首屏、深游标和搜索分支都从全局事件索引取页。
func TestZZZPublicFeedQueryPlanEnvelope(t *testing.T) {
	if os.Getenv("RUN_PUBLIC_FEED_PLAN_TEST") != "1" {
		t.Skip("set RUN_PUBLIC_FEED_PLAN_TEST=1 to run the public Feed plan gate")
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
	resetComponentRepo(t, pool)
	seedPublicFeedPlanEnvelope(t, ctx, pool)

	actor := mustUUID(t, "17000000-0000-0000-0000-000000000001")
	firstTime := time.Date(9999, 12, 31, 23, 59, 59, 0, time.UTC)
	firstID := mustUUID(t, "ffffffff-ffff-ffff-ffff-ffffffffffff")
	for _, scenario := range []struct {
		name    string
		filters publicFeedPlanFilters
	}{
		{name: "unfiltered", filters: publicFeedPlanFilters{namePatterns: []string{}}},
		{name: "selective", filters: publicFeedPlanFilters{namePatterns: []string{"%public%", "%999%"}}},
		{name: "high-match", filters: publicFeedPlanFilters{namePatterns: []string{"%public%"}}},
		{name: "high-match-size", filters: publicFeedPlanFilters{
			namePatterns: []string{}, hasWidth: true, hasDepth: true, hasHeight: true,
			widthStud: 1, depthStud: 2, heightPlate: 3,
		}},
	} {
		_ = explainPublicFeed(t, ctx, pool, actor, firstTime, firstID, scenario.filters)
		plan := explainPublicFeed(t, ctx, pool, actor, firstTime, firstID, scenario.filters)
		assertPublicFeedPlan(t, scenario.name, plan)
		t.Logf("public-feed-%s %s", scenario.name, explainTiming(plan))
	}

	var deepTime time.Time
	var deepID pgtype.UUID
	if err := pool.QueryRow(ctx, `
		SELECT entry.available_at, event.id
		FROM component_repo.component_feed_entries entry
		JOIN component_repo.component_domain_events event ON event.id=entry.event_id
		JOIN component_repo.components component ON component.id=event.component_id
		WHERE entry.render_status IN ('ready','fallback')
		  AND event.event_type='component.version.published.v1'
		  AND component.content_kind='user' AND component.status='active' AND component.deleted_at IS NULL
		ORDER BY entry.available_at DESC, event.id DESC
		OFFSET 80000 LIMIT 1`).Scan(&deepTime, &deepID); err != nil {
		t.Fatalf("read deep public Feed cursor: %v", err)
	}
	deepFilters := publicFeedPlanFilters{namePatterns: []string{}}
	_ = explainPublicFeed(t, ctx, pool, actor, deepTime, deepID, deepFilters)
	deepPlan := explainPublicFeed(t, ctx, pool, actor, deepTime, deepID, deepFilters)
	assertPublicFeedPlan(t, "deep-cursor", deepPlan)
	if !strings.Contains(deepPlan, "available_at") || !strings.Contains(deepPlan, "event_id") {
		t.Fatalf("deep cursor was not represented in the event index condition:\n%s", deepPlan)
	}
	t.Logf("public-feed-deep-cursor %s", explainTiming(deepPlan))

	var eventCount, userEventCount, feedEntryCount int64
	if err := pool.QueryRow(ctx, `
		SELECT count(*), count(*) FILTER (WHERE component.content_kind='user')
		FROM component_repo.component_domain_events event
		JOIN component_repo.components component ON component.id=event.component_id`).Scan(&eventCount, &userEventCount); err != nil {
		t.Fatal(err)
	}
	if eventCount != 100_000 || userEventCount != 90_000 {
		t.Fatalf("unexpected public Feed dataset: events=%d userEvents=%d", eventCount, userEventCount)
	}
	if err := pool.QueryRow(ctx, `SELECT count(*) FROM component_repo.component_feed_entries`).Scan(&feedEntryCount); err != nil || feedEntryCount != 100_000 {
		t.Fatalf("unexpected public Feed entries=%d error=%v", feedEntryCount, err)
	}
	t.Logf("public Feed dataset: events=%d entries=%d userEvents=%d officialEvents=%d", eventCount, feedEntryCount, userEventCount, eventCount-userEventCount)
}

func seedPublicFeedPlanEnvelope(t *testing.T, ctx context.Context, pool *pgxpool.Pool) {
	t.Helper()
	_, err := pool.Exec(ctx, `
		INSERT INTO component_repo.artifacts (
			id, owner_id, artifact_type, source_kind, original_filename, storage_provider,
			storage_bucket, storage_key, sha256, file_size, mime_type, verification_status,
			verified_at, uploaded_by
		) VALUES (
			'17000000-0000-0000-0000-000000000010',
			'17000000-0000-0000-0000-000000000002', 'component_source', 'source', 'public-feed.ldr',
			'test', 'test', 'public-feed/perf.ldr', repeat('a',64), 1, 'text/plain', 'verified', now(),
			'17000000-0000-0000-0000-000000000002'
		);
		INSERT INTO component_repo.upload_sessions (
			id, owner_id, status, locale, timezone, created_by, expires_at, completed_at
		) VALUES (
			'17000000-0000-0000-0000-000000000013',
			'17000000-0000-0000-0000-000000000002', 'completed', 'en-US', 'UTC',
			'17000000-0000-0000-0000-000000000002', now()+interval '1 hour', now()
		);
		INSERT INTO component_repo.tasks (id, owner_id, task_type, payload, locale, timezone, created_by)
		VALUES
			('17000000-0000-0000-0000-000000000014', '17000000-0000-0000-0000-000000000002',
			 'component.artifact.verify', '{"artifactId":"17000000-0000-0000-0000-000000000010"}',
			 'en-US', 'UTC', '17000000-0000-0000-0000-000000000002'),
			('17000000-0000-0000-0000-000000000015', '17000000-0000-0000-0000-000000000002',
			 'component.import.parse', '{"importId":"17000000-0000-0000-0000-000000000011","parserVersion":"feed-perf-v1"}',
			 'en-US', 'UTC', '17000000-0000-0000-0000-000000000002');
		INSERT INTO component_repo.task_dependencies (task_id, prerequisite_task_id, owner_id)
		VALUES ('17000000-0000-0000-0000-000000000015', '17000000-0000-0000-0000-000000000014',
		        '17000000-0000-0000-0000-000000000002');
		INSERT INTO component_repo.imports (
			id, owner_id, source_artifact_id, status, parser_version, locale, timezone, created_by,
			upload_session_id, parse_task_id
		) VALUES (
			'17000000-0000-0000-0000-000000000011', '17000000-0000-0000-0000-000000000002',
			'17000000-0000-0000-0000-000000000010', 'succeeded', 'feed-perf-v1', 'en-US', 'UTC',
			'17000000-0000-0000-0000-000000000002', '17000000-0000-0000-0000-000000000013',
			'17000000-0000-0000-0000-000000000015'
		);
		INSERT INTO component_repo.scene_snapshots (id, import_id, schema_version, parser_version, document, bom, parse_issues)
		VALUES ('17000000-0000-0000-0000-000000000012', '17000000-0000-0000-0000-000000000011',
		        '1', 'feed-perf-v1', '{}', '{}', '[]');
		INSERT INTO component_repo.components (
			id, owner_id, content_kind, content_locale, name, category, status, created_by
		)
		SELECT md5('public-feed-component-' || item)::uuid,
		       CASE WHEN item % 10 = 0 THEN NULL ELSE '17000000-0000-0000-0000-000000000002'::uuid END,
		       CASE WHEN item % 10 = 0 THEN 'official' ELSE 'user' END,
		       'en-US', 'Public component ' || item, 'building', 'active',
		       '17000000-0000-0000-0000-000000000002'
		FROM generate_series(1, 1000) item;
		-- 性能 fixture 共享一套来源资产，只验证公共 Feed 查询形状；事务结束前恢复完整性触发器。
		ALTER TABLE component_repo.component_versions DISABLE TRIGGER component_versions_require_source_integrity;
		-- 十万条历史 Version 若逐行刷新同一千个 Component，会把 fixture 构造退化为无关的 O(events × versions) 工作。
		ALTER TABLE component_repo.component_versions DISABLE TRIGGER component_versions_refresh_component_availability;
		INSERT INTO component_repo.component_versions (
			id, component_id, version_label, revision, status, source_artifact_id, scene_snapshot_id,
			parser_version, interface_signature, structure_hash, geometry_hash,
			preview_bbox_min, preview_bbox_max, logical_width_stud, logical_depth_stud,
			logical_height_plate, preview_bounds_complete, created_by, published_at
		)
		SELECT md5('public-feed-version-' || component_item || '-' || event_item)::uuid,
		       md5('public-feed-component-' || component_item)::uuid,
		       'v' || event_item, 1, 'published', '17000000-0000-0000-0000-000000000010',
		       '17000000-0000-0000-0000-000000000012', 'feed-perf-v1', repeat('1',64), repeat('2',64),
		       repeat('3',64), ARRAY[0,0,0]::float8[], ARRAY[20,24,40]::float8[],
		       1, 2, 3, true, '17000000-0000-0000-0000-000000000002',
		       '2026-09-12 00:00:00+00'::timestamptz - make_interval(secs => event_item*1000+component_item)
		FROM generate_series(1, 1000) component_item
		CROSS JOIN generate_series(1, 100) event_item;
		ALTER TABLE component_repo.component_versions ENABLE TRIGGER component_versions_require_source_integrity;
		ALTER TABLE component_repo.component_versions ENABLE TRIGGER component_versions_refresh_component_availability;
		UPDATE component_repo.components component
		SET current_version_id=md5('public-feed-version-' || item || '-1')::uuid,
		    version_available=true,
		    public_version_available=true
		FROM generate_series(1, 1000) item
		WHERE component.id=md5('public-feed-component-' || item)::uuid;
		INSERT INTO component_repo.component_domain_events (
			id, event_type, component_id, component_version_id, actor_id, occurred_at
		)
		SELECT md5('public-feed-event-' || component_item || '-' || event_item)::uuid,
		       'component.version.published.v1', md5('public-feed-component-' || component_item)::uuid,
		       md5('public-feed-version-' || component_item || '-' || event_item)::uuid,
		       '17000000-0000-0000-0000-000000000002',
		       '2026-09-12 00:00:00+00'::timestamptz - make_interval(secs => event_item*1000+component_item)
		FROM generate_series(1, 1000) component_item
		CROSS JOIN generate_series(1, 100) event_item;
		INSERT INTO component_repo.component_feed_entries (
			event_id, component_id, component_version_id, render_profile, renderer_version, render_status, available_at
		)
		SELECT event.id, event.component_id, event.component_version_id, 'feed_card_3x2', 'component-feed-renderer-v1',
		       'fallback', event.occurred_at
		FROM component_repo.component_domain_events event
		WHERE event.event_type='component.version.published.v1';
		ANALYZE component_repo.components;
		ANALYZE component_repo.component_versions;
		ANALYZE component_repo.component_domain_events;
		ANALYZE component_repo.component_feed_entries;
	`)
	if err != nil {
		t.Fatalf("seed public Feed capacity envelope: %v", err)
	}
}

type publicFeedPlanFilters struct {
	namePatterns []string
	componentID  string
	hasWidth     bool
	hasDepth     bool
	hasHeight    bool
	widthStud    float64
	depthStud    float64
	heightPlate  float64
}

func explainPublicFeed(t *testing.T, ctx context.Context, pool *pgxpool.Pool, actor pgtype.UUID, cursorTime time.Time, cursorID pgtype.UUID, filters publicFeedPlanFilters) string {
	t.Helper()
	return collectExplain(t, ctx, pool, `
		EXPLAIN (ANALYZE, BUFFERS, SETTINGS)
		WITH feed_page AS MATERIALIZED (
			SELECT source.event_id, source.occurred_at, entry.available_at, source.component_version_id,
			       source.id, source.current_version_id
			FROM component_repo.component_feed_entries entry
			JOIN LATERAL (
				SELECT source_event.id AS event_id, source_event.occurred_at,
				       source_event.component_version_id, component.id, component.current_version_id
				FROM component_repo.component_domain_events source_event
				JOIN component_repo.components component
				  ON component.id=entry.component_id AND component.id=source_event.component_id
				 AND component.content_kind='user' AND component.status='active' AND component.deleted_at IS NULL
				JOIN component_repo.component_versions version
				  ON version.id=entry.component_version_id AND version.id=source_event.component_version_id
				 AND version.component_id=component.id AND version.deleted_at IS NULL
				LEFT JOIN LATERAL (
					SELECT projection.logical_width_stud,projection.logical_depth_stud,projection.logical_height_plate
					FROM component_repo.component_catalog_projection projection
					WHERE ($4::boolean OR $5::boolean OR $6::boolean) AND projection.id=component.id
				) filter_size ON true
				WHERE source_event.id=entry.event_id
				  AND source_event.event_type='component.version.published.v1'
				  AND lower(component.name) LIKE ALL($7::text[])
				  AND ($8::text='' OR position($8 IN lower(component.id::text)) > 0)
				  AND (
				      (NOT $4::boolean AND NOT $5::boolean)
				      OR ($4::boolean AND $5::boolean
				          AND least(filter_size.logical_width_stud,filter_size.logical_depth_stud) BETWEEN least($9::float8,$10::float8)-0.25 AND least($9::float8,$10::float8)+0.25
				          AND greatest(filter_size.logical_width_stud,filter_size.logical_depth_stud) BETWEEN greatest($9::float8,$10::float8)-0.25 AND greatest($9::float8,$10::float8)+0.25)
				      OR ($4::boolean AND NOT $5::boolean AND (filter_size.logical_width_stud BETWEEN $9::float8-0.25 AND $9::float8+0.25 OR filter_size.logical_depth_stud BETWEEN $9::float8-0.25 AND $9::float8+0.25))
				      OR (NOT $4::boolean AND $5::boolean AND (filter_size.logical_width_stud BETWEEN $10::float8-0.25 AND $10::float8+0.25 OR filter_size.logical_depth_stud BETWEEN $10::float8-0.25 AND $10::float8+0.25))
				  )
				  AND (NOT $6::boolean OR filter_size.logical_height_plate BETWEEN $11::float8-0.625 AND $11::float8+0.625)
				OFFSET 0
			) source ON true
			WHERE entry.render_status IN ('ready','fallback') AND entry.available_at IS NOT NULL
			  AND (entry.available_at,entry.event_id) < ($2::timestamptz,$3::uuid)
			ORDER BY entry.available_at DESC,entry.event_id DESC
			LIMIT 21
		), page_star_counts AS (
			SELECT star.component_id,count(*) FROM component_repo.component_stars star
			JOIN (SELECT DISTINCT id FROM feed_page) page_component ON page_component.id=star.component_id
			GROUP BY star.component_id
		)
		SELECT page.event_id,page.occurred_at,page.available_at,page.component_version_id,page.id,
		       COALESCE(page_star_counts.count,0),active_watch.watch_level
		FROM feed_page page
		LEFT JOIN page_star_counts ON page_star_counts.component_id=page.id
		LEFT JOIN component_repo.component_watch_periods active_watch
		  ON active_watch.actor_id=$1 AND active_watch.component_id=page.id AND active_watch.ended_seq IS NULL
		ORDER BY page.available_at DESC,page.event_id DESC`, actor, cursorTime, cursorID,
		filters.hasWidth, filters.hasDepth, filters.hasHeight, filters.namePatterns, filters.componentID,
		filters.widthStud, filters.depthStud, filters.heightPlate)
}

func assertPublicFeedPlan(t *testing.T, name, plan string) {
	t.Helper()
	if !strings.Contains(plan, "component_feed_entries_available_idx") {
		t.Fatalf("%s did not use the terminal Feed entry index:\n%s", name, plan)
	}
	if strings.Contains(plan, "Seq Scan on component_feed_entries") {
		t.Fatalf("%s scanned the complete Feed entry relation:\n%s", name, plan)
	}
	if strings.Contains(plan, "temp read=") || strings.Contains(plan, "temp written=") || strings.Contains(plan, "Sort Method: external") {
		t.Fatalf("%s spilled public Feed paging to temporary storage:\n%s", name, plan)
	}
}
