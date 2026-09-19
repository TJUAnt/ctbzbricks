package partlibrary

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"io/fs"
	"math"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
)

type GeometryStats struct {
	SourceRelativePath string
	SourceSHA256       string
	BBoxMin            [3]float64
	BBoxMax            [3]float64
	VertexCount        int
	FaceCount          int
}

type ldrawIndex struct {
	files map[string]string
	memo  map[string][]ldrawTriangle
}

type ldrawVector struct{ x, y, z float64 }

type ldrawTransform struct {
	m [9]float64
	o ldrawVector
}

type ldrawTriangle [3]ldrawVector

type ldrawGeometryError struct {
	reason     string
	fromPath   string
	reference  string
	candidates []string
}

func (e ldrawGeometryError) Error() string {
	return e.reason
}

var identityLDrawTransform = ldrawTransform{m: [9]float64{1, 0, 0, 0, 1, 0, 0, 0, 1}}

var standardPartLogicalSizePattern = regexp.MustCompile(`(?i)^(brick|plate|tile)\s+(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\b`)

const LogicalSizeAlgorithmVersion = "ldraw-description-nominal-v1"

func (t ldrawTransform) apply(v ldrawVector) ldrawVector {
	return ldrawVector{
		t.m[0]*v.x + t.m[1]*v.y + t.m[2]*v.z + t.o.x,
		t.m[3]*v.x + t.m[4]*v.y + t.m[5]*v.z + t.o.y,
		t.m[6]*v.x + t.m[7]*v.y + t.m[8]*v.z + t.o.z,
	}
}

func newLDrawIndex(root string) (*ldrawIndex, error) {
	files, err := indexLDrawGeometryFiles(root)
	if err != nil {
		return nil, err
	}
	return &ldrawIndex{files: files, memo: map[string][]ldrawTriangle{}}, nil
}

func ComputeGeometryStats(ldrawRoot, manifestRelativePath string) (GeometryStats, error) {
	index, err := newLDrawIndex(ldrawRoot)
	if err != nil {
		return GeometryStats{}, err
	}
	return index.computeStats(manifestRelativePath)
}

func ComputeGeometryStatsWithIndex(index *ldrawIndex, manifestRelativePath string) (GeometryStats, error) {
	return index.computeStats(manifestRelativePath)
}

// sourceName 从顶层 LDraw 文件头读取源语言描述；缺少描述不阻断 snapshot 导入，而是退回稳定 Part 编号。
func (idx *ldrawIndex) sourceName(manifestRelativePath, fallback string) string {
	sourcePath := LDrawWorkerRelativePath(manifestRelativePath)
	absolute, ok := idx.files[sourcePath]
	if !ok {
		return fallback
	}
	file, err := os.Open(absolute)
	if err != nil {
		return fallback
	}
	defer file.Close()
	reader := bufio.NewReader(file)
	for lineNumber := 0; lineNumber < 64; lineNumber++ {
		line, readErr := reader.ReadString('\n')
		line = strings.TrimSpace(line)
		if description := ldrawDescription(line); description != "" {
			return description
		}
		if readErr != nil {
			break
		}
	}
	return fallback
}

func ldrawDescription(line string) string {
	fields := strings.Fields(line)
	if len(fields) < 2 || fields[0] != "0" {
		return ""
	}
	value := strings.TrimSpace(strings.TrimPrefix(line, "0"))
	upper := strings.ToUpper(value)
	for _, prefix := range []string{"FILE ", "NOFILE", "NAME:", "AUTHOR:", "!", "BFC ", "//", "PE_TEX_"} {
		if strings.HasPrefix(upper, prefix) {
			return ""
		}
	}
	// LDraw 官方描述中常用多个空格对齐；持久化前规范化空白，避免展示和 token 搜索随排版漂移。
	return strings.Join(strings.Fields(value), " ")
}

// deriveLogicalSize 只把可由官方描述直接解释的标准 Brick/Plate/Tile 标为精确标称尺寸；
// 其他零件仍保留 bbox 近似值供展示，但不得进入精确尺寸筛选。
func deriveLogicalSize(sourceName string, stats GeometryStats) (width, depth, height float64, status string) {
	width = roundNonNegative((stats.BBoxMax[0] - stats.BBoxMin[0]) / 20)
	depth = roundNonNegative((stats.BBoxMax[2] - stats.BBoxMin[2]) / 20)
	height = roundNonNegative((stats.BBoxMax[1] - stats.BBoxMin[1]) / 8)
	status = "derived_approximate"

	match := standardPartLogicalSizePattern.FindStringSubmatch(sourceName)
	if match == nil {
		return width, depth, height, status
	}
	nominalWidth, widthErr := strconv.ParseFloat(match[2], 64)
	nominalDepth, depthErr := strconv.ParseFloat(match[3], 64)
	if widthErr != nil || depthErr != nil || nominalWidth <= 0 || nominalDepth <= 0 {
		return width, depth, height, status
	}
	nominalHeight := 1.0
	if strings.EqualFold(match[1], "brick") {
		nominalHeight = 3
	}
	return nominalWidth, nominalDepth, nominalHeight, "derived_exact"
}

func (idx *ldrawIndex) computeStats(manifestRelativePath string) (GeometryStats, error) {
	sourcePath := LDrawWorkerRelativePath(manifestRelativePath)
	absolute, ok := idx.files[sourcePath]
	if !ok {
		return GeometryStats{}, errors.New("LDraw source file missing")
	}
	sourceHash, err := sha256FileForGeometry(absolute)
	if err != nil {
		return GeometryStats{}, err
	}
	triangles, err := idx.collect(sourcePath, nil)
	if err != nil {
		return GeometryStats{}, err
	}
	if len(triangles) == 0 {
		return GeometryStats{}, errors.New("LDraw source has no faces")
	}
	minimum := [3]float64{math.Inf(1), math.Inf(1), math.Inf(1)}
	maximum := [3]float64{math.Inf(-1), math.Inf(-1), math.Inf(-1)}
	for _, triangle := range triangles {
		for _, vertex := range triangle {
			for axis, value := range []float64{vertex.x, vertex.y, vertex.z} {
				minimum[axis] = math.Min(minimum[axis], value)
				maximum[axis] = math.Max(maximum[axis], value)
			}
		}
	}
	return GeometryStats{
		SourceRelativePath: sourcePath,
		SourceSHA256:       sourceHash,
		BBoxMin:            minimum,
		BBoxMax:            maximum,
		VertexCount:        len(triangles) * 3,
		FaceCount:          len(triangles),
	}, nil
}

func indexLDrawGeometryFiles(root string) (map[string]string, error) {
	root = strings.TrimSpace(root)
	if root == "" {
		return nil, errors.New("ldraw root is required")
	}
	info, err := os.Stat(root)
	if err != nil || !info.IsDir() {
		return nil, errors.New("ldraw root must be an existing directory")
	}
	result := map[string]string{}
	aliases := map[string]string{}
	for _, base := range []string{root, filepath.Join(root, "UnOfficial"), filepath.Join(root, "Unofficial")} {
		baseInfo, statErr := os.Stat(base)
		if statErr != nil || !baseInfo.IsDir() {
			continue
		}
		for _, section := range []string{"parts", "p"} {
			sectionRoot := filepath.Join(base, section)
			sectionInfo, statErr := os.Stat(sectionRoot)
			if statErr != nil || !sectionInfo.IsDir() {
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
				key := normalizeLDrawGeometryPath(relative)
				if _, exists := result[key]; !exists {
					result[key] = path
				}
				if !samePath(base, root) {
					full, fullErr := filepath.Rel(root, path)
					if fullErr != nil {
						return fullErr
					}
					fullKey := normalizeLDrawGeometryPath(full)
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
		return nil, errors.New("ldraw root contains no Part or primitive files")
	}
	return result, nil
}

func samePath(left, right string) bool {
	leftAbs, leftErr := filepath.Abs(left)
	rightAbs, rightErr := filepath.Abs(right)
	return leftErr == nil && rightErr == nil && leftAbs == rightAbs
}

func LDrawWorkerRelativePath(manifestRelativePath string) string {
	value := normalizeLDrawGeometryPath(manifestRelativePath)
	value = strings.TrimPrefix(value, "unofficial/")
	return value
}

func normalizeLDrawGeometryPath(value string) string {
	value = strings.ReplaceAll(strings.TrimSpace(value), "\\", "/")
	return strings.ToLower(strings.TrimPrefix(filepath.ToSlash(value), "./"))
}

func (idx *ldrawIndex) collect(relativePath string, stack []string) ([]ldrawTriangle, error) {
	relativePath = normalizeLDrawGeometryPath(relativePath)
	if len(stack) >= 64 {
		return nil, errors.New("maximum LDraw recursion exceeded")
	}
	for _, active := range stack {
		if active == relativePath {
			return nil, errors.New("recursive LDraw include")
		}
	}
	if cached, ok := idx.memo[relativePath]; ok {
		return cached, nil
	}
	path, ok := idx.files[relativePath]
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
			values, parseErr := parseLDrawGeometryFloats(fields[2:14])
			if parseErr != nil {
				return nil, parseErr
			}
			childTransform := ldrawTransform{
				m: [9]float64{values[3], values[4], values[5], values[6], values[7], values[8], values[9], values[10], values[11]},
				o: ldrawVector{values[0], values[1], values[2]},
			}
			reference := normalizeLDrawGeometryPath(strings.Trim(fields[14], `"`))
			candidates := ldrawGeometryReferenceCandidates(relativePath, reference)
			childPath := resolveLDrawGeometryReferenceCandidates(candidates, idx.files)
			if childPath == "" {
				if reference == "6221655zc01.dat" {
					continue
				}
				return nil, ldrawGeometryError{
					reason:     "missing LDraw reference",
					fromPath:   relativePath,
					reference:  reference,
					candidates: candidates,
				}
			}
			childTriangles, childErr := idx.collect(childPath, append(stack, relativePath))
			if childErr != nil {
				return nil, childErr
			}
			for _, triangle := range childTriangles {
				triangles = append(triangles, ldrawTriangle{
					childTransform.apply(triangle[0]),
					childTransform.apply(triangle[1]),
					childTransform.apply(triangle[2]),
				})
			}
		case "3", "4":
			expected := 11
			if fields[0] == "4" {
				expected = 14
			}
			if len(fields) < expected {
				return nil, errors.New("invalid LDraw face")
			}
			values, parseErr := parseLDrawGeometryFloats(fields[2:expected])
			if parseErr != nil {
				return nil, parseErr
			}
			vertices := make([]ldrawVector, 0, len(values)/3)
			for index := 0; index < len(values); index += 3 {
				vertices = append(vertices, identityLDrawTransform.apply(ldrawVector{values[index], values[index+1], values[index+2]}))
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
	idx.memo[relativePath] = triangles
	return triangles, nil
}

func parseLDrawGeometryFloats(values []string) ([]float64, error) {
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

func resolveLDrawGeometryReference(fromPath, reference string, files map[string]string) string {
	return resolveLDrawGeometryReferenceCandidates(ldrawGeometryReferenceCandidates(fromPath, reference), files)
}

func ldrawGeometryReferenceCandidates(fromPath, reference string) []string {
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
	seen := map[string]struct{}{}
	normalized := make([]string, 0, len(candidates))
	for _, candidate := range candidates {
		candidate = normalizeLDrawGeometryPath(candidate)
		if _, exists := seen[candidate]; exists {
			continue
		}
		seen[candidate] = struct{}{}
		normalized = append(normalized, candidate)
	}
	return normalized
}

func resolveLDrawGeometryReferenceCandidates(candidates []string, files map[string]string) string {
	for _, candidate := range candidates {
		if _, exists := files[candidate]; exists {
			return candidate
		}
	}
	return ""
}

func sha256FileForGeometry(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}
