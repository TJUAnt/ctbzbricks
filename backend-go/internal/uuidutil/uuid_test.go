package uuidutil

import "testing"

func TestNewParseAndStringRoundTrip(t *testing.T) {
	generated, err := New()
	if err != nil {
		t.Fatalf("new UUID: %v", err)
	}
	formatted := String(generated)
	parsed, err := Parse(formatted)
	if err != nil {
		t.Fatalf("parse UUID: %v", err)
	}
	if !Equal(generated, parsed) {
		t.Fatalf("round trip mismatch: %s", formatted)
	}
}

func TestParseRejectsInvalidUUID(t *testing.T) {
	if _, err := Parse("not-a-uuid"); err == nil {
		t.Fatal("expected invalid UUID error")
	}
}
