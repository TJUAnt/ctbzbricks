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

type sceneTransform struct {
	Position map[string]float64 `json:"position"`
	Matrix   []float64          `json:"matrix"`
}

type sceneReference struct {
	InstanceID    string         `json:"instanceId"`
	ReferenceName string         `json:"referenceName"`
	ReferenceKind string         `json:"referenceKind"`
	TargetModelID string         `json:"targetModelId"`
	ColorCode     string         `json:"colorCode"`
	Transform     sceneTransform `json:"transform"`
}

type sceneModel struct {
	ModelID    string           `json:"modelId"`
	References []sceneReference `json:"references"`
}

type sceneDocument struct {
	RootModelID string       `json:"rootModelId"`
	Models      []sceneModel `json:"models"`
}

func (h *ValidationTaskHandler) Handle(ctx context.Context, claimed task.ClaimedTask) (task.Result, error) {
	var payload validationPayload
	if err := strictTaskPayload(claimed.Payload, &payload); err != nil || payload.ValidationLevel != "publish" || payload.ValidatorVersion != ValidatorVersion {
		return task.Result{}, &task.Failure{Code: "component_repo.publish_validation_failed", Params: map[string]any{}, Retryable: false}
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
		if passed {
			if attachErr := q.AttachPassingValidationReport(ctx, db.AttachPassingValidationReportParams{ReportID: reportID, VersionID: versionID, CandidateID: candidateID, InterfaceSignature: input.InterfaceSignature, StructureHash: input.StructureHash, GeometryHash: input.GeometryHash}); attachErr != nil {
				return db.CreateValidationReportRow{}, attachErr
			}
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
	var document sceneDocument
	if json.Unmarshal(raw, &document) != nil || document.RootModelID == "" || len(document.Models) == 0 {
		return nil, 0, false, false
	}
	models := make(map[string]sceneModel, len(document.Models))
	for _, model := range document.Models {
		if model.ModelID == "" {
			return nil, 0, false, false
		}
		if _, duplicate := models[model.ModelID]; duplicate {
			return nil, 0, false, false
		}
		models[model.ModelID] = model
	}
	partRefs := map[string]int{}
	partCount := 0
	minPosition := [3]float64{math.Inf(1), math.Inf(1), math.Inf(1)}
	maxPosition := [3]float64{math.Inf(-1), math.Inf(-1), math.Inf(-1)}
	active := map[string]bool{}
	var expand func(string, [16]float64, int) bool
	expand = func(modelID string, parent [16]float64, depth int) bool {
		if depth > 64 || active[modelID] {
			return false
		}
		model, exists := models[modelID]
		if !exists {
			return false
		}
		active[modelID] = true
		defer delete(active, modelID)
		for _, reference := range model.References {
			if reference.InstanceID == "" || reference.ReferenceName == "" {
				return false
			}
			local, err := glTFMatrix(reference.Transform)
			if err != nil {
				return false
			}
			world := multiply4(parent, local)
			switch reference.ReferenceKind {
			case "submodel":
				if reference.TargetModelID == "" || !expand(reference.TargetModelID, world, depth+1) {
					return false
				}
			case "part":
				name := strings.ToLower(strings.TrimSpace(reference.ReferenceName))
				if name == "" {
					return false
				}
				partRefs[name]++
				partCount++
				for index, value := range world[12:15] {
					if math.IsNaN(value) || math.IsInf(value, 0) {
						return false
					}
					minPosition[index] = math.Min(minPosition[index], value)
					maxPosition[index] = math.Max(maxPosition[index], value)
				}
			default:
				return false
			}
		}
		return true
	}
	identity := [16]float64{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1}
	valid := expand(document.RootModelID, identity, 0)
	return partRefs, partCount, valid, valid && partCount > 0 && minPosition[0] <= maxPosition[0]
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
	if input.PreviewStatus == "ready" && input.PreviewArtifactID.Valid {
		return task.Result{Payload: mustJSON(map[string]any{"versionId": payload.VersionID, "artifactId": uuidutil.String(input.PreviewArtifactID), "generatorVersion": payload.GeneratorVersion}), ArtifactID: input.PreviewArtifactID}, nil
	}
	if err := h.q.MarkVersionPreviewRunning(ctx, db.MarkVersionPreviewRunningParams{VersionID: versionID, TaskID: claimed.ID}); err != nil {
		return task.Result{}, err
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
	if len(geometryRows) != len(requiredPartRefs) {
		return task.Result{}, previewFailure(payload.VersionID, false)
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
	glb, err := buildComponentGLB(worldParts, trianglesByPart, payload.GeneratorVersion)
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
				"partLibrarySourceHash": input.PartLibrarySourceHash,
			}),
			DerivedFromArtifactID: input.SourceArtifactID,
		}); upsertErr != nil {
			return struct{}{}, upsertErr
		}
		if readyErr := q.MarkVersionPreviewReady(ctx, db.MarkVersionPreviewReadyParams{ArtifactID: artifactID, GeneratorVersion: stringPointer(payload.GeneratorVersion), VersionID: versionID, TaskID: claimed.ID, PreviewGeneration: payload.Generation}); readyErr != nil {
			return struct{}{}, readyErr
		}
		return struct{}{}, nil
	})
	if err != nil {
		return task.Result{}, err
	}
	return task.Result{Payload: mustJSON(map[string]any{"versionId": payload.VersionID, "artifactId": artifactText, "generatorVersion": payload.GeneratorVersion}), ArtifactID: artifactID}, nil
}

type componentWorldPart struct {
	instanceID string
	partRef    string
	colorCode  string
	matrix     [16]float64
}

func collectComponentWorldParts(raw json.RawMessage) ([]componentWorldPart, error) {
	var document sceneDocument
	if err := json.Unmarshal(raw, &document); err != nil {
		return nil, err
	}
	models := map[string]sceneModel{}
	for _, item := range document.Models {
		if item.ModelID == "" {
			return nil, errors.New("component preview model missing")
		}
		if _, exists := models[item.ModelID]; exists {
			return nil, errors.New("component preview duplicate model")
		}
		models[item.ModelID] = item
	}
	worldParts := []componentWorldPart{}
	active := map[string]bool{}
	var expand func(string, [16]float64, int) error
	expand = func(modelID string, parent [16]float64, depth int) error {
		if depth > 64 || active[modelID] {
			return errors.New("component preview recursion exceeded")
		}
		item, ok := models[modelID]
		if !ok {
			return errors.New("component preview model missing")
		}
		active[modelID] = true
		defer delete(active, modelID)
		for _, ref := range item.References {
			local, err := glTFMatrix(ref.Transform)
			if err != nil {
				return err
			}
			world := multiply4(parent, local)
			if ref.ReferenceKind == "submodel" {
				if err := expand(ref.TargetModelID, world, depth+1); err != nil {
					return err
				}
				continue
			}
			if ref.ReferenceKind == "part" {
				partRef := strings.ToLower(strings.TrimSpace(ref.ReferenceName))
				if ref.InstanceID == "" || partRef == "" {
					return errors.New("component preview part missing")
				}
				colorCode := strings.TrimSpace(ref.ColorCode)
				if colorCode == "" {
					colorCode = "16"
				}
				worldParts = append(worldParts, componentWorldPart{
					instanceID: ref.InstanceID,
					partRef:    partRef,
					colorCode:  colorCode,
					matrix:     world,
				})
				continue
			}
			return errors.New("component preview reference unsupported")
		}
		return nil
	}
	identity := [16]float64{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1}
	if document.RootModelID == "" || expand(document.RootModelID, identity, 0) != nil || len(worldParts) == 0 {
		return nil, errors.New("component preview unavailable")
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

func buildComponentGLB(parts []componentWorldPart, trianglesByPart map[string][]ldrawTriangle, generator string) ([]byte, error) {
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
	for _, part := range parts {
		meshKey := part.partRef + "\x00" + part.colorCode
		meshIndex, exists := meshIndexByKey[meshKey]
		if !exists {
			triangles := trianglesByPart[part.partRef]
			if len(triangles) == 0 {
				return nil, errors.New("component preview part geometry missing")
			}
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
					return nil, err
				}
			}
			indexOffset := bin.Len()
			for _, value := range indices {
				if err := binary.Write(bin, binary.LittleEndian, value); err != nil {
					return nil, err
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
		"asset":       map[string]any{"version": "2.0", "generator": generator},
		"scene":       0,
		"scenes":      []any{map[string]any{"nodes": []int{0}}},
		"nodes":       nodes,
		"meshes":      meshes,
		"materials":   materials,
		"buffers":     []any{map[string]any{"byteLength": bin.Len()}},
		"bufferViews": bufferViews,
		"accessors":   accessors,
	}
	jsonChunk, err := json.Marshal(gltf)
	if err != nil {
		return nil, err
	}
	for len(jsonChunk)%4 != 0 {
		jsonChunk = append(jsonChunk, ' ')
	}
	total := 12 + 8 + len(jsonChunk) + 8 + bin.Len()
	output := &bytes.Buffer{}
	output.WriteString("glTF")
	_ = binary.Write(output, binary.LittleEndian, uint32(2))
	_ = binary.Write(output, binary.LittleEndian, uint32(total))
	_ = binary.Write(output, binary.LittleEndian, uint32(len(jsonChunk)))
	output.WriteString("JSON")
	output.Write(jsonChunk)
	_ = binary.Write(output, binary.LittleEndian, uint32(bin.Len()))
	output.WriteString("BIN\x00")
	output.Write(bin.Bytes())
	return output.Bytes(), nil
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

func glTFMatrix(value sceneTransform) ([16]float64, error) {
	if len(value.Matrix) != 9 || len(value.Position) != 3 {
		return [16]float64{}, errors.New("invalid transform")
	}
	for _, axis := range []string{"x", "y", "z"} {
		number, exists := value.Position[axis]
		if !exists || math.IsNaN(number) || math.IsInf(number, 0) {
			return [16]float64{}, errors.New("invalid transform")
		}
	}
	for _, number := range value.Matrix {
		if math.IsNaN(number) || math.IsInf(number, 0) {
			return [16]float64{}, errors.New("invalid transform")
		}
	}
	return [16]float64{value.Matrix[0], value.Matrix[3], value.Matrix[6], 0, value.Matrix[1], value.Matrix[4], value.Matrix[7], 0, value.Matrix[2], value.Matrix[5], value.Matrix[8], 0, value.Position["x"], value.Position["y"], value.Position["z"], 1}, nil
}

func multiply4(a, b [16]float64) [16]float64 {
	var result [16]float64
	for column := 0; column < 4; column++ {
		for row := 0; row < 4; row++ {
			for k := 0; k < 4; k++ {
				result[column*4+row] += a[k*4+row] * b[column*4+k]
			}
		}
	}
	return result
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
	return &task.Failure{Code: "component_repo.publish_validation_failed", Params: map[string]any{"candidateId": candidateID}, Retryable: false}
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
