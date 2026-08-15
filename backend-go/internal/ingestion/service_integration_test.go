//go:build integration

package ingestion

import (
	"context"
	"errors"
	"os"
	"testing"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5/pgxpool"
)

func TestG6ImportAndCandidateOwnership(t *testing.T) {
	databaseURL := os.Getenv("TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("TEST_DATABASE_URL is required")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatalf("connect PostgreSQL: %v", err)
	}
	defer pool.Close()
	if _, err := pool.Exec(ctx, `
		TRUNCATE component_repo.components, component_repo.upload_sessions,
		         component_repo.artifacts, component_repo.tasks, component_repo.outbox_events
		RESTART IDENTITY CASCADE;
		INSERT INTO component_repo.components
			(id, owner_id, content_kind, content_locale, name, created_by)
		VALUES
			('66000000-0000-0000-0000-000000000001',
			 '66000000-0000-0000-0000-000000000002', 'user', 'en-US', 'fixture',
			 '66000000-0000-0000-0000-000000000002');
		INSERT INTO component_repo.upload_sessions
			(id, owner_id, status, target_component_id, locale, timezone, created_by,
			 expires_at, completed_at)
		VALUES
			('66000000-0000-0000-0000-000000000003',
			 '66000000-0000-0000-0000-000000000002', 'completed',
			 '66000000-0000-0000-0000-000000000001', 'en-US', 'UTC',
			 '66000000-0000-0000-0000-000000000002', now() + interval '1 hour', now());
		INSERT INTO component_repo.artifacts
			(id, owner_id, artifact_type, source_kind, original_filename, storage_provider,
			 storage_bucket, storage_key, sha256, file_size, mime_type, verification_status,
			 verified_at, uploaded_by)
		VALUES
			('66000000-0000-0000-0000-000000000004',
			 '66000000-0000-0000-0000-000000000002', 'ldraw_ldr', 'source', 'fixture.ldr',
			 'test', 'test', 'fixture.ldr', repeat('0', 64), 1, 'text/plain', 'verified', now(),
			 '66000000-0000-0000-0000-000000000002');
		INSERT INTO component_repo.tasks
			(id, owner_id, task_type, payload, locale, timezone, created_by)
		VALUES
			('66000000-0000-0000-0000-000000000005',
			 '66000000-0000-0000-0000-000000000002', 'component.artifact.verify',
			 '{"artifactId":"66000000-0000-0000-0000-000000000004"}', 'en-US', 'UTC',
			 '66000000-0000-0000-0000-000000000002'),
			('66000000-0000-0000-0000-000000000006',
			 '66000000-0000-0000-0000-000000000002', 'component.import.parse',
			 '{"importId":"66000000-0000-0000-0000-000000000007","parserVersion":"fixture-parser","snapshotSchema":"fixture-schema"}',
			 'en-US', 'UTC', '66000000-0000-0000-0000-000000000002');
		INSERT INTO component_repo.task_dependencies (task_id, prerequisite_task_id, owner_id)
		VALUES
			('66000000-0000-0000-0000-000000000006',
			 '66000000-0000-0000-0000-000000000005',
			 '66000000-0000-0000-0000-000000000002');
		INSERT INTO component_repo.imports
			(id, owner_id, source_artifact_id, target_component_id, status, parser_version,
			 locale, timezone, created_by, upload_session_id, parse_task_id)
		VALUES
			('66000000-0000-0000-0000-000000000007',
			 '66000000-0000-0000-0000-000000000002',
			 '66000000-0000-0000-0000-000000000004',
			 '66000000-0000-0000-0000-000000000001', 'succeeded', 'fixture-parser',
			 'en-US', 'UTC', '66000000-0000-0000-0000-000000000002',
			 '66000000-0000-0000-0000-000000000003',
			 '66000000-0000-0000-0000-000000000006');
		INSERT INTO component_repo.scene_snapshots
			(id, import_id, schema_version, parser_version, document, bom, parse_issues)
		VALUES
			('66000000-0000-0000-0000-000000000008',
			 '66000000-0000-0000-0000-000000000007', 'fixture-schema', 'fixture-parser',
			 '{"models":[]}', '{}', '[]');
		INSERT INTO component_repo.candidates
			(id, owner_id, import_id, scene_snapshot_id, summary, interface_signature,
			 structure_hash, geometry_hash)
		VALUES
			('66000000-0000-0000-0000-000000000009',
			 '66000000-0000-0000-0000-000000000002',
			 '66000000-0000-0000-0000-000000000007',
			 '66000000-0000-0000-0000-000000000008', '{}', repeat('1', 64), repeat('2', 64), repeat('3', 64));
		INSERT INTO component_repo.component_versions
			(id, component_id, component_candidate_id, version_label, source_artifact_id,
			 scene_snapshot_id, parser_version, interface_signature, structure_hash,
			 geometry_hash, created_by)
		VALUES
			('66000000-0000-0000-0000-000000000010',
			 '66000000-0000-0000-0000-000000000001',
			 '66000000-0000-0000-0000-000000000009', '0.1.0',
			 '66000000-0000-0000-0000-000000000004',
			 '66000000-0000-0000-0000-000000000008', 'fixture-parser', repeat('1', 64),
			 repeat('2', 64), repeat('3', 64), '66000000-0000-0000-0000-000000000002');`); err != nil {
		t.Fatalf("seed G6 fixture: %v", err)
	}

	owner, _ := uuidutil.Parse("66000000-0000-0000-0000-000000000002")
	other, _ := uuidutil.Parse("66000000-0000-0000-0000-000000000011")
	service := NewService(pool)
	importView, err := service.GetImport(ctx, owner, "66000000-0000-0000-0000-000000000007")
	if err != nil || importView.Status != "succeeded" || importView.CandidateID == nil || importView.DraftVersionID == nil {
		t.Fatalf("owned import = %+v error=%v", importView, err)
	}
	candidate, err := service.GetCandidate(ctx, owner, "66000000-0000-0000-0000-000000000009")
	if err != nil || candidate.SceneSnapshot.ParserVersion != "fixture-parser" || candidate.DraftVersionID == nil {
		t.Fatalf("owned candidate = %+v error=%v", candidate, err)
	}
	if _, err := service.GetImport(ctx, other, importView.ID); publicCode(err) != "component_repo.import_not_found" {
		t.Fatalf("cross-owner import error = %v", err)
	}
	if _, err := service.GetCandidate(ctx, other, candidate.ID); publicCode(err) != "component_repo.candidate_id_not_found" {
		t.Fatalf("cross-owner candidate error = %v", err)
	}
}

func publicCode(err error) string {
	var public *apierror.Error
	if errors.As(err, &public) {
		return public.Code
	}
	return ""
}
