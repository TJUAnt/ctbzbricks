package workbench

import (
	"reflect"
	"testing"
)

func TestParsePartSearchQuerySeparatesKeywordsAndExactDimensions(t *testing.T) {
	keywords, dimensions, err := parsePartSearchQuery("Tile, 4x2 1×2×3 tile")
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(keywords, []string{"tile"}) {
		t.Fatalf("keywords = %#v", keywords)
	}
	if !reflect.DeepEqual(dimensions, [][]float64{{2, 4}, {1, 2, 3}}) {
		t.Fatalf("dimensions = %#v", dimensions)
	}
}

func TestParsePartSearchQueryKeepsNonDimensionFragmentsAsSourceKeywords(t *testing.T) {
	keywords, dimensions, err := parsePartSearchQuery("3001.dat red-brick")
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(keywords, []string{"3001.dat", "red-brick"}) || len(dimensions) != 0 {
		t.Fatalf("keywords/dimensions = %#v / %#v", keywords, dimensions)
	}
}
