package localeutil

import "testing"

func TestNormalizeStrictContract(t *testing.T) {
	t.Parallel()
	tests := []struct {
		input string
		want  string
		ok    bool
	}{
		{input: "zh", want: "zh-CN", ok: true},
		{input: " zh_CN ", want: "zh-CN", ok: true},
		{input: "zh-Hans-SG", want: "zh-CN", ok: true},
		{input: "en", want: "en-US", ok: true},
		{input: "EN_gb", want: "en-US", ok: true},
		{input: "", ok: false},
		{input: "fr-FR", ok: false},
		{input: "zh-Hant-TW", ok: false},
	}
	for _, test := range tests {
		test := test
		t.Run(test.input, func(t *testing.T) {
			t.Parallel()
			got, ok := Normalize(test.input)
			if got != test.want || ok != test.ok {
				t.Fatalf("Normalize(%q) = %q, %v; want %q, %v", test.input, got, ok, test.want, test.ok)
			}
		})
	}
}

func TestDisplayFallsBackWithoutExpandingStrictContract(t *testing.T) {
	t.Parallel()
	for _, input := range []string{"", "fr-FR", "zh-Hant-TW"} {
		if got := Display(input); got != "zh-CN" {
			t.Fatalf("Display(%q) = %q, want zh-CN", input, got)
		}
	}
	if got := Display("en-GB"); got != "en-US" {
		t.Fatalf("Display(en-GB) = %q, want en-US", got)
	}
}
