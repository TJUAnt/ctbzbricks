package component

import (
	"testing"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
)

func TestComponentListCursorRoundTripFreezesOrderingAndFilters(t *testing.T) {
	t.Parallel()
	updatedAt := time.Date(2026, 9, 13, 12, 34, 56, 789, time.UTC)
	id, err := uuidutil.Parse("20000000-0000-0000-0000-000000000070")
	if err != nil {
		t.Fatalf("parse fixture UUID: %v", err)
	}

	encoded, err := encodeComponentListCursor(updatedAt, id, "zh-CN", "火车", "vehicle", "active")
	if err != nil {
		t.Fatalf("encode cursor: %v", err)
	}
	decoded, err := decodeComponentListCursor(encoded)
	if err != nil {
		t.Fatalf("decode cursor: %v", err)
	}
	if !decoded.UpdatedAt.Valid || !decoded.UpdatedAt.Time.Equal(updatedAt) ||
		uuidutil.String(decoded.ComponentID) != uuidutil.String(id) || decoded.Locale != "zh-CN" ||
		decoded.Query != "火车" || decoded.Category != "vehicle" || decoded.Status != "active" {
		t.Fatalf("cursor fields changed: %+v", decoded)
	}
}

func TestComponentListCursorRejectsMalformedValue(t *testing.T) {
	t.Parallel()
	if _, err := decodeComponentListCursor("not-a-valid-cursor"); err == nil {
		t.Fatal("malformed cursor must be rejected")
	}
}
