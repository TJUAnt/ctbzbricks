package feedrender

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"image"
	"image/color"
	"image/png"
	"os"
	"strings"
	"testing"
	"time"
)

func TestCyclesMaterialOverridesUsesSharedPhysicalProfile(t *testing.T) {
	value, err := cyclesMaterialOverrides(boxGLBWithMaterial(t, "LDraw 40"))
	if err != nil {
		t.Fatal(err)
	}
	var overrides map[string]cyclesMaterial
	if err := json.Unmarshal(value, &overrides); err != nil {
		t.Fatal(err)
	}
	glass := overrides["LDraw 40"]
	if glass.ProfileVersion != "ldraw-studio-pbr-v1" || glass.Class != "glass" || glass.Transmission <= 0 || glass.IOR <= 1 {
		t.Fatalf("Cycles glass profile = %+v", glass)
	}
}

type rendererStub struct {
	result RenderedImage
	err    error
	calls  int
}

func (s *rendererStub) Render(context.Context, []byte) (RenderedImage, error) {
	s.calls++
	return s.result, s.err
}

func TestRenderPipelineUsesCyclesResultWithoutFallback(t *testing.T) {
	primary := &rendererStub{result: RenderedImage{PNG: []byte("cycles"), Engine: PathTracerEngine}}
	fallback := &rendererStub{result: RenderedImage{PNG: []byte("raster"), Engine: RasterEngine}}
	result, err := (&renderPipeline{primary: primary, fallback: fallback}).Render(context.Background(), []byte("glb"))
	if err != nil {
		t.Fatal(err)
	}
	if string(result.PNG) != "cycles" || result.Fallback || primary.calls != 1 || fallback.calls != 0 {
		t.Fatalf("unexpected primary result: %#v calls=%d/%d", result, primary.calls, fallback.calls)
	}
}

func TestRenderPipelineFallsBackWhenCyclesFails(t *testing.T) {
	primary := &rendererStub{err: errors.New("offline renderer unavailable")}
	fallback := &rendererStub{result: RenderedImage{PNG: []byte("raster"), Engine: RasterEngine}}
	result, err := (&renderPipeline{primary: primary, fallback: fallback}).Render(context.Background(), []byte("glb"))
	if err != nil {
		t.Fatal(err)
	}
	if string(result.PNG) != "raster" || !result.Fallback || result.FallbackCode != "path_tracer_failed" || fallback.calls != 1 {
		t.Fatalf("unexpected fallback result: %#v calls=%d", result, fallback.calls)
	}
}

func TestBlenderCyclesRendererUsesIsolatedPathsAndValidatesPNG(t *testing.T) {
	runner := func(_ context.Context, executable string, args []string, directory string) error {
		if executable != "/fixed/blender" || directory == "" {
			t.Fatalf("unexpected command boundary: %q %q", executable, directory)
		}
		if len(args) < 10 || args[0] != "--background" || args[1] != "--factory-startup" || args[2] != "--disable-autoexec" {
			t.Fatalf("unexpected Blender arguments: %#v", args)
		}
		outputPath := args[len(args)-7]
		file, err := os.Create(outputPath)
		if err != nil {
			return err
		}
		imageValue := image.NewRGBA(image.Rect(0, 0, ImageWidth, ImageHeight))
		imageValue.SetRGBA(ImageWidth/2, ImageHeight/2, color.RGBA{R: 255, A: 255})
		encodeErr := png.Encode(file, imageValue)
		closeErr := file.Close()
		if encodeErr != nil {
			return encodeErr
		}
		return closeErr
	}
	renderer := &blenderCyclesRenderer{path: "/fixed/blender", timeout: time.Second, run: runner}
	result, err := renderer.Render(context.Background(), boxGLB(t))
	if err != nil {
		t.Fatal(err)
	}
	if result.Engine != PathTracerEngine || result.Fallback || len(result.PNG) == 0 {
		t.Fatalf("unexpected Cycles result: %#v", result)
	}
}

func TestRenderPipelineDoesNotFallbackAfterTaskCancellation(t *testing.T) {
	primary := &rendererStub{err: context.Canceled}
	fallback := &rendererStub{result: RenderedImage{PNG: []byte("raster"), Engine: RasterEngine}}
	_, err := (&renderPipeline{primary: primary, fallback: fallback}).Render(context.Background(), []byte("glb"))
	if !errors.Is(err, context.Canceled) || fallback.calls != 0 {
		t.Fatalf("cancellation result = %v, fallback calls = %d", err, fallback.calls)
	}
}

func TestRenderPipelineDoesNotFallbackAfterParentDeadline(t *testing.T) {
	ctx, cancel := context.WithDeadline(context.Background(), time.Now().Add(-time.Second))
	defer cancel()
	primary := &rendererStub{err: context.DeadlineExceeded}
	fallback := &rendererStub{result: RenderedImage{PNG: []byte("raster"), Engine: RasterEngine}}
	_, err := (&renderPipeline{primary: primary, fallback: fallback}).Render(ctx, []byte("glb"))
	if !errors.Is(err, context.DeadlineExceeded) || fallback.calls != 0 {
		t.Fatalf("deadline result = %v, fallback calls = %d", err, fallback.calls)
	}
}

func TestCleanTransparentPNGRemovesShadowCatcherVeil(t *testing.T) {
	input := image.NewNRGBA(image.Rect(0, 0, 3, 1))
	input.SetNRGBA(0, 0, color.NRGBA{A: 20})
	input.SetNRGBA(1, 0, color.NRGBA{R: 40, G: 30, B: 20, A: 64})
	input.SetNRGBA(2, 0, color.NRGBA{R: 200, G: 180, B: 30, A: 255})
	var encoded bytes.Buffer
	if err := png.Encode(&encoded, input); err != nil {
		t.Fatal(err)
	}
	output, err := cleanTransparentPNG(encoded.Bytes())
	if err != nil {
		t.Fatal(err)
	}
	decoded, err := png.Decode(bytes.NewReader(output))
	if err != nil {
		t.Fatal(err)
	}
	if _, _, _, alpha := decoded.At(0, 0).RGBA(); alpha != 0 {
		t.Fatalf("background alpha = %d, want 0", alpha)
	}
	if _, _, _, alpha := decoded.At(1, 0).RGBA(); alpha>>8 != 40 {
		t.Fatalf("shadow alpha = %d, want 40", alpha>>8)
	}
	if red, green, blue, alpha := decoded.At(2, 0).RGBA(); red>>8 != 200 || green>>8 != 180 || blue>>8 != 30 || alpha>>8 != 255 {
		t.Fatalf("opaque pixel changed: rgba=(%d,%d,%d,%d)", red>>8, green>>8, blue>>8, alpha>>8)
	}
}

func TestBlenderEnvironmentExcludesWorkerCredentials(t *testing.T) {
	t.Setenv("DATABASE_URL", "postgres://secret")
	t.Setenv("SUPABASE_SECRET_KEY", "secret-key")
	t.Setenv("PATH", "/safe/path")
	environment := blenderEnvironment("/isolated")
	joined := strings.Join(environment, "\n")
	if strings.Contains(joined, "DATABASE_URL") || strings.Contains(joined, "SUPABASE_SECRET_KEY") {
		t.Fatalf("Blender inherited Worker credentials: %q", joined)
	}
	if !strings.Contains(joined, "PATH=/safe/path") || !strings.Contains(joined, "BLENDER_USER_CONFIG=/isolated/blender-user") {
		t.Fatalf("Blender environment missed required runtime values: %q", joined)
	}
}
