package partlibrary

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const StudioImporterVersion = "studio-part-library-importer-v1"

type ImportOptions struct {
	DatabaseURL  string
	ManifestPath string
	LDrawRoot    string
	LibraryID    string
	CreatedBy    string
	Status       string
	DryRun       bool
	Limit        int
}

type ImportResult struct {
	LibraryID      string
	Status         string
	ManifestSHA256 string
	PartCount      int
	GeometryReady  int
	GeometryFailed int
	PreviewRows    int64
	DryRun         bool
	FailuresSample []GeometryFailure
	Elapsed        time.Duration
}

type GeometryFailure struct {
	LDrawPartNum string   `json:"ldrawPartNum"`
	SourcePath   string   `json:"sourcePath"`
	Error        string   `json:"error"`
	Reference    string   `json:"reference,omitempty"`
	FromPath     string   `json:"fromPath,omitempty"`
	Candidates   []string `json:"candidates,omitempty"`
}

type importPartRow struct {
	LDrawPartNum string
	SourceName   string
	Metadata     []byte
	Geometry     importGeometryRow
}

type importGeometryRow struct {
	SourceRelativePath string
	SourceSHA256       string
	BBoxMin            [3]float64
	BBoxMax            [3]float64
	LogicalWidthStud   *float64
	LogicalDepthStud   *float64
	LogicalHeightPlate *float64
	VertexCount        int
	FaceCount          int
	Status             string
	ErrorCode          *string
	ErrorParams        []byte
	DerivationStatus   string
}

func ImportStudioLibrary(ctx context.Context, opts ImportOptions) (ImportResult, error) {
	started := time.Now()
	manifest, err := readManifest(opts.ManifestPath)
	if err != nil {
		return ImportResult{}, err
	}
	if manifest.ManifestSHA256 == "" {
		return ImportResult{}, errors.New("manifestSha256 is required")
	}
	status := strings.TrimSpace(opts.Status)
	if status == "" {
		status = "building"
	}
	if status != "building" && status != "active" && status != "retired" && status != "failed" {
		return ImportResult{}, fmt.Errorf("invalid status %q", status)
	}
	libraryID := strings.TrimSpace(opts.LibraryID)
	if libraryID == "" {
		libraryID = deterministicUUIDString("studio-part-library:" + manifest.ManifestSHA256)
	}
	createdBy := strings.TrimSpace(opts.CreatedBy)
	if createdBy == "" {
		createdBy = "00000000-0000-4000-8000-000000000001"
	}
	ldrawRoot := strings.TrimSpace(opts.LDrawRoot)
	if ldrawRoot == "" {
		ldrawRoot = manifest.LDrawRoot
	}
	if ldrawRoot == "" {
		return ImportResult{}, errors.New("ldraw root is required")
	}

	parts := manifest.CanonicalTopLevelParts
	if opts.Limit > 0 && opts.Limit < len(parts) {
		parts = parts[:opts.Limit]
	}
	fileByPath := map[string]FileEntry{}
	for _, file := range manifest.Files {
		fileByPath[normalizeLDrawGeometryPath(file.RelativePath)] = file
	}
	index, err := newLDrawIndex(ldrawRoot)
	if err != nil {
		return ImportResult{}, err
	}
	rows := make([]importPartRow, 0, len(parts))
	failures := []GeometryFailure{}
	ready := 0
	failed := 0
	for _, part := range parts {
		row := importPartRow{
			LDrawPartNum: part.LDrawPartNum,
			SourceName:   part.LDrawPartNum,
		}
		preferredPath := normalizeLDrawGeometryPath(part.PreferredRelativePath)
		preferredFile, hasPreferred := fileByPath[preferredPath]
		row.Metadata = mustMarshalJSON(map[string]any{
			"sourceSystem":             SourceSystem,
			"preferredRelativePath":    part.PreferredRelativePath,
			"preferredSource":          part.PreferredSource,
			"candidateRelativePaths":   part.CandidateRelativePaths,
			"hasDuplicateSources":      part.HasDuplicateSources,
			"manifestSha256":           manifest.ManifestSHA256,
			"studioImporterVersion":    StudioImporterVersion,
			"preferredSourceFileHash":  optionalFileHash(preferredFile, hasPreferred),
			"preferredSourceFileBytes": optionalFileSize(preferredFile, hasPreferred),
		})
		stats, statsErr := ComputeGeometryStatsWithIndex(index, part.PreferredRelativePath)
		if statsErr != nil {
			failed++
			sourcePath := LDrawWorkerRelativePath(part.PreferredRelativePath)
			sourceHash := optionalFileHash(preferredFile, hasPreferred)
			if sourceHash == "" {
				sourceHash = strings.Repeat("0", 64)
			}
			code := "component_repo.geometry_not_materialized"
			errorParams := map[string]any{
				"reason":             statsErr.Error(),
				"sourceRelativePath": sourcePath,
			}
			var geometryErr ldrawGeometryError
			if errors.As(statsErr, &geometryErr) {
				errorParams["fromPath"] = geometryErr.fromPath
				errorParams["reference"] = geometryErr.reference
				errorParams["candidates"] = geometryErr.candidates
			}
			params := mustMarshalJSON(errorParams)
			row.Geometry = importGeometryRow{
				SourceRelativePath: sourcePath,
				SourceSHA256:       sourceHash,
				BBoxMin:            [3]float64{0, 0, 0},
				BBoxMax:            [3]float64{0, 0, 0},
				VertexCount:        0,
				FaceCount:          0,
				Status:             "failed",
				ErrorCode:          &code,
				ErrorParams:        params,
				DerivationStatus:   "failed",
			}
			if len(failures) < 25 {
				failure := GeometryFailure{LDrawPartNum: part.LDrawPartNum, SourcePath: sourcePath, Error: statsErr.Error()}
				if errors.As(statsErr, &geometryErr) {
					failure.Reference = geometryErr.reference
					failure.FromPath = geometryErr.fromPath
					failure.Candidates = geometryErr.candidates
				}
				failures = append(failures, failure)
			}
		} else {
			ready++
			width := roundNonNegative((stats.BBoxMax[0] - stats.BBoxMin[0]) / 20)
			depth := roundNonNegative((stats.BBoxMax[2] - stats.BBoxMin[2]) / 20)
			height := roundNonNegative((stats.BBoxMax[1] - stats.BBoxMin[1]) / 8)
			row.Geometry = importGeometryRow{
				SourceRelativePath: stats.SourceRelativePath,
				SourceSHA256:       stats.SourceSHA256,
				BBoxMin:            stats.BBoxMin,
				BBoxMax:            stats.BBoxMax,
				LogicalWidthStud:   &width,
				LogicalDepthStud:   &depth,
				LogicalHeightPlate: &height,
				VertexCount:        stats.VertexCount,
				FaceCount:          stats.FaceCount,
				Status:             "ready",
				DerivationStatus:   "derived_approximate",
			}
		}
		rows = append(rows, row)
	}

	result := ImportResult{
		LibraryID:      libraryID,
		Status:         status,
		ManifestSHA256: manifest.ManifestSHA256,
		PartCount:      len(rows),
		GeometryReady:  ready,
		GeometryFailed: failed,
		DryRun:         opts.DryRun,
		FailuresSample: failures,
		Elapsed:        time.Since(started),
	}
	if opts.DryRun {
		return result, nil
	}
	if strings.TrimSpace(opts.DatabaseURL) == "" {
		return ImportResult{}, errors.New("database url is required unless dry-run is set")
	}
	pool, err := pgxpool.New(ctx, opts.DatabaseURL)
	if err != nil {
		return ImportResult{}, fmt.Errorf("open database pool: %w", err)
	}
	defer pool.Close()
	if err := pool.Ping(ctx); err != nil {
		return ImportResult{}, fmt.Errorf("database unavailable: %w", err)
	}
	tx, err := pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return ImportResult{}, err
	}
	defer tx.Rollback(ctx)
	if err := importRows(ctx, tx, manifest, libraryID, createdBy, status, rows); err != nil {
		return ImportResult{}, err
	}
	var previewRows int64
	if err := tx.QueryRow(ctx, `
		SELECT count(*) FROM component_repo.part_previews
		WHERE part_library_version_id = $1::uuid
	`, libraryID).Scan(&previewRows); err != nil {
		return ImportResult{}, err
	}
	if err := tx.Commit(ctx); err != nil {
		return ImportResult{}, err
	}
	result.PreviewRows = previewRows
	result.Elapsed = time.Since(started)
	return result, nil
}

func importRows(ctx context.Context, tx pgx.Tx, manifest Manifest, libraryID, createdBy, status string, rows []importPartRow) error {
	if _, err := tx.Exec(ctx, `SET LOCAL statement_timeout = '30min'`); err != nil {
		return err
	}
	metadata := mustMarshalJSON(map[string]any{
		"sourceSystem":          SourceSystem,
		"schemaVersion":         manifest.SchemaVersion,
		"manifestSha256":        manifest.ManifestSHA256,
		"duplicatePolicy":       manifest.DuplicatePolicy,
		"studioRoot":            manifest.StudioRoot,
		"ldrawRoot":             manifest.LDrawRoot,
		"manifestFileCount":     len(manifest.Files),
		"canonicalPartCount":    len(manifest.CanonicalTopLevelParts),
		"studioImporterVersion": StudioImporterVersion,
		"geometryMode":          "ldraw_recursive_bbox_v1",
	})
	if _, err := tx.Exec(ctx, `
		INSERT INTO component_repo.part_library_versions (
			id, source_name, source_hash, connector_count, status, metadata, created_by
		) VALUES ($1::uuid, $2, $3, 0, $4, $5::jsonb, $6::uuid)
		ON CONFLICT (id) DO UPDATE SET
			source_name = EXCLUDED.source_name,
			source_hash = EXCLUDED.source_hash,
			status = EXCLUDED.status,
			metadata = EXCLUDED.metadata,
			created_by = EXCLUDED.created_by
	`, libraryID, SourceSystem, manifest.ManifestSHA256, status, string(metadata), createdBy); err != nil {
		return fmt.Errorf("upsert part library version: %w", err)
	}
	if _, err := tx.Exec(ctx, `
		CREATE TEMP TABLE studio_import_parts (
			ldraw_part_num text NOT NULL,
			source_name text NOT NULL,
			metadata jsonb NOT NULL
		) ON COMMIT DROP;
		CREATE TEMP TABLE studio_import_geometries (
			ldraw_part_num text NOT NULL,
			source_relative_path text NOT NULL,
			source_file_hash text NOT NULL,
			bbox_min double precision[] NOT NULL,
			bbox_max double precision[] NOT NULL,
			logical_width_stud double precision,
			logical_depth_stud double precision,
			logical_height_plate double precision,
			vertex_count integer NOT NULL,
			face_count integer NOT NULL,
			geometry_status text NOT NULL,
			geometry_error_code text,
			geometry_error_params jsonb,
			logical_size_derivation_status text NOT NULL
		) ON COMMIT DROP;
	`); err != nil {
		return fmt.Errorf("create temp import tables: %w", err)
	}
	partCopyRows := make([][]any, 0, len(rows))
	geometryCopyRows := make([][]any, 0, len(rows))
	for _, row := range rows {
		g := row.Geometry
		partCopyRows = append(partCopyRows, []any{row.LDrawPartNum, row.SourceName, string(row.Metadata)})
		geometryCopyRows = append(geometryCopyRows, []any{
			row.LDrawPartNum, g.SourceRelativePath, g.SourceSHA256,
			floatArray(g.BBoxMin), floatArray(g.BBoxMax),
			nullableFloat(g.LogicalWidthStud), nullableFloat(g.LogicalDepthStud), nullableFloat(g.LogicalHeightPlate),
			g.VertexCount, g.FaceCount, g.Status, nullableText(g.ErrorCode), nullableJSON(g.ErrorParams), g.DerivationStatus,
		})
	}
	if _, err := tx.CopyFrom(ctx, pgx.Identifier{"studio_import_parts"}, []string{
		"ldraw_part_num", "source_name", "metadata",
	}, pgx.CopyFromRows(partCopyRows)); err != nil {
		return fmt.Errorf("copy import parts: %w", err)
	}
	if _, err := tx.CopyFrom(ctx, pgx.Identifier{"studio_import_geometries"}, []string{
		"ldraw_part_num", "source_relative_path", "source_file_hash",
		"bbox_min", "bbox_max", "logical_width_stud", "logical_depth_stud", "logical_height_plate",
		"vertex_count", "face_count", "geometry_status", "geometry_error_code",
		"geometry_error_params", "logical_size_derivation_status",
	}, pgx.CopyFromRows(geometryCopyRows)); err != nil {
		return fmt.Errorf("copy import geometries: %w", err)
	}
	if _, err := tx.Exec(ctx, `
		INSERT INTO component_repo.parts (
			part_library_version_id, ldraw_part_num, source_name, content_locale, metadata
		)
		SELECT $1::uuid, ldraw_part_num, source_name, 'en-US', metadata
		FROM studio_import_parts
		ON CONFLICT (part_library_version_id, ldraw_part_num) DO UPDATE SET
			source_name = EXCLUDED.source_name,
			content_locale = EXCLUDED.content_locale,
			metadata = EXCLUDED.metadata
	`, libraryID); err != nil {
		return fmt.Errorf("upsert parts from staging: %w", err)
	}
	if _, err := tx.Exec(ctx, `
		INSERT INTO component_repo.part_geometries (
			part_library_version_id, ldraw_part_num,
			source_relative_path, source_file_hash,
			bbox_min, bbox_max,
			logical_width_stud, logical_depth_stud, logical_height_plate,
			vertex_count, face_count, geometry_status,
			geometry_error_code, geometry_error_params,
			logical_size_derivation_status
		)
		SELECT $1::uuid, ldraw_part_num,
		       source_relative_path, source_file_hash,
		       bbox_min, bbox_max,
		       logical_width_stud, logical_depth_stud, logical_height_plate,
		       vertex_count, face_count, geometry_status,
		       geometry_error_code, geometry_error_params,
		       logical_size_derivation_status
		FROM studio_import_geometries
		ON CONFLICT (part_library_version_id, ldraw_part_num) DO UPDATE SET
			source_relative_path = EXCLUDED.source_relative_path,
			source_file_hash = EXCLUDED.source_file_hash,
			bbox_min = EXCLUDED.bbox_min,
			bbox_max = EXCLUDED.bbox_max,
			logical_width_stud = EXCLUDED.logical_width_stud,
			logical_depth_stud = EXCLUDED.logical_depth_stud,
			logical_height_plate = EXCLUDED.logical_height_plate,
			vertex_count = EXCLUDED.vertex_count,
			face_count = EXCLUDED.face_count,
			geometry_status = EXCLUDED.geometry_status,
			geometry_error_code = EXCLUDED.geometry_error_code,
			geometry_error_params = EXCLUDED.geometry_error_params,
			logical_size_derivation_status = EXCLUDED.logical_size_derivation_status,
			updated_at = now()
	`, libraryID); err != nil {
		return fmt.Errorf("upsert geometries from staging: %w", err)
	}
	return nil
}

func readManifest(path string) (Manifest, error) {
	if strings.TrimSpace(path) == "" {
		return Manifest{}, errors.New("manifest path is required")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return Manifest{}, fmt.Errorf("read manifest: %w", err)
	}
	var manifest Manifest
	if err := json.Unmarshal(raw, &manifest); err != nil {
		return Manifest{}, fmt.Errorf("parse manifest: %w", err)
	}
	if manifest.SchemaVersion != ManifestSchemaVersion {
		return Manifest{}, fmt.Errorf("unsupported manifest schema %q", manifest.SchemaVersion)
	}
	return manifest, nil
}

func deterministicUUIDString(input string) string {
	sum := sha256.Sum256([]byte(input))
	b := sum[:16]
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	hexed := hex.EncodeToString(b)
	return fmt.Sprintf("%s-%s-%s-%s-%s", hexed[0:8], hexed[8:12], hexed[12:16], hexed[16:20], hexed[20:32])
}

func mustMarshalJSON(value any) []byte {
	data, err := json.Marshal(value)
	if err != nil {
		panic(err)
	}
	return data
}

func optionalFileHash(entry FileEntry, ok bool) string {
	if !ok {
		return ""
	}
	return entry.SHA256
}

func optionalFileSize(entry FileEntry, ok bool) any {
	if !ok {
		return nil
	}
	return entry.SizeBytes
}

func roundNonNegative(value float64) float64 {
	if value < 0 {
		value = -value
	}
	return mathRound(value, 4)
}

func mathRound(value float64, places int) float64 {
	scale := 1.0
	for i := 0; i < places; i++ {
		scale *= 10
	}
	return float64(int(value*scale+0.5)) / scale
}

func floatArray(values [3]float64) []float64 {
	return []float64{values[0], values[1], values[2]}
}

func nullableJSON(value []byte) *string {
	if len(value) == 0 {
		return nil
	}
	text := string(value)
	return &text
}

func nullableFloat(value *float64) any {
	if value == nil {
		return nil
	}
	return *value
}

func nullableText(value *string) any {
	if value == nil {
		return nil
	}
	return *value
}

func ManifestPathFromOutDir(outDir string) string {
	return filepath.Join(outDir, "studio_manifest.json")
}
