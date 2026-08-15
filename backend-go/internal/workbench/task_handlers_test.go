package workbench

import (
	"encoding/json"
	"testing"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
)

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
