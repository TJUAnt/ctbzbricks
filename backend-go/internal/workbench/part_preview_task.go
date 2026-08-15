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
	pool      *pgxpool.Pool
	q         *db.Queries
	store     storage.Store
	keyPrefix string
	files     map[string]string
}

type partPreviewPayload struct {
	PartLibraryVersionID string `json:"partLibraryVersionId"`
	LDrawPartNum         string `json:"ldrawPartNum"`
	GeneratorVersion     string `json:"generatorVersion"`
	Generation           int32  `json:"generation"`
	InputHash            string `json:"inputHash"`
}

func NewPartPreviewTaskHandler(pool *pgxpool.Pool, store storage.Store, keyPrefix, ldrawRoot string) (*PartPreviewTaskHandler, error) {
	files, err := indexLDrawFiles(ldrawRoot)
	if err != nil {
		return nil, err
	}
	return &PartPreviewTaskHandler{
		pool: pool, q: db.New(pool), store: store,
		keyPrefix: strings.Trim(keyPrefix, "/"), files: files,
	}, nil
}

func (h *PartPreviewTaskHandler) Handle(ctx context.Context, claimed task.ClaimedTask) (task.Result, error) {
	var payload partPreviewPayload
	if err := strictTaskPayload(claimed.Payload, &payload); err != nil ||
		payload.GeneratorVersion != PartPreviewGeneratorVersion || payload.Generation < 0 {
		return task.Result{}, partPreviewFailure(payload, false)
	}
	libraryID, err := uuidutil.Parse(payload.PartLibraryVersionID)
	if err != nil {
		return task.Result{}, partPreviewFailure(payload, false)
	}
	partNumber, err := normalizePartNumber(payload.LDrawPartNum)
	if err != nil || partNumber != payload.LDrawPartNum {
		return task.Result{}, partPreviewFailure(payload, false)
	}
	input, err := h.q.GetPartPreviewTaskInput(ctx, db.GetPartPreviewTaskInputParams{
		PartLibraryVersionID: libraryID, LdrawPartNum: partNumber, TaskID: claimed.ID,
	})
	if errors.Is(err, pgx.ErrNoRows) {
		return task.Result{}, partPreviewFailure(payload, false)
	}
	if err != nil {
		return task.Result{}, err
	}
	if input.GeometryStatus != "ready" || input.Generation != payload.Generation ||
		input.GeneratorVersion == nil || *input.GeneratorVersion != payload.GeneratorVersion ||
		payload.InputHash != hashStrings(input.PartLibrarySourceHash, input.SourceFileHash, payload.GeneratorVersion) {
		return task.Result{}, partPreviewFailure(payload, false)
	}
	if input.PreviewStatus == "ready" && input.ArtifactID.Valid {
		return partPreviewResult(payload, input.ArtifactID), nil
	}
	rows, err := h.q.MarkPartPreviewRunning(ctx, db.MarkPartPreviewRunningParams{
		PartLibraryVersionID: libraryID, LdrawPartNum: partNumber, TaskID: claimed.ID,
	})
	if err != nil {
		return task.Result{}, err
	}
	if rows != 1 {
		return task.Result{}, partPreviewFailure(payload, false)
	}
	sourcePath, ok := h.files[normalizeLDrawPath(input.SourceRelativePath)]
	if !ok {
		return task.Result{}, partPreviewFailure(payload, false)
	}
	source, err := os.ReadFile(sourcePath)
	if err != nil {
		return task.Result{}, partPreviewFailure(payload, true)
	}
	sourceSum := sha256.Sum256(source)
	if hex.EncodeToString(sourceSum[:]) != input.SourceFileHash {
		return task.Result{}, partPreviewFailure(payload, false)
	}
	triangles, err := collectLDrawTriangles(normalizeLDrawPath(input.SourceRelativePath), h.files)
	if err != nil || len(triangles) == 0 {
		return task.Result{}, partPreviewFailure(payload, false)
	}
	glb, err := buildPartGLB(triangles, payload.GeneratorVersion)
	if err != nil {
		return task.Result{}, partPreviewFailure(payload, false)
	}
	ownerText := uuidutil.String(claimed.OwnerID)
	artifactID := deterministicUUID(strings.Join([]string{
		"part-preview", ownerText, payload.PartLibraryVersionID, partNumber, payload.GeneratorVersion,
	}, ":"))
	artifactText := uuidutil.String(artifactID)
	key := strings.Join(filterNonEmpty([]string{
		ownerText, h.keyPrefix, "part-previews", payload.PartLibraryVersionID,
		partNumber, payload.GeneratorVersion, artifactText + ".glb",
	}), "/")
	if err := h.store.Put(ctx, key, "model/gltf-binary", bytes.NewReader(glb), int64(len(glb))); err != nil {
		return task.Result{}, partPreviewFailure(payload, true)
	}
	sum := sha256.Sum256(glb)
	digest := hex.EncodeToString(sum[:])
	_, err = txValue(ctx, h.pool, func(q *db.Queries) (struct{}, error) {
		if _, upsertErr := q.UpsertPartPreviewArtifact(ctx, db.UpsertPartPreviewArtifactParams{
			ID: artifactID, OwnerID: claimed.OwnerID, OriginalFilename: partNumber + ".glb",
			StorageProvider: h.store.Provider(), StorageBucket: h.store.Bucket(), StorageKey: key,
			Sha256: digest, FileSize: int64(len(glb)), UploadedBy: claimed.OwnerID,
			Metadata: mustJSON(map[string]any{
				"derivedBy": PartPreviewMaterializeType, "generatorVersion": payload.GeneratorVersion,
				"partLibraryVersionId": payload.PartLibraryVersionID, "ldrawPartNum": partNumber,
				"sourceFileHash": input.SourceFileHash,
			}),
		}); upsertErr != nil {
			return struct{}{}, upsertErr
		}
		updated, readyErr := q.MarkPartPreviewReady(ctx, db.MarkPartPreviewReadyParams{
			ArtifactID: artifactID, GeneratorVersion: stringPointer(payload.GeneratorVersion),
			PartLibraryVersionID: libraryID, LdrawPartNum: partNumber,
			TaskID: claimed.ID, Generation: payload.Generation,
		})
		if readyErr != nil {
			return struct{}{}, readyErr
		}
		if updated != 1 {
			return struct{}{}, errors.New("stale part preview task")
		}
		return struct{}{}, nil
	})
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
		ArtifactID: artifactID,
	}
}

func partPreviewFailure(payload partPreviewPayload, retryable bool) *task.Failure {
	return &task.Failure{Code: "component_repo.part_preview_unavailable", Params: map[string]any{
		"partLibraryVersionId": payload.PartLibraryVersionID, "ldrawPartNum": payload.LDrawPartNum,
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
		return nil, errors.New("LDRAW_ROOT is required for Part preview materialization")
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
	return strings.ToLower(strings.TrimPrefix(filepath.ToSlash(strings.TrimSpace(value)), "./"))
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
	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 64*1024), 1024*1024)
	triangles := []ldrawTriangle{}
	for scanner.Scan() {
		fields := strings.Fields(strings.TrimSpace(scanner.Text()))
		if len(fields) == 0 || fields[0] == "0" || fields[0] == "2" || fields[0] == "5" {
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
			if len(fields) != expected {
				return nil, errors.New("invalid LDraw face")
			}
			values, parseErr := parseLDrawFloats(fields[2:])
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
	}
	if err := scanner.Err(); err != nil {
		return nil, err
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
	bin := &bytes.Buffer{}
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
	gltf := map[string]any{
		"asset": map[string]any{"version": "2.0", "generator": generator},
		"scene": 0, "scenes": []any{map[string]any{"nodes": []int{0}}},
		"nodes": []any{map[string]any{"name": "LDraw Part", "mesh": 0}},
		"meshes": []any{map[string]any{"primitives": []any{map[string]any{
			"attributes": map[string]any{"POSITION": 0}, "indices": 1, "material": 0,
		}}}},
		"materials": []any{map[string]any{"doubleSided": true, "pbrMetallicRoughness": map[string]any{
			"baseColorFactor": []float64{0.72, 0.74, 0.78, 1}, "metallicFactor": 0, "roughnessFactor": 0.72,
		}}},
		"buffers": []any{map[string]any{"byteLength": bin.Len()}},
		"bufferViews": []any{
			map[string]any{"buffer": 0, "byteOffset": 0, "byteLength": indexOffset, "target": 34962},
			map[string]any{"buffer": 0, "byteOffset": indexOffset, "byteLength": len(indices) * 4, "target": 34963},
		},
		"accessors": []any{
			map[string]any{"bufferView": 0, "componentType": 5126, "count": len(positions) / 3, "type": "VEC3", "min": minimum, "max": maximum},
			map[string]any{"bufferView": 1, "componentType": 5125, "count": len(indices), "type": "SCALAR"},
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
