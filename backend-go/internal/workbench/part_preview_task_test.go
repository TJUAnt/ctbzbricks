package workbench

import (
	"context"
	"encoding/binary"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type identityPartGLBOptimizer struct{}

func (identityPartGLBOptimizer) Optimize(_ context.Context, source []byte) ([]byte, error) {
	return source, nil
}

func TestCollectLDrawTrianglesAndBuildGLB(t *testing.T) {
	root := t.TempDir()
	parts := filepath.Join(root, "parts")
	primitives := filepath.Join(root, "p")
	if err := os.MkdirAll(parts, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(primitives, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(primitives, "triangle.dat"), []byte("3 16 0 0 0 10 0 0 0 10 0\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	part := "0 Test\n1 16 1 2 3 1 0 0 0 1 0 0 0 1 triangle.dat\n4 16 0 0 0 0 0 10 10 0 10 10 0 0\n"
	if err := os.WriteFile(filepath.Join(parts, "test.dat"), []byte(part), 0o644); err != nil {
		t.Fatal(err)
	}
	files, err := indexLDrawFiles(root)
	if err != nil {
		t.Fatalf("index: %v", err)
	}
	triangles, err := collectLDrawTriangles("parts/test.dat", files)
	if err != nil {
		t.Fatalf("collect: %v", err)
	}
	if len(triangles) != 3 {
		t.Fatalf("expected 3 triangles, got %d", len(triangles))
	}
	if got := triangles[0][0]; got != (ldrawVector{1, 2, 3}) {
		t.Fatalf("reference transform not applied: %#v", got)
	}
	glb, err := buildPartGLB(triangles, PartPreviewGeneratorVersion)
	if err != nil {
		t.Fatalf("build glb: %v", err)
	}
	if string(glb[:4]) != "glTF" || binary.LittleEndian.Uint32(glb[4:8]) != 2 {
		t.Fatalf("invalid GLB header: %q", glb[:12])
	}
	if int(binary.LittleEndian.Uint32(glb[8:12])) != len(glb) {
		t.Fatalf("GLB byte length mismatch")
	}
	document := decodeComponentGLBJSON(t, glb)
	primitive := document["meshes"].([]any)[0].(map[string]any)["primitives"].([]any)[0].(map[string]any)
	attributes := primitive["attributes"].(map[string]any)
	if _, exists := attributes["NORMAL"]; !exists {
		t.Fatal("Part GLB must persist Worker-generated normals")
	}
	accessors := document["accessors"].([]any)
	minimum := accessors[0].(map[string]any)["min"].([]any)
	if minimum[1].(float64) >= 0 {
		t.Fatalf("Part GLB did not convert LDraw Y-down coordinates: min=%v", minimum)
	}
}

func TestIsMeshoptGLBRejectsUncompressedPartGLB(t *testing.T) {
	glb, err := buildPartGLB([]ldrawTriangle{{{0, 0, 0}, {20, 0, 0}, {0, 8, 0}}}, PartPreviewGeneratorVersion)
	if err != nil {
		t.Fatal(err)
	}
	if isMeshoptGLB(glb) {
		t.Fatal("raw Part GLB must not be mistaken for meshopt output")
	}
}

func TestGLTFPackOptimizerProducesMeshoptGLB(t *testing.T) {
	path := os.Getenv("TEST_GLTFPACK_PATH")
	if path == "" {
		t.Skip("TEST_GLTFPACK_PATH is required")
	}
	raw, err := buildPartGLB([]ldrawTriangle{{{0, 0, 0}, {20, 0, 0}, {0, 8, 20}}}, PartPreviewGeneratorVersion)
	if err != nil {
		t.Fatal(err)
	}
	optimizer, err := NewGLTFPackOptimizer(path)
	if err != nil {
		t.Fatal(err)
	}
	optimized, err := optimizer.Optimize(context.Background(), raw)
	if err != nil {
		t.Fatal(err)
	}
	if !isMeshoptGLB(optimized) {
		t.Fatal("gltfpack output did not declare EXT_meshopt_compression")
	}
}

func TestConfiguredLDrawPartCanBeOptimized(t *testing.T) {
	root := os.Getenv("TEST_LDRAW_ROOT")
	optimizerPath := os.Getenv("TEST_GLTFPACK_PATH")
	partPath := os.Getenv("TEST_LDRAW_PART_PATH")
	if root == "" || optimizerPath == "" || partPath == "" {
		t.Skip("TEST_LDRAW_ROOT, TEST_GLTFPACK_PATH and TEST_LDRAW_PART_PATH are required")
	}
	files, err := indexLDrawFiles(root)
	if err != nil {
		t.Fatal(err)
	}
	triangles, err := collectLDrawTriangles(partPath, files)
	if err != nil {
		t.Fatalf("collect %s: %v", partPath, err)
	}
	if len(triangles) == 0 {
		t.Fatalf("collect %s returned no triangles", partPath)
	}
	raw, err := buildPartGLB(triangles, PartPreviewGeneratorVersion)
	if err != nil {
		t.Fatal(err)
	}
	optimizer, err := NewGLTFPackOptimizer(optimizerPath)
	if err != nil {
		t.Fatal(err)
	}
	optimized, err := optimizer.Optimize(context.Background(), raw)
	if err != nil {
		t.Fatal(err)
	}
	t.Logf("part=%s faces=%d raw=%d meshopt=%d", partPath, len(triangles), len(raw), len(optimized))
}

func TestCollectLDrawTrianglesRejectsRecursiveInclude(t *testing.T) {
	root := t.TempDir()
	parts := filepath.Join(root, "parts")
	if err := os.MkdirAll(parts, 0o755); err != nil {
		t.Fatal(err)
	}
	content := []byte("1 16 0 0 0 1 0 0 0 1 0 0 0 1 loop.dat\n")
	if err := os.WriteFile(filepath.Join(parts, "loop.dat"), content, 0o644); err != nil {
		t.Fatal(err)
	}
	files, err := indexLDrawFiles(root)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := collectLDrawTriangles("parts/loop.dat", files); err == nil {
		t.Fatal("expected recursive include to fail")
	}
}

func TestCollectLDrawTrianglesAcceptsStudioTexturedFacesAndLongMetadata(t *testing.T) {
	root := t.TempDir()
	parts := filepath.Join(root, "UnOfficial", "parts")
	if err := os.MkdirAll(parts, 0o755); err != nil {
		t.Fatal(err)
	}
	content := "0 PE_TEX_INFO " + strings.Repeat("A", 2*1024*1024) + "\n" +
		"3 16 0 0 0 20 0 0 0 8 0 0 0 1 1 0 1\n" +
		"4 16 0 0 0 20 0 0 20 8 0 0 8 0 0 0 1 1 0 1 1 0 1\n"
	if err := os.WriteFile(filepath.Join(parts, "14769pb079.dat"), []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	files, err := indexLDrawFiles(root)
	if err != nil {
		t.Fatal(err)
	}
	triangles, err := collectLDrawTriangles("parts/14769pb079.dat", files)
	if err != nil {
		t.Fatalf("collect: %v", err)
	}
	if len(triangles) != 3 {
		t.Fatalf("triangles = %d, want 3", len(triangles))
	}
}

func TestCollectLDrawTrianglesFallsBackFromResolutionReferenceToPlainPrimitive(t *testing.T) {
	root := t.TempDir()
	parts := filepath.Join(root, "parts")
	primitives := filepath.Join(root, "UnOfficial", "p")
	if err := os.MkdirAll(parts, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(primitives, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(parts, "uses_resolution_ref.dat"), []byte("1 16 0 0 0 1 0 0 0 1 0 0 0 1 48\\tm04i2000.dat\n1 16 10 0 0 1 0 0 0 1 0 0 0 1 8\\3-8tang.dat\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(primitives, "tm04i2000.dat"), []byte("3 16 0 0 0 10 0 0 0 10 0\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(primitives, "3-8tang.dat"), []byte("3 16 0 0 0 10 0 0 0 10 0\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	files, err := indexLDrawFiles(root)
	if err != nil {
		t.Fatal(err)
	}
	triangles, err := collectLDrawTriangles("parts/uses_resolution_ref.dat", files)
	if err != nil {
		t.Fatalf("collect: %v", err)
	}
	if len(triangles) != 2 {
		t.Fatalf("triangles = %d, want 2", len(triangles))
	}
}
