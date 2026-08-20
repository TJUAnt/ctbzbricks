package partlibrary

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestGenerateStudioManifest(t *testing.T) {
	root := t.TempDir()
	ldraw := filepath.Join(root, "ldraw")
	data := filepath.Join(root, "data")
	mustMkdir(t, filepath.Join(ldraw, "parts", "s"))
	mustMkdir(t, filepath.Join(ldraw, "parts", "textures"))
	mustMkdir(t, filepath.Join(ldraw, "UnOfficial", "parts"))
	mustMkdir(t, filepath.Join(ldraw, "p", "48"))
	mustMkdir(t, filepath.Join(ldraw, "connectivity"))
	mustMkdir(t, filepath.Join(ldraw, "collider"))
	mustMkdir(t, data)

	mustWrite(t, filepath.Join(ldraw, "parts", "3001.dat"), "0 Brick 2 x 4\n")
	mustWrite(t, filepath.Join(ldraw, "parts", "untitled.ldr"), "0 Not a top-level part\n")
	mustWrite(t, filepath.Join(ldraw, "UnOfficial", "parts", "3001.dat"), "0 Duplicate\n")
	mustWrite(t, filepath.Join(ldraw, "UnOfficial", "parts", "bl_973.dat"), "0 BrickLink custom\n")
	mustWrite(t, filepath.Join(ldraw, "parts", "s", "3001s01.dat"), "0 Subpart\n")
	mustWrite(t, filepath.Join(ldraw, "p", "48", "stud.dat"), "0 Primitive\n")
	mustWrite(t, filepath.Join(ldraw, "parts", "textures", "3001.png"), "png")
	mustWrite(t, filepath.Join(ldraw, "connectivity", "3001.conn"), "conn")
	mustWrite(t, filepath.Join(ldraw, "collider", "3001.col"), "col")
	mustWrite(t, filepath.Join(data, "ldraw_new.xml"), `<LDrawMapping>
<Material ldraw="15" lego="1" type="" />
<Transformation ldraw="3001.dat" lego="3001" type="" />
<Assembly ldraw="3001c01.dat" lego="73081" type="" />
<Decoration ldraw="3001p01.dat" lego="3001" decoration="88626,0" type="" />
</LDrawMapping>`)
	mustWrite(t, filepath.Join(data, "designid.xml"), `<DesignIdMapping>
<Part designID="3001" alternateDesignIDs="123, 456" />
</DesignIdMapping>`)
	mustWrite(t, filepath.Join(data, "elementInfoList.json"), `[
{"elementId":"300101","blItemNo":"3001","blColorCode":"1","weight":"2.32"},
{"elementId":"300102","blItemNo":"3001","blColorCode":"2","weight":"2.32"},
{"elementId":"973001","blItemNo":"973","blColorCode":"1","weight":"1"}
]`)
	legacy := filepath.Join(root, "legacy_parts.tsv")
	mustWrite(t, legacy, "3001.dat\n3020.dat\n")

	out := filepath.Join(root, "out")
	result, err := GenerateStudioManifest(Options{
		StudioRoot:      root,
		OutDir:          out,
		LegacyPartsFile: legacy,
		GeneratedAt:     time.Date(2026, 8, 15, 0, 0, 0, 0, time.UTC),
	})
	if err != nil {
		t.Fatalf("GenerateStudioManifest: %v", err)
	}
	if result.Manifest.ManifestSHA256 == "" {
		t.Fatal("manifest hash is empty")
	}
	if result.Summary.TopLevelParts.CanonicalDistinctParts != 2 {
		t.Fatalf("canonical top-level parts = %d, want 2", result.Summary.TopLevelParts.CanonicalDistinctParts)
	}
	if result.Summary.TopLevelParts.DuplicatePartNums != 1 {
		t.Fatalf("duplicate part nums = %d, want 1", result.Summary.TopLevelParts.DuplicatePartNums)
	}
	if result.Summary.TopLevelParts.BLPrefixedParts != 1 {
		t.Fatalf("bl-prefixed part count = %d, want 1", result.Summary.TopLevelParts.BLPrefixedParts)
	}
	if got := result.Summary.FileKindCounts["connectivity"]; got != 1 {
		t.Fatalf("connectivity count = %d, want 1", got)
	}
	if got := result.Summary.FileKindCounts["ldraw_other"]; got != 1 {
		t.Fatalf("ldraw_other count = %d, want 1", got)
	}
	if got := result.Summary.FileKindCounts["ldraw_primitive_official"]; got != 1 {
		t.Fatalf("official primitive count = %d, want 1", got)
	}
	if got := result.Summary.MetadataSources.LDrawNewXML.TransformationCount; got != 1 {
		t.Fatalf("transformation count = %d, want 1", got)
	}
	if got := result.Summary.MetadataSources.DesignIDXML.AlternateIDsTotal; got != 2 {
		t.Fatalf("alternate IDs = %d, want 2", got)
	}
	if got := result.Summary.MetadataSources.ElementInfoListJSON.Sample3001Rows; got != 2 {
		t.Fatalf("3001 element rows = %d, want 2", got)
	}
	if result.Coverage == nil {
		t.Fatal("coverage is nil")
	}
	if result.Coverage.Intersection != 1 || result.Coverage.StudioOnly != 1 || result.Coverage.LegacyOnly != 1 {
		t.Fatalf("coverage = %+v, want 1/1/1", result.Coverage)
	}

	result2, err := GenerateStudioManifest(Options{
		StudioRoot:      filepath.Join(root, "ldraw"),
		OutDir:          filepath.Join(root, "out2"),
		LegacyPartsFile: legacy,
		GeneratedAt:     time.Date(2027, 1, 1, 0, 0, 0, 0, time.UTC),
	})
	if err != nil {
		t.Fatalf("GenerateStudioManifest second run: %v", err)
	}
	if result.Manifest.ManifestSHA256 != result2.Manifest.ManifestSHA256 {
		t.Fatalf("manifest hash changed across generatedAt/root form: %s != %s", result.Manifest.ManifestSHA256, result2.Manifest.ManifestSHA256)
	}

	raw, err := os.ReadFile(result.SummaryPath)
	if err != nil {
		t.Fatal(err)
	}
	var summary Summary
	if err := json.Unmarshal(raw, &summary); err != nil {
		t.Fatal(err)
	}
	if summary.ManifestSHA256 != result.Manifest.ManifestSHA256 {
		t.Fatalf("summary hash = %s, want %s", summary.ManifestSHA256, result.Manifest.ManifestSHA256)
	}
}

func mustMkdir(t *testing.T, path string) {
	t.Helper()
	if err := os.MkdirAll(path, 0o755); err != nil {
		t.Fatal(err)
	}
}

func mustWrite(t *testing.T, path, content string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}
