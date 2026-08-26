package partlibrary

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestImportStudioLibraryDryRunIncludesConnectorAndColliderCapabilities(t *testing.T) {
	root := t.TempDir()
	ldraw := filepath.Join(root, "ldraw")
	mustMkdir(t, filepath.Join(ldraw, "parts"))
	mustMkdir(t, filepath.Join(ldraw, "connectivity"))
	mustMkdir(t, filepath.Join(ldraw, "collider"))
	mustWrite(t, filepath.Join(ldraw, "parts", "3001.dat"), "0 Brick\n4 16 0 0 0 20 0 0 20 8 0 0 8 0\n")
	var connectivity bytes.Buffer
	writeStudioMatrixFixture(t, &connectivity, 3, 23, [3]float32{-10, 0, 10}, 2, 2, []studioMatrixCell{
		{3, 1}, {0, 4}, {3, 1}, {0, 4}, {10, 4}, {0, 4}, {3, 1}, {0, 4}, {3, 1},
	})
	if err := os.WriteFile(filepath.Join(ldraw, "connectivity", "3001.conn"), connectivity.Bytes(), 0o644); err != nil {
		t.Fatal(err)
	}
	mustWrite(t, filepath.Join(ldraw, "collider", "3001.col"), "9 0 1 0 0 0 1 0 0 0 1 0 2 0 10 3 10 null\n")
	out := filepath.Join(root, "manifest")
	manifest, err := GenerateStudioManifest(Options{StudioRoot: root, OutDir: out, GeneratedAt: time.Date(2026, 8, 22, 0, 0, 0, 0, time.UTC)})
	if err != nil {
		t.Fatalf("GenerateStudioManifest: %v", err)
	}
	result, err := ImportStudioLibrary(t.Context(), ImportOptions{ManifestPath: manifest.ManifestPath, DryRun: true})
	if err != nil {
		t.Fatalf("ImportStudioLibrary: %v", err)
	}
	if !result.PreviewReady || !result.RelationReady || result.ConnectorCount != 1 || result.ColliderCount != 1 {
		t.Fatalf("capabilities = %+v", result)
	}
	if result.ColliderStorage != ColliderStorageMetadataOnly || result.ColliderStored != 0 {
		t.Fatalf("default collider storage = %+v", result)
	}
	if len(result.ConnectorHash) != 64 || len(result.ColliderHash) != 64 || len(result.SidecarFailuresSample) != 0 {
		t.Fatalf("sidecar evidence = %+v", result)
	}
	databaseRows, err := ImportStudioLibrary(t.Context(), ImportOptions{
		ManifestPath: manifest.ManifestPath, DryRun: true, ColliderStorage: ColliderStorageDatabase,
	})
	if err != nil || databaseRows.ColliderStored != 1 {
		t.Fatalf("database collider storage = %+v error=%v", databaseRows, err)
	}
}

func TestImportStudioLibraryDryRun(t *testing.T) {
	root := t.TempDir()
	ldraw := filepath.Join(root, "ldraw")
	mustMkdir(t, filepath.Join(ldraw, "parts"))
	mustMkdir(t, filepath.Join(ldraw, "p"))
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

	result, err := ImportStudioLibrary(t.Context(), ImportOptions{
		ManifestPath: manifest.ManifestPath,
		DryRun:       true,
	})
	if err != nil {
		t.Fatalf("ImportStudioLibrary dry-run: %v", err)
	}
	if result.LibraryID == "" {
		t.Fatal("library ID is empty")
	}
	if result.PartCount != 2 {
		t.Fatalf("part count = %d, want 2", result.PartCount)
	}
	if result.GeometryReady != 1 || result.GeometryFailed != 1 {
		t.Fatalf("geometry ready/failed = %d/%d, want 1/1", result.GeometryReady, result.GeometryFailed)
	}
	if len(result.FailuresSample) != 1 || result.FailuresSample[0].LDrawPartNum != "bad.dat" {
		t.Fatalf("failures sample = %+v", result.FailuresSample)
	}

	again, err := ImportStudioLibrary(t.Context(), ImportOptions{
		ManifestPath: manifest.ManifestPath,
		DryRun:       true,
	})
	if err != nil {
		t.Fatalf("ImportStudioLibrary dry-run again: %v", err)
	}
	if result.LibraryID != again.LibraryID {
		t.Fatalf("deterministic library ID changed: %s != %s", result.LibraryID, again.LibraryID)
	}
}

func TestComputeGeometryStatsUnofficialManifestPath(t *testing.T) {
	root := t.TempDir()
	ldraw := filepath.Join(root, "ldraw")
	mustMkdir(t, filepath.Join(ldraw, "UnOfficial", "parts"))
	mustWrite(t, filepath.Join(ldraw, "UnOfficial", "parts", "bl_foo.dat"), "0 Unofficial\n3 16 0 0 0 10 0 0 0 10 0\n")
	stats, err := ComputeGeometryStats(ldraw, "UnOfficial/parts/bl_foo.dat")
	if err != nil {
		t.Fatalf("ComputeGeometryStats: %v", err)
	}
	if stats.SourceRelativePath != "parts/bl_foo.dat" {
		t.Fatalf("source relative path = %q, want parts/bl_foo.dat", stats.SourceRelativePath)
	}
	if stats.FaceCount != 1 || stats.VertexCount != 3 {
		t.Fatalf("face/vertex count = %d/%d, want 1/3", stats.FaceCount, stats.VertexCount)
	}
}

func TestLDrawSourceNameUsesDescriptionAndFallsBackToPartNumber(t *testing.T) {
	root := t.TempDir()
	ldraw := filepath.Join(root, "ldraw")
	mustMkdir(t, filepath.Join(ldraw, "parts"))
	mustWrite(t, filepath.Join(ldraw, "parts", "3001.dat"), "0 Brick 2 x 4\n0 Name: 3001.dat\n")
	mustWrite(t, filepath.Join(ldraw, "parts", "meta.dat"), "0 !LDRAW_ORG Part UPDATE 2026-01\n0 BFC CERTIFY CCW\n")
	index, err := newLDrawIndex(ldraw)
	if err != nil {
		t.Fatal(err)
	}
	if got := index.sourceName("parts/3001.dat", "3001.dat"); got != "Brick 2 x 4" {
		t.Fatalf("source name = %q", got)
	}
	if got := index.sourceName("parts/meta.dat", "meta.dat"); got != "meta.dat" {
		t.Fatalf("fallback source name = %q", got)
	}
}

func TestComputeGeometryStatsNormalizesBackslashReferences(t *testing.T) {
	root := t.TempDir()
	ldraw := filepath.Join(root, "ldraw")
	mustMkdir(t, filepath.Join(ldraw, "parts", "s"))
	mustWrite(t, filepath.Join(ldraw, "parts", "3001.dat"), "0 Brick\n1 16 0 0 0 1 0 0 0 1 0 0 0 1 s\\3001s01.dat\n")
	mustWrite(t, filepath.Join(ldraw, "parts", "s", "3001s01.dat"), "0 Subpart\n3 16 0 0 0 10 0 0 0 10 0\n")
	stats, err := ComputeGeometryStats(ldraw, "parts/3001.dat")
	if err != nil {
		t.Fatalf("ComputeGeometryStats: %v", err)
	}
	if stats.FaceCount != 1 {
		t.Fatalf("face count = %d, want 1", stats.FaceCount)
	}
}

func TestComputeGeometryStatsAcceptsStudioTexturedFacesAndLongMetadata(t *testing.T) {
	root := t.TempDir()
	ldraw := filepath.Join(root, "ldraw")
	mustMkdir(t, filepath.Join(ldraw, "UnOfficial", "parts"))
	longTextureMeta := "0 PE_TEX_INFO " + strings.Repeat("A", 2*1024*1024) + "\n"
	texturedTriangle := "3 16 0 0 0 20 0 0 0 8 0 0 0 1 1 0 1\n"
	texturedQuad := "4 16 0 0 0 20 0 0 20 8 0 0 8 0 0 0 1 1 0 1 1 0 1\n"
	mustWrite(t, filepath.Join(ldraw, "UnOfficial", "parts", "14769pb079.dat"), longTextureMeta+texturedTriangle+texturedQuad)

	stats, err := ComputeGeometryStats(ldraw, "UnOfficial/parts/14769pb079.dat")
	if err != nil {
		t.Fatalf("ComputeGeometryStats: %v", err)
	}
	if stats.FaceCount != 3 || stats.VertexCount != 9 {
		t.Fatalf("face/vertex count = %d/%d, want 3/9", stats.FaceCount, stats.VertexCount)
	}
}

func TestComputeGeometryStatsReportsMissingReferenceDetails(t *testing.T) {
	root := t.TempDir()
	ldraw := filepath.Join(root, "ldraw")
	mustMkdir(t, filepath.Join(ldraw, "parts"))
	mustWrite(t, filepath.Join(ldraw, "parts", "bad.dat"), "0 Bad\n1 16 0 0 0 1 0 0 0 1 0 0 0 1 s\\missing.dat\n")

	_, err := ComputeGeometryStats(ldraw, "parts/bad.dat")
	if err == nil {
		t.Fatal("expected missing reference error")
	}
	var geometryErr ldrawGeometryError
	if !errors.As(err, &geometryErr) {
		t.Fatalf("error type = %T, want ldrawGeometryError", err)
	}
	if geometryErr.reference != "s/missing.dat" || len(geometryErr.candidates) == 0 {
		t.Fatalf("missing reference details = %+v", geometryErr)
	}
}

func TestComputeGeometryStatsFallsBackFromResolutionReferenceToPlainPrimitive(t *testing.T) {
	root := t.TempDir()
	ldraw := filepath.Join(root, "ldraw")
	mustMkdir(t, filepath.Join(ldraw, "parts"))
	mustMkdir(t, filepath.Join(ldraw, "UnOfficial", "p"))
	mustWrite(t, filepath.Join(ldraw, "parts", "uses_resolution_ref.dat"), "0 Uses fallback\n1 16 0 0 0 1 0 0 0 1 0 0 0 1 48\\tm04i2000.dat\n1 16 10 0 0 1 0 0 0 1 0 0 0 1 8\\3-8tang.dat\n")
	mustWrite(t, filepath.Join(ldraw, "UnOfficial", "p", "tm04i2000.dat"), "0 Primitive fallback\n3 16 0 0 0 10 0 0 0 10 0\n")
	mustWrite(t, filepath.Join(ldraw, "UnOfficial", "p", "3-8tang.dat"), "0 Primitive fallback\n3 16 0 0 0 10 0 0 0 10 0\n")

	stats, err := ComputeGeometryStats(ldraw, "parts/uses_resolution_ref.dat")
	if err != nil {
		t.Fatalf("ComputeGeometryStats: %v", err)
	}
	if stats.FaceCount != 2 {
		t.Fatalf("face count = %d, want 2", stats.FaceCount)
	}
}

func TestReadManifestRejectsUnsupportedSchema(t *testing.T) {
	path := filepath.Join(t.TempDir(), "manifest.json")
	if err := os.WriteFile(path, []byte(`{"schemaVersion":"old"}`), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := readManifest(path); err == nil {
		t.Fatal("expected unsupported schema error")
	}
}
