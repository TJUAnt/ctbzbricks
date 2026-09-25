package workbench

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"io/fs"
	"math"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/storage"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

type PartPreviewTaskHandler struct {
	q         *db.Queries
	store     storage.Store
	keyPrefix string
	files     map[string]string
	optimizer PartGLBOptimizer
}

type partPreviewPayload struct {
	PartLibraryVersionID string `json:"partLibraryVersionId"`
	LDrawPartNum         string `json:"ldrawPartNum"`
	GeneratorVersion     string `json:"generatorVersion"`
	Generation           int32  `json:"generation"`
	InputHash            string `json:"inputHash"`
}

// NewPartPreviewTaskHandler 创建 Part GLB 物化入口；LDraw 展开和 meshopt 压缩都在 Worker 边界内完成。
func NewPartPreviewTaskHandler(pool *pgxpool.Pool, store storage.Store, keyPrefix, ldrawRoot string, optimizer PartGLBOptimizer) (*PartPreviewTaskHandler, error) {
	files, err := indexLDrawFiles(ldrawRoot)
	if err != nil {
		return nil, err
	}
	return &PartPreviewTaskHandler{
		q: db.New(pool), store: store,
		keyPrefix: strings.Trim(keyPrefix, "/"), files: files, optimizer: optimizer,
	}, nil
}

func (h *PartPreviewTaskHandler) Handle(ctx context.Context, claimed task.ClaimedTask) (task.Result, error) {
	var payload partPreviewPayload
	if err := strictTaskPayload(claimed.Payload, &payload); err != nil ||
		payload.GeneratorVersion != PartPreviewGeneratorVersion || payload.Generation < 0 {
		return task.Result{}, partPreviewFailure(payload, false, "payload_invalid")
	}
	return h.materialize(ctx, claimed, payload)
}

// materialize 执行单个 Part 的确定性物化；按需任务与全库预生成共用该入口，避免两套 GLB 语义漂移。
func (h *PartPreviewTaskHandler) materialize(ctx context.Context, claimed task.ClaimedTask, payload partPreviewPayload) (task.Result, error) {
	libraryID, err := uuidutil.Parse(payload.PartLibraryVersionID)
	if err != nil {
		return task.Result{}, partPreviewFailure(payload, false, "library_invalid")
	}
	partNumber, err := normalizePartNumber(payload.LDrawPartNum)
	if err != nil || partNumber != payload.LDrawPartNum {
		return task.Result{}, partPreviewFailure(payload, false, "part_number_invalid")
	}
	input, err := h.q.GetPartPreviewTaskInput(ctx, db.GetPartPreviewTaskInputParams{
		PartLibraryVersionID: libraryID, LdrawPartNum: partNumber, TaskID: claimed.ID,
	})
	if errors.Is(err, pgx.ErrNoRows) {
		return task.Result{}, partPreviewFailure(payload, false, "input_missing")
	}
	if err != nil {
		return task.Result{}, err
	}
	if input.GeometryStatus != "ready" || input.Generation != payload.Generation ||
		input.GeneratorVersion == nil || *input.GeneratorVersion != payload.GeneratorVersion ||
		payload.InputHash != hashStrings(input.PartLibrarySourceHash, input.SourceFileHash, payload.GeneratorVersion) {
		return task.Result{}, partPreviewFailure(payload, false, "input_stale")
	}
	if input.PreviewStatus == "ready" && input.ArtifactID.Valid {
		return partPreviewResult(payload, input.ArtifactID), nil
	}
	return h.materializePrepared(ctx, claimed, payload, libraryID, partNumber, input.SourceRelativePath, input.SourceFileHash, true)
}

// materializePrepared 处理已经由数据库冻结并校验的 Part 输入；prebuild 可跳过逐行准备查询，
// 单项任务则通过 markRunning 呈现更精确的运行状态。
func (h *PartPreviewTaskHandler) materializePrepared(
	ctx context.Context,
	claimed task.ClaimedTask,
	payload partPreviewPayload,
	libraryID pgtype.UUID,
	partNumber, sourceRelativePath, sourceFileHash string,
	markRunning bool,
) (task.Result, error) {
	if markRunning {
		rows, err := h.q.MarkPartPreviewRunning(ctx, db.MarkPartPreviewRunningParams{
			PartLibraryVersionID: libraryID, LdrawPartNum: partNumber, TaskID: claimed.ID,
		})
		if err != nil {
			return task.Result{}, err
		}
		if rows != 1 {
			return task.Result{}, partPreviewFailure(payload, false, "state_stale")
		}
	}
	sourcePath, ok := h.files[normalizeLDrawPath(sourceRelativePath)]
	if !ok {
		return task.Result{}, partPreviewFailure(payload, false, "source_missing")
	}
	source, err := os.ReadFile(sourcePath)
	if err != nil {
		return task.Result{}, partPreviewFailure(payload, true, "source_read")
	}
	sourceSum := sha256.Sum256(source)
	if hex.EncodeToString(sourceSum[:]) != sourceFileHash {
		return task.Result{}, partPreviewFailure(payload, false, "source_hash_mismatch")
	}
	triangles, err := collectLDrawTriangles(normalizeLDrawPath(sourceRelativePath), h.files)
	if err != nil || len(triangles) == 0 {
		return task.Result{}, partPreviewFailure(payload, false, "geometry_expand")
	}
	rawGLB, err := buildPartGLB(triangles, payload.GeneratorVersion)
	if err != nil {
		return task.Result{}, partPreviewFailure(payload, false, "glb_build")
	}
	if h.optimizer == nil {
		return task.Result{}, partPreviewFailure(payload, false, "optimizer_missing")
	}
	glb, err := h.optimizer.Optimize(ctx, rawGLB)
	if err != nil {
		return task.Result{}, partPreviewFailure(payload, true, "optimizer_run")
	}
	// Part 模型是全局只读派生资产：最终字节决定对象键和 Artifact ID，跨用户、跨版本复用同一对象。
	sum := sha256.Sum256(glb)
	digest := hex.EncodeToString(sum[:])
	artifactID := deterministicUUID("part-preview-glb:" + digest)
	key := strings.Join(filterNonEmpty([]string{
		h.keyPrefix, "part-library-assets", "glb", payload.GeneratorVersion,
		digest[:2], digest + ".glb",
	}), "/")
	reusable := false
	if !markRunning {
		// 全库 snapshot 换代会重新生成同一内容哈希；verified Artifact 的完整定位均一致时直接复用对象。
		// 单项 materialize 可能由对象丢失触发，必须继续 PUT 才能承担 Storage 修复职责。
		reusable, err = h.q.IsVerifiedPartPreviewArtifactReusable(ctx, db.IsVerifiedPartPreviewArtifactReusableParams{
			ArtifactID: artifactID, StorageProvider: h.store.Provider(), StorageBucket: h.store.Bucket(),
			StorageKey: key, Sha256: digest, FileSize: int64(len(glb)),
		})
		if err != nil {
			return task.Result{}, err
		}
	}
	if !reusable {
		// Supabase 的 object info 对“尚不存在”的返回在不同网关版本并不稳定；内容寻址键配合 upsert
		// 本身就是幂等写，直接 PUT 还能为首次生成省去一次网络往返。
		if err := h.store.Put(ctx, key, "model/gltf-binary", bytes.NewReader(glb), int64(len(glb))); err != nil {
			return task.Result{}, partPreviewFailure(payload, true, "storage_put")
		}
	}
	_, err = h.q.FinalizePartPreviewArtifact(ctx, db.FinalizePartPreviewArtifactParams{
		GeneratorVersion: stringPointer(payload.GeneratorVersion), PartLibraryVersionID: libraryID,
		LdrawPartNum: partNumber, TaskID: claimed.ID, Generation: payload.Generation,
		ArtifactID: artifactID, OriginalFilename: digest + ".glb",
		StorageProvider: h.store.Provider(), StorageBucket: h.store.Bucket(), StorageKey: key,
		Sha256: digest, FileSize: int64(len(glb)), UploadedBy: claimed.OwnerID,
		Metadata: mustJSON(map[string]any{
			"derivedBy": PartPreviewMaterializeType, "generatorVersion": payload.GeneratorVersion,
			"meshCompression": "EXT_meshopt_compression", "gltfpackVersion": partPreviewGLTFPackVersion,
			"contentAddressed": true,
		}),
	})
	if errors.Is(err, pgx.ErrNoRows) {
		return task.Result{}, partPreviewFailure(payload, false, "state_stale")
	}
	if err != nil {
		return task.Result{}, err
	}
	return partPreviewResult(payload, artifactID), nil
}

func partPreviewResult(payload partPreviewPayload, artifactID pgtype.UUID) task.Result {
	return task.Result{
		Payload: mustJSON(map[string]any{
			"partLibraryVersionId": payload.PartLibraryVersionID, "ldrawPartNum": payload.LDrawPartNum,
			"artifactId": uuidutil.String(artifactID), "generatorVersion": payload.GeneratorVersion,
		}),
		// 全局 Part Artifact 没有 owner，不能写入要求 owner 一致的通用 tasks.result_artifact_id；
		// Part 到 Artifact 的权威关系已由同一事务中的 part_previews.artifact_id 固化。
		ArtifactID: pgtype.UUID{},
	}
}

func partPreviewFailure(payload partPreviewPayload, retryable bool, stage string) *task.Failure {
	return &task.Failure{Code: "component_repo.part_preview_unavailable", Params: map[string]any{
		"partLibraryVersionId": payload.PartLibraryVersionID, "ldrawPartNum": payload.LDrawPartNum, "stage": stage,
	}, Retryable: retryable}
}

type ldrawVector struct{ x, y, z float64 }

type ldrawTransform struct {
	m [9]float64
	o ldrawVector
}

type ldrawTriangle [3]ldrawVector

var identityLDrawTransform = ldrawTransform{m: [9]float64{1, 0, 0, 0, 1, 0, 0, 0, 1}}

func (t ldrawTransform) apply(v ldrawVector) ldrawVector {
	return ldrawVector{
		t.m[0]*v.x + t.m[1]*v.y + t.m[2]*v.z + t.o.x,
		t.m[3]*v.x + t.m[4]*v.y + t.m[5]*v.z + t.o.y,
		t.m[6]*v.x + t.m[7]*v.y + t.m[8]*v.z + t.o.z,
	}
}

func (t ldrawTransform) combine(child ldrawTransform) ldrawTransform {
	var combined ldrawTransform
	for row := 0; row < 3; row++ {
		for column := 0; column < 3; column++ {
			for k := 0; k < 3; k++ {
				combined.m[row*3+column] += t.m[row*3+k] * child.m[k*3+column]
			}
		}
	}
	combined.o = t.apply(child.o)
	return combined
}

func indexLDrawFiles(root string) (map[string]string, error) {
	root = strings.TrimSpace(root)
	if root == "" {
		return nil, errors.New("LDRAW_ROOT is required for preview materialization")
	}
	info, err := os.Stat(root)
	if err != nil || !info.IsDir() {
		return nil, errors.New("LDRAW_ROOT must be an existing directory")
	}
	result := map[string]string{}
	aliases := map[string]string{}
	for _, base := range []string{root, filepath.Join(root, "UnOfficial"), filepath.Join(root, "Unofficial")} {
		if baseInfo, statErr := os.Stat(base); statErr != nil || !baseInfo.IsDir() {
			continue
		}
		for _, section := range []string{"parts", "p"} {
			sectionRoot := filepath.Join(base, section)
			if sectionInfo, statErr := os.Stat(sectionRoot); statErr != nil || !sectionInfo.IsDir() {
				continue
			}
			err = filepath.WalkDir(sectionRoot, func(path string, entry fs.DirEntry, walkErr error) error {
				if walkErr != nil {
					return walkErr
				}
				if entry.IsDir() || !strings.EqualFold(filepath.Ext(entry.Name()), ".dat") {
					return nil
				}
				relative, relErr := filepath.Rel(base, path)
				if relErr != nil {
					return relErr
				}
				key := normalizeLDrawPath(relative)
				if _, exists := result[key]; !exists {
					result[key] = path
				}
				if !samePath(base, root) {
					full, fullErr := filepath.Rel(root, path)
					if fullErr != nil {
						return fullErr
					}
					fullKey := normalizeLDrawPath(full)
					if _, exists := result[fullKey]; !exists {
						result[fullKey] = path
					}
				}
				if strings.HasPrefix(key, "p/48/") {
					aliases["p/"+strings.TrimPrefix(key, "p/48/")] = path
				}
				return nil
			})
			if err != nil {
				return nil, err
			}
		}
	}
	for alias, path := range aliases {
		if _, exists := result[alias]; !exists {
			result[alias] = path
		}
	}
	if len(result) == 0 {
		return nil, errors.New("LDRAW_ROOT contains no Part or primitive files")
	}
	return result, nil
}

func normalizeLDrawPath(value string) string {
	value = strings.ReplaceAll(strings.TrimSpace(value), "\\", "/")
	return strings.ToLower(strings.TrimPrefix(filepath.ToSlash(value), "./"))
}

func samePath(left, right string) bool {
	leftAbs, leftErr := filepath.Abs(left)
	rightAbs, rightErr := filepath.Abs(right)
	return leftErr == nil && rightErr == nil && leftAbs == rightAbs
}

func collectLDrawTriangles(relativePath string, files map[string]string) ([]ldrawTriangle, error) {
	return collectLDrawFile(relativePath, files, identityLDrawTransform, nil)
}

func collectLDrawFile(relativePath string, files map[string]string, transform ldrawTransform, stack []string) ([]ldrawTriangle, error) {
	if len(stack) >= 64 {
		return nil, errors.New("maximum LDraw recursion exceeded")
	}
	for _, active := range stack {
		if active == relativePath {
			return nil, errors.New("recursive LDraw include")
		}
	}
	path, ok := files[relativePath]
	if !ok {
		return nil, errors.New("LDraw file missing")
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	reader := bufio.NewReader(file)
	triangles := []ldrawTriangle{}
	for {
		line, readErr := reader.ReadString('\n')
		if readErr != nil && len(line) == 0 {
			if errors.Is(readErr, io.EOF) {
				break
			}
			return nil, readErr
		}
		fields := strings.Fields(strings.TrimSpace(line))
		if len(fields) == 0 || fields[0] == "0" || fields[0] == "2" || fields[0] == "5" {
			if readErr != nil {
				if errors.Is(readErr, io.EOF) {
					break
				}
				return nil, readErr
			}
			continue
		}
		switch fields[0] {
		case "1":
			if len(fields) != 15 {
				return nil, errors.New("invalid LDraw reference")
			}
			values, parseErr := parseLDrawFloats(fields[2:14])
			if parseErr != nil {
				return nil, parseErr
			}
			child := ldrawTransform{
				m: [9]float64{values[3], values[4], values[5], values[6], values[7], values[8], values[9], values[10], values[11]},
				o: ldrawVector{values[0], values[1], values[2]},
			}
			reference := normalizeLDrawPath(strings.Trim(fields[14], `"`))
			childPath := resolveLDrawReference(relativePath, reference, files)
			if childPath == "" {
				if reference == "6221655zc01.dat" {
					continue
				}
				return nil, errors.New("missing LDraw reference")
			}
			childTriangles, childErr := collectLDrawFile(childPath, files, transform.combine(child), append(stack, relativePath))
			if childErr != nil {
				return nil, childErr
			}
			triangles = append(triangles, childTriangles...)
		case "3", "4":
			expected := 11
			if fields[0] == "4" {
				expected = 14
			}
			if len(fields) < expected {
				return nil, errors.New("invalid LDraw face")
			}
			values, parseErr := parseLDrawFloats(fields[2:expected])
			if parseErr != nil {
				return nil, parseErr
			}
			vertices := make([]ldrawVector, 0, len(values)/3)
			for index := 0; index < len(values); index += 3 {
				vertices = append(vertices, transform.apply(ldrawVector{values[index], values[index+1], values[index+2]}))
			}
			triangles = append(triangles, ldrawTriangle{vertices[0], vertices[1], vertices[2]})
			if len(vertices) == 4 {
				triangles = append(triangles, ldrawTriangle{vertices[0], vertices[2], vertices[3]})
			}
		}
		if readErr != nil {
			if errors.Is(readErr, io.EOF) {
				break
			}
			return nil, readErr
		}
	}
	return triangles, nil
}

func parseLDrawFloats(values []string) ([]float64, error) {
	parsed := make([]float64, len(values))
	for index, value := range values {
		number, err := strconv.ParseFloat(value, 64)
		if err != nil || math.IsNaN(number) || math.IsInf(number, 0) {
			return nil, errors.New("invalid LDraw number")
		}
		parsed[index] = number
	}
	return parsed, nil
}

func resolveLDrawReference(fromPath, reference string, files map[string]string) string {
	section := strings.SplitN(fromPath, "/", 2)[0]
	directory := strings.TrimSuffix(fromPath, filepath.ToSlash(filepath.Base(fromPath)))
	directory = strings.TrimSuffix(directory, "/")
	candidates := []string{}
	if strings.HasPrefix(reference, "parts/") || strings.HasPrefix(reference, "p/") {
		candidates = append(candidates, reference)
	} else if strings.Contains(reference, "/") {
		if strings.HasPrefix(reference, "s/") {
			candidates = append(candidates, "parts/"+reference)
		}
		if strings.HasPrefix(reference, "48/") || strings.HasPrefix(reference, "8/") {
			candidates = append(candidates, "p/"+strings.TrimPrefix(strings.TrimPrefix(reference, "48/"), "8/"))
		}
		if section == "p" {
			candidates = append(candidates, "p/"+reference)
		}
		candidates = append(candidates, "p/"+reference, reference)
	} else {
		if directory != "" {
			candidates = append(candidates, directory+"/"+reference)
		}
		if section == "parts" {
			candidates = append(candidates, "parts/"+reference)
		}
		candidates = append(candidates, "p/"+reference)
	}
	for _, candidate := range candidates {
		candidate = normalizeLDrawPath(candidate)
		if _, exists := files[candidate]; exists {
			return candidate
		}
	}
	return ""
}

func buildPartGLB(triangles []ldrawTriangle, generator string) ([]byte, error) {
	if len(triangles) == 0 {
		return nil, errors.New("part GLB requires at least one triangle")
	}
	// LDraw 使用 Y 向下的 LDU；项目 GLB 使用 Y 向上并把 20 LDU 缩放为 1 stud。
	converted := make([]ldrawTriangle, 0, len(triangles))
	for _, triangle := range triangles {
		converted = append(converted, ldrawTriangle{
			convertPartVertex(triangle[0]), convertPartVertex(triangle[2]), convertPartVertex(triangle[1]),
		})
	}
	faceNormals := make([]ldrawVector, len(converted))
	positionNormals := map[[3]uint64][]ldrawVector{}
	for index, triangle := range converted {
		normal := normalizedCross(triangle[1], triangle[0], triangle[2])
		faceNormals[index] = normal
		for _, vertex := range triangle {
			key := ldrawPositionKey(vertex)
			positionNormals[key] = append(positionNormals[key], normal)
		}
	}
	type vertexKey struct{ px, py, pz, nx, ny, nz uint32 }
	vertexLookup := map[vertexKey]uint32{}
	positions := make([]float32, 0, len(converted)*9)
	normals := make([]float32, 0, len(converted)*9)
	indices := make([]uint32, 0, len(triangles)*3)
	minimum := [3]float64{math.Inf(1), math.Inf(1), math.Inf(1)}
	maximum := [3]float64{math.Inf(-1), math.Inf(-1), math.Inf(-1)}
	for faceIndex, triangle := range converted {
		for _, vertex := range triangle {
			normal := creasedNormal(faceNormals[faceIndex], positionNormals[ldrawPositionKey(vertex)])
			position := [3]float32{float32(vertex.x), float32(vertex.y), float32(vertex.z)}
			normal32 := [3]float32{float32(normal.x), float32(normal.y), float32(normal.z)}
			key := vertexKey{
				math.Float32bits(position[0]), math.Float32bits(position[1]), math.Float32bits(position[2]),
				math.Float32bits(normal32[0]), math.Float32bits(normal32[1]), math.Float32bits(normal32[2]),
			}
			index, exists := vertexLookup[key]
			if !exists {
				index = uint32(len(positions) / 3)
				vertexLookup[key] = index
				positions = append(positions, position[:]...)
				normals = append(normals, normal32[:]...)
			}
			indices = append(indices, index)
			for axis, value := range []float64{vertex.x, vertex.y, vertex.z} {
				minimum[axis] = math.Min(minimum[axis], value)
				maximum[axis] = math.Max(maximum[axis], value)
			}
		}
	}
	bin := &bytes.Buffer{}
	for _, value := range positions {
		if err := binary.Write(bin, binary.LittleEndian, value); err != nil {
			return nil, err
		}
	}
	normalOffset := bin.Len()
	for _, value := range normals {
		if err := binary.Write(bin, binary.LittleEndian, value); err != nil {
			return nil, err
		}
	}
	indexOffset := bin.Len()
	for _, value := range indices {
		if err := binary.Write(bin, binary.LittleEndian, value); err != nil {
			return nil, err
		}
	}
	gltf := map[string]any{
		"asset": map[string]any{"version": "2.0", "generator": generator},
		"scene": 0, "scenes": []any{map[string]any{"nodes": []int{0}}},
		"nodes": []any{map[string]any{"name": "LDraw Part", "mesh": 0}},
		"meshes": []any{map[string]any{"primitives": []any{map[string]any{
			"attributes": map[string]any{"POSITION": 0, "NORMAL": 1}, "indices": 2, "material": 0,
		}}}},
		"materials": []any{map[string]any{"doubleSided": true, "pbrMetallicRoughness": map[string]any{
			"baseColorFactor": []float64{0.72, 0.74, 0.78, 1}, "metallicFactor": 0, "roughnessFactor": 0.72,
		}}},
		"buffers": []any{map[string]any{"byteLength": bin.Len()}},
		"bufferViews": []any{
			map[string]any{"buffer": 0, "byteOffset": 0, "byteLength": normalOffset, "target": 34962},
			map[string]any{"buffer": 0, "byteOffset": normalOffset, "byteLength": indexOffset - normalOffset, "target": 34962},
			map[string]any{"buffer": 0, "byteOffset": indexOffset, "byteLength": len(indices) * 4, "target": 34963},
		},
		"accessors": []any{
			map[string]any{"bufferView": 0, "componentType": 5126, "count": len(positions) / 3, "type": "VEC3", "min": minimum, "max": maximum},
			map[string]any{"bufferView": 1, "componentType": 5126, "count": len(normals) / 3, "type": "VEC3"},
			map[string]any{"bufferView": 2, "componentType": 5125, "count": len(indices), "type": "SCALAR"},
		},
	}
	jsonChunk, err := json.Marshal(gltf)
	if err != nil {
		return nil, err
	}
	for len(jsonChunk)%4 != 0 {
		jsonChunk = append(jsonChunk, ' ')
	}
	for bin.Len()%4 != 0 {
		bin.WriteByte(0)
	}
	total := 12 + 8 + len(jsonChunk) + 8 + bin.Len()
	output := &bytes.Buffer{}
	output.WriteString("glTF")
	for _, value := range []uint32{2, uint32(total), uint32(len(jsonChunk))} {
		if err := binary.Write(output, binary.LittleEndian, value); err != nil {
			return nil, err
		}
	}
	output.WriteString("JSON")
	output.Write(jsonChunk)
	if err := binary.Write(output, binary.LittleEndian, uint32(bin.Len())); err != nil {
		return nil, err
	}
	output.WriteString("BIN\x00")
	output.Write(bin.Bytes())
	return output.Bytes(), nil
}

func convertPartVertex(vertex ldrawVector) ldrawVector {
	return ldrawVector{x: vertex.x * 0.05, y: -vertex.y * 0.05, z: vertex.z * 0.05}
}

func ldrawPositionKey(vertex ldrawVector) [3]uint64 {
	return [3]uint64{math.Float64bits(vertex.x), math.Float64bits(vertex.y), math.Float64bits(vertex.z)}
}

func normalizedCross(a, origin, b ldrawVector) ldrawVector {
	left := ldrawVector{x: a.x - origin.x, y: a.y - origin.y, z: a.z - origin.z}
	right := ldrawVector{x: b.x - origin.x, y: b.y - origin.y, z: b.z - origin.z}
	normal := ldrawVector{
		x: left.y*right.z - left.z*right.y,
		y: left.z*right.x - left.x*right.z,
		z: left.x*right.y - left.y*right.x,
	}
	return normalizeVector(normal)
}

func normalizeVector(vector ldrawVector) ldrawVector {
	length := math.Sqrt(vector.x*vector.x + vector.y*vector.y + vector.z*vector.z)
	if length == 0 {
		return ldrawVector{y: 1}
	}
	return ldrawVector{x: vector.x / length, y: vector.y / length, z: vector.z / length}
}

func creasedNormal(face ldrawVector, candidates []ldrawVector) ldrawVector {
	const creaseCosine = 0.5 // 60°：平面保持硬边，圆柱相邻面共享平滑法线。
	combined := ldrawVector{}
	for _, candidate := range candidates {
		if face.x*candidate.x+face.y*candidate.y+face.z*candidate.z >= creaseCosine {
			combined.x += candidate.x
			combined.y += candidate.y
			combined.z += candidate.z
		}
	}
	return normalizeVector(combined)
}
