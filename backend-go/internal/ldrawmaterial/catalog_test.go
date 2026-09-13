package ldrawmaterial

import (
	"math"
	"testing"
)

func TestLookupClassifiesCommonLDrawMaterials(t *testing.T) {
	tests := []struct {
		code, class string
		alpha       float64
		metallic    bool
	}{
		{code: "14", class: Plastic, alpha: 1},
		{code: "40", class: Glass, alpha: 128.0 / 255},
		{code: "256", class: Rubber, alpha: 1},
		{code: "80", class: Metal, alpha: 1, metallic: true},
		{code: "114", class: Glitter, alpha: 128.0 / 255, metallic: true},
		{code: "132", class: Speckle, alpha: 1, metallic: true},
		{code: "183", class: Pearl, alpha: 1, metallic: true},
		{code: "334", class: Chrome, alpha: 1, metallic: true},
		{code: "601", class: Luminous, alpha: 250.0 / 255},
	}
	for _, test := range tests {
		value := Lookup(test.code)
		if value.Class != test.class || math.Abs(value.Alpha-test.alpha) > 1e-8 || (value.Metallic > 0) != test.metallic {
			t.Errorf("Lookup(%q) = %+v", test.code, value)
		}
	}
}

func TestCatalogMatchesPinnedStudioLDConfig(t *testing.T) {
	if len(catalog) != 148 {
		t.Fatalf("Studio catalog size = %d, want 148", len(catalog))
	}
	glass := Lookup("40")
	if glass.Transmission <= 0 || glass.IOR <= 1 || glass.Clearcoat <= 0 {
		t.Fatalf("glass physical profile = %+v", glass)
	}
	if glow := Lookup("601"); glow.EmissiveStrength <= 0 {
		t.Fatalf("luminous physical profile = %+v", glow)
	}
	if chrome, pearl := Lookup("334"), Lookup("183"); chrome.Metallic <= pearl.Metallic || chrome.Roughness >= pearl.Roughness {
		t.Fatalf("chrome=%+v pearl=%+v", chrome, pearl)
	}
}

func TestLookupStoresGLTFLinearColor(t *testing.T) {
	yellow := Lookup("14")
	if yellow.BaseColor[0] >= 0.9 || yellow.BaseColor[0] <= 0.8 {
		t.Fatalf("yellow red linear channel = %.4f", yellow.BaseColor[0])
	}
}

func TestLookupNormalizesStudioEmbeddedMaterialCode(t *testing.T) {
	standard := Lookup("40")
	embedded := Lookup("100040")
	if embedded != standard || embedded.Class != Glass {
		t.Fatalf("embedded Studio material = %#v, standard = %#v", embedded, standard)
	}
}
