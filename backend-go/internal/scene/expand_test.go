package scene

import (
	"encoding/json"
	"testing"
)

func TestExpandCountsRepeatedNestedInstancesAndIgnoresUnusedDefinitions(t *testing.T) {
	document := Document{
		RootModelID: "root",
		RootInstances: []RootInstance{{
			InstanceID: "root-a", TargetModelID: "root", Transform: IdentityTransform(),
		}},
		Models: []Model{
			{ModelID: "root", References: []Reference{
				instance("sub-a", "sub", "submodel", "sub", 10),
				instance("sub-b", "sub", "submodel", "sub", 20),
			}},
			{ModelID: "sub", References: []Reference{
				instance("part-a", "3001.DAT", "part", "", 2),
			}},
			{ModelID: "unused", References: []Reference{
				instance("unused-part", "3002.dat", "part", "", 0),
			}},
		},
	}

	expanded, err := Expand(document)
	if err != nil {
		t.Fatalf("Expand: %v", err)
	}
	if len(expanded.Parts) != 2 || expanded.SubmodelInstanceCount != 2 {
		t.Fatalf("parts/submodels = %d/%d", len(expanded.Parts), expanded.SubmodelInstanceCount)
	}
	if got := expanded.BOM(); got["3001.dat"] != 2 || got["3002.dat"] != 0 {
		t.Fatalf("BOM = %+v", got)
	}
	if expanded.Parts[0].InstanceID == expanded.Parts[1].InstanceID {
		t.Fatalf("重复模型实例生成了相同实例路径：%q", expanded.Parts[0].InstanceID)
	}
	if expanded.Parts[0].Matrix[12] != 12 || expanded.Parts[0].Matrix[13] != 0 ||
		expanded.Parts[1].Matrix[12] != 22 || expanded.Parts[1].Matrix[13] != 0 {
		t.Fatalf("world transforms = %+v / %+v", expanded.Parts[0].Matrix, expanded.Parts[1].Matrix)
	}
}

func TestExpandMergesMultipleRootsWithoutDeduplicatingInstances(t *testing.T) {
	document := Document{
		RootModelID: "assembly",
		RootInstances: []RootInstance{
			{InstanceID: "left", TargetModelID: "assembly", Transform: translated(0)},
			{InstanceID: "right", TargetModelID: "assembly", Transform: translated(40)},
		},
		Models: []Model{{ModelID: "assembly", References: []Reference{
			instance("part", "3001.dat", "part", "", 5),
		}}},
	}

	expanded, err := Expand(document)
	if err != nil {
		t.Fatalf("Expand: %v", err)
	}
	if len(expanded.Parts) != 2 || expanded.BOM()["3001.dat"] != 2 {
		t.Fatalf("expanded = %+v BOM=%+v", expanded.Parts, expanded.BOM())
	}
	if expanded.Parts[0].Matrix[12] != 5 || expanded.Parts[1].Matrix[12] != 45 {
		t.Fatalf("root transforms = %v / %v", expanded.Parts[0].Matrix[12], expanded.Parts[1].Matrix[12])
	}
}

func TestExpandJSONSupportsLegacyRootModelID(t *testing.T) {
	raw := json.RawMessage(`{"rootModelId":"root","models":[{"modelId":"root","references":[{"instanceId":"part","referenceName":"3001.dat","referenceKind":"part","transform":{"position":{"x":0,"y":0,"z":0},"matrix":[1,0,0,0,1,0,0,0,1]}}]}]}`)
	expanded, err := ExpandJSON(raw)
	if err != nil || len(expanded.Parts) != 1 || expanded.Parts[0].InstanceID != "root_0001/part" {
		t.Fatalf("legacy expansion = %+v error=%v", expanded, err)
	}
}

func TestExpandRejectsCycleAndDuplicateRootInstance(t *testing.T) {
	cycle := Document{
		RootInstances: []RootInstance{{InstanceID: "root", TargetModelID: "loop", Transform: IdentityTransform()}},
		Models: []Model{{ModelID: "loop", References: []Reference{
			instance("again", "loop", "submodel", "loop", 0),
		}}},
	}
	if _, err := Expand(cycle); err == nil {
		t.Fatal("cycle should fail")
	}

	duplicateRoots := Document{
		RootInstances: []RootInstance{
			{InstanceID: "same", TargetModelID: "part-model", Transform: IdentityTransform()},
			{InstanceID: "same", TargetModelID: "part-model", Transform: IdentityTransform()},
		},
		Models: []Model{{ModelID: "part-model", References: []Reference{
			instance("part", "3001.dat", "part", "", 0),
		}}},
	}
	if _, err := Expand(duplicateRoots); err == nil {
		t.Fatal("duplicate root instance should fail")
	}
}

func instance(id, name, kind, target string, x float64) Reference {
	return Reference{
		InstanceID: id, ReferenceName: name, ReferenceKind: kind, TargetModelID: target,
		ColorCode: "16", Transform: translated(x),
	}
}

func translated(x float64) Transform {
	value := IdentityTransform()
	value.Position.X = x
	return value
}
