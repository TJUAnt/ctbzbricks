package ingestion

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"path/filepath"
	"strconv"
	"strings"
	"unicode/utf8"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/scene"
)

const (
	artifactTypeStudioIO = "studio_io"
	artifactTypeLDrawLDR = "ldraw_ldr"
	artifactTypeLDrawMPD = "ldraw_mpd"

	maxStudioExchangeBytes = 100 * 1024 * 1024
)

var errImportParse = errors.New("component import parse failed")

type materializedImport struct {
	Document           map[string]any
	BOM                map[string]int
	ParseIssues        []map[string]any
	RootModelID        *string
	Summary            map[string]any
	InterfaceSignature string
	StructureHash      string
	GeometryHash       string
	ExchangeBytes      []byte
	ExchangeFilename   string
}

type rawModel struct {
	SourceName  string
	StartLineNo int
	MetaLines   []string
	References  []ldrawReference
	DisplayName *string
}

type ldrawModel struct {
	ModelID     string
	SourceName  string
	SourceOrder int
	StartLineNo int
	DisplayName *string
	MetaLines   []string
	References  []ldrawReference
}

type ldrawReference struct {
	InstanceID    string
	SourceModelID string
	SourceLineNo  int
	SourceOrder   int
	ColorCode     string
	Position      [3]float64
	Matrix        [9]float64
	ReferenceName string
	ReferenceKind string
	TargetModelID *string
	RawLine       string
}

func materializeImport(content []byte, artifactType, originalFilename, parserVersion string) (materializedImport, error) {
	parseBytes := content
	var exchangeBytes []byte
	var exchangeFilename string
	switch artifactType {
	case artifactTypeStudioIO:
		extracted, err := extractStudioExchange(content)
		if err != nil {
			return materializedImport{}, err
		}
		exchangeBytes = extracted
		exchangeFilename = stem(originalFilename) + ".ldr"
		parseBytes = extracted
	case artifactTypeLDrawLDR, artifactTypeLDrawMPD:
	default:
		return materializedImport{}, errImportParse
	}

	if !utf8.Valid(parseBytes) {
		return materializedImport{}, errImportParse
	}
	sourceText := strings.TrimPrefix(string(parseBytes), "\ufeff")
	document, models, issues, rootModelID, err := deserializeLDrawDocument(sourceText, parserVersion)
	if err != nil {
		return materializedImport{}, err
	}
	serializedDocument, err := json.Marshal(document)
	if err != nil {
		return materializedImport{}, errImportParse
	}
	// BOM 必须来自场景实例展开结果，不能按模型定义去重或把未被入口引用的定义计入数量。
	expanded, err := scene.ExpandJSON(serializedDocument)
	if err != nil {
		return materializedImport{}, errImportParse
	}
	bom := expanded.BOM()
	document["bom"] = bom
	document["parseIssues"] = issues
	geometry := geometryProjection(expanded.Parts)
	return materializedImport{
		Document:    document,
		BOM:         bom,
		ParseIssues: issues,
		RootModelID: rootModelID,
		Summary: map[string]any{
			"modelCount":            len(models),
			"partInstanceCount":     len(expanded.Parts),
			"submodelInstanceCount": expanded.SubmodelInstanceCount,
			"bom":                   bom,
			"parseIssueCount":       len(issues),
		},
		InterfaceSignature: stableHash([]any{}),
		StructureHash:      stableHash(document),
		GeometryHash:       stableHash(geometry),
		ExchangeBytes:      exchangeBytes,
		ExchangeFilename:   exchangeFilename,
	}, nil
}

func extractStudioExchange(content []byte) ([]byte, error) {
	reader, err := zip.NewReader(bytes.NewReader(content), int64(len(content)))
	if err != nil {
		return nil, errImportParse
	}
	for _, file := range reader.File {
		if file.Name != "model.ldr" {
			continue
		}
		if file.UncompressedSize64 > maxStudioExchangeBytes {
			return nil, errImportParse
		}
		body, err := file.Open()
		if err != nil {
			return nil, errImportParse
		}
		defer body.Close()
		extracted, err := io.ReadAll(io.LimitReader(body, maxStudioExchangeBytes+1))
		if err != nil || len(extracted) > maxStudioExchangeBytes {
			return nil, errImportParse
		}
		return extracted, nil
	}
	return nil, errImportParse
}

func deserializeLDrawDocument(content, parserVersion string) (map[string]any, []ldrawModel, []map[string]any, *string, error) {
	lines := normalizedLines(content)
	rawModels := make([]rawModel, 0, 1)
	issues := make([]map[string]any, 0)
	var current *rawModel
	referenceCounter := 0
	for index, rawLine := range lines {
		lineNo := index + 1
		line := strings.TrimSpace(rawLine)
		if line == "" {
			continue
		}
		if strings.HasPrefix(line, "0 FILE ") {
			if current != nil {
				rawModels = append(rawModels, *current)
			}
			sourceName := strings.TrimSpace(strings.TrimPrefix(line, "0 FILE "))
			if sourceName == "" {
				sourceName = "root"
			}
			current = &rawModel{SourceName: sourceName, StartLineNo: lineNo, MetaLines: []string{rawLine}}
			continue
		}
		if line == "0 NOFILE" {
			if current != nil {
				current.MetaLines = append(current.MetaLines, rawLine)
				rawModels = append(rawModels, *current)
				current = nil
			}
			continue
		}
		if current == nil {
			current = &rawModel{SourceName: "root", StartLineNo: lineNo}
		}
		if strings.HasPrefix(line, "0 Name:") {
			display := strings.TrimSpace(strings.TrimPrefix(line, "0 Name:"))
			current.DisplayName = &display
			current.MetaLines = append(current.MetaLines, rawLine)
			continue
		}
		tokens := strings.Fields(line)
		if len(tokens) == 0 {
			continue
		}
		switch tokens[0] {
		case "1":
			referenceCounter++
			reference, ok := parseType1Reference(lineNo, referenceCounter, rawLine, tokens, &issues, len(rawModels))
			if ok {
				current.References = append(current.References, reference)
			}
		case "11":
			issues = append(issues, parseIssue("unsupported_line_type", lineNo, nil))
			current.MetaLines = append(current.MetaLines, rawLine)
		default:
			current.MetaLines = append(current.MetaLines, rawLine)
		}
	}
	if current != nil {
		issues = append(issues, parseIssue("unclosed_model", current.StartLineNo, nil))
		rawModels = append(rawModels, *current)
	}

	models := materializeModels(rawModels, &issues)
	classifyReferences(models)
	var rootModelID *string
	if len(models) > 0 {
		root := models[0].ModelID
		rootModelID = &root
	}
	modelObjects := make([]map[string]any, 0, len(models))
	for _, model := range models {
		modelObjects = append(modelObjects, modelToMap(model))
	}
	rootInstances := make([]scene.RootInstance, 0, 1)
	if rootModelID != nil {
		rootInstances = append(rootInstances, scene.RootInstance{
			InstanceID:    "root_0001",
			TargetModelID: *rootModelID,
			Transform:     scene.IdentityTransform(),
		})
	}
	document := map[string]any{
		"parserVersion":     parserVersion,
		"rootModelId":       rootModelID,
		"rootInstances":     rootInstances,
		"models":            modelObjects,
		"partInstances":     refsToMaps(leafReferences(models)),
		"submodelInstances": refsToMaps(submodelReferences(models)),
	}
	return document, models, issues, rootModelID, nil
}

func normalizedLines(content string) []string {
	content = strings.ReplaceAll(content, "\r\n", "\n")
	content = strings.ReplaceAll(content, "\r", "\n")
	content = strings.TrimPrefix(content, "\ufeff")
	return strings.Split(content, "\n")
}

func parseType1Reference(lineNo, referenceCounter int, rawLine string, tokens []string, issues *[]map[string]any, modelIndex int) (ldrawReference, bool) {
	if len(tokens) < 15 {
		*issues = append(*issues, parseIssue("invalid_type1_line", lineNo, nil))
		return ldrawReference{}, false
	}
	values := make([]float64, 12)
	for i, token := range tokens[2:14] {
		value, err := strconv.ParseFloat(token, 64)
		if err != nil {
			*issues = append(*issues, parseIssue("invalid_type1_line", lineNo, nil))
			return ldrawReference{}, false
		}
		values[i] = value
	}
	var position [3]float64
	var matrix [9]float64
	copy(position[:], values[:3])
	copy(matrix[:], values[3:])
	return ldrawReference{
		InstanceID:    fmt.Sprintf("part_%06d", referenceCounter),
		SourceModelID: fmt.Sprintf("model_%04d", modelIndex+1),
		SourceLineNo:  lineNo,
		SourceOrder:   referenceCounter,
		ColorCode:     tokens[1],
		Position:      position,
		Matrix:        matrix,
		ReferenceName: strings.TrimSpace(strings.Join(tokens[14:], " ")),
		ReferenceKind: "unresolved",
		RawLine:       rawLine,
	}, true
}

func materializeModels(rawModels []rawModel, issues *[]map[string]any) []ldrawModel {
	models := make([]ldrawModel, 0, len(rawModels))
	seen := map[string]bool{}
	for i, raw := range rawModels {
		if seen[normalizeReferenceName(raw.SourceName)] {
			*issues = append(*issues, parseIssue("duplicate_model_name", raw.StartLineNo, map[string]any{"modelName": raw.SourceName}))
		}
		seen[normalizeReferenceName(raw.SourceName)] = true
		modelID := fmt.Sprintf("model_%04d", i+1)
		references := make([]ldrawReference, 0, len(raw.References))
		for _, reference := range raw.References {
			reference.SourceModelID = modelID
			references = append(references, reference)
		}
		models = append(models, ldrawModel{
			ModelID: modelID, SourceName: raw.SourceName, SourceOrder: i + 1,
			StartLineNo: raw.StartLineNo, DisplayName: raw.DisplayName,
			MetaLines: raw.MetaLines, References: references,
		})
	}
	return models
}

func classifyReferences(models []ldrawModel) {
	lookup := map[string][]int{}
	for i, model := range models {
		key := normalizeReferenceName(model.SourceName)
		lookup[key] = append(lookup[key], i)
	}
	for modelIndex := range models {
		for referenceIndex := range models[modelIndex].References {
			reference := &models[modelIndex].References[referenceIndex]
			targetIndex, ok := resolveSubmodelReference(models, modelIndex, reference.ReferenceName, lookup)
			if !ok {
				reference.ReferenceKind = "part"
				reference.TargetModelID = nil
				continue
			}
			reference.InstanceID = strings.Replace(reference.InstanceID, "part_", "submodel_", 1)
			reference.ReferenceKind = "submodel"
			target := models[targetIndex].ModelID
			reference.TargetModelID = &target
		}
	}
}

func resolveSubmodelReference(models []ldrawModel, sourceIndex int, referenceName string, lookup map[string][]int) (int, bool) {
	candidates := lookup[normalizeReferenceName(referenceName)]
	if len(candidates) == 0 {
		return 0, false
	}
	for _, candidate := range candidates {
		if models[candidate].SourceOrder > models[sourceIndex].SourceOrder {
			return candidate, true
		}
	}
	for _, candidate := range candidates {
		if models[candidate].ModelID != models[sourceIndex].ModelID {
			return candidate, true
		}
	}
	return 0, false
}

func modelToMap(model ldrawModel) map[string]any {
	return map[string]any{
		"modelId":     model.ModelID,
		"sourceName":  model.SourceName,
		"sourceOrder": model.SourceOrder,
		"startLineNo": model.StartLineNo,
		"displayName": model.DisplayName,
		"metaLines":   model.MetaLines,
		"references":  refsToMaps(model.References),
	}
}

func refsToMaps(references []ldrawReference) []map[string]any {
	result := make([]map[string]any, 0, len(references))
	for _, reference := range references {
		result = append(result, referenceToMap(reference))
	}
	return result
}

func referenceToMap(reference ldrawReference) map[string]any {
	return map[string]any{
		"instanceId":    reference.InstanceID,
		"sourceModelId": reference.SourceModelID,
		"sourceLineNo":  reference.SourceLineNo,
		"sourceOrder":   reference.SourceOrder,
		"colorCode":     reference.ColorCode,
		"transform": map[string]any{
			"position": map[string]any{
				"x": reference.Position[0],
				"y": reference.Position[1],
				"z": reference.Position[2],
			},
			"matrix": reference.Matrix[:],
		},
		"referenceName": reference.ReferenceName,
		"referenceKind": reference.ReferenceKind,
		"targetModelId": reference.TargetModelID,
		"rawLine":       reference.RawLine,
	}
}

func leafReferences(models []ldrawModel) []ldrawReference {
	var result []ldrawReference
	for _, model := range models {
		for _, reference := range model.References {
			if reference.ReferenceKind == "part" {
				result = append(result, reference)
			}
		}
	}
	return result
}

func submodelReferences(models []ldrawModel) []ldrawReference {
	var result []ldrawReference
	for _, model := range models {
		for _, reference := range model.References {
			if reference.ReferenceKind == "submodel" {
				result = append(result, reference)
			}
		}
	}
	return result
}

func parseIssue(issueType string, lineNo int, params map[string]any) map[string]any {
	if params == nil {
		params = map[string]any{}
	}
	params["line"] = lineNo
	return map[string]any{
		"code":     "component_repo.parse." + issueType,
		"severity": "warning",
		"params":   params,
		"path":     []any{"lines", lineNo},
	}
}

// geometryProjection 只投影真实场景 Part 实例，使 geometry hash 与 BOM/GLB 使用相同实例集合。
func geometryProjection(parts []scene.WorldPart) []map[string]any {
	projection := make([]map[string]any, 0, len(parts))
	for _, part := range parts {
		projection = append(projection, map[string]any{
			"instanceId":  part.InstanceID,
			"partRef":     part.PartRef,
			"colorCode":   part.ColorCode,
			"worldMatrix": part.Matrix,
		})
	}
	return projection
}

func stableHash(payload any) string {
	serialized, err := json.Marshal(payload)
	if err != nil {
		return ""
	}
	digest := sha256.Sum256(serialized)
	return hex.EncodeToString(digest[:])
}

func normalizeReferenceName(value string) string {
	return strings.ToLower(strings.TrimSpace(value))
}

func stem(filename string) string {
	base := filepath.Base(filename)
	extension := filepath.Ext(base)
	result := strings.TrimSpace(strings.TrimSuffix(base, extension))
	if result == "" {
		return "model"
	}
	return result
}
