package workbench

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"os"
	"sort"
	"strings"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/scene"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/storage"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

type ValidationTaskHandler struct {
	pool *pgxpool.Pool
	q    *db.Queries
}

func NewValidationTaskHandler(pool *pgxpool.Pool) *ValidationTaskHandler {
	return &ValidationTaskHandler{pool: pool, q: db.New(pool)}
}

type validationPayload struct {
	CandidateID      string `json:"candidateId"`
	VersionID        string `json:"versionId"`
	ValidationLevel  string `json:"validationLevel"`
	ValidatorVersion string `json:"validatorVersion"`
	InputHash        string `json:"inputHash"`
}

func (h *ValidationTaskHandler) Handle(ctx context.Context, claimed task.ClaimedTask) (task.Result, error) {
	var payload validationPayload
	if err := strictTaskPayload(claimed.Payload, &payload); err != nil || payload.ValidationLevel != "publish" || payload.ValidatorVersion != ValidatorVersion {
		return task.Result{}, &task.Failure{Code: "component_repo.validation_unavailable", Params: map[string]any{}, Retryable: false}
	}
	candidateID, err := uuidutil.Parse(payload.CandidateID)
	if err != nil {
		return task.Result{}, permanentValidation(payload.CandidateID)
	}
	versionID, err := uuidutil.Parse(payload.VersionID)
	if err != nil {
		return task.Result{}, permanentValidation(payload.CandidateID)
	}
	if existing, existingErr := h.q.GetValidationReportByTask(ctx, db.GetValidationReportByTaskParams{TaskID: claimed.ID, OwnerID: claimed.OwnerID}); existingErr == nil {
		return validationResult(existing.ID, existing.Passed), nil
	} else if !errors.Is(existingErr, pgx.ErrNoRows) {
		return task.Result{}, existingErr
	}
	input, err := h.q.GetValidationTaskInput(ctx, db.GetValidationTaskInputParams{CandidateID: candidateID, OwnerID: claimed.OwnerID, VersionID: versionID})
	if errors.Is(err, pgx.ErrNoRows) {
		return task.Result{}, permanentValidation(payload.CandidateID)
	}
	if err != nil {
		return task.Result{}, err
	}
	currentInputHash := hashStrings(input.InterfaceSignature, input.StructureHash,
		input.GeometryHash, valueOrEmpty(input.PartLibrarySourceHash), ValidatorVersion)
	if payload.InputHash != currentInputHash {
		return task.Result{}, permanentValidation(payload.CandidateID)
	}
	checks, issues := validateInput(input)
	passed := len(issues) == 0
	reportID, err := uuidutil.New()
	if err != nil {
		return task.Result{}, err
	}
	report, err := txValue(ctx, h.pool, func(q *db.Queries) (db.CreateValidationReportRow, error) {
		created, createErr := q.CreateValidationReport(ctx, db.CreateValidationReportParams{ID: reportID, ComponentCandidateID: candidateID, ComponentVersionID: versionID, OwnerID: claimed.OwnerID, TaskID: claimed.ID, ValidationLevel: payload.ValidationLevel, Passed: passed, Checks: mustJSON(checks), Issues: mustJSON(issues), ValidatorVersion: ValidatorVersion, InterfaceSignature: input.InterfaceSignature, StructureHash: input.StructureHash, GeometryHash: input.GeometryHash})
		if createErr != nil {
			return db.CreateValidationReportRow{}, createErr
		}
		// 验证是可选质量报告而非发布门禁；无论通过与否都关联最新报告，详情页才能稳定恢复结果。
		if attachErr := q.AttachLatestValidationReport(ctx, db.AttachLatestValidationReportParams{ReportID: reportID, VersionID: versionID, CandidateID: candidateID, InterfaceSignature: input.InterfaceSignature, StructureHash: input.StructureHash, GeometryHash: input.GeometryHash}); attachErr != nil {
			return db.CreateValidationReportRow{}, attachErr
		}
		return created, nil
	})
	if err != nil {
		return task.Result{}, err
	}
	return validationResult(report.ID, passed), nil
}

func validateInput(input db.GetValidationTaskInputRow) ([]map[string]any, []map[string]any) {
	partRefs, partCount, transformsOK, bboxOK := analyzeScene(input.Document)
	var bom map[string]int
	bomOK := json.Unmarshal(input.Bom, &bom) == nil && validBOM(bom, partRefs)
	var parseIssues []json.RawMessage
	parseOK := json.Unmarshal(input.ParseIssues, &parseIssues) == nil
	checks := []struct {
		name   string
		passed bool
	}{
		{"source_hash_valid", input.SourceVerificationStatus == "verified" && validSHA256(input.SourceSha256)},
		{"exchange_artifact_present", (input.ExchangeArtifactID.Valid && input.ExchangeVerificationStatus != nil && *input.ExchangeVerificationStatus == "verified") || input.SourceArtifactType == "ldraw_ldr" || input.SourceArtifactType == "ldraw_mpd"},
		{"parts_resolved", transformsOK && bomOK && partCount > 0 && input.PartLibraryConsistent && input.UnresolvedPartCount == 0},
		{"transforms_valid", transformsOK},
		{"relations_valid", input.InvalidRelationCount == 0},
		{"interfaces_valid", validSHA256(input.InterfaceSignature) && input.ValidExternalInterfaceCount > 0 && input.InvalidInterfaceCount == 0},
		{"bbox_calculated", bboxOK && parseOK && validSHA256(input.StructureHash) && validSHA256(input.GeometryHash)},
	}
	result := make([]map[string]any, 0, len(checks))
	issues := []map[string]any{}
	for _, check := range checks {
		status := "pass"
		if !check.passed {
			status = "fail"
		}
		code := "component_repo.validation." + check.name
		result = append(result, map[string]any{"code": code, "status": status, "params": map[string]any{}, "path": []any{}})
		if !check.passed {
			issues = append(issues, map[string]any{"code": code, "severity": "error", "params": map[string]any{}, "path": []any{}})
		}
	}
	return result, issues
}

func analyzeScene(raw json.RawMessage) (map[string]int, int, bool, bool) {
	// 发布校验直接消费共享场景展开结果，避免 BOM 校验与 Preview 对 root/递归规则产生漂移。
	expanded, err := scene.ExpandJSON(raw)
	if err != nil {
		return nil, 0, false, false
	}
	partRefs := expanded.BOM()
	partCount := len(expanded.Parts)
	minPosition := [3]float64{math.Inf(1), math.Inf(1), math.Inf(1)}
	maxPosition := [3]float64{math.Inf(-1), math.Inf(-1), math.Inf(-1)}
	for _, part := range expanded.Parts {
		for index, value := range part.Matrix[12:15] {
			if math.IsNaN(value) || math.IsInf(value, 0) {
				return nil, 0, false, false
			}
			minPosition[index] = math.Min(minPosition[index], value)
			maxPosition[index] = math.Max(maxPosition[index], value)
		}
	}
	return partRefs, partCount, true, partCount > 0 && minPosition[0] <= maxPosition[0]
}

func validBOM(bom, actual map[string]int) bool {
	if len(bom) == 0 || len(bom) != len(actual) {
		return false
	}
	normalized := make(map[string]int, len(bom))
	for reference, quantity := range bom {
		name := strings.ToLower(strings.TrimSpace(reference))
		if name == "" || quantity <= 0 {
			return false
		}
		if _, duplicate := normalized[name]; duplicate {
			return false
		}
		normalized[name] = quantity
	}
	if len(normalized) != len(actual) {
		return false
	}
	for reference, quantity := range actual {
		if normalized[reference] != quantity {
			return false
		}
	}
	return true
}

type PreviewTaskHandler struct {
	pool      *pgxpool.Pool
	q         *db.Queries
	store     storage.Store
	keyPrefix string
	files     map[string]string
}

func NewPreviewTaskHandler(pool *pgxpool.Pool, store storage.Store, keyPrefix, ldrawRoot string) (*PreviewTaskHandler, error) {
	files, err := indexLDrawFiles(ldrawRoot)
	if err != nil {
		return nil, err
	}
	return &PreviewTaskHandler{
		pool: pool, q: db.New(pool), store: store,
		keyPrefix: strings.Trim(keyPrefix, "/"), files: files,
	}, nil
}

type previewPayload struct {
	VersionID        string `json:"versionId"`
	GeneratorVersion string `json:"generatorVersion"`
	Generation       int32  `json:"generation"`
	InputHash        string `json:"inputHash"`
}

func (h *PreviewTaskHandler) Handle(ctx context.Context, claimed task.ClaimedTask) (task.Result, error) {
	var payload previewPayload
	if err := strictTaskPayload(claimed.Payload, &payload); err != nil || payload.GeneratorVersion != PreviewGeneratorVersion || payload.Generation < 0 {
		return task.Result{}, &task.Failure{Code: "component_repo.preview_unavailable", Params: map[string]any{}, Retryable: false}
	}
	versionID, err := uuidutil.Parse(payload.VersionID)
	if err != nil {
		return task.Result{}, previewFailure(payload.VersionID, false)
	}
	input, err := h.q.GetPreviewTaskInput(ctx, db.GetPreviewTaskInputParams{VersionID: versionID, OwnerID: claimed.OwnerID, TaskID: claimed.ID})
	if errors.Is(err, pgx.ErrNoRows) {
		return task.Result{}, previewFailure(payload.VersionID, false)
	}
	if err != nil {
		return task.Result{}, err
	}
	if input.PreviewGeneration != payload.Generation || input.PreviewGeneratorVersion == nil || *input.PreviewGeneratorVersion != payload.GeneratorVersion {
		return task.Result{}, previewFailure(payload.VersionID, false)
	}
	if payload.InputHash != componentPreviewInputHash(
		uuidutil.String(input.VersionID), uuidutil.String(input.SceneSnapshotID),
		input.StructureHash, input.GeometryHash,
		uuidutil.String(input.PartLibraryVersionID), input.PartLibrarySourceHash,
		payload.GeneratorVersion,
	) {
		return task.Result{}, previewFailure(payload.VersionID, false)
	}
	worldParts, err := collectComponentWorldParts(input.Document)
	if err != nil {
		return task.Result{}, previewFailure(payload.VersionID, false)
	}
	requiredPartRefs := uniqueComponentPartRefs(worldParts)
	geometryRows, err := h.q.ListReadyPartGeometryForPreview(ctx, db.ListReadyPartGeometryForPreviewParams{
		LdrawPartNums: requiredPartRefs, PartLibraryVersionID: input.PartLibraryVersionID,
	})
	if err != nil {
		return task.Result{}, err
	}
	readyPartRefs := make(map[string]bool, len(geometryRows))
	for _, row := range geometryRows {
		readyPartRefs[row.LdrawPartNum] = true
	}
	omittedPartRefs := missingComponentPartRefs(requiredPartRefs, readyPartRefs)
	if input.PreviewStatus == "ready" && input.PreviewArtifactID.Valid {
		return task.Result{Payload: mustJSON(map[string]any{
			"versionId": payload.VersionID, "artifactId": uuidutil.String(input.PreviewArtifactID),
			"generatorVersion": payload.GeneratorVersion, "omittedPartRefs": omittedPartRefs,
			"complete": len(omittedPartRefs) == 0,
		}), ArtifactID: input.PreviewArtifactID}, nil
	}
	if err := h.q.MarkVersionPreviewRunning(ctx, db.MarkVersionPreviewRunningParams{VersionID: versionID, TaskID: claimed.ID}); err != nil {
		return task.Result{}, err
	}
	trianglesByPart := make(map[string][]ldrawTriangle, len(geometryRows))
	for _, row := range geometryRows {
		sourcePath := normalizeLDrawPath(row.SourceRelativePath)
		localPath, ok := h.files[sourcePath]
		if !ok {
			return task.Result{}, previewFailure(payload.VersionID, false)
		}
		source, readErr := os.ReadFile(localPath)
		if readErr != nil {
			return task.Result{}, previewFailure(payload.VersionID, true)
		}
		sourceSum := sha256.Sum256(source)
		if hex.EncodeToString(sourceSum[:]) != row.SourceFileHash {
			return task.Result{}, previewFailure(payload.VersionID, false)
		}
		triangles, collectErr := collectLDrawTriangles(sourcePath, h.files)
		if collectErr != nil || len(triangles) == 0 {
			return task.Result{}, previewFailure(payload.VersionID, false)
		}
		trianglesByPart[row.LdrawPartNum] = triangles
	}
	// Part Library 未提供 ready geometry 时保留 BOM 事实，但从整体预览中跳过对应实例。
	// 已声明 ready 的 source 缺失、哈希漂移或解析失败仍属于运行环境/快照错误，不能静默降级。
	glb, bounds, err := buildComponentGLB(worldParts, trianglesByPart, payload.GeneratorVersion)
	if err != nil {
		return task.Result{}, previewFailure(payload.VersionID, false)
	}
	artifactID := deterministicUUID("component-preview:" + payload.VersionID + ":" + payload.GeneratorVersion)
	artifactText := uuidutil.String(artifactID)
	ownerText := uuidutil.String(claimed.OwnerID)
	key := strings.Join(filterNonEmpty([]string{ownerText, h.keyPrefix, "previews", payload.VersionID, payload.GeneratorVersion, artifactText + ".glb"}), "/")
	if err := h.store.Put(ctx, key, "model/gltf-binary", bytes.NewReader(glb), int64(len(glb))); err != nil {
		return task.Result{}, previewFailure(payload.VersionID, true)
	}
	sum := sha256.Sum256(glb)
	digest := hex.EncodeToString(sum[:])
	_, err = txValue(ctx, h.pool, func(q *db.Queries) (struct{}, error) {
		if _, upsertErr := q.UpsertPreviewArtifact(ctx, db.UpsertPreviewArtifactParams{
			ID: artifactID, OwnerID: claimed.OwnerID, OriginalFilename: payload.VersionID + ".glb",
			StorageProvider: h.store.Provider(), StorageBucket: h.store.Bucket(), StorageKey: key,
			Sha256: digest, FileSize: int64(len(glb)), UploadedBy: claimed.OwnerID,
			Metadata: mustJSON(map[string]any{
				"derivedBy": PreviewMaterializeType, "generatorVersion": payload.GeneratorVersion,
				"versionId": payload.VersionID, "partLibraryVersionId": uuidutil.String(input.PartLibraryVersionID),
				"partLibrarySourceHash": input.PartLibrarySourceHash, "omittedPartRefs": omittedPartRefs,
				"complete": len(omittedPartRefs) == 0,
			}),
			DerivedFromArtifactID: input.SourceArtifactID,
		}); upsertErr != nil {
			return struct{}{}, upsertErr
		}
		readyParams := db.MarkVersionPreviewReadyParams{
			ArtifactID: artifactID, GeneratorVersion: stringPointer(payload.GeneratorVersion),
			VersionID: versionID, TaskID: claimed.ID, PreviewGeneration: payload.Generation,
		}
		if bounds != nil {
			readyParams.PreviewBboxMin = bounds.minimum[:]
			readyParams.PreviewBboxMax = bounds.maximum[:]
			readyParams.LogicalWidthStud = previewNumeric(bounds.logicalWidthStud)
			readyParams.LogicalDepthStud = previewNumeric(bounds.logicalDepthStud)
			readyParams.LogicalHeightPlate = previewNumeric(bounds.logicalHeightPlate)
			readyParams.PreviewBoundsComplete = boolPointer(bounds.complete)
		}
		if readyErr := q.MarkVersionPreviewReady(ctx, readyParams); readyErr != nil {
			return struct{}{}, readyErr
		}
		return struct{}{}, nil
	})
	if err != nil {
		return task.Result{}, err
	}
	return task.Result{Payload: mustJSON(map[string]any{
		"versionId": payload.VersionID, "artifactId": artifactText, "generatorVersion": payload.GeneratorVersion,
		"omittedPartRefs": omittedPartRefs, "complete": len(omittedPartRefs) == 0,
	}), ArtifactID: artifactID}, nil
}

type componentWorldPart struct {
	instanceID string
	partRef    string
	colorCode  string
	matrix     [16]float64
}

// componentPreviewBounds 保存 Preview 实际渲染几何在 LDraw 世界坐标中的整体 AABB。
// logicalSize 使用 LEGO 业务单位投影；complete=false 表示 Box 只覆盖可渲染零件。
type componentPreviewBounds struct {
	minimum            [3]float64
	maximum            [3]float64
	logicalWidthStud   float64
	logicalDepthStud   float64
	logicalHeightPlate float64
	complete           bool
}

func collectComponentWorldParts(raw json.RawMessage) ([]componentWorldPart, error) {
	// Relation 与 GLB 保留既有内部结构，但实例集合和 world transform 统一来自 scene 包。
	expanded, err := scene.ExpandJSON(raw)
	if err != nil || len(expanded.Parts) == 0 {
		return nil, errors.New("component preview unavailable")
	}
	worldParts := make([]componentWorldPart, 0, len(expanded.Parts))
	for _, part := range expanded.Parts {
		worldParts = append(worldParts, componentWorldPart{
			instanceID: part.InstanceID,
			partRef:    part.PartRef,
			colorCode:  part.ColorCode,
			matrix:     part.Matrix,
		})
	}
	return worldParts, nil
}

func uniqueComponentPartRefs(parts []componentWorldPart) []string {
	seen := map[string]bool{}
	result := []string{}
	for _, part := range parts {
		if !seen[part.partRef] {
			seen[part.partRef] = true
			result = append(result, part.partRef)
		}
	}
	sort.Strings(result)
	return result
}

// missingComponentPartRefs 返回缺少 ready geometry 的稳定排序 Part 编号，用于任务结果和产物元数据。
func missingComponentPartRefs(required []string, readyPartRefs map[string]bool) []string {
	missing := make([]string, 0)
	for _, partRef := range required {
		if !readyPartRefs[partRef] {
			missing = append(missing, partRef)
		}
	}
	return missing
}

// buildComponentGLB 同时生成整体 GLB 与多 Root 展开后的世界空间 Box。
// Box 只统计真正写入 GLB 的三角形；缺失几何不会阻断预览，但会将完整性标记为 false。
func buildComponentGLB(parts []componentWorldPart, trianglesByPart map[string][]ldrawTriangle, generator string) ([]byte, *componentPreviewBounds, error) {
	bin := &bytes.Buffer{}
	bufferViews := []any{}
	accessors := []any{}
	meshes := []any{}
	materials := []any{}
	meshIndexByKey := map[string]int{}
	materialIndexByColor := map[string]int{}
	rootNode := map[string]any{"name": "Component Preview", "scale": []float64{0.05, -0.05, 0.05}, "children": []int{}}
	nodes := []any{rootNode}
	rootChildren := []int{}
	minimum := [3]float64{math.Inf(1), math.Inf(1), math.Inf(1)}
	maximum := [3]float64{math.Inf(-1), math.Inf(-1), math.Inf(-1)}
	renderedParts := 0
	for _, part := range parts {
		// 缺少几何的实例只从 GLB 场景中省略；BOM 仍由独立接口完整返回。
		if len(trianglesByPart[part.partRef]) == 0 {
			continue
		}
		renderedParts++
		// 使用每个实例的 world matrix 变换所有顶点，旋转、多层子模型与多个 Root
		// 都统一落入同一个 AABB；不能只变换局部 min/max 两个角点。
		for _, triangle := range trianglesByPart[part.partRef] {
			for _, vertex := range triangle {
				point := transformComponentPoint(part.matrix, [3]float64{vertex.x, vertex.y, vertex.z})
				for axis, value := range point {
					minimum[axis] = math.Min(minimum[axis], value)
					maximum[axis] = math.Max(maximum[axis], value)
				}
			}
		}
		meshKey := part.partRef + "\x00" + part.colorCode
		meshIndex, exists := meshIndexByKey[meshKey]
		if !exists {
			triangles := trianglesByPart[part.partRef]
			materialIndex, exists := materialIndexByColor[part.colorCode]
			if !exists {
				materialIndex = len(materials)
				materialIndexByColor[part.colorCode] = materialIndex
				materials = append(materials, ldrawMaterial(part.colorCode))
			}
			positions, indices, minimum, maximum := ldrawTrianglesToBuffers(triangles)
			positionOffset := bin.Len()
			for _, value := range positions {
				if err := binary.Write(bin, binary.LittleEndian, value); err != nil {
					return nil, nil, err
				}
			}
			indexOffset := bin.Len()
			for _, value := range indices {
				if err := binary.Write(bin, binary.LittleEndian, value); err != nil {
					return nil, nil, err
				}
			}
			positionView := len(bufferViews)
			bufferViews = append(bufferViews, map[string]any{
				"buffer": 0, "byteOffset": positionOffset, "byteLength": len(positions) * 4, "target": 34962,
			})
			indexView := len(bufferViews)
			bufferViews = append(bufferViews, map[string]any{
				"buffer": 0, "byteOffset": indexOffset, "byteLength": len(indices) * 4, "target": 34963,
			})
			positionAccessor := len(accessors)
			accessors = append(accessors, map[string]any{
				"bufferView": positionView, "componentType": 5126, "count": len(positions) / 3,
				"type": "VEC3", "min": minimum, "max": maximum,
			})
			indexAccessor := len(accessors)
			accessors = append(accessors, map[string]any{
				"bufferView": indexView, "componentType": 5125, "count": len(indices), "type": "SCALAR",
			})
			meshIndex = len(meshes)
			meshIndexByKey[meshKey] = meshIndex
			meshes = append(meshes, map[string]any{"name": part.partRef, "primitives": []any{map[string]any{
				"attributes": map[string]any{"POSITION": positionAccessor}, "indices": indexAccessor, "material": materialIndex,
			}}})
		}
		matrix := make([]float64, 16)
		copy(matrix, part.matrix[:])
		nodeIndex := len(nodes)
		nodes = append(nodes, map[string]any{"name": part.instanceID, "mesh": meshIndex, "matrix": matrix})
		rootChildren = append(rootChildren, nodeIndex)
	}
	rootNode["children"] = rootChildren
	for bin.Len()%4 != 0 {
		bin.WriteByte(0)
	}
	gltf := map[string]any{
		"asset":  map[string]any{"version": "2.0", "generator": generator},
		"scene":  0,
		"scenes": []any{map[string]any{"nodes": []int{0}}},
		"nodes":  nodes,
	}
	if bin.Len() > 0 {
		gltf["meshes"] = meshes
		gltf["materials"] = materials
		gltf["buffers"] = []any{map[string]any{"byteLength": bin.Len()}}
		gltf["bufferViews"] = bufferViews
		gltf["accessors"] = accessors
	}
	jsonChunk, err := json.Marshal(gltf)
	if err != nil {
		return nil, nil, err
	}
	for len(jsonChunk)%4 != 0 {
		jsonChunk = append(jsonChunk, ' ')
	}
	total := 12 + 8 + len(jsonChunk)
	if bin.Len() > 0 {
		total += 8 + bin.Len()
	}
	output := &bytes.Buffer{}
	output.WriteString("glTF")
	_ = binary.Write(output, binary.LittleEndian, uint32(2))
	_ = binary.Write(output, binary.LittleEndian, uint32(total))
	_ = binary.Write(output, binary.LittleEndian, uint32(len(jsonChunk)))
	output.WriteString("JSON")
	output.Write(jsonChunk)
	if bin.Len() > 0 {
		_ = binary.Write(output, binary.LittleEndian, uint32(bin.Len()))
		output.WriteString("BIN\x00")
		output.Write(bin.Bytes())
	}
	var bounds *componentPreviewBounds
	if renderedParts > 0 {
		bounds = &componentPreviewBounds{
			minimum: minimum, maximum: maximum,
			logicalWidthStud:   roundPreviewSize((maximum[0] - minimum[0]) / 20),
			logicalDepthStud:   roundPreviewSize((maximum[2] - minimum[2]) / 20),
			logicalHeightPlate: roundPreviewSize((maximum[1] - minimum[1]) / 8),
			complete:           renderedParts == len(parts),
		}
	}
	return output.Bytes(), bounds, nil
}

// roundPreviewSize 与数据库 numeric(12,4) 精度保持一致，避免不同读取路径出现浮点尾差。
func roundPreviewSize(value float64) float64 {
	return math.Round(value*10000) / 10000
}

func previewNumeric(value float64) pgtype.Numeric {
	var numeric pgtype.Numeric
	_ = numeric.Scan(fmt.Sprintf("%.4f", value))
	return numeric
}

func boolPointer(value bool) *bool {
	return &value
}

func ldrawTrianglesToBuffers(triangles []ldrawTriangle) ([]float32, []uint32, [3]float64, [3]float64) {
	positions := make([]float32, 0, len(triangles)*9)
	indices := make([]uint32, 0, len(triangles)*3)
	minimum := [3]float64{math.Inf(1), math.Inf(1), math.Inf(1)}
	maximum := [3]float64{math.Inf(-1), math.Inf(-1), math.Inf(-1)}
	for _, triangle := range triangles {
		for _, vertex := range triangle {
			indices = append(indices, uint32(len(indices)))
			positions = append(positions, float32(vertex.x), float32(vertex.y), float32(vertex.z))
			for axis, value := range []float64{vertex.x, vertex.y, vertex.z} {
				minimum[axis] = math.Min(minimum[axis], value)
				maximum[axis] = math.Max(maximum[axis], value)
			}
		}
	}
	return positions, indices, minimum, maximum
}

func ldrawMaterial(colorCode string) map[string]any {
	r, g, b := ldrawColor(colorCode)
	return map[string]any{"name": "LDraw " + colorCode, "doubleSided": true, "pbrMetallicRoughness": map[string]any{
		"baseColorFactor": []float64{r, g, b, 1}, "metallicFactor": 0, "roughnessFactor": 0.72,
	}}
}

func ldrawColor(colorCode string) (float64, float64, float64) {
	colors := map[string][3]float64{
		"0": {0.02, 0.02, 0.02}, "1": {0.00, 0.13, 0.55}, "2": {0.00, 0.45, 0.16},
		"3": {0.00, 0.52, 0.58}, "4": {0.80, 0.00, 0.05}, "5": {0.75, 0.00, 0.45},
		"6": {0.36, 0.20, 0.10}, "7": {0.60, 0.62, 0.64}, "8": {0.28, 0.30, 0.32},
		"9": {0.35, 0.55, 0.85}, "10": {0.30, 0.70, 0.20}, "11": {0.00, 0.70, 0.78},
		"12": {0.95, 0.36, 0.24}, "13": {1.00, 0.55, 0.75}, "14": {0.96, 0.82, 0.08},
		"15": {0.95, 0.95, 0.92}, "16": {0.72, 0.74, 0.78},
	}
	if value, ok := colors[colorCode]; ok {
		return value[0], value[1], value[2]
	}
	return 0.72, 0.74, 0.78
}

func componentPreviewInputHash(versionID, sceneSnapshotID, structureHash, geometryHash, partLibraryVersionID, partLibrarySourceHash, generator string) string {
	return hashStrings(versionID, sceneSnapshotID, structureHash, geometryHash, partLibraryVersionID, partLibrarySourceHash, generator)
}

func previewGeneratorStale(status string, generator *string) bool {
	if generator == nil {
		return status == "ready" || status == "failed"
	}
	return *generator != PreviewGeneratorVersion
}

func deterministicUUID(value string) pgtype.UUID {
	sum := sha256.Sum256([]byte(value))
	var data [16]byte
	copy(data[:], sum[:16])
	data[6] = (data[6] & 0x0f) | 0x50
	data[8] = (data[8] & 0x3f) | 0x80
	return pgtype.UUID{Bytes: data, Valid: true}
}
func validationResult(id pgtype.UUID, passed bool) task.Result {
	return task.Result{Payload: mustJSON(map[string]any{"validationReportId": uuidutil.String(id), "passed": passed})}
}
func permanentValidation(candidateID string) *task.Failure {
	return &task.Failure{Code: "component_repo.validation_unavailable", Params: map[string]any{"candidateId": candidateID}, Retryable: false}
}
func previewFailure(versionID string, retryable bool) *task.Failure {
	return &task.Failure{Code: "component_repo.preview_unavailable", Params: map[string]any{"versionId": versionID}, Retryable: retryable}
}
func validSHA256(value string) bool {
	if len(value) != 64 {
		return false
	}
	_, err := hex.DecodeString(value)
	return err == nil
}
func strictTaskPayload(raw []byte, target any) error {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	if decoder.More() {
		return fmt.Errorf("multiple json values")
	}
	return nil
}
func filterNonEmpty(values []string) []string {
	result := values[:0]
	for _, value := range values {
		if value != "" {
			result = append(result, value)
		}
	}
	return result
}
