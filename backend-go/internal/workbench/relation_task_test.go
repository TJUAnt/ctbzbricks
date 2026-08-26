package workbench

import (
	"encoding/json"
	"testing"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
)

func TestDetectComponentRelationsBuildsStudTubeRelation(t *testing.T) {
	document := mustJSON(map[string]any{
		"rootModelId": "root",
		"models": []any{map[string]any{
			"modelId": "root",
			"references": []any{
				map[string]any{"instanceId": "a", "referenceName": "3001.dat", "referenceKind": "part", "colorCode": "1", "transform": map[string]any{"position": map[string]any{"x": 0, "y": 0, "z": 0}, "matrix": []float64{1, 0, 0, 0, 1, 0, 0, 0, 1}}},
				map[string]any{"instanceId": "b", "referenceName": "3002.dat", "referenceKind": "part", "colorCode": "1", "transform": map[string]any{"position": map[string]any{"x": 0, "y": 0, "z": 0}, "matrix": []float64{1, 0, 0, 0, 1, 0, 0, 0, 1}}},
			},
		}},
	})
	candidateID, _ := uuidutil.Parse("77000000-0000-0000-0000-000000000009")
	libraryID, _ := uuidutil.Parse("77000000-0000-0000-0000-000000000020")
	identity := [9]float64{1, 0, 0, 0, 1, 0, 0, 0, 1}
	definitions := []relationDefinition{
		{id: 1, partRef: "3001.dat", kind: "stud", normalizedType: "stud", gender: "M", orientation: identity, direction: [3]float64{0, 1, 0}, confidence: 1},
		{id: 2, partRef: "3002.dat", kind: "tube", normalizedType: "anti_stud", gender: "F", orientation: identity, direction: [3]float64{0, -1, 0}, confidence: 1},
	}
	connectors, relations, signature, err := detectComponentRelations(json.RawMessage(document), candidateID, libraryID, definitions, map[string]bool{"3001.dat": true, "3002.dat": true})
	if err != nil {
		t.Fatalf("detectComponentRelations: %v", err)
	}
	if len(connectors) != 2 || len(relations) != 1 {
		t.Fatalf("connectors/relations = %d/%d", len(connectors), len(relations))
	}
	if relations[0].connectionType != "stud_tube" || !relations[0].verified || len(signature) != 64 {
		t.Fatalf("relation/signature = %+v / %q", relations[0], signature)
	}
	if !connectors[0].clearanceData || !connectors[1].clearanceData {
		t.Fatalf("clearance flags = %+v", connectors)
	}
}
