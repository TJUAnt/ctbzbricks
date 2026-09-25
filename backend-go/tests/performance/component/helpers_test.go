//go:build integration

package component_test

import (
	"context"
	"testing"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

func resetComponentRepo(t *testing.T, pool *pgxpool.Pool) {
	t.Helper()
	_, err := pool.Exec(context.Background(), `
		TRUNCATE component_repo.components, component_repo.artifacts,
		         component_repo.upload_sessions, component_repo.imports,
		         component_repo.part_library_versions, component_repo.component_groups,
		         component_repo.tasks, component_repo.outbox_events
		RESTART IDENTITY CASCADE`)
	if err != nil {
		t.Fatalf("reset component_repo fixtures: %v", err)
	}
}

func mustUUID(t *testing.T, value string) pgtype.UUID {
	t.Helper()
	id, err := uuidutil.Parse(value)
	if err != nil {
		t.Fatalf("parse UUID %q: %v", value, err)
	}
	return id
}
