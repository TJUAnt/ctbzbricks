package component

import "testing"

func TestParseComponentSizeQuery(t *testing.T) {
	tests := []struct {
		name  string
		query string
		want  componentSizeFilter
		ok    bool
	}{
		{name: "three dimensions sorted", query: "6 x 1.1 × 5", want: componentSizeFilter{DimensionCount: 3, A: 1.1, B: 5, C: 6}, ok: true},
		{name: "two dimensions sorted", query: "3X1", want: componentSizeFilter{DimensionCount: 2, A: 1, B: 3}, ok: true},
		{name: "decimal without leading zero", query: ".5x2", want: componentSizeFilter{DimensionCount: 2, A: .5, B: 2}, ok: true},
		{name: "ordinary name", query: "car 2x4", ok: false},
		{name: "one dimension", query: "3", ok: false},
		{name: "incomplete dimensions", query: "1x2x", ok: false},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			got, ok := parseComponentSizeQuery(test.query)
			if ok != test.ok || got != test.want {
				t.Fatalf("parseComponentSizeQuery(%q) = %+v, %v; want %+v, %v", test.query, got, ok, test.want, test.ok)
			}
		})
	}
}
