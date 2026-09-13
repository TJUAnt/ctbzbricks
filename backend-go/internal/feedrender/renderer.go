package feedrender

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"errors"
	"image"
	"image/color"
	"image/png"
	"math"
	"sort"
	"strings"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/ldrawmaterial"
)

const (
	supersample       = 2
	targetWidthRatio  = 0.70
	targetHeightRatio = 0.65
	maximumTriangles  = 500_000
	creaseCosine      = 0.74
)

var errUnsupportedGLB = errors.New("unsupported component GLB")

type vec3 struct{ x, y, z float64 }
type mat4 [16]float64
type renderMaterial struct {
	base                   vec3
	rough, metallic, alpha float64
	class                  string
}
type renderTriangle struct {
	a, b, c    vec3
	na, nb, nc vec3
	material   renderMaterial
	group      int
}
type projectedVertex struct{ x, y, inverseDepth float64 }
type shadedVertex struct {
	projectedVertex
	shade color.RGBA
}
type projectedTriangle struct {
	a, b, c shadedVertex
	depth   float64
	alpha   float64
}

type gltfDocument struct {
	Scene       int              `json:"scene"`
	Scenes      []gltfScene      `json:"scenes"`
	Nodes       []gltfNode       `json:"nodes"`
	Meshes      []gltfMesh       `json:"meshes"`
	Materials   []gltfMaterial   `json:"materials"`
	Accessors   []gltfAccessor   `json:"accessors"`
	BufferViews []gltfBufferView `json:"bufferViews"`
}
type gltfScene struct {
	Nodes []int `json:"nodes"`
}
type gltfNode struct {
	Mesh        *int      `json:"mesh"`
	Children    []int     `json:"children"`
	Matrix      []float64 `json:"matrix"`
	Translation []float64 `json:"translation"`
	Rotation    []float64 `json:"rotation"`
	Scale       []float64 `json:"scale"`
}
type gltfMesh struct {
	Primitives []gltfPrimitive `json:"primitives"`
}
type gltfPrimitive struct {
	Attributes map[string]int `json:"attributes"`
	Indices    *int           `json:"indices"`
	Material   *int           `json:"material"`
	Mode       *int           `json:"mode"`
}
type gltfMaterial struct {
	Name      string `json:"name"`
	AlphaMode string `json:"alphaMode"`
	PBR       struct {
		BaseColorFactor []float64 `json:"baseColorFactor"`
		RoughnessFactor *float64  `json:"roughnessFactor"`
		MetallicFactor  *float64  `json:"metallicFactor"`
	} `json:"pbrMetallicRoughness"`
}
type gltfAccessor struct {
	BufferView    *int   `json:"bufferView"`
	ByteOffset    int    `json:"byteOffset"`
	ComponentType int    `json:"componentType"`
	Count         int    `json:"count"`
	Type          string `json:"type"`
}
type gltfBufferView struct {
	ByteOffset int `json:"byteOffset"`
	ByteLength int `json:"byteLength"`
	ByteStride int `json:"byteStride"`
}

// RenderGLB 把受控 Component Preview GLB 渲染成固定 3:2 PNG。
// 构图按屏幕投影把模型限制在 70%×65%，并通过超采样、分类材质、平滑法线、摄影棚光和接触阴影改善 Feed 质感。
func RenderGLB(source []byte) ([]byte, error) {
	document, binChunk, err := parseGLB(source)
	if err != nil {
		return nil, err
	}
	triangles, err := flattenScene(document, binChunk)
	if err != nil || len(triangles) == 0 || len(triangles) > maximumTriangles {
		return nil, errUnsupportedGLB
	}
	imageValue := rasterize(triangles, ImageWidth*supersample, ImageHeight*supersample)
	imageValue = downsample(imageValue, ImageWidth, ImageHeight)
	var output bytes.Buffer
	encoder := png.Encoder{CompressionLevel: png.BestSpeed}
	if err := encoder.Encode(&output, imageValue); err != nil {
		return nil, err
	}
	return output.Bytes(), nil
}

func parseGLB(source []byte) (gltfDocument, []byte, error) {
	if len(source) < 20 || string(source[:4]) != "glTF" || binary.LittleEndian.Uint32(source[4:8]) != 2 {
		return gltfDocument{}, nil, errUnsupportedGLB
	}
	declared := int(binary.LittleEndian.Uint32(source[8:12]))
	if declared != len(source) {
		return gltfDocument{}, nil, errUnsupportedGLB
	}
	var document gltfDocument
	var binChunk []byte
	for offset := 12; offset+8 <= len(source); {
		length := int(binary.LittleEndian.Uint32(source[offset : offset+4]))
		kind := string(source[offset+4 : offset+8])
		offset += 8
		if length < 0 || offset+length > len(source) {
			return gltfDocument{}, nil, errUnsupportedGLB
		}
		chunk := source[offset : offset+length]
		switch kind {
		case "JSON":
			if err := json.Unmarshal(chunk, &document); err != nil {
				return gltfDocument{}, nil, errUnsupportedGLB
			}
		case "BIN\x00":
			binChunk = chunk
		}
		offset += length
	}
	if len(document.Scenes) == 0 || len(binChunk) == 0 {
		return gltfDocument{}, nil, errUnsupportedGLB
	}
	return document, binChunk, nil
}

func flattenScene(document gltfDocument, binChunk []byte) ([]renderTriangle, error) {
	sceneIndex := document.Scene
	if sceneIndex < 0 || sceneIndex >= len(document.Scenes) {
		sceneIndex = 0
	}
	result := make([]renderTriangle, 0)
	group := 0
	visiting := make(map[int]bool)
	var visit func(int, mat4) error
	visit = func(nodeIndex int, parent mat4) error {
		if nodeIndex < 0 || nodeIndex >= len(document.Nodes) {
			return errUnsupportedGLB
		}
		// GLB 来自受控 Worker，但解析边界仍拒绝循环节点，避免损坏派生文件造成无限递归。
		if visiting[nodeIndex] {
			return errUnsupportedGLB
		}
		visiting[nodeIndex] = true
		defer delete(visiting, nodeIndex)
		node := document.Nodes[nodeIndex]
		world := multiplyMatrix(parent, nodeMatrix(node))
		if node.Mesh != nil {
			if *node.Mesh < 0 || *node.Mesh >= len(document.Meshes) {
				return errUnsupportedGLB
			}
			for _, primitive := range document.Meshes[*node.Mesh].Primitives {
				group++
				if primitive.Mode != nil && *primitive.Mode != 4 {
					continue
				}
				positionAccessor, ok := primitive.Attributes["POSITION"]
				if !ok {
					continue
				}
				positions, err := readPositions(document, binChunk, positionAccessor)
				if err != nil {
					return err
				}
				indices, err := readIndices(document, binChunk, primitive.Indices, len(positions))
				if err != nil {
					return err
				}
				materialValue := material(document, primitive.Material)
				for index := 0; index+2 < len(indices); index += 3 {
					if len(result) >= maximumTriangles {
						return errUnsupportedGLB
					}
					a, b, c := indices[index], indices[index+1], indices[index+2]
					if a >= len(positions) || b >= len(positions) || c >= len(positions) {
						return errUnsupportedGLB
					}
					result = append(result, renderTriangle{
						a: transformPoint(world, positions[a]), b: transformPoint(world, positions[b]),
						c: transformPoint(world, positions[c]), material: materialValue, group: group,
					})
				}
			}
		}
		for _, child := range node.Children {
			if err := visit(child, world); err != nil {
				return err
			}
		}
		return nil
	}
	identity := identityMatrix()
	for _, root := range document.Scenes[sceneIndex].Nodes {
		if err := visit(root, identity); err != nil {
			return nil, err
		}
	}
	smoothTriangleNormals(result)
	return result, nil
}

func readPositions(document gltfDocument, binChunk []byte, accessorIndex int) ([]vec3, error) {
	if accessorIndex < 0 || accessorIndex >= len(document.Accessors) {
		return nil, errUnsupportedGLB
	}
	accessor := document.Accessors[accessorIndex]
	if accessor.BufferView == nil || accessor.ComponentType != 5126 || accessor.Type != "VEC3" || accessor.Count < 1 {
		return nil, errUnsupportedGLB
	}
	view, offset, stride, err := accessorData(document, binChunk, accessor, 12)
	if err != nil {
		return nil, err
	}
	result := make([]vec3, accessor.Count)
	for index := range result {
		start := offset + index*stride
		result[index] = vec3{
			x: float64(math.Float32frombits(binary.LittleEndian.Uint32(view[start : start+4]))),
			y: float64(math.Float32frombits(binary.LittleEndian.Uint32(view[start+4 : start+8]))),
			z: float64(math.Float32frombits(binary.LittleEndian.Uint32(view[start+8 : start+12]))),
		}
	}
	return result, nil
}

func readIndices(document gltfDocument, binChunk []byte, accessorIndex *int, positionCount int) ([]int, error) {
	if accessorIndex == nil {
		result := make([]int, positionCount)
		for index := range result {
			result[index] = index
		}
		return result, nil
	}
	if *accessorIndex < 0 || *accessorIndex >= len(document.Accessors) {
		return nil, errUnsupportedGLB
	}
	accessor := document.Accessors[*accessorIndex]
	if accessor.BufferView == nil || accessor.Type != "SCALAR" || accessor.Count < 3 {
		return nil, errUnsupportedGLB
	}
	componentSize := map[int]int{5121: 1, 5123: 2, 5125: 4}[accessor.ComponentType]
	if componentSize == 0 {
		return nil, errUnsupportedGLB
	}
	view, offset, stride, err := accessorData(document, binChunk, accessor, componentSize)
	if err != nil {
		return nil, err
	}
	result := make([]int, accessor.Count)
	for index := range result {
		start := offset + index*stride
		switch componentSize {
		case 1:
			result[index] = int(view[start])
		case 2:
			result[index] = int(binary.LittleEndian.Uint16(view[start : start+2]))
		case 4:
			result[index] = int(binary.LittleEndian.Uint32(view[start : start+4]))
		}
	}
	return result, nil
}

func accessorData(document gltfDocument, binChunk []byte, accessor gltfAccessor, itemSize int) ([]byte, int, int, error) {
	viewIndex := *accessor.BufferView
	if viewIndex < 0 || viewIndex >= len(document.BufferViews) {
		return nil, 0, 0, errUnsupportedGLB
	}
	view := document.BufferViews[viewIndex]
	stride := view.ByteStride
	if stride == 0 {
		stride = itemSize
	}
	offset := view.ByteOffset + accessor.ByteOffset
	end := offset + (accessor.Count-1)*stride + itemSize
	if offset < 0 || stride < itemSize || end > len(binChunk) || view.ByteOffset+view.ByteLength > len(binChunk) {
		return nil, 0, 0, errUnsupportedGLB
	}
	return binChunk, offset, stride, nil
}

func material(document gltfDocument, materialIndex *int) renderMaterial {
	result := renderMaterial{base: vec3{0.48, 0.51, 0.57}, rough: 0.38, alpha: 1, class: ldrawmaterial.Plastic}
	if materialIndex == nil || *materialIndex < 0 || *materialIndex >= len(document.Materials) {
		return result
	}
	materialValue := document.Materials[*materialIndex]
	pbr := materialValue.PBR
	if len(pbr.BaseColorFactor) >= 3 {
		result.base = vec3{clamp01(pbr.BaseColorFactor[0]), clamp01(pbr.BaseColorFactor[1]), clamp01(pbr.BaseColorFactor[2])}
	}
	if len(pbr.BaseColorFactor) >= 4 && strings.EqualFold(materialValue.AlphaMode, "BLEND") {
		result.alpha = clamp01(pbr.BaseColorFactor[3])
	}
	if pbr.RoughnessFactor != nil {
		result.rough = math.Max(0.08, math.Min(0.92, *pbr.RoughnessFactor))
	}
	if pbr.MetallicFactor != nil {
		result.metallic = clamp01(*pbr.MetallicFactor)
	}
	if code, ok := strings.CutPrefix(strings.TrimSpace(materialValue.Name), "LDraw "); ok {
		definition := ldrawmaterial.Lookup(code)
		result.base = vec3{definition.BaseColor[0], definition.BaseColor[1], definition.BaseColor[2]}
		result.rough, result.metallic, result.alpha, result.class = definition.Roughness, definition.Metallic, definition.Alpha, definition.Class
	}
	// LDraw 的 128 alpha 表示名义透明度；光栅器没有折射，降低单层覆盖率避免前后表面叠加成不透明白片。
	if result.class == ldrawmaterial.Glass {
		result.alpha *= 0.64
	}
	return result
}

type smoothKey struct {
	group   int
	x, y, z uint64
}

// smoothTriangleNormals 在单个 Part 实例内按共享位置和折角重建顶点法线；跨积木实例绝不互相平滑。
func smoothTriangleNormals(triangles []renderTriangle) {
	faces := make([]vec3, len(triangles))
	buckets := make(map[smoothKey][]vec3, len(triangles)*2)
	for index, triangle := range triangles {
		face := normalize(cross(sub(triangle.b, triangle.a), sub(triangle.c, triangle.a)))
		faces[index] = face
		for _, point := range []vec3{triangle.a, triangle.b, triangle.c} {
			key := smoothKey{group: triangle.group, x: math.Float64bits(point.x), y: math.Float64bits(point.y), z: math.Float64bits(point.z)}
			buckets[key] = append(buckets[key], face)
		}
	}
	for index := range triangles {
		triangle := &triangles[index]
		triangle.na = creasedVertexNormal(faces[index], buckets[smoothKey{triangle.group, math.Float64bits(triangle.a.x), math.Float64bits(triangle.a.y), math.Float64bits(triangle.a.z)}])
		triangle.nb = creasedVertexNormal(faces[index], buckets[smoothKey{triangle.group, math.Float64bits(triangle.b.x), math.Float64bits(triangle.b.y), math.Float64bits(triangle.b.z)}])
		triangle.nc = creasedVertexNormal(faces[index], buckets[smoothKey{triangle.group, math.Float64bits(triangle.c.x), math.Float64bits(triangle.c.y), math.Float64bits(triangle.c.z)}])
	}
}

func creasedVertexNormal(face vec3, candidates []vec3) vec3 {
	result := vec3{}
	for _, candidate := range candidates {
		if dot(face, candidate) >= creaseCosine {
			result = add(result, candidate)
		}
	}
	if dot(result, result) < 0.0000001 {
		return face
	}
	return normalize(result)
}

type cameraFrame struct {
	position, right, up, forward  vec3
	focal, aspect, shiftX, shiftY float64
	width, height                 int
}

func rasterize(triangles []renderTriangle, width, height int) *image.RGBA {
	minimum, maximum := sceneBounds(triangles)
	frame := fitCamera(triangles, minimum, maximum, width, height)
	canvas := image.NewRGBA(image.Rect(0, 0, width, height))
	drawBackground(canvas)
	projectedBounds := projectionBounds(triangles, frame)
	drawContactShadow(canvas, projectedBounds)
	depth := make([]float64, width*height)
	for index := range depth {
		depth[index] = math.Inf(-1)
	}
	keyLight := normalize(vec3{-0.55, 0.82, 0.68})
	fillLight := normalize(vec3{0.72, 0.38, -0.58})
	transparent := make([]projectedTriangle, 0)
	for _, triangle := range triangles {
		pa, okA := project(triangle.a, frame)
		pb, okB := project(triangle.b, frame)
		pc, okC := project(triangle.c, frame)
		if !okA || !okB || !okC {
			continue
		}
		faceNormal := normalize(cross(sub(triangle.b, triangle.a), sub(triangle.c, triangle.a)))
		center := mul(add(add(triangle.a, triangle.b), triangle.c), 1.0/3)
		viewDirection := normalize(sub(frame.position, center))
		if dot(faceNormal, viewDirection) < 0 {
			triangle.na, triangle.nb, triangle.nc = mul(triangle.na, -1), mul(triangle.nb, -1), mul(triangle.nc, -1)
		}
		a := shadedVertex{projectedVertex: pa, shade: shadeColor(triangle.material, triangle.na, normalize(sub(frame.position, triangle.a)), keyLight, fillLight)}
		b := shadedVertex{projectedVertex: pb, shade: shadeColor(triangle.material, triangle.nb, normalize(sub(frame.position, triangle.b)), keyLight, fillLight)}
		c := shadedVertex{projectedVertex: pc, shade: shadeColor(triangle.material, triangle.nc, normalize(sub(frame.position, triangle.c)), keyLight, fillLight)}
		projected := projectedTriangle{a: a, b: b, c: c, depth: (pa.inverseDepth + pb.inverseDepth + pc.inverseDepth) / 3, alpha: triangle.material.alpha}
		if triangle.material.alpha < 0.995 {
			transparent = append(transparent, projected)
			continue
		}
		rasterTriangle(canvas, depth, projected, true)
	}
	// 透明三角形按中心深度从远到近混合；只与已写入的 opaque depth 比较，不互相覆盖深度。
	sort.SliceStable(transparent, func(i, j int) bool { return transparent[i].depth < transparent[j].depth })
	for _, triangle := range transparent {
		rasterTriangle(canvas, depth, triangle, false)
	}
	return canvas
}

func fitCamera(triangles []renderTriangle, minimum, maximum vec3, width, height int) cameraFrame {
	center := mul(add(minimum, maximum), 0.5)
	extent := sub(maximum, minimum)
	radius := math.Max(math.Max(extent.x, extent.y), extent.z) * 0.5
	if radius < 0.001 {
		radius = 1
	}
	direction := normalize(vec3{1, 0.72, 1})
	worldUp := vec3{0, 1, 0}
	focal := 1 / math.Tan(15*math.Pi/360)
	frame := cameraFrame{right: normalize(cross(mul(direction, -1), worldUp)), focal: focal, aspect: float64(width) / float64(height), width: width, height: height}
	frame.forward = mul(direction, -1)
	frame.up = normalize(cross(frame.right, frame.forward))
	low, high := radius*1.01, radius*60
	for iteration := 0; iteration < 36; iteration++ {
		distance := (low + high) * 0.5
		frame.position = add(center, mul(direction, distance))
		bounds := projectionBounds(triangles, frame)
		widthRatio := (bounds.maxX - bounds.minX) / float64(width)
		heightRatio := (bounds.maxY - bounds.minY) / float64(height)
		if widthRatio > targetWidthRatio || heightRatio > targetHeightRatio {
			low = distance
		} else {
			high = distance
		}
	}
	frame.position = add(center, mul(direction, high))
	bounds := projectionBounds(triangles, frame)
	frame.shiftX = float64(width)/2 - (bounds.minX+bounds.maxX)/2
	frame.shiftY = float64(height)*0.47 - (bounds.minY+bounds.maxY)/2
	return frame
}

type pixelBounds struct{ minX, minY, maxX, maxY float64 }

func projectionBounds(triangles []renderTriangle, frame cameraFrame) pixelBounds {
	bounds := pixelBounds{minX: math.Inf(1), minY: math.Inf(1), maxX: math.Inf(-1), maxY: math.Inf(-1)}
	for _, triangle := range triangles {
		for _, point := range []vec3{triangle.a, triangle.b, triangle.c} {
			value, ok := project(point, frame)
			if !ok {
				continue
			}
			bounds.minX = math.Min(bounds.minX, value.x)
			bounds.minY = math.Min(bounds.minY, value.y)
			bounds.maxX = math.Max(bounds.maxX, value.x)
			bounds.maxY = math.Max(bounds.maxY, value.y)
		}
	}
	return bounds
}

func project(point vec3, frame cameraFrame) (projectedVertex, bool) {
	relative := sub(point, frame.position)
	depth := dot(relative, frame.forward)
	if depth <= 0.0001 {
		return projectedVertex{}, false
	}
	ndcX := dot(relative, frame.right) / depth * frame.focal / frame.aspect
	ndcY := dot(relative, frame.up) / depth * frame.focal
	return projectedVertex{
		x:            (ndcX+1)*0.5*float64(frame.width) + frame.shiftX,
		y:            (1-ndcY)*0.5*float64(frame.height) + frame.shiftY,
		inverseDepth: 1 / depth,
	}, true
}

func rasterTriangle(canvas *image.RGBA, depth []float64, triangle projectedTriangle, writeDepth bool) {
	a, b, c := triangle.a, triangle.b, triangle.c
	area := edge(a.x, a.y, b.x, b.y, c.x, c.y)
	if math.Abs(area) < 0.00001 {
		return
	}
	minimumX := maxInt(0, int(math.Floor(math.Min(a.x, math.Min(b.x, c.x)))))
	maximumX := minInt(canvas.Bounds().Dx()-1, int(math.Ceil(math.Max(a.x, math.Max(b.x, c.x)))))
	minimumY := maxInt(0, int(math.Floor(math.Min(a.y, math.Min(b.y, c.y)))))
	maximumY := minInt(canvas.Bounds().Dy()-1, int(math.Ceil(math.Max(a.y, math.Max(b.y, c.y)))))
	if minimumX > maximumX || minimumY > maximumY {
		return
	}
	negative := area < 0
	for y := minimumY; y <= maximumY; y++ {
		for x := minimumX; x <= maximumX; x++ {
			px, py := float64(x)+0.5, float64(y)+0.5
			wa := edge(b.x, b.y, c.x, c.y, px, py)
			wb := edge(c.x, c.y, a.x, a.y, px, py)
			wc := edge(a.x, a.y, b.x, b.y, px, py)
			if negative {
				wa, wb, wc = -wa, -wb, -wc
			}
			if wa < 0 || wb < 0 || wc < 0 {
				continue
			}
			inverseDepth := (wa*a.inverseDepth + wb*b.inverseDepth + wc*c.inverseDepth) / math.Abs(area)
			index := y*canvas.Bounds().Dx() + x
			if inverseDepth <= depth[index] {
				continue
			}
			if writeDepth {
				depth[index] = inverseDepth
			}
			// 颜色使用 perspective-correct 权重，避免近距离大三角形出现线性屏幕插值偏色。
			denominator := wa*a.inverseDepth + wb*b.inverseDepth + wc*c.inverseDepth
			if denominator <= 0 {
				continue
			}
			weightA, weightB, weightC := wa*a.inverseDepth/denominator, wb*b.inverseDepth/denominator, wc*c.inverseDepth/denominator
			red := weightA*float64(a.shade.R) + weightB*float64(b.shade.R) + weightC*float64(c.shade.R)
			green := weightA*float64(a.shade.G) + weightB*float64(b.shade.G) + weightC*float64(c.shade.G)
			blue := weightA*float64(a.shade.B) + weightB*float64(b.shade.B) + weightC*float64(c.shade.B)
			alpha := triangle.alpha
			if writeDepth {
				alpha = 1
			}
			background := canvas.RGBAAt(x, y)
			canvas.SetRGBA(x, y, color.RGBA{
				R: uint8(math.Round(red*alpha + float64(background.R)*(1-alpha))),
				G: uint8(math.Round(green*alpha + float64(background.G)*(1-alpha))),
				B: uint8(math.Round(blue*alpha + float64(background.B)*(1-alpha))), A: 255,
			})
		}
	}
}

func shadeColor(material renderMaterial, normal, view, key, fill vec3) color.RGBA {
	keyAmount := math.Max(0, dot(normal, key))
	fillAmount := math.Max(0, dot(normal, fill))
	hemisphere := 0.32 + 0.12*math.Max(0, normal.y)
	halfVector := normalize(add(key, view))
	specularStrength := 0.20 + material.metallic*0.42
	if material.class == ldrawmaterial.Rubber {
		specularStrength = 0.035
	} else if material.class == ldrawmaterial.Glass {
		specularStrength = 0.62
	}
	specular := math.Pow(math.Max(0, dot(normal, halfVector)), 18+90*(1-material.rough)) * specularStrength
	light := hemisphere + 0.68*keyAmount + 0.20*fillAmount
	if material.class == ldrawmaterial.Glass {
		light = 0.38 + 0.32*keyAmount + 0.10*fillAmount
	}
	return color.RGBA{
		R: linearByte(material.base.x*light + specular),
		G: linearByte(material.base.y*light + specular),
		B: linearByte(material.base.z*light + specular), A: 255,
	}
}

func linearByte(value float64) uint8 {
	value = math.Max(0, value)
	// 轻量 filmic 压缩高光，避免高饱和 LEGO 色在摄影棚灯光下截断。
	value = value * (2.51*value + 0.03) / (value*(2.43*value+0.59) + 0.14)
	value = clamp01(value)
	if value <= 0.0031308 {
		value *= 12.92
	} else {
		value = 1.055*math.Pow(value, 1/2.4) - 0.055
	}
	return uint8(math.Round(clamp01(value) * 255))
}

func drawBackground(canvas *image.RGBA) {
	width, height := canvas.Bounds().Dx(), canvas.Bounds().Dy()
	for y := 0; y < height; y++ {
		t := float64(y) / float64(height-1)
		base := uint8(math.Round(248 - 22*t))
		for x := 0; x < width; x++ {
			canvas.SetRGBA(x, y, color.RGBA{R: base, G: base + 1, B: base + 3, A: 255})
		}
	}
}

func drawContactShadow(canvas *image.RGBA, bounds pixelBounds) {
	centerX := (bounds.minX + bounds.maxX) * 0.5
	centerY := bounds.maxY - (bounds.maxY-bounds.minY)*0.015
	radiusX := math.Max(8, (bounds.maxX-bounds.minX)*0.43)
	radiusY := math.Max(5, (bounds.maxY-bounds.minY)*0.075)
	minimumX := maxInt(0, int(centerX-radiusX*1.15))
	maximumX := minInt(canvas.Bounds().Dx()-1, int(centerX+radiusX*1.15))
	minimumY := maxInt(0, int(centerY-radiusY*1.8))
	maximumY := minInt(canvas.Bounds().Dy()-1, int(centerY+radiusY*1.8))
	for y := minimumY; y <= maximumY; y++ {
		for x := minimumX; x <= maximumX; x++ {
			dx, dy := (float64(x)-centerX)/radiusX, (float64(y)-centerY)/radiusY
			strength := math.Exp(-(dx*dx+dy*dy)*2.2) * 0.22
			if strength < 0.002 {
				continue
			}
			current := canvas.RGBAAt(x, y)
			canvas.SetRGBA(x, y, color.RGBA{
				R: uint8(float64(current.R) * (1 - strength)),
				G: uint8(float64(current.G) * (1 - strength)),
				B: uint8(float64(current.B) * (1 - strength)), A: 255,
			})
		}
	}
}

func downsample(source *image.RGBA, width, height int) *image.RGBA {
	target := image.NewRGBA(image.Rect(0, 0, width, height))
	for y := 0; y < height; y++ {
		for x := 0; x < width; x++ {
			var red, green, blue uint32
			for offsetY := 0; offsetY < supersample; offsetY++ {
				for offsetX := 0; offsetX < supersample; offsetX++ {
					value := source.RGBAAt(x*supersample+offsetX, y*supersample+offsetY)
					red += uint32(value.R)
					green += uint32(value.G)
					blue += uint32(value.B)
				}
			}
			count := uint32(supersample * supersample)
			target.SetRGBA(x, y, color.RGBA{R: uint8(red / count), G: uint8(green / count), B: uint8(blue / count), A: 255})
		}
	}
	return target
}

func sceneBounds(triangles []renderTriangle) (vec3, vec3) {
	minimum := vec3{math.Inf(1), math.Inf(1), math.Inf(1)}
	maximum := vec3{math.Inf(-1), math.Inf(-1), math.Inf(-1)}
	for _, triangle := range triangles {
		for _, point := range []vec3{triangle.a, triangle.b, triangle.c} {
			minimum.x, minimum.y, minimum.z = math.Min(minimum.x, point.x), math.Min(minimum.y, point.y), math.Min(minimum.z, point.z)
			maximum.x, maximum.y, maximum.z = math.Max(maximum.x, point.x), math.Max(maximum.y, point.y), math.Max(maximum.z, point.z)
		}
	}
	return minimum, maximum
}

func nodeMatrix(node gltfNode) mat4 {
	if len(node.Matrix) == 16 {
		var result mat4
		copy(result[:], node.Matrix)
		return result
	}
	translation := vec3{}
	if len(node.Translation) == 3 {
		translation = vec3{node.Translation[0], node.Translation[1], node.Translation[2]}
	}
	scale := vec3{1, 1, 1}
	if len(node.Scale) == 3 {
		scale = vec3{node.Scale[0], node.Scale[1], node.Scale[2]}
	}
	rotation := [4]float64{0, 0, 0, 1}
	if len(node.Rotation) == 4 {
		copy(rotation[:], node.Rotation)
	}
	x, y, z, w := rotation[0], rotation[1], rotation[2], rotation[3]
	result := mat4{
		(1 - 2*y*y - 2*z*z) * scale.x, (2*x*y + 2*w*z) * scale.x, (2*x*z - 2*w*y) * scale.x, 0,
		(2*x*y - 2*w*z) * scale.y, (1 - 2*x*x - 2*z*z) * scale.y, (2*y*z + 2*w*x) * scale.y, 0,
		(2*x*z + 2*w*y) * scale.z, (2*y*z - 2*w*x) * scale.z, (1 - 2*x*x - 2*y*y) * scale.z, 0,
		translation.x, translation.y, translation.z, 1,
	}
	return result
}

func identityMatrix() mat4 { return mat4{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1} }
func multiplyMatrix(a, b mat4) mat4 {
	var result mat4
	for column := 0; column < 4; column++ {
		for row := 0; row < 4; row++ {
			for k := 0; k < 4; k++ {
				result[column*4+row] += a[k*4+row] * b[column*4+k]
			}
		}
	}
	return result
}
func transformPoint(matrix mat4, point vec3) vec3 {
	return vec3{
		x: matrix[0]*point.x + matrix[4]*point.y + matrix[8]*point.z + matrix[12],
		y: matrix[1]*point.x + matrix[5]*point.y + matrix[9]*point.z + matrix[13],
		z: matrix[2]*point.x + matrix[6]*point.y + matrix[10]*point.z + matrix[14],
	}
}
func add(a, b vec3) vec3             { return vec3{a.x + b.x, a.y + b.y, a.z + b.z} }
func sub(a, b vec3) vec3             { return vec3{a.x - b.x, a.y - b.y, a.z - b.z} }
func mul(a vec3, value float64) vec3 { return vec3{a.x * value, a.y * value, a.z * value} }
func dot(a, b vec3) float64          { return a.x*b.x + a.y*b.y + a.z*b.z }
func cross(a, b vec3) vec3           { return vec3{a.y*b.z - a.z*b.y, a.z*b.x - a.x*b.z, a.x*b.y - a.y*b.x} }
func normalize(value vec3) vec3 {
	length := math.Sqrt(dot(value, value))
	if length < 0.0000001 {
		return vec3{0, 1, 0}
	}
	return mul(value, 1/length)
}
func edge(ax, ay, bx, by, px, py float64) float64 { return (px-ax)*(by-ay) - (py-ay)*(bx-ax) }
func clamp01(value float64) float64               { return math.Max(0, math.Min(1, value)) }
func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}
func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}
