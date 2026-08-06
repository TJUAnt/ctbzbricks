//go:build integration

package database

import (
	"context"
	"errors"
	"os"
	"slices"
	"testing"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

func TestComponentRepoBaselineContract(t *testing.T) {
	databaseURL := os.Getenv("TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
	}
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, databaseURL)
	if err != nil {
		t.Fatalf("connect to isolated PostgreSQL: %v", err)
	}
	defer conn.Close(ctx)

	expectedTables := []string{
		"artifacts", "assembly_relations", "candidates", "component_group_memberships",
		"component_groups", "component_subscriptions", "component_translations",
		"component_versions", "components", "connector_analyses",
		"connector_analysis_blockers", "connector_analysis_items",
		"connector_analysis_path_nodes", "connector_analysis_relations", "imports",
		"interfaces", "outbox_events", "part_connector_definitions",
		"part_library_versions", "relation_candidates", "scene_snapshots", "task_events",
		"tasks", "upload_session_files", "upload_sessions", "validation_reports",
	}
	rows, err := conn.Query(ctx, `
		SELECT c.relname
		FROM pg_catalog.pg_class c
		JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
		WHERE n.nspname = 'component_repo' AND c.relkind = 'r'
		ORDER BY c.relname`)
	if err != nil {
		t.Fatalf("list component_repo tables: %v", err)
	}
	tables, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		t.Fatalf("collect component_repo tables: %v", err)
	}
	if !slices.Equal(tables, expectedTables) {
		t.Fatalf("unexpected component_repo tables\nwant: %v\n got: %v", expectedTables, tables)
	}

	var rlsDisabled []string
	rows, err = conn.Query(ctx, `
		SELECT c.relname
		FROM pg_catalog.pg_class c
		JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
		WHERE n.nspname = 'component_repo' AND c.relkind = 'r' AND NOT c.relrowsecurity
		ORDER BY c.relname`)
	if err != nil {
		t.Fatalf("query RLS state: %v", err)
	}
	rlsDisabled, err = pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		t.Fatalf("collect RLS state: %v", err)
	}
	if len(rlsDisabled) != 0 {
		t.Fatalf("tables without RLS enabled: %v", rlsDisabled)
	}

	assertSQLState(t, conn, `
		INSERT INTO component_repo.components
			(id, content_kind, content_locale, name, created_by)
		VALUES
			('00000000-0000-0000-0000-000000000001', 'user', 'zh-CN', 'user content',
			 '00000000-0000-0000-0000-000000000002')`, "23514")

	assertSQLState(t, conn, `
		WITH inserted AS (
			INSERT INTO component_repo.components
				(id, owner_id, content_kind, content_locale, name, created_by)
			VALUES
				('00000000-0000-0000-0000-000000000003',
				 '00000000-0000-0000-0000-000000000002', 'user', 'zh-CN', 'user content',
				 '00000000-0000-0000-0000-000000000002')
			RETURNING id
		)
		INSERT INTO component_repo.component_translations
			(component_id, locale, name)
		SELECT id, 'en-US', 'translated user content' FROM inserted`, "23514")

	testPublishedVersionImmutability(t, conn)
}

func testPublishedVersionImmutability(t *testing.T, conn *pgx.Conn) {
	ctx := context.Background()
	tx, err := conn.Begin(ctx)
	if err != nil {
		t.Fatalf("begin immutability fixture: %v", err)
	}
	defer tx.Rollback(ctx)

	fixture := `
		INSERT INTO component_repo.components
			(id, owner_id, content_kind, content_locale, name, created_by)
		VALUES
			('10000000-0000-0000-0000-000000000001',
			 '10000000-0000-0000-0000-000000000002', 'user', 'en-US', 'fixture',
			 '10000000-0000-0000-0000-000000000002');
		INSERT INTO component_repo.artifacts
			(id, owner_id, artifact_type, source_kind, original_filename, storage_provider,
			 storage_bucket, storage_key, sha256, file_size, mime_type, uploaded_by)
		VALUES
			('10000000-0000-0000-0000-000000000003',
			 '10000000-0000-0000-0000-000000000002', 'ldraw', 'source', 'fixture.ldr',
			 'test', 'test', 'fixture.ldr', repeat('0', 64), 1, 'text/plain',
			 '10000000-0000-0000-0000-000000000002');
		INSERT INTO component_repo.imports
			(id, owner_id, source_artifact_id, locale, timezone, created_by)
		VALUES
			('10000000-0000-0000-0000-000000000004',
			 '10000000-0000-0000-0000-000000000002',
			 '10000000-0000-0000-0000-000000000003', 'en-US', 'UTC',
			 '10000000-0000-0000-0000-000000000002');
		INSERT INTO component_repo.scene_snapshots
			(id, import_id, schema_version, parser_version, document, bom, parse_issues)
		VALUES
			('10000000-0000-0000-0000-000000000005',
			 '10000000-0000-0000-0000-000000000004', '1', 'fixture', '{}', '[]', '[]');
		INSERT INTO component_repo.component_versions
			(id, component_id, version_label, status, source_artifact_id, scene_snapshot_id,
			 parser_version, interface_signature, structure_hash, geometry_hash, created_by,
			 published_at)
		VALUES
			('10000000-0000-0000-0000-000000000006',
			 '10000000-0000-0000-0000-000000000001', '1.0.0', 'published',
			 '10000000-0000-0000-0000-000000000003',
			 '10000000-0000-0000-0000-000000000005', 'fixture', repeat('1', 64),
			 repeat('2', 64), repeat('3', 64),
			 '10000000-0000-0000-0000-000000000002', now());`
	if _, err := tx.Exec(ctx, fixture); err != nil {
		t.Fatalf("create immutability fixture: %v", err)
	}
	_, err = tx.Exec(ctx, `
		UPDATE component_repo.component_versions
		SET structure_hash = repeat('4', 64)
		WHERE id = '10000000-0000-0000-0000-000000000006'`)
	if sqlState(err) != "23514" {
		t.Fatalf("published structure update SQLSTATE = %q, want 23514 (error: %v)", sqlState(err), err)
	}
}

func assertSQLState(t *testing.T, conn *pgx.Conn, statement, expected string) {
	t.Helper()
	ctx := context.Background()
	tx, err := conn.Begin(ctx)
	if err != nil {
		t.Fatalf("begin constraint assertion: %v", err)
	}
	defer tx.Rollback(ctx)
	_, err = tx.Exec(ctx, statement)
	if sqlState(err) != expected {
		t.Fatalf("SQLSTATE = %q, want %q (error: %v)", sqlState(err), expected, err)
	}
}

func sqlState(err error) string {
	var pgError *pgconn.PgError
	if errors.As(err, &pgError) {
		return pgError.Code
	}
	return ""
}
