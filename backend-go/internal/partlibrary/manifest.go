package partlibrary

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

const (
	ManifestSchemaVersion = "studio-part-library-manifest-v1"
	SourceSystem          = "bricklink_studio_ldraw"
	DuplicatePolicy       = "official_parts_preferred_over_unofficial_for_same_ldraw_part_num"
)

type Options struct {
	StudioRoot      string
	OutDir          string
	LegacyPartsFile string
	GeneratedAt     time.Time
}

type Result struct {
	ManifestPath string
	SummaryPath  string
	CoveragePath string
	Manifest     Manifest
	Summary      Summary
	Coverage     *CoverageReport
}

type Manifest struct {
	SchemaVersion          string         `json:"schemaVersion"`
	SourceSystem           string         `json:"sourceSystem"`
	StudioRoot             string         `json:"studioRoot"`
	LDrawRoot              string         `json:"ldrawRoot"`
	GeneratedAt            string         `json:"generatedAt"`
	ManifestSHA256         string         `json:"manifestSha256"`
	DuplicatePolicy        string         `json:"duplicatePolicy"`
	Files                  []FileEntry    `json:"files"`
	CanonicalTopLevelParts []TopLevelPart `json:"canonicalTopLevelParts"`
}

type FileEntry struct {
	RelativePath string `json:"relativePath"`
	FileKind     string `json:"fileKind"`
	SHA256       string `json:"sha256"`
	SizeBytes    int64  `json:"sizeBytes"`
}

type TopLevelPart struct {
	LDrawPartNum           string   `json:"ldrawPartNum"`
	PreferredRelativePath  string   `json:"preferredRelativePath"`
	PreferredSource        string   `json:"preferredSource"`
	CandidateRelativePaths []string `json:"candidateRelativePaths"`
	HasDuplicateSources    bool     `json:"hasDuplicateSources"`
}

type Summary struct {
	SchemaVersion   string            `json:"schemaVersion"`
	SourceSystem    string            `json:"sourceSystem"`
	StudioRoot      string            `json:"studioRoot"`
	LDrawRoot       string            `json:"ldrawRoot"`
	GeneratedAt     string            `json:"generatedAt"`
	ManifestSHA256  string            `json:"manifestSha256"`
	FileKindCounts  map[string]int    `json:"fileKindCounts"`
	TotalFiles      int               `json:"totalFiles"`
	TotalBytes      int64             `json:"totalBytes"`
	TopLevelParts   TopLevelSummary   `json:"topLevelParts"`
	MetadataSources MetadataSummary   `json:"metadataSources"`
	OutputArtifacts map[string]string `json:"outputArtifacts"`
}

type TopLevelSummary struct {
	CanonicalDistinctParts int `json:"canonicalDistinctParts"`
	OfficialParts          int `json:"officialParts"`
	UnofficialParts        int `json:"unofficialParts"`
	LEGOParts              int `json:"legoParts"`
	BLPrefixedParts        int `json:"blPrefixedParts"`
	DuplicatePartNums      int `json:"duplicatePartNums"`
}

type MetadataSummary struct {
	LDrawNewXML         *LDrawNewXMLSummary     `json:"ldrawNewXml,omitempty"`
	DesignIDXML         *DesignIDXMLSummary     `json:"designIdXml,omitempty"`
	ElementInfoListJSON *ElementInfoListSummary `json:"elementInfoListJson,omitempty"`
}

type LDrawNewXMLSummary struct {
	Path                      string `json:"path"`
	MaterialCount             int    `json:"materialCount"`
	TransformationCount       int    `json:"transformationCount"`
	UniqueTransformationLDraw int    `json:"uniqueTransformationLDraw"`
	UniqueTransformationLEGO  int    `json:"uniqueTransformationLego"`
	AssemblyCount             int    `json:"assemblyCount"`
	UniqueAssemblyLDraw       int    `json:"uniqueAssemblyLDraw"`
	UniqueAssemblyLEGO        int    `json:"uniqueAssemblyLego"`
	DecorationCount           int    `json:"decorationCount"`
	UniqueDecorationLDraw     int    `json:"uniqueDecorationLDraw"`
	UniqueDecorationLEGO      int    `json:"uniqueDecorationLego"`
	UniqueDecorationIDs       int    `json:"uniqueDecorationIds"`
}

type DesignIDXMLSummary struct {
	Path              string `json:"path"`
	PartCount         int    `json:"partCount"`
	AlternateIDsTotal int    `json:"alternateIdsTotal"`
}

type ElementInfoListSummary struct {
	Path                 string `json:"path"`
	RowCount             int    `json:"rowCount"`
	DistinctElementIDs   int    `json:"distinctElementIds"`
	DistinctBLItemNos    int    `json:"distinctBlItemNos"`
	DistinctBLColorCodes int    `json:"distinctBlColorCodes"`
	RowsWithWeight       int    `json:"rowsWithWeight"`
	Sample3001Rows       int    `json:"sample3001Rows"`
}

type CoverageReport struct {
	SchemaVersion        string   `json:"schemaVersion"`
	LegacyPartsFile      string   `json:"legacyPartsFile"`
	StudioCanonicalParts int      `json:"studioCanonicalParts"`
	LegacyParts          int      `json:"legacyParts"`
	Intersection         int      `json:"intersection"`
	StudioOnly           int      `json:"studioOnly"`
	LegacyOnly           int      `json:"legacyOnly"`
	StudioOnlySamples    []string `json:"studioOnlySamples"`
	LegacyOnlySamples    []string `json:"legacyOnlySamples"`
	IntersectionSamples  []string `json:"intersectionSamples"`
}

type studioRoots struct {
	studioRoot string
	ldrawRoot  string
	dataRoot   string
}

func GenerateStudioManifest(opts Options) (Result, error) {
	if strings.TrimSpace(opts.StudioRoot) == "" {
		return Result{}, errors.New("studio root is required")
	}
	if strings.TrimSpace(opts.OutDir) == "" {
		return Result{}, errors.New("out dir is required")
	}
	generatedAt := opts.GeneratedAt
	if generatedAt.IsZero() {
		generatedAt = time.Now().UTC()
	}
	roots, err := resolveStudioRoots(opts.StudioRoot)
	if err != nil {
		return Result{}, err
	}
	if err := os.MkdirAll(opts.OutDir, 0o755); err != nil {
		return Result{}, fmt.Errorf("create out dir: %w", err)
	}

	files, topParts, summaryTop, err := scanLDrawRoot(roots.ldrawRoot)
	if err != nil {
		return Result{}, err
	}
	metadata := scanMetadata(roots.dataRoot)

	manifest := Manifest{
		SchemaVersion:          ManifestSchemaVersion,
		SourceSystem:           SourceSystem,
		StudioRoot:             roots.studioRoot,
		LDrawRoot:              roots.ldrawRoot,
		GeneratedAt:            generatedAt.Format(time.RFC3339),
		DuplicatePolicy:        DuplicatePolicy,
		Files:                  files,
		CanonicalTopLevelParts: topParts,
	}
	hash, err := manifestHash(manifest)
	if err != nil {
		return Result{}, err
	}
	manifest.ManifestSHA256 = hash

	summary := buildSummary(manifest, summaryTop, metadata)

	var coverage *CoverageReport
	if strings.TrimSpace(opts.LegacyPartsFile) != "" {
		report, err := buildCoverageReport(opts.LegacyPartsFile, topParts)
		if err != nil {
			return Result{}, err
		}
		coverage = &report
	}

	manifestPath := filepath.Join(opts.OutDir, "studio_manifest.json")
	summaryPath := filepath.Join(opts.OutDir, "studio_manifest_summary.json")
	coveragePath := ""
	if err := writePrettyJSON(manifestPath, manifest); err != nil {
		return Result{}, err
	}
	summary.OutputArtifacts = map[string]string{
		"manifest": manifestPath,
		"summary":  summaryPath,
	}
	if coverage != nil {
		coveragePath = filepath.Join(opts.OutDir, "studio_manifest_coverage.json")
		summary.OutputArtifacts["coverage"] = coveragePath
	}
	if err := writePrettyJSON(summaryPath, summary); err != nil {
		return Result{}, err
	}
	if coverage != nil {
		if err := writePrettyJSON(coveragePath, coverage); err != nil {
			return Result{}, err
		}
	}

	return Result{
		ManifestPath: manifestPath,
		SummaryPath:  summaryPath,
		CoveragePath: coveragePath,
		Manifest:     manifest,
		Summary:      summary,
		Coverage:     coverage,
	}, nil
}

func resolveStudioRoots(input string) (studioRoots, error) {
	abs, err := filepath.Abs(input)
	if err != nil {
		return studioRoots{}, err
	}
	info, err := os.Stat(abs)
	if err != nil {
		return studioRoots{}, fmt.Errorf("stat studio root: %w", err)
	}
	if !info.IsDir() {
		return studioRoots{}, fmt.Errorf("studio root is not a directory: %s", abs)
	}
	ldrawCandidate := filepath.Join(abs, "ldraw")
	if isDir(ldrawCandidate) {
		return studioRoots{studioRoot: abs, ldrawRoot: ldrawCandidate, dataRoot: filepath.Join(abs, "data")}, nil
	}
	if isDir(filepath.Join(abs, "parts")) && strings.EqualFold(filepath.Base(abs), "ldraw") {
		studioRoot := filepath.Dir(abs)
		return studioRoots{studioRoot: studioRoot, ldrawRoot: abs, dataRoot: filepath.Join(studioRoot, "data")}, nil
	}
	return studioRoots{}, fmt.Errorf("could not find ldraw root under %s", abs)
}

func isDir(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.IsDir()
}

func scanLDrawRoot(root string) ([]FileEntry, []TopLevelPart, TopLevelSummary, error) {
	var files []FileEntry
	topCandidates := map[string][]FileEntry{}
	summary := TopLevelSummary{}

	err := filepath.WalkDir(root, func(path string, d os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if d.IsDir() {
			return nil
		}
		rel, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		rel = filepath.ToSlash(rel)
		kind := classifyLDrawFile(rel)
		if kind == "" {
			return nil
		}
		entry, err := fileEntry(root, rel, kind)
		if err != nil {
			return err
		}
		files = append(files, entry)
		switch kind {
		case "ldraw_top_level_part_official":
			summary.OfficialParts++
			topCandidates[normalizePartNum(filepath.Base(rel))] = append(topCandidates[normalizePartNum(filepath.Base(rel))], entry)
		case "ldraw_top_level_part_unofficial":
			summary.UnofficialParts++
			partNum := normalizePartNum(filepath.Base(rel))
			if strings.HasPrefix(partNum, "bl_") {
				summary.BLPrefixedParts++
			}
			topCandidates[partNum] = append(topCandidates[partNum], entry)
		case "ldraw_lego_part":
			summary.LEGOParts++
		}
		return nil
	})
	if err != nil {
		return nil, nil, TopLevelSummary{}, fmt.Errorf("scan ldraw root: %w", err)
	}

	sort.Slice(files, func(i, j int) bool { return files[i].RelativePath < files[j].RelativePath })
	topParts := canonicalTopLevelParts(topCandidates)
	summary.CanonicalDistinctParts = len(topParts)
	for _, p := range topParts {
		if p.HasDuplicateSources {
			summary.DuplicatePartNums++
		}
	}
	return files, topParts, summary, nil
}

func classifyLDrawFile(rel string) string {
	relLower := strings.ToLower(filepath.ToSlash(rel))
	ext := strings.ToLower(filepath.Ext(relLower))
	if strings.Contains(relLower, "/textures/") || strings.HasPrefix(relLower, "parts/textures/") || strings.HasPrefix(relLower, "unofficial/parts/textures/") {
		return "texture"
	}
	if strings.HasPrefix(relLower, "connectivity/") && ext == ".conn" {
		return "connectivity"
	}
	if strings.HasPrefix(relLower, "collider/") && ext == ".col" {
		return "collider"
	}
	if ext != ".dat" && ext != ".ldr" && ext != ".mpd" {
		return ""
	}
	dir := strings.ToLower(filepath.ToSlash(filepath.Dir(relLower)))
	switch {
	case dir == "parts" && ext == ".dat":
		return "ldraw_top_level_part_official"
	case dir == "unofficial/parts" && ext == ".dat":
		return "ldraw_top_level_part_unofficial"
	case dir == "lego" && ext == ".dat":
		return "ldraw_lego_part"
	case strings.HasPrefix(dir, "parts/s"):
		return "ldraw_subpart_official"
	case strings.HasPrefix(dir, "unofficial/parts/s"):
		return "ldraw_subpart_unofficial"
	case dir == "p" || strings.HasPrefix(dir, "p/"):
		return "ldraw_primitive_official"
	case dir == "unofficial/p" || strings.HasPrefix(dir, "unofficial/p/"):
		return "ldraw_primitive_unofficial"
	default:
		return "ldraw_other"
	}
}

func fileEntry(root, rel, kind string) (FileEntry, error) {
	path := filepath.Join(root, filepath.FromSlash(rel))
	info, err := os.Stat(path)
	if err != nil {
		return FileEntry{}, err
	}
	hash, err := sha256File(path)
	if err != nil {
		return FileEntry{}, err
	}
	return FileEntry{RelativePath: rel, FileKind: kind, SHA256: hash, SizeBytes: info.Size()}, nil
}

func sha256File(path string) (string, error) {
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

func canonicalTopLevelParts(candidates map[string][]FileEntry) []TopLevelPart {
	parts := make([]string, 0, len(candidates))
	for part := range candidates {
		if part != "" {
			parts = append(parts, part)
		}
	}
	sort.Strings(parts)
	out := make([]TopLevelPart, 0, len(parts))
	for _, part := range parts {
		entries := candidates[part]
		sort.Slice(entries, func(i, j int) bool {
			pi := sourcePrecedence(entries[i].FileKind)
			pj := sourcePrecedence(entries[j].FileKind)
			if pi != pj {
				return pi < pj
			}
			return entries[i].RelativePath < entries[j].RelativePath
		})
		paths := make([]string, len(entries))
		for i, entry := range entries {
			paths[i] = entry.RelativePath
		}
		out = append(out, TopLevelPart{
			LDrawPartNum:           part,
			PreferredRelativePath:  entries[0].RelativePath,
			PreferredSource:        entries[0].FileKind,
			CandidateRelativePaths: paths,
			HasDuplicateSources:    len(entries) > 1,
		})
	}
	return out
}

func sourcePrecedence(kind string) int {
	switch kind {
	case "ldraw_top_level_part_official":
		return 0
	case "ldraw_top_level_part_unofficial":
		return 1
	default:
		return 99
	}
}

func scanMetadata(dataRoot string) MetadataSummary {
	var out MetadataSummary
	if !isDir(dataRoot) {
		return out
	}
	if s, err := parseLDrawNewXML(filepath.Join(dataRoot, "ldraw_new.xml")); err == nil {
		out.LDrawNewXML = &s
	}
	if s, err := parseDesignIDXML(filepath.Join(dataRoot, "designid.xml")); err == nil {
		out.DesignIDXML = &s
	}
	if s, err := parseElementInfoList(filepath.Join(dataRoot, "elementInfoList.json")); err == nil {
		out.ElementInfoListJSON = &s
	}
	return out
}

func parseLDrawNewXML(path string) (LDrawNewXMLSummary, error) {
	f, err := os.Open(path)
	if err != nil {
		return LDrawNewXMLSummary{}, err
	}
	defer f.Close()
	decoder := xml.NewDecoder(f)
	ldrawTransformation := map[string]struct{}{}
	legoTransformation := map[string]struct{}{}
	ldrawAssembly := map[string]struct{}{}
	legoAssembly := map[string]struct{}{}
	ldrawDecoration := map[string]struct{}{}
	legoDecoration := map[string]struct{}{}
	decorationIDs := map[string]struct{}{}
	out := LDrawNewXMLSummary{Path: path}
	for {
		tok, err := decoder.Token()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return LDrawNewXMLSummary{}, err
		}
		start, ok := tok.(xml.StartElement)
		if !ok {
			continue
		}
		switch start.Name.Local {
		case "Material":
			out.MaterialCount++
		case "Transformation":
			out.TransformationCount++
			addAttr(ldrawTransformation, start, "ldraw")
			addAttr(legoTransformation, start, "lego")
		case "Assembly":
			out.AssemblyCount++
			addAttr(ldrawAssembly, start, "ldraw")
			addAttr(legoAssembly, start, "lego")
		case "Decoration":
			out.DecorationCount++
			addAttr(ldrawDecoration, start, "ldraw")
			addAttr(legoDecoration, start, "lego")
			for _, id := range strings.Split(attr(start, "decoration"), ",") {
				id = strings.TrimSpace(id)
				if id != "" && id != "0" {
					decorationIDs[id] = struct{}{}
				}
			}
		}
	}
	out.UniqueTransformationLDraw = len(ldrawTransformation)
	out.UniqueTransformationLEGO = len(legoTransformation)
	out.UniqueAssemblyLDraw = len(ldrawAssembly)
	out.UniqueAssemblyLEGO = len(legoAssembly)
	out.UniqueDecorationLDraw = len(ldrawDecoration)
	out.UniqueDecorationLEGO = len(legoDecoration)
	out.UniqueDecorationIDs = len(decorationIDs)
	return out, nil
}

func parseDesignIDXML(path string) (DesignIDXMLSummary, error) {
	f, err := os.Open(path)
	if err != nil {
		return DesignIDXMLSummary{}, err
	}
	defer f.Close()
	decoder := xml.NewDecoder(f)
	out := DesignIDXMLSummary{Path: path}
	for {
		tok, err := decoder.Token()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return DesignIDXMLSummary{}, err
		}
		start, ok := tok.(xml.StartElement)
		if !ok || start.Name.Local != "Part" {
			continue
		}
		out.PartCount++
		for _, id := range strings.Split(attr(start, "alternateDesignIDs"), ",") {
			if strings.TrimSpace(id) != "" {
				out.AlternateIDsTotal++
			}
		}
	}
	return out, nil
}

func parseElementInfoList(path string) (ElementInfoListSummary, error) {
	f, err := os.Open(path)
	if err != nil {
		return ElementInfoListSummary{}, err
	}
	defer f.Close()
	decoder := json.NewDecoder(f)
	tok, err := decoder.Token()
	if err != nil {
		return ElementInfoListSummary{}, err
	}
	if delim, ok := tok.(json.Delim); !ok || delim != '[' {
		return ElementInfoListSummary{}, fmt.Errorf("element info list must be a JSON array")
	}
	elementIDs := map[string]struct{}{}
	blItems := map[string]struct{}{}
	blColors := map[string]struct{}{}
	out := ElementInfoListSummary{Path: path}
	for decoder.More() {
		var row struct {
			ElementID   string `json:"elementId"`
			BLItemNo    string `json:"blItemNo"`
			BLColorCode string `json:"blColorCode"`
			Weight      string `json:"weight"`
		}
		if err := decoder.Decode(&row); err != nil {
			return ElementInfoListSummary{}, err
		}
		out.RowCount++
		if row.ElementID != "" {
			elementIDs[row.ElementID] = struct{}{}
		}
		if row.BLItemNo != "" {
			blItems[strings.ToLower(row.BLItemNo)] = struct{}{}
		}
		if row.BLColorCode != "" {
			blColors[row.BLColorCode] = struct{}{}
		}
		if row.Weight != "" {
			out.RowsWithWeight++
		}
		if strings.EqualFold(row.BLItemNo, "3001") {
			out.Sample3001Rows++
		}
	}
	out.DistinctElementIDs = len(elementIDs)
	out.DistinctBLItemNos = len(blItems)
	out.DistinctBLColorCodes = len(blColors)
	return out, nil
}

func addAttr(dst map[string]struct{}, start xml.StartElement, name string) {
	value := strings.TrimSpace(attr(start, name))
	if value != "" {
		dst[strings.ToLower(value)] = struct{}{}
	}
}

func attr(start xml.StartElement, name string) string {
	for _, attr := range start.Attr {
		if attr.Name.Local == name {
			return attr.Value
		}
	}
	return ""
}

func buildSummary(manifest Manifest, top TopLevelSummary, metadata MetadataSummary) Summary {
	counts := map[string]int{}
	var totalBytes int64
	for _, file := range manifest.Files {
		counts[file.FileKind]++
		totalBytes += file.SizeBytes
	}
	return Summary{
		SchemaVersion:   manifest.SchemaVersion,
		SourceSystem:    manifest.SourceSystem,
		StudioRoot:      manifest.StudioRoot,
		LDrawRoot:       manifest.LDrawRoot,
		GeneratedAt:     manifest.GeneratedAt,
		ManifestSHA256:  manifest.ManifestSHA256,
		FileKindCounts:  counts,
		TotalFiles:      len(manifest.Files),
		TotalBytes:      totalBytes,
		TopLevelParts:   top,
		MetadataSources: metadata,
	}
}

func buildCoverageReport(path string, topParts []TopLevelPart) (CoverageReport, error) {
	legacy, err := readLegacyParts(path)
	if err != nil {
		return CoverageReport{}, err
	}
	studio := map[string]struct{}{}
	for _, part := range topParts {
		studio[part.LDrawPartNum] = struct{}{}
	}
	var intersection, studioOnly, legacyOnly []string
	for part := range studio {
		if _, ok := legacy[part]; ok {
			intersection = append(intersection, part)
		} else {
			studioOnly = append(studioOnly, part)
		}
	}
	for part := range legacy {
		if _, ok := studio[part]; !ok {
			legacyOnly = append(legacyOnly, part)
		}
	}
	sort.Strings(intersection)
	sort.Strings(studioOnly)
	sort.Strings(legacyOnly)
	return CoverageReport{
		SchemaVersion:        ManifestSchemaVersion,
		LegacyPartsFile:      path,
		StudioCanonicalParts: len(studio),
		LegacyParts:          len(legacy),
		Intersection:         len(intersection),
		StudioOnly:           len(studioOnly),
		LegacyOnly:           len(legacyOnly),
		StudioOnlySamples:    firstN(studioOnly, 25),
		LegacyOnlySamples:    firstN(legacyOnly, 25),
		IntersectionSamples:  firstN(intersection, 25),
	}, nil
}

func readLegacyParts(path string) (map[string]struct{}, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open legacy parts file: %w", err)
	}
	defer f.Close()
	parts := map[string]struct{}{}
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		field := strings.FieldsFunc(line, func(r rune) bool {
			return r == '\t' || r == ',' || r == ';'
		})[0]
		part := normalizePartNum(field)
		if part != "" {
			parts[part] = struct{}{}
		}
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	return parts, nil
}

func normalizePartNum(value string) string {
	value = strings.TrimSpace(strings.Trim(value, `"'`))
	value = filepath.ToSlash(value)
	if strings.Contains(value, "/") {
		value = filepath.Base(value)
	}
	value = strings.ToLower(value)
	ext := strings.ToLower(filepath.Ext(value))
	if ext == "" {
		value += ".dat"
	}
	return value
}

func firstN(values []string, n int) []string {
	if len(values) <= n {
		return values
	}
	return values[:n]
}

func manifestHash(manifest Manifest) (string, error) {
	payload := struct {
		SchemaVersion          string         `json:"schemaVersion"`
		SourceSystem           string         `json:"sourceSystem"`
		DuplicatePolicy        string         `json:"duplicatePolicy"`
		Files                  []FileEntry    `json:"files"`
		CanonicalTopLevelParts []TopLevelPart `json:"canonicalTopLevelParts"`
	}{
		SchemaVersion:          manifest.SchemaVersion,
		SourceSystem:           manifest.SourceSystem,
		DuplicatePolicy:        manifest.DuplicatePolicy,
		Files:                  manifest.Files,
		CanonicalTopLevelParts: manifest.CanonicalTopLevelParts,
	}
	data, err := json.Marshal(payload)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:]), nil
}

func writePrettyJSON(path string, value any) error {
	f, err := os.Create(path)
	if err != nil {
		return fmt.Errorf("create %s: %w", path, err)
	}
	defer f.Close()
	enc := json.NewEncoder(f)
	enc.SetIndent("", "  ")
	if err := enc.Encode(value); err != nil {
		return fmt.Errorf("write %s: %w", path, err)
	}
	return nil
}
