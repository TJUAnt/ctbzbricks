package ingestion

import (
	"archive/zip"
	"bytes"
	"os"
	"testing"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/scene"
)

func TestMaterializeImportParsesLDrawBOMAndSubmodels(t *testing.T) {
	content := []byte(`0 FILE root.ldr
0 Name: Root
1 16 0 0 0 1 0 0 0 1 0 0 0 1 child.ldr
0 FILE child.ldr
1 4 1 2 3 1 0 0 0 1 0 0 0 1 3001.dat
`)
	result, err := materializeImport(content, artifactTypeLDrawMPD, "fixture.mpd", "component-repo-ldraw-parser-v2")
	if err != nil {
		t.Fatalf("materialize import: %v", err)
	}
	if result.RootModelID == nil || *result.RootModelID != "model_0001" {
		t.Fatalf("root model = %v", result.RootModelID)
	}
	if result.BOM["3001.dat"] != 1 {
		t.Fatalf("bom = %+v", result.BOM)
	}
	if result.Summary["partInstanceCount"] != 1 || result.Summary["submodelInstanceCount"] != 1 {
		t.Fatalf("summary = %+v", result.Summary)
	}
	if result.StructureHash == "" || result.GeometryHash == "" || result.InterfaceSignature == "" {
		t.Fatalf("hashes were not computed: %+v", result)
	}
}

func TestMaterializeImportExtractsStudioExchange(t *testing.T) {
	var archive bytes.Buffer
	writer := zip.NewWriter(&archive)
	member, err := writer.Create("model.ldr")
	if err != nil {
		t.Fatalf("create member: %v", err)
	}
	if _, err := member.Write([]byte("1 16 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n")); err != nil {
		t.Fatalf("write member: %v", err)
	}
	if err := writer.Close(); err != nil {
		t.Fatalf("close archive: %v", err)
	}
	result, err := materializeImport(archive.Bytes(), artifactTypeStudioIO, "studio.io", "component-repo-ldraw-parser-v2")
	if err != nil {
		t.Fatalf("materialize studio import: %v", err)
	}
	if result.ExchangeFilename != "studio.ldr" || len(result.ExchangeBytes) == 0 {
		t.Fatalf("derived exchange = %q %d bytes", result.ExchangeFilename, len(result.ExchangeBytes))
	}
	if result.BOM["3001.dat"] != 1 {
		t.Fatalf("bom = %+v", result.BOM)
	}
}

func TestMaterializeImportBOMUsesExpandedSceneInstances(t *testing.T) {
	content := []byte(`0 FILE root.ldr
1 16 10 0 0 1 0 0 0 1 0 0 0 1 child.ldr
1 16 20 0 0 1 0 0 0 1 0 0 0 1 child.ldr
0 FILE child.ldr
1 16 0 2 0 1 0 0 0 1 0 0 0 1 nested.ldr
1 16 0 4 0 1 0 0 0 1 0 0 0 1 nested.ldr
0 FILE nested.ldr
1 4 0 0 3 1 0 0 0 1 0 0 0 1 3001.DAT
0 FILE unused.ldr
1 1 0 0 0 1 0 0 0 1 0 0 0 1 3002.dat
`)
	result, err := materializeImport(content, artifactTypeLDrawMPD, "nested.mpd", "component-repo-ldraw-parser-v2")
	if err != nil {
		t.Fatalf("materialize import: %v", err)
	}
	if result.BOM["3001.dat"] != 4 || result.BOM["3002.dat"] != 0 || len(result.BOM) != 1 {
		t.Fatalf("expanded BOM = %+v", result.BOM)
	}
	if result.Summary["partInstanceCount"] != 4 || result.Summary["submodelInstanceCount"] != 6 {
		t.Fatalf("expanded summary = %+v", result.Summary)
	}
	roots, ok := result.Document["rootInstances"].([]scene.RootInstance)
	if !ok || len(roots) != 1 || roots[0].TargetModelID != "model_0001" {
		t.Fatalf("rootInstances = %#v", result.Document["rootInstances"])
	}
}

func TestMaterializeImportTrackedStudioFixtureMatchesDeclaredBrickCount(t *testing.T) {
	content, err := os.ReadFile("../../../test.io")
	if err != nil {
		t.Fatalf("read tracked Studio fixture: %v", err)
	}
	result, err := materializeImport(content, artifactTypeStudioIO, "test.io", "component-repo-ldraw-parser-v2")
	if err != nil {
		t.Fatalf("materialize tracked Studio fixture: %v", err)
	}
	quantity := 0
	for _, count := range result.BOM {
		quantity += count
	}
	if quantity != 210 || result.Summary["partInstanceCount"] != 210 {
		t.Fatalf("tracked Studio BOM quantity/summary = %d/%v", quantity, result.Summary["partInstanceCount"])
	}
}

func BenchmarkMaterializeImportTrackedStudioFixture(b *testing.B) {
	content, err := os.ReadFile("../../../test.io")
	if err != nil {
		b.Fatalf("read tracked Studio fixture: %v", err)
	}
	b.ReportAllocs()
	b.ResetTimer()
	for range b.N {
		if _, err := materializeImport(content, artifactTypeStudioIO, "test.io", "component-repo-ldraw-parser-v2"); err != nil {
			b.Fatalf("materialize tracked Studio fixture: %v", err)
		}
	}
}
