package componentwatch

import (
	"testing"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
)

func TestWatchCursorRoundTrip(t *testing.T) {
	componentID, err := uuidutil.Parse("22000000-0000-0000-0000-000000000001")
	if err != nil {
		t.Fatalf("parse fixture UUID: %v", err)
	}
	watchedAt := time.Date(2026, 8, 31, 10, 20, 30, 123456000, time.UTC)
	encoded, err := encodeCursor(watchedAt, componentID)
	if err != nil {
		t.Fatalf("encode cursor: %v", err)
	}
	decoded, err := decodeCursor(encoded)
	if err != nil {
		t.Fatalf("decode cursor: %v", err)
	}
	if !decoded.WatchedAt.Valid || !decoded.WatchedAt.Time.Equal(watchedAt) || !uuidutil.Equal(decoded.ComponentID, componentID) {
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

func TestNormalizeNotificationContextFreezesSupportedLocaleAndZone(t *testing.T) {
	context, err := normalizeNotificationContext(NotificationContext{
		Locale: "zh-Hans", Timezone: "Asia/Shanghai", CatalogVersion: "frontend-2026.09.06.1",
	})
	if err != nil {
		t.Fatalf("normalize notification context: %v", err)
	}
	if context.Locale != "zh-CN" || context.Timezone != "Asia/Shanghai" || context.CatalogVersion != "frontend-2026.09.06.1" {
		t.Fatalf("unexpected notification context: %+v", context)
	}
}

func TestNormalizeNotificationContextRejectsUntrustedMachineValues(t *testing.T) {
	for field, context := range map[string]NotificationContext{
		"locale":         {Locale: "fr-FR", Timezone: "UTC", CatalogVersion: "frontend-2026.09.06.1"},
		"timezone":       {Locale: "en-US", Timezone: "../../etc/passwd", CatalogVersion: "frontend-2026.09.06.1"},
		"catalogVersion": {Locale: "en-US", Timezone: "UTC", CatalogVersion: "version with spaces"},
	} {
		if _, err := normalizeNotificationContext(context); err == nil {
			t.Fatalf("%s context unexpectedly accepted", field)
		}
	}
}
