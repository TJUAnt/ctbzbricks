package component

import (
	"testing"
	"time"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/feedrender"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5/pgtype"
)

func TestPublicFeedCursorRoundTrip(t *testing.T) {
	eventID, err := uuidutil.Parse("23000000-0000-0000-0000-000000000001")
	if err != nil {
		t.Fatalf("parse event UUID: %v", err)
	}
	availableAt := time.Date(2026, 9, 12, 1, 2, 3, 456789000, time.UTC)
	encoded, err := encodePublicFeedCursor(availableAt, eventID, "castle")
	if err != nil {
		t.Fatalf("encode public Feed cursor: %v", err)
	}
	decoded, err := decodePublicFeedCursor(encoded)
	if err != nil {
		t.Fatalf("decode public Feed cursor: %v", err)
	}
	if !decoded.AvailableAt.Valid || !decoded.AvailableAt.Time.Equal(availableAt) ||
		!uuidutil.Equal(decoded.EventID, eventID) || decoded.Query != "castle" {
		t.Fatalf("public Feed cursor round trip = %+v", decoded)
	}
}

func TestPublicFeedCursorRejectsInvalidInput(t *testing.T) {
	for _, value := range []string{"not-base64", "e30", "eyJvY2N1cnJlZEF0IjoiYmFkIn0"} {
		if _, err := decodePublicFeedCursor(value); err == nil {
			t.Fatalf("cursor %q unexpectedly accepted", value)
		}
	}
}

func TestPublicFeedReadyImageMappingRequiresSignedURL(t *testing.T) {
	eventID := mustPublicFeedUUID(t, "23000000-0000-0000-0000-000000000001")
	versionID := mustPublicFeedUUID(t, "23000000-0000-0000-0000-000000000002")
	publisherID := mustPublicFeedUUID(t, "23000000-0000-0000-0000-000000000003")
	componentID := mustPublicFeedUUID(t, "23000000-0000-0000-0000-000000000004")
	imageID := mustPublicFeedUUID(t, "23000000-0000-0000-0000-000000000005")
	storageKey, sha256 := "feed/image.png", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	fileSize := int64(4096)
	now := time.Date(2026, 9, 12, 1, 2, 3, 0, time.UTC)
	row := db.ListComponentPublicFeedRow{
		EventID: eventID, OccurredAt: validPublicFeedTime(now.Add(-time.Minute)), AvailableAt: validPublicFeedTime(now),
		RenderStatus: "ready", ImageArtifactID: imageID, ImageStorageKey: &storageKey, ImageSha256: &sha256,
		ImageFileSize: &fileSize, ComponentVersionID: versionID, PublisherID: publisherID,
		VersionLabel: "1.0.0", Revision: 1, ID: componentID, ContentKind: "user", ContentLocale: "en-US",
		Name: "Fixture", Status: "active", Metadata: []byte(`{}`), CreatedAt: validPublicFeedTime(now), UpdatedAt: validPublicFeedTime(now),
	}
	item := publicFeedItemFromDB(row, map[string]string{storageKey: "https://assets.example/feed/image.png"})
	if item.Render.Status != "ready" || item.Render.Image == nil || item.Render.Image.URL == "" ||
		item.Render.Image.Width != feedrender.ImageWidth || item.Render.Image.Height != feedrender.ImageHeight {
		t.Fatalf("ready Feed image projection = %+v", item.Render)
	}
	fallback := publicFeedItemFromDB(row, nil)
	if fallback.Render.Status != "fallback" || fallback.Render.Image != nil {
		t.Fatalf("unsigned Feed image must map to fallback: %+v", fallback.Render)
	}
}

func mustPublicFeedUUID(t *testing.T, value string) pgtype.UUID {
	t.Helper()
	id, err := uuidutil.Parse(value)
	if err != nil {
		t.Fatal(err)
	}
	return id
}

func validPublicFeedTime(value time.Time) pgtype.Timestamptz {
	return pgtype.Timestamptz{Time: value, Valid: true}
}
