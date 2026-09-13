package feedrender

import (
	"context"
	"errors"
	"testing"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
)

func TestHandlerRejectsNonCanonicalPayloadBeforePersistence(t *testing.T) {
	for _, payload := range []string{
		`{"eventId":"id","componentVersionId":"id","renderProfile":"feed_card_3x2","rendererVersion":"component-feed-renderer-v4","unknown":true}`,
		`{"eventId":"id","componentVersionId":"id","renderProfile":"feed_card_3x2","rendererVersion":"component-feed-renderer-v4"}{}`,
	} {
		_, err := (&Handler{}).Handle(context.Background(), task.ClaimedTask{Payload: []byte(payload)})
		var failure *task.Failure
		if !errors.As(err, &failure) || failure.Retryable || failure.Code != "component_repo.feed_render_unavailable" {
			t.Fatalf("invalid payload failure = %#v", err)
		}
	}
}

func TestFeedArtifactIdentityIncludesRenderedBytes(t *testing.T) {
	cycles := feedArtifactID("version", "source", "cycles-png")
	fallback := feedArtifactID("version", "source", "raster-png")
	if !cycles.Valid || !fallback.Valid || cycles.Bytes == fallback.Bytes {
		t.Fatalf("rendered output must produce distinct immutable identities: cycles=%v fallback=%v", cycles, fallback)
	}
}
