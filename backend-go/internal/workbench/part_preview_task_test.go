package workbench

import (
	"encoding/binary"
	"os"
	"path/filepath"
	"testing"
)

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
