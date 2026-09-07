package pixel2d

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"image"
	"image/color"
	"image/png"
	"os"
	"reflect"
	"testing"
)

// TestPythonQuantizationGolden 用迁移前固化结果校验颜色、坐标及侧面元数据，不在 Go 测试中启动 Python。
func TestPythonQuantizationGolden(t *testing.T) {
	data, e := os.ReadFile("testdata/quantization.json")
	if e != nil {
		t.Fatal(e)
	}
	var cases []struct {
		Name     string   `json:"name"`
		Settings Settings `json:"settings"`
		Expected Project  `json:"expected"`
	}
	if e = json.Unmarshal(data, &cases); e != nil {
		t.Fatal(e)
	}
	for _, tc := range cases {
		t.Run(tc.Name, func(t *testing.T) {
			source, e := os.ReadFile("testdata/" + tc.Name + ".png")
			if e != nil {
				t.Fatal(e)
			}
			got, png, e := Quantize(context.Background(), source, tc.Settings)
			if e != nil {
				t.Fatal(e)
			}
			if !reflect.DeepEqual(got.Pixels, tc.Expected.Pixels) || !reflect.DeepEqual(got.Palette, tc.Expected.Palette) {
				t.Fatalf("golden mismatch\ngot %s\nwant %s", mustJSON(got.Pixels), mustJSON(tc.Expected.Pixels))
			}
			if len(png) == 0 {
				t.Fatal("missing preview")
			}
		})
	}
}
func fixture(t *testing.T) (Project, Metadata, Design) {
	t.Helper()
	data, e := os.ReadFile("testdata/design.json")
	if e != nil {
		t.Fatal(e)
	}
	var f struct {
		Project  Project
		Metadata Metadata
		Expected Design
	}
	if e = json.Unmarshal(data, &f); e != nil {
		t.Fatal(e)
	}
	return f.Project, f.Metadata, f.Expected
}

// TestDesignGolden 检查覆盖、BOM 和底座/非底座双语言 LDraw 的精确几何与步骤顺序。
func TestDesignGolden(t *testing.T) {
	p, m, want := fixture(t)
	got, e := GenerateDesign(context.Background(), p, m)
	if e != nil {
		t.Fatal(e)
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("design mismatch\ngot %s\nwant %s", mustJSON(got), mustJSON(want))
	}
	for _, locale := range []string{"zh-CN", "en-US"} {
		for _, base := range []bool{false, true} {
			t.Run(fmt.Sprintf("%s-%t", locale, base), func(t *testing.T) {
				ldraw, plan, e := ExportDesign(context.Background(), got, m, base, ExportContext{locale, "Asia/Shanghai", ExportVersion})
				if e != nil {
					t.Fatal(e)
				}
				want, e := os.ReadFile(fmt.Sprintf("testdata/%s-%t.ldr", locale, base))
				if e != nil {
					t.Fatal(e)
				}
				if string(ldraw) != string(want) {
					t.Fatalf("ldraw mismatch\ngot %s\nwant %s", ldraw, want)
				}
				var doc map[string]any
				if e = json.Unmarshal(plan, &doc); e != nil {
					t.Fatal(e)
				}
				goldenPlan, err := os.ReadFile(fmt.Sprintf("testdata/%s-%t.json", locale, base))
				if err != nil {
					t.Fatal(err)
				}
				var expectedPlan map[string]any
				if err := json.Unmarshal(goldenPlan, &expectedPlan); err != nil {
					t.Fatal(err)
				}
				if !reflect.DeepEqual(doc, expectedPlan) {
					t.Fatalf("plan contract mismatch\ngot %s\nwant %s", plan, goldenPlan)
				}
				if doc["document"].(map[string]any)["locale"] != locale {
					t.Fatal("unfrozen locale")
				}
			})
		}
	}
}
func TestInvalidPixelEditAndCancelledComputation(t *testing.T) {
	p, m, _ := fixture(t)
	p.Pixels[1] = p.Pixels[0]
	if _, e := GenerateDesign(context.Background(), p, m); e == nil {
		t.Fatal("duplicate pixel accepted")
	}
	p, _, _ = fixture(t)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, e := GenerateDesign(ctx, p, m); e == nil {
		t.Fatal("cancel ignored")
	}
	p.GridWidth = 0
	if _, e := normalizePixels(&p); e == nil {
		t.Fatal("invalid dimensions")
	}
}
func TestTinyTransparentImageAndNarrowSupport(t *testing.T) {
	img := image.NewNRGBA(image.Rect(0, 0, 1, 1))
	img.SetNRGBA(0, 0, color.NRGBA{255, 0, 0, 0})
	var b bytes.Buffer
	png.Encode(&b, img)
	s := Settings{Algorithm: "photo_illustration", GridWidth: 1, GridHeight: 1, ColorCount: 2}
	s.Crop.Width = 1
	s.Crop.Height = 1
	s.Preprocessing.Brightness = 1
	s.Preprocessing.Contrast = 1
	s.Preprocessing.Saturation = 1
	s.Preprocessing.Sharpness = 1
	p, _, e := Quantize(context.Background(), b.Bytes(), s)
	if e != nil {
		t.Fatal(e)
	}
	if p.Pixels[0].RGB != "#FFFFFF" {
		t.Fatal(p.Pixels)
	}
	_, m, _ := fixture(t)
	d, e := GenerateDesign(context.Background(), p, m)
	if e != nil {
		t.Fatal(e)
	}
	white, black, e := supportLayers(context.Background(), d, m)
	if e != nil {
		t.Fatal(e)
	}
	for _, ps := range [][]Placement{white, black} {
		for _, v := range ps {
			if v.X < 0 || v.Y < 0 || v.X+v.Width > 1 || v.Y+v.Height > 1 {
				t.Fatal("support outside grid")
			}
		}
	}
}

// TestEmbeddedResourcesMatchCanonical 防止 Go 嵌入副本形成独立词典或静默偏离旧算法配置。
func TestEmbeddedResourcesMatchCanonical(t *testing.T) {
	for _, pair := range [][2]string{
		{"en-US.json", "../../../backend/src/i18n/export_resources/en-US.json"},
		{"zh-CN.json", "../../../backend/src/i18n/export_resources/zh-CN.json"},
		{"pixel_art.json", "../../../backend/config/pixel_art.json"},
		{"lego_design.json", "../../../backend/config/lego_design.json"},
	} {
		got, err := resources.ReadFile("resources/" + pair[0])
		if err != nil {
			t.Fatal(err)
		}
		want, err := os.ReadFile(pair[1])
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(got, want) {
			t.Fatalf("resource %s differs from canonical", pair[0])
		}
	}
}
