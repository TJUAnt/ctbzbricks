package componentwatch

import (
	"testing"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5/pgtype"
)

func TestWatchCursorRoundTrip(t *testing.T) {
	componentID, err := uuidutil.Parse("22000000-0000-0000-0000-000000000001")
	if err != nil {
		t.Fatalf("parse fixture UUID: %v", err)
	}
	watchedAt := time.Date(2026, 8, 31, 10, 20, 30, 123456000, time.UTC)
	encoded, err := encodeCursor(watchedAt, componentID, "en-US", "castle", "building")
	if err != nil {
		t.Fatalf("encode cursor: %v", err)
	}
	decoded, err := decodeCursor(encoded)
	if err != nil {
		t.Fatalf("decode cursor: %v", err)
	}
	if !decoded.WatchedAt.Valid || !decoded.WatchedAt.Time.Equal(watchedAt) || !uuidutil.Equal(decoded.ComponentID, componentID) ||
		decoded.Locale != "en-US" || decoded.Query != "castle" || decoded.Category != "building" {
		t.Fatalf("cursor round trip = %+v", decoded)
	}
}

func TestWatchCursorRejectsInvalidInput(t *testing.T) {
	for _, value := range []string{"not-base64", "e30", "eyJ3YXRjaGVkQXQiOiJiYWQifQ"} {
		if _, err := decodeCursor(value); err == nil {
			t.Fatalf("cursor %q unexpectedly accepted", value)
		}
	}
}

func TestFeedCursorRoundTripFreezesWindow(t *testing.T) {
	eventID, err := uuidutil.Parse("22000000-0000-0000-0000-000000000002")
	if err != nil {
		t.Fatalf("parse fixture UUID: %v", err)
	}
	windowStart := time.Date(2026, 8, 1, 0, 0, 0, 0, time.UTC)
	occurredAt := time.Date(2026, 8, 31, 10, 20, 30, 123456000, time.UTC)
	encoded, err := encodeFeedCursor(windowStart, occurredAt, eventID)
	if err != nil {
		t.Fatalf("encode Feed cursor: %v", err)
	}
	decoded, err := decodeFeedCursor(encoded)
	if err != nil {
		t.Fatalf("decode Feed cursor: %v", err)
	}
	if !decoded.WindowStart.Equal(windowStart) || !decoded.OccurredAt.Valid ||
		!decoded.OccurredAt.Time.Equal(occurredAt) || !uuidutil.Equal(decoded.EventID, eventID) {
		t.Fatalf("Feed cursor round trip = %+v", decoded)
	}
}

func TestResolveFeedWindowStartUsesDefaultAndRejectsCursorMismatch(t *testing.T) {
	now := time.Date(2026, 9, 9, 12, 0, 0, 0, time.UTC)
	window, err := resolveFeedWindowStart("", decodedFeedCursor{}, now)
	if err != nil || !window.Equal(now.Add(-defaultFeedWindow)) {
		t.Fatalf("default Feed window = %s, error=%v", window, err)
	}
	cursor := decodedFeedCursor{
		WindowStart: window,
		OccurredAt:  timestamp(now),
		EventID:     mustFeedUUID(t, "22000000-0000-0000-0000-000000000003"),
	}
	if _, err := resolveFeedWindowStart("2026-08-01T00:00:00Z", cursor, now); err == nil {
		t.Fatal("Feed cursor accepted a different since boundary")
	}
}

func mustFeedUUID(t *testing.T, value string) pgtype.UUID {
	t.Helper()
	id, err := uuidutil.Parse(value)
	if err != nil {
		t.Fatalf("parse fixture UUID: %v", err)
	}
	return id
}
