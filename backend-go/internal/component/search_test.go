package component

import (
	"math"
	"reflect"
	"strings"
	"testing"
)

func TestNormalizeComponentSearch(t *testing.T) {
	width, depth, height := 2.0, 4.0, 3.0
	got, err := normalizeComponentSearch(ComponentSearchFilters{
		Name: "  Castle，tower castle 100%_ ", ComponentID: " ABCD ",
		WidthStud: &width, DepthStud: &depth, HeightPlate: &height,
	})
	if err != nil {
		t.Fatalf("normalize component search: %v", err)
	}
	wantPatterns := []string{"%castle%", "%tower%", `%100\%\_%`}
	if !reflect.DeepEqual(got.NamePatterns, wantPatterns) {
		t.Fatalf("name patterns = %#v, want %#v", got.NamePatterns, wantPatterns)
	}
	if got.ComponentID != "abcd" || !got.HasWidth || !got.HasDepth || !got.HasHeight ||
		got.WidthStud != width || got.DepthStud != depth || got.HeightPlate != height || got.Signature == "" {
		t.Fatalf("normalized filters = %+v", got)
	}
}

func TestNormalizeComponentSearchAllowsPartialDimensions(t *testing.T) {
	depth := 6.0
	got, err := normalizeComponentSearch(ComponentSearchFilters{DepthStud: &depth})
	if err != nil {
		t.Fatalf("normalize partial dimensions: %v", err)
	}
	if got.HasWidth || !got.HasDepth || got.HasHeight || got.DepthStud != depth {
		t.Fatalf("partial dimensions = %+v", got)
	}
}

func TestNormalizeComponentSearchRejectsInvalidValues(t *testing.T) {
	zero, tooLarge, nan := 0.0, 1000.01, math.NaN()
	tests := []ComponentSearchFilters{
		{Name: strings.Repeat("界", 201)},
		{ComponentID: "../private"},
		{WidthStud: &zero},
		{DepthStud: &tooLarge},
		{HeightPlate: &nan},
	}
	for index, input := range tests {
		if _, err := normalizeComponentSearch(input); err == nil {
			t.Fatalf("case %d unexpectedly accepted: %+v", index, input)
		}
	}
}
