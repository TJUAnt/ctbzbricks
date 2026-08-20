//go:build integration

package partlibrary

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

func TestImportStudioLibraryWritesComponentRepoSnapshot(t *testing.T) {
	databaseURL := os.Getenv("TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("TEST_DATABASE_URL is required")
	}
	ctx := context.Background()
	root := t.TempDir()
	ldraw := filepath.Join(root, "ldraw")
	mustMkdir(t, filepath.Join(ldraw, "parts"))
	mustWrite(t, filepath.Join(ldraw, "parts", "3001.dat"), "0 Brick\n4 16 0 0 0 20 0 0 20 8 0 0 8 0\n")
	mustWrite(t, filepath.Join(ldraw, "parts", "bad.dat"), "0 Bad\n1 16 0 0 0 1 0 0 0 1 0 0 0 1 missing.dat\n")
	out := filepath.Join(root, "manifest")
	manifest, err := GenerateStudioManifest(Options{
		StudioRoot:  root,
		OutDir:      out,
		GeneratedAt: time.Date(2026, 8, 15, 0, 0, 0, 0, time.UTC),
	})
	if err != nil {
		t.Fatalf("GenerateStudioManifest: %v", err)
	}
	result, err := ImportStudioLibrary(ctx, ImportOptions{
		DatabaseURL:  databaseURL,
		ManifestPath: manifest.ManifestPath,
		Status:       "active",
		CreatedBy:    "00000000-0000-4000-8000-000000000123",
	})
	if err != nil {
		t.Fatalf("ImportStudioLibrary: %v", err)
	}
	if result.PartCount != 2 || result.GeometryReady != 1 || result.GeometryFailed != 1 || result.PreviewRows != 2 {
		t.Fatalf("unexpected result: %+v", result)
	}
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	var libraryCount, partCount, readyCount, failedCount, previewCount int
	if err := pool.QueryRow(ctx, `
		SELECT
		  (SELECT count(*) FROM component_repo.part_library_versions WHERE id = $1::uuid AND status = 'active'),
		  (SELECT count(*) FROM component_repo.parts WHERE part_library_version_id = $1::uuid),
		  (SELECT count(*) FROM component_repo.part_geometries WHERE part_library_version_id = $1::uuid AND geometry_status = 'ready'),
		  (SELECT count(*) FROM component_repo.part_geometries WHERE part_library_version_id = $1::uuid AND geometry_status = 'failed'),
		  (SELECT count(*) FROM component_repo.part_previews WHERE part_library_version_id = $1::uuid)
	`, result.LibraryID).Scan(&libraryCount, &partCount, &readyCount, &failedCount, &previewCount); err != nil {
		t.Fatal(err)
	}
	if libraryCount != 1 || partCount != 2 || readyCount != 1 || failedCount != 1 || previewCount != 2 {
		t.Fatalf("counts library/parts/ready/failed/previews = %d/%d/%d/%d/%d", libraryCount, partCount, readyCount, failedCount, previewCount)
	}
}
