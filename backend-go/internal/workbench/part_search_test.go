package workbench

import (
	"reflect"
	"testing"
)

func TestNormalizePartDescriptionSearchUsesAllUniqueTokens(t *testing.T) {
	phrase, patterns := normalizePartDescriptionSearch(" Plate，2 x 4 plate% ")
	if phrase != "plate 2 x 4 plate%" || !reflect.DeepEqual(patterns, []string{"%plate%", "%2%", "%x%", "%4%", `%plate\%%`}) {
		t.Fatalf("phrase/patterns = %q / %#v", phrase, patterns)
	}
}
