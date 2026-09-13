package feedrender

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"image"
	"image/color"
	"image/png"
	"math"
	"testing"
)

func TestRenderGLBProducesLargeThreeByTwoStudioImage(t *testing.T) {
	output, err := RenderGLB(boxGLB(t))
	if err != nil {
		t.Fatalf("render box GLB: %v", err)
	}
	decoded, err := png.Decode(bytes.NewReader(output))
	if err != nil {
		t.Fatalf("decode Feed PNG: %v", err)
	}
	if decoded.Bounds().Dx() != ImageWidth || decoded.Bounds().Dy() != ImageHeight {
		t.Fatalf("Feed PNG size = %dx%d, want %dx%d", decoded.Bounds().Dx(), decoded.Bounds().Dy(), ImageWidth, ImageHeight)
	}

	minX, minY, maxX, maxY := ImageWidth, ImageHeight, -1, -1
	for y := 0; y < ImageHeight; y++ {
		for x := 0; x < ImageWidth; x++ {
			red, green, blue, _ := decoded.At(x, y).RGBA()
			// fixture 使用高饱和红色；只统计模型本体，排除灰色背景和接触阴影。
			if red > green*3/2 && red > blue*3/2 {
				if x < minX {
					minX = x
				}
				if x > maxX {
					maxX = x
				}
				if y < minY {
					minY = y
				}
				if y > maxY {
					maxY = y
				}
			}
		}
	}
	if maxX < 0 {
		t.Fatal("Feed PNG did not contain the rendered model")
	}
	widthRatio := float64(maxX-minX+1) / ImageWidth
	heightRatio := float64(maxY-minY+1) / ImageHeight
	if widthRatio < 0.38 || widthRatio > targetWidthRatio+0.02 || heightRatio < 0.62 || heightRatio > targetHeightRatio+0.02 {
		t.Fatalf("rendered bounds ratios = %.3f x %.3f, pixels=(%d,%d)-(%d,%d)", widthRatio, heightRatio, minX, minY, maxX, maxY)
	}
}

func TestMaterialRestoresLegacyLDrawTransparency(t *testing.T) {
	document := gltfDocument{Materials: []gltfMaterial{{Name: "LDraw 40"}}}
	value := material(document, intPointer(0))
	if value.class != "glass" || value.alpha <= 0.2 || value.alpha >= 0.4 {
		t.Fatalf("legacy LDraw glass = class %q alpha %.3f", value.class, value.alpha)
	}
	if value.base.x <= value.base.y || value.base.y <= value.base.z {
		t.Fatalf("trans-black linear color = %+v", value.base)
	}
}

func TestSmoothTriangleNormalsStaysInsidePrimitiveInstance(t *testing.T) {
	triangles := []renderTriangle{
		{a: vec3{0, 0, 0}, b: vec3{1, 0, 0}, c: vec3{0, 1, 0}, group: 1},
		{a: vec3{1, 0, 0}, b: vec3{1, 1, 0.35}, c: vec3{0, 1, 0}, group: 1},
		{a: vec3{0, 0, 0}, b: vec3{0, 1, 0}, c: vec3{1, 0, 0}, group: 2},
	}
	smoothTriangleNormals(triangles)
	face := normalize(cross(sub(triangles[0].b, triangles[0].a), sub(triangles[0].c, triangles[0].a)))
	if dot(triangles[0].nb, face) >= 0.9999 {
		t.Fatalf("shared curved edge was not smoothed: %+v", triangles[0].nb)
	}
	otherFace := normalize(cross(sub(triangles[2].b, triangles[2].a), sub(triangles[2].c, triangles[2].a)))
	if dot(triangles[2].na, otherFace) < 0.9999 {
		t.Fatalf("separate primitive instance was incorrectly smoothed: %+v", triangles[2].na)
	}
}

func TestRasterTriangleAlphaBlendsWithoutHidingOpaqueDepth(t *testing.T) {
	canvas := image.NewRGBA(image.Rect(0, 0, 8, 8))
	for y := 0; y < 8; y++ {
		for x := 0; x < 8; x++ {
			canvas.SetRGBA(x, y, color.RGBA{R: 100, G: 100, B: 100, A: 255})
		}
	}
	depth := make([]float64, 64)
	for index := range depth {
		depth[index] = math.Inf(-1)
	}
	shade := color.RGBA{R: 200, A: 255}
	rasterTriangle(canvas, depth, projectedTriangle{
		a:     shadedVertex{projectedVertex: projectedVertex{x: 1, y: 1, inverseDepth: 1}, shade: shade},
		b:     shadedVertex{projectedVertex: projectedVertex{x: 6, y: 1, inverseDepth: 1}, shade: shade},
		c:     shadedVertex{projectedVertex: projectedVertex{x: 1, y: 6, inverseDepth: 1}, shade: shade},
		alpha: 0.5,
	}, false)
	if got := canvas.RGBAAt(2, 2); got.R != 150 || got.G != 50 || got.B != 50 {
		t.Fatalf("alpha blended pixel = %#v", got)
	}
	if !math.IsInf(depth[2*8+2], -1) {
		t.Fatalf("transparent triangle wrote opaque depth = %v", depth[2*8+2])
	}
}

func TestRenderGLBRejectsInvalidInput(t *testing.T) {
	if _, err := RenderGLB([]byte("not-a-glb")); err == nil {
		t.Fatal("invalid GLB unexpectedly rendered")
	}
}

func intPointer(value int) *int { return &value }

// boxGLB 构造最小的索引立方体，覆盖 Worker 实际消费的 glTF 2.0 POSITION/indices/material 子集。
func boxGLB(t *testing.T) []byte {
	return boxGLBWithMaterial(t, "")
}

func boxGLBWithMaterial(t *testing.T, materialName string) []byte {
	t.Helper()
	vertices := [][3]float32{
		{-3, -2, -1}, {3, -2, -1}, {3, 2, -1}, {-3, 2, -1},
		{-3, -2, 1}, {3, -2, 1}, {3, 2, 1}, {-3, 2, 1},
	}
	indices := []uint16{
		0, 2, 1, 0, 3, 2, 4, 5, 6, 4, 6, 7,
		0, 1, 5, 0, 5, 4, 3, 7, 6, 3, 6, 2,
		0, 4, 7, 0, 7, 3, 1, 2, 6, 1, 6, 5,
	}
	var binaryChunk bytes.Buffer
	for _, vertex := range vertices {
		for _, value := range vertex {
			if err := binary.Write(&binaryChunk, binary.LittleEndian, value); err != nil {
				t.Fatal(err)
			}
		}
	}
	for _, index := range indices {
		if err := binary.Write(&binaryChunk, binary.LittleEndian, index); err != nil {
			t.Fatal(err)
		}
	}
	material := map[string]any{"pbrMetallicRoughness": map[string]any{
		"baseColorFactor": []float64{0.82, 0.03, 0.02, 1}, "roughnessFactor": 0.35,
	}}
	if materialName != "" {
		material["name"] = materialName
	}
	document := map[string]any{
		"asset": map[string]string{"version": "2.0"}, "scene": 0,
		"scenes": []any{map[string]any{"nodes": []int{0}}},
		"nodes":  []any{map[string]any{"mesh": 0}},
		"meshes": []any{map[string]any{"primitives": []any{map[string]any{
			"attributes": map[string]int{"POSITION": 0}, "indices": 1, "material": 0,
		}}}},
		"materials": []any{material},
		"accessors": []any{
			map[string]any{"bufferView": 0, "componentType": 5126, "count": len(vertices), "type": "VEC3"},
			map[string]any{"bufferView": 1, "componentType": 5123, "count": len(indices), "type": "SCALAR"},
		},
		"bufferViews": []any{
			map[string]any{"buffer": 0, "byteOffset": 0, "byteLength": len(vertices) * 12},
			map[string]any{"buffer": 0, "byteOffset": len(vertices) * 12, "byteLength": len(indices) * 2},
		},
		"buffers": []any{map[string]any{"byteLength": binaryChunk.Len()}},
	}
	jsonChunk, err := json.Marshal(document)
	if err != nil {
		t.Fatal(err)
	}
	for len(jsonChunk)%4 != 0 {
		jsonChunk = append(jsonChunk, ' ')
	}
	binBytes := binaryChunk.Bytes()
	for len(binBytes)%4 != 0 {
		binBytes = append(binBytes, 0)
	}
	total := 12 + 8 + len(jsonChunk) + 8 + len(binBytes)
	result := make([]byte, 0, total)
	result = append(result, 'g', 'l', 'T', 'F')
	result = binary.LittleEndian.AppendUint32(result, 2)
	result = binary.LittleEndian.AppendUint32(result, uint32(total))
	result = binary.LittleEndian.AppendUint32(result, uint32(len(jsonChunk)))
	result = append(result, 'J', 'S', 'O', 'N')
	result = append(result, jsonChunk...)
	result = binary.LittleEndian.AppendUint32(result, uint32(len(binBytes)))
	result = append(result, 'B', 'I', 'N', 0)
	return append(result, binBytes...)
}
