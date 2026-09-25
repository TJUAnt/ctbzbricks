//go:build integration

package feedrender_test

import (
	"context"
	"os"
	"testing"
	"time"

	. "github.com/ctbzbricks/brickbuilder/backend-go/internal/feedrender"
)

func TestImageRendererWithBlender(t *testing.T) {
	blenderPath := os.Getenv("FEED_RENDER_INTEGRATION_BLENDER")
	fixturePath := os.Getenv("FEED_RENDER_INTEGRATION_GLB")
	if blenderPath == "" || fixturePath == "" {
		t.Skip("set FEED_RENDER_INTEGRATION_BLENDER and FEED_RENDER_INTEGRATION_GLB to run the offline renderer")
	}
	source, err := os.ReadFile(fixturePath)
	if err != nil {
		t.Fatal(err)
	}
	result, err := NewImageRenderer(blenderPath, 5*time.Minute).Render(context.Background(), source)
	if err != nil {
		t.Fatal(err)
	}
	if result.Engine != PathTracerEngine || result.Fallback || len(result.PNG) == 0 {
		t.Fatalf("unexpected integration result: engine=%q fallback=%t code=%q bytes=%d", result.Engine, result.Fallback, result.FallbackCode, len(result.PNG))
	}
}
