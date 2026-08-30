package componentdiff

import (
	"encoding/json"
	"errors"
	"testing"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/scene"
)

func TestComparePartsClassifiesStableChanges(t *testing.T) {
	before := []scene.WorldPart{
		worldPart("before-same", "3001.dat", "4", 0),
		worldPart("before-color", "3002.dat", "1", 20),
		worldPart("before-move", "3003.dat", "2", 40),
		worldPart("before-replace", "3004.dat", "3", 60),
		worldPart("before-remove", "3005.dat", "5", 80),
	}
	after := []scene.WorldPart{
		worldPart("renamed-same", "3001.dat", "4", 0),
		worldPart("after-color", "3002.dat", "14", 20),
		worldPart("after-move", "3003.dat", "2", 45),
		worldPart("after-replace", "3010.dat", "3", 60),
		worldPart("after-add", "3006.dat", "6", 100),
	}

	result, err := CompareParts(before, after, Options{})
	if err != nil {
		t.Fatalf("compare parts: %v", err)
	}
	want := Summary{
		BeforeInstances: 5, AfterInstances: 5, UnchangedInstances: 1,
		AddedInstances: 1, RemovedInstances: 1, TransformChangedInstances: 1,
		ColorChangedInstances: 1, ReplacedInstances: 1, BOMChangedPartTypes: 4,
	}
	if result.Summary != want {
		t.Fatalf("summary = %+v, want %+v", result.Summary, want)
	}
	wantKinds := []string{"color_changed", "part_replaced", "transform_changed", "part_removed", "part_added"}
	if len(result.InstanceChanges) != len(wantKinds) {
		t.Fatalf("instance changes = %+v", result.InstanceChanges)
	}
	for index, kind := range wantKinds {
		if result.InstanceChanges[index].Kind != kind {
			t.Fatalf("change %d kind = %q, want %q", index, result.InstanceChanges[index].Kind, kind)
		}
	}
	if delta := result.InstanceChanges[2].TransformDelta; delta == nil || !delta.TranslationChanged || delta.LinearTransformChanged {
		t.Fatalf("unexpected transform delta: %+v", delta)
	}
}

func TestCompareJSONSupportsMultipleRootsAndIgnoresDefinitionOrder(t *testing.T) {
	before := scene.Document{
		RootInstances: []scene.RootInstance{
			{InstanceID: "root-b", TargetModelID: "assembly", Transform: translatedTransform(20)},
			{InstanceID: "root-a", TargetModelID: "assembly", Transform: translatedTransform(0)},
		},
		Models: []scene.Model{{ModelID: "assembly", References: []scene.Reference{{
			InstanceID: "leaf", ReferenceName: "3001.DAT", ReferenceKind: "part", ColorCode: "4", Transform: scene.IdentityTransform(),
		}}}},
	}
	after := scene.Document{
		RootInstances: []scene.RootInstance{
			{InstanceID: "new-a", TargetModelID: "assembly", Transform: translatedTransform(0)},
			{InstanceID: "new-b", TargetModelID: "assembly", Transform: translatedTransform(20)},
		},
		Models: before.Models,
	}

	result, err := CompareJSON(mustJSON(t, before), mustJSON(t, after), Options{})
	if err != nil {
		t.Fatalf("compare snapshots: %v", err)
	}
	if result.Summary.BeforeInstances != 2 || result.Summary.AfterInstances != 2 || result.Summary.UnchangedInstances != 2 || len(result.InstanceChanges) != 0 {
		t.Fatalf("multiple root comparison = %+v", result)
	}
}

func TestComparePartsReportsRepeatedTransformAmbiguity(t *testing.T) {
	before := []scene.WorldPart{
		worldPart("left-1", "3001.dat", "4", 0),
		worldPart("left-2", "3001.dat", "4", 20),
	}
	after := []scene.WorldPart{
		worldPart("right-1", "3001.dat", "4", 40),
		worldPart("right-2", "3001.dat", "4", 60),
	}

	result, err := CompareParts(before, after, Options{})
	if err != nil {
		t.Fatalf("compare parts: %v", err)
	}
	if result.Summary.AmbiguousGroups != 1 || result.Summary.AmbiguousBeforeInstances != 2 || result.Summary.AmbiguousAfterInstances != 2 {
		t.Fatalf("ambiguous summary = %+v", result.Summary)
	}
	if result.Summary.TransformChangedInstances != 0 || len(result.AmbiguousGroups) != 1 {
		t.Fatalf("ambiguous instances were guessed: %+v", result)
	}
	limited, err := CompareParts(before, after, Options{MaxDetails: 3})
	if err != nil || !limited.Truncated || len(limited.AmbiguousGroups) != 0 || limited.Summary.AmbiguousGroups != 1 {
		t.Fatalf("ambiguous detail budget = %+v, %v", limited, err)
	}
}

func TestComparePartsAppliesToleranceAndDetailLimit(t *testing.T) {
	before := []scene.WorldPart{worldPart("same", "3001.dat", "4", 0)}
	after := []scene.WorldPart{
		worldPart("same-enough", "3001.dat", "4", 0.0000004),
		worldPart("added-1", "3002.dat", "2", 20),
		worldPart("added-2", "3003.dat", "3", 40),
	}
	result, err := CompareParts(before, after, Options{MaxDetails: 1})
	if err != nil {
		t.Fatalf("compare parts: %v", err)
	}
	if result.Summary.UnchangedInstances != 1 || result.Summary.AddedInstances != 2 || len(result.InstanceChanges) != 1 || !result.Truncated {
		t.Fatalf("limited result = %+v", result)
	}
}

func TestCompareFromEmptyAndResourceErrors(t *testing.T) {
	document := scene.Document{
		RootModelID: "root",
		Models: []scene.Model{{ModelID: "root", References: []scene.Reference{{
			InstanceID: "leaf", ReferenceName: "3001.dat", ReferenceKind: "part", ColorCode: "4", Transform: scene.IdentityTransform(),
		}}}},
	}
	result, err := CompareFromEmptyJSON(mustJSON(t, document), Options{})
	if err != nil || result.Summary.AddedInstances != 1 || len(result.BOMChanges) != 1 || result.BOMChanges[0].Delta != 1 {
		t.Fatalf("empty comparison = %+v, %v", result, err)
	}
	if _, err := CompareJSON(json.RawMessage(`{}`), mustJSON(t, document), Options{}); !errors.Is(err, ErrInvalidSnapshot) {
		t.Fatalf("invalid snapshot error = %v", err)
	}
	if _, err := CompareParts(nil, []scene.WorldPart{worldPart("one", "3001.dat", "4", 0), worldPart("two", "3002.dat", "4", 20)}, Options{MaxInstances: 1}); !errors.Is(err, ErrTooLarge) {
		t.Fatalf("instance limit error = %v", err)
	}
}

func worldPart(instanceID, partRef, color string, x float64) scene.WorldPart {
	matrix := [16]float64{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, 0, 0, 1}
	return scene.WorldPart{InstanceID: instanceID, PartRef: partRef, ColorCode: color, Matrix: matrix}
}

func translatedTransform(x float64) scene.Transform {
	transform := scene.IdentityTransform()
	transform.Position.X = x
	return transform
}

func mustJSON(t *testing.T, value any) json.RawMessage {
	t.Helper()
	encoded, err := json.Marshal(value)
	if err != nil {
		t.Fatalf("marshal fixture: %v", err)
	}
	return encoded
}
