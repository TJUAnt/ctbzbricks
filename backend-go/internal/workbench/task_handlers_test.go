package workbench

import (
	"encoding/binary"
	"encoding/json"
	"testing"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
)

func TestBuildComponentGLBSkipsMissingPartGeometry(t *testing.T) {
	identity := [16]float64{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1}
	parts := []componentWorldPart{
		{instanceID: "available", partRef: "3001.dat", colorCode: "4", matrix: identity},
		{instanceID: "missing", partRef: "missing.dat", colorCode: "1", matrix: identity},
	}
	triangles := map[string][]ldrawTriangle{
		"3001.dat": {{{0, 0, 0}, {20, 0, 0}, {0, 20, 0}}},
	}

	glb, bounds, err := buildComponentGLB(parts, triangles, PreviewGeneratorVersion)
	if err != nil {
		t.Fatalf("build partial GLB: %v", err)
	}
	document := decodeComponentGLBJSON(t, glb)
	if got := len(document["nodes"].([]any)); got != 2 {
		t.Fatalf("partial GLB nodes = %d, want root plus one available instance", got)
	}
	if bounds == nil || bounds.complete {
		t.Fatalf("partial bounds = %+v, want incomplete rendered bounds", bounds)
	}
	if bounds.logicalWidthStud != 1 || bounds.logicalHeightPlate != 2.5 || bounds.logicalDepthStud != 0 {
		t.Fatalf("logical bounds = %+v", bounds)
	}
	if missing := missingComponentPartRefs([]string{"3001.dat", "missing.dat"}, map[string]bool{"3001.dat": true}); len(missing) != 1 || missing[0] != "missing.dat" {
		t.Fatalf("missing refs = %v", missing)
	}

	empty, emptyBounds, err := buildComponentGLB(parts[1:], map[string][]ldrawTriangle{}, PreviewGeneratorVersion)
	if err != nil {
		t.Fatalf("build empty partial GLB: %v", err)
	}
	if got := len(decodeComponentGLBJSON(t, empty)["nodes"].([]any)); got != 1 {
		t.Fatalf("empty partial GLB nodes = %d, want root only", got)
	}
	if emptyBounds != nil {
		t.Fatalf("empty bounds = %+v, want nil", emptyBounds)
	}
}

func TestBuildComponentGLBBoundsMergeRotatedMultipleRoots(t *testing.T) {
	parts := []componentWorldPart{
		{instanceID: "left", partRef: "part.dat", colorCode: "4", matrix: [16]float64{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1}},
		// 绕 Y 轴旋转 90 度并平移到 X=60，验证不能仅变换局部 AABB 的 min/max。
		{instanceID: "right", partRef: "part.dat", colorCode: "4", matrix: [16]float64{0, 0, -1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 60, 0, 0, 1}},
	}
	triangles := map[string][]ldrawTriangle{
		"part.dat": {{{0, 0, 0}, {20, 0, 0}, {0, 8, 40}}},
	}

	_, bounds, err := buildComponentGLB(parts, triangles, PreviewGeneratorVersion)
	if err != nil {
		t.Fatalf("build multi-root bounds: %v", err)
	}
	if bounds == nil || !bounds.complete {
		t.Fatalf("bounds = %+v, want complete", bounds)
	}
	if bounds.minimum != [3]float64{0, 0, -20} || bounds.maximum != [3]float64{100, 8, 40} {
		t.Fatalf("world bbox = min %v max %v", bounds.minimum, bounds.maximum)
	}
	if bounds.logicalWidthStud != 5 || bounds.logicalDepthStud != 3 || bounds.logicalHeightPlate != 1 {
		t.Fatalf("logical bounds = %+v", bounds)
	}
}

func decodeComponentGLBJSON(t *testing.T, glb []byte) map[string]any {
	t.Helper()
	if len(glb) < 20 || string(glb[:4]) != "glTF" {
		t.Fatalf("invalid GLB header")
	}
	jsonLength := int(binary.LittleEndian.Uint32(glb[12:16]))
	if 20+jsonLength > len(glb) {
		t.Fatalf("invalid GLB JSON length %d", jsonLength)
	}
	var document map[string]any
	if err := json.Unmarshal(glb[20:20+jsonLength], &document); err != nil {
		t.Fatalf("decode GLB JSON: %v", err)
	}
	return document
}

func TestValidateInputUsesFrozenDomainFacts(t *testing.T) {
	validDocument := json.RawMessage(`{
		"rootModelId":"root",
		"models":[
			{"modelId":"root","references":[
				{"instanceId":"sub-1","referenceName":"sub","referenceKind":"submodel","targetModelId":"sub","transform":{"position":{"x":10,"y":0,"z":0},"matrix":[1,0,0,0,1,0,0,0,1]}}
			]},
			{"modelId":"sub","references":[
				{"instanceId":"part-1","referenceName":"3001.dat","referenceKind":"part","targetModelId":"","transform":{"position":{"x":0,"y":2,"z":0},"matrix":[1,0,0,0,1,0,0,0,1]}}
			]}
		]
	}`)
	base := db.GetValidationTaskInputRow{
		InterfaceSignature:          repeatedHex('1'),
		StructureHash:               repeatedHex('2'),
		GeometryHash:                repeatedHex('3'),
		Document:                    validDocument,
		Bom:                         json.RawMessage(`{"3001.dat":1}`),
		ParseIssues:                 json.RawMessage(`[]`),
		SourceArtifactType:          "ldraw_ldr",
		SourceSha256:                repeatedHex('0'),
		SourceVerificationStatus:    "verified",
		PartLibraryConsistent:       true,
		ValidExternalInterfaceCount: 1,
	}

	t.Run("valid graph with no assembly relations passes", func(t *testing.T) {
		_, issues := validateInput(base)
		if len(issues) != 0 {
			t.Fatalf("valid input issues = %+v", issues)
		}
	})

	t.Run("missing frozen part fails parts resolution", func(t *testing.T) {
		input := base
		input.UnresolvedPartCount = 1
		assertValidationFailure(t, input, "component_repo.validation.parts_resolved")
	})

	t.Run("BOM must match recursively expanded leaf parts", func(t *testing.T) {
		input := base
		input.Bom = json.RawMessage(`{"3001.dat":2}`)
		assertValidationFailure(t, input, "component_repo.validation.parts_resolved")
	})

	t.Run("multiple scene roots are merged without deduplicating parts", func(t *testing.T) {
		input := base
		input.Document = json.RawMessage(`{
			"rootModelId":"root",
			"rootInstances":[
				{"instanceId":"left","targetModelId":"root","transform":{"position":{"x":0,"y":0,"z":0},"matrix":[1,0,0,0,1,0,0,0,1]}},
				{"instanceId":"right","targetModelId":"root","transform":{"position":{"x":40,"y":0,"z":0},"matrix":[1,0,0,0,1,0,0,0,1]}}
			],
			"models":[{"modelId":"root","references":[
				{"instanceId":"part","referenceName":"3001.dat","referenceKind":"part","targetModelId":"","transform":{"position":{"x":0,"y":0,"z":0},"matrix":[1,0,0,0,1,0,0,0,1]}}
			]}]
		}`)
		input.Bom = json.RawMessage(`{"3001.dat":2}`)
		_, issues := validateInput(input)
		if len(issues) != 0 {
			t.Fatalf("multi-root input issues = %+v", issues)
		}
	})

	t.Run("cyclic scene graph fails transforms and bounding box", func(t *testing.T) {
		input := base
		input.Document = json.RawMessage(`{"rootModelId":"root","models":[{"modelId":"root","references":[{"instanceId":"loop","referenceName":"root","referenceKind":"submodel","targetModelId":"root","transform":{"position":{"x":0,"y":0,"z":0},"matrix":[1,0,0,0,1,0,0,0,1]}}]}]}`)
		assertValidationFailure(t, input, "component_repo.validation.transforms_valid")
		assertValidationFailure(t, input, "component_repo.validation.bbox_calculated")
	})

	t.Run("persisted relation and interface inconsistencies fail", func(t *testing.T) {
		input := base
		input.InvalidRelationCount = 1
		input.InvalidInterfaceCount = 1
		assertValidationFailure(t, input, "component_repo.validation.relations_valid")
		assertValidationFailure(t, input, "component_repo.validation.interfaces_valid")
	})
}

func assertValidationFailure(t *testing.T, input db.GetValidationTaskInputRow, code string) {
	t.Helper()
	_, issues := validateInput(input)
	for _, issue := range issues {
		if issue["code"] == code {
			return
		}
	}
	t.Fatalf("missing validation failure %s in %+v", code, issues)
}

func repeatedHex(value byte) string {
	buffer := make([]byte, 64)
	for index := range buffer {
		buffer[index] = value
	}
	return string(buffer)
}
