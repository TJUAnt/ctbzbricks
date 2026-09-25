package partlibrary

import (
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const StudioImporterVersion = "studio-part-library-importer-v5"

const (
	ColliderStorageMetadataOnly = "metadata-only"
	ColliderStorageDatabase     = "database"
)

type ImportOptions struct {
	DatabaseURL     string
	ManifestPath    string
	LDrawRoot       string
	LibraryID       string
	CreatedBy       string
	Status          string
	ColliderStorage string
	DryRun          bool
	Limit           int
}

type ImportResult struct {
	LibraryID              string
	Status                 string
	ManifestSHA256         string
	PartCount              int
	GeometryReady          int
	GeometryFailed         int
	LogicalSizeNominal     int
	LogicalSizeBoundingBox int
	PreviewRows            int64
	PreviewReady           bool
	RelationReady          bool
	ConnectorCount         int
	ConnectorFiles         int
	ConnectorHash          string
	ConnectorFailed        int
	ColliderCount          int
	ColliderFiles          int
	ColliderHash           string
	ColliderFailed         int
	ColliderStored         int
	ColliderStorage        string
	DryRun                 bool
	FailuresSample         []GeometryFailure
	SidecarFailuresSample  []SidecarFailure
	Elapsed                time.Duration
}

type SidecarFailure struct {
	LDrawPartNum string `json:"ldrawPartNum"`
	SourcePath   string `json:"sourcePath"`
	FileKind     string `json:"fileKind"`
	Error        string `json:"error"`
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
	Connectors   []importConnectorRow
	Colliders    []importColliderRow
}

type importConnectorRow struct {
	SourceID   int64
	Definition StudioConnectorDefinition
	RawParams  []byte
}

type importColliderRow struct {
	SourceID   int64
	Definition StudioColliderDefinition
	RawParams  []byte
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

// ImportStudioLibrary 离线构建版本化 Studio Part Library；所有数据库写入在单事务中提交，API/Worker 启动不会调用它。
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
		// 同一 Studio 源在派生算法升级后必须得到新的不可变版本，不能原地覆盖旧 snapshot。
		libraryID = deterministicUUIDString("studio-part-library:" + manifest.ManifestSHA256 + ":" + StudioImporterVersion + ":" + LogicalSizeAlgorithmVersion)
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
	colliderStorage := strings.TrimSpace(opts.ColliderStorage)
	if colliderStorage == "" {
		colliderStorage = ColliderStorageMetadataOnly
	}
	if colliderStorage != ColliderStorageMetadataOnly && colliderStorage != ColliderStorageDatabase {
		return ImportResult{}, fmt.Errorf("invalid collider storage %q", colliderStorage)
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
	sidecars := importStudioSidecars(ldrawRoot, manifest, parts, opts.Limit > 0, colliderStorage == ColliderStorageDatabase)
	rows := make([]importPartRow, 0, len(parts))
	failures := []GeometryFailure{}
	ready := 0
	failed := 0
	nominalSizes := 0
	boundingBoxSizes := 0
	for _, part := range parts {
		row := importPartRow{
			LDrawPartNum: part.LDrawPartNum,
			Connectors:   sidecars.connectors[part.LDrawPartNum],
			Colliders:    sidecars.colliders[part.LDrawPartNum],
		}
		preferredPath := normalizeLDrawGeometryPath(part.PreferredRelativePath)
		preferredFile, hasPreferred := fileByPath[preferredPath]
		// Part Search 只读取数据库，导入期必须把 LDraw 文件头的源名称固化，不能让 API 依赖本地 Studio 目录。
		row.SourceName = index.sourceName(part.PreferredRelativePath, part.LDrawPartNum)
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
			// 标准零件固化标称尺寸，非标准零件固化 bbox；两类 ready 几何都可参与 ±2mm 尺寸搜索。
			width, depth, height, derivationStatus := deriveLogicalSize(row.SourceName, stats)
			if derivationStatus == "derived_exact" {
				nominalSizes++
			} else {
				boundingBoxSizes++
			}
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
				DerivationStatus:   derivationStatus,
			}
		}
		rows = append(rows, row)
	}

	result := ImportResult{
		LibraryID:              libraryID,
		Status:                 status,
		ManifestSHA256:         manifest.ManifestSHA256,
		PartCount:              len(rows),
		GeometryReady:          ready,
		GeometryFailed:         failed,
		LogicalSizeNominal:     nominalSizes,
		LogicalSizeBoundingBox: boundingBoxSizes,
		PreviewReady:           ready > 0,
		RelationReady:          sidecars.relationReady,
		ConnectorCount:         sidecars.connectorCount,
		ConnectorFiles:         sidecars.connectorFiles,
		ConnectorHash:          sidecars.connectorHash,
		ConnectorFailed:        len(sidecars.connectorFailures),
		ColliderCount:          sidecars.colliderCount,
		ColliderFiles:          sidecars.colliderFiles,
		ColliderHash:           sidecars.colliderHash,
		ColliderFailed:         len(sidecars.colliderFailures),
		ColliderStored:         sidecars.colliderStored,
		ColliderStorage:        colliderStorage,
		DryRun:                 opts.DryRun,
		FailuresSample:         failures,
		SidecarFailuresSample:  sidecars.failureSample(),
		Elapsed:                time.Since(started),
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
	if err := importRows(ctx, tx, manifest, libraryID, createdBy, status, rows, result); err != nil {
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

func importRows(ctx context.Context, tx pgx.Tx, manifest Manifest, libraryID, createdBy, status string, rows []importPartRow, result ImportResult) error {
	if _, err := tx.Exec(ctx, `SET LOCAL statement_timeout = '30min'`); err != nil {
		return err
	}
	if status == "active" {
		if _, err := tx.Exec(ctx, `
			UPDATE component_repo.part_library_versions
			SET status = 'retired'
			WHERE status = 'active' AND id <> $1::uuid
		`, libraryID); err != nil {
			return fmt.Errorf("retire previous active Part Library: %w", err)
		}
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
		"logicalSizeAlgorithm":  LogicalSizeAlgorithmVersion,
		"previewReady":          result.PreviewReady,
		"relationReady":         result.RelationReady,
		"connectorFileCount":    result.ConnectorFiles,
		"connectorFailureCount": result.ConnectorFailed,
		"colliderFileCount":     result.ColliderFiles,
		"colliderFailureCount":  result.ColliderFailed,
		"colliderStoredCount":   result.ColliderStored,
		"colliderStorage":       result.ColliderStorage,
	})
	if _, err := tx.Exec(ctx, `
		INSERT INTO component_repo.part_library_versions (
			id, source_name, source_hash, connector_count, status, metadata, created_by,
			preview_ready, relation_ready, connector_source_hash, connector_parser_version,
			collider_count, collider_source_hash, collider_parser_version
		) VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb, $7::uuid,
		          $8, $9, $10, $11, $12, $13, $14)
		ON CONFLICT (id) DO UPDATE SET
			source_name = EXCLUDED.source_name,
			source_hash = EXCLUDED.source_hash,
			connector_count = EXCLUDED.connector_count,
			status = EXCLUDED.status,
			metadata = EXCLUDED.metadata,
			created_by = EXCLUDED.created_by,
			preview_ready = EXCLUDED.preview_ready,
			relation_ready = EXCLUDED.relation_ready,
			connector_source_hash = EXCLUDED.connector_source_hash,
			connector_parser_version = EXCLUDED.connector_parser_version,
			collider_count = EXCLUDED.collider_count,
			collider_source_hash = EXCLUDED.collider_source_hash,
			collider_parser_version = EXCLUDED.collider_parser_version
	`, libraryID, SourceSystem, manifest.ManifestSHA256, result.ConnectorCount, status, string(metadata), createdBy,
		result.PreviewReady, result.RelationReady, nullableHash(result.ConnectorHash), StudioConnectivityParserVersion,
		result.ColliderCount, nullableHash(result.ColliderHash), StudioColliderParserVersion); err != nil {
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
		CREATE TEMP TABLE studio_import_connectors (
			source_connector_id bigint NOT NULL,
			ldraw_part_num text NOT NULL,
			connector_kind text NOT NULL,
			normalized_connector_type text,
			connector_group text,
			connector_gender text,
			position double precision[] NOT NULL,
			orientation double precision[] NOT NULL,
			direction double precision[] NOT NULL,
			radius double precision,
			length double precision,
			caps text,
			center_flag boolean NOT NULL,
			slide_flag boolean NOT NULL,
			raw_params jsonb NOT NULL
		) ON COMMIT DROP;
		CREATE TEMP TABLE studio_import_colliders (
			source_collider_id bigint NOT NULL,
			ldraw_part_num text NOT NULL,
			collider_kind text NOT NULL,
			position double precision[] NOT NULL,
			orientation double precision[] NOT NULL,
			half_extents double precision[] NOT NULL,
			raw_params jsonb NOT NULL
		) ON COMMIT DROP;
	`); err != nil {
		return fmt.Errorf("create temp import tables: %w", err)
	}
	partCopyRows := make([][]any, 0, len(rows))
	geometryCopyRows := make([][]any, 0, len(rows))
	connectorCopyRows := make([][]any, 0)
	colliderCopyRows := make([][]any, 0)
	for _, row := range rows {
		g := row.Geometry
		partCopyRows = append(partCopyRows, []any{row.LDrawPartNum, row.SourceName, string(row.Metadata)})
		geometryCopyRows = append(geometryCopyRows, []any{
			row.LDrawPartNum, g.SourceRelativePath, g.SourceSHA256,
			floatArray(g.BBoxMin), floatArray(g.BBoxMax),
			nullableFloat(g.LogicalWidthStud), nullableFloat(g.LogicalDepthStud), nullableFloat(g.LogicalHeightPlate),
			g.VertexCount, g.FaceCount, g.Status, nullableText(g.ErrorCode), nullableJSON(g.ErrorParams), g.DerivationStatus,
		})
		for _, connector := range row.Connectors {
			definition := connector.Definition
			connectorCopyRows = append(connectorCopyRows, []any{
				connector.SourceID, row.LDrawPartNum, definition.ConnectorKind,
				nullableString(definition.NormalizedConnectorType), nullableString(definition.ConnectorGroup), nullableString(definition.ConnectorGender),
				floatArray(definition.Position), floatArray9(definition.Orientation), floatArray(definition.Direction),
				nullableFloat(definition.Radius), nullableFloat(definition.Length), capsText(definition.Caps),
				definition.CenterFlag, definition.SlideFlag, string(connector.RawParams),
			})
		}
		for _, collider := range row.Colliders {
			definition := collider.Definition
			colliderCopyRows = append(colliderCopyRows, []any{
				collider.SourceID, row.LDrawPartNum, definition.ColliderKind,
				floatArray(definition.Position), floatArray9(definition.Orientation), floatArray(definition.HalfExtents), string(collider.RawParams),
			})
		}
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
	if len(connectorCopyRows) > 0 {
		if _, err := tx.CopyFrom(ctx, pgx.Identifier{"studio_import_connectors"}, []string{
			"source_connector_id", "ldraw_part_num", "connector_kind", "normalized_connector_type",
			"connector_group", "connector_gender", "position", "orientation", "direction",
			"radius", "length", "caps", "center_flag", "slide_flag", "raw_params",
		}, pgx.CopyFromRows(connectorCopyRows)); err != nil {
			return fmt.Errorf("copy import connectors: %w", err)
		}
	}
	if len(colliderCopyRows) > 0 {
		if _, err := tx.CopyFrom(ctx, pgx.Identifier{"studio_import_colliders"}, []string{
			"source_collider_id", "ldraw_part_num", "collider_kind", "position", "orientation", "half_extents", "raw_params",
		}, pgx.CopyFromRows(colliderCopyRows)); err != nil {
			return fmt.Errorf("copy import colliders: %w", err)
		}
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
	if _, err := tx.Exec(ctx, `DELETE FROM component_repo.part_connector_definitions WHERE part_library_version_id = $1::uuid`, libraryID); err != nil {
		return fmt.Errorf("delete previous Studio connector definitions: %w", err)
	}
	if _, err := tx.Exec(ctx, `
		INSERT INTO component_repo.part_connector_definitions (
			part_library_version_id, source_connector_id, ldraw_part_num,
			connector_kind, normalized_connector_type, connector_group, connector_gender,
			position, orientation, direction, radius, length, caps,
			center_flag, slide_flag, confidence, raw_params
		)
		SELECT $1::uuid, source_connector_id, ldraw_part_num,
		       connector_kind, normalized_connector_type, connector_group, connector_gender,
		       position, orientation, direction, radius, length, caps,
		       center_flag, slide_flag, 1.0, raw_params
		FROM studio_import_connectors
	`, libraryID); err != nil {
		return fmt.Errorf("insert Studio connector definitions: %w", err)
	}
	if _, err := tx.Exec(ctx, `DELETE FROM component_repo.part_collider_definitions WHERE part_library_version_id = $1::uuid`, libraryID); err != nil {
		return fmt.Errorf("delete previous Studio collider definitions: %w", err)
	}
	if _, err := tx.Exec(ctx, `
		INSERT INTO component_repo.part_collider_definitions (
			part_library_version_id, source_collider_id, ldraw_part_num,
			collider_kind, position, orientation, half_extents, raw_params
		)
		SELECT $1::uuid, source_collider_id, ldraw_part_num,
		       collider_kind, position, orientation, half_extents, raw_params
		FROM studio_import_colliders
	`, libraryID); err != nil {
		return fmt.Errorf("insert Studio collider definitions: %w", err)
	}
	return nil
}

type studioSidecarImport struct {
	connectors        map[string][]importConnectorRow
	colliders         map[string][]importColliderRow
	connectorFiles    int
	connectorCount    int
	connectorHash     string
	connectorFailures []SidecarFailure
	colliderFiles     int
	colliderCount     int
	colliderStored    int
	colliderHash      string
	colliderFailures  []SidecarFailure
	relationReady     bool
}

func importStudioSidecars(ldrawRoot string, manifest Manifest, parts []TopLevelPart, partial, storeColliderRows bool) studioSidecarImport {
	result := studioSidecarImport{
		connectors: map[string][]importConnectorRow{},
		colliders:  map[string][]importColliderRow{},
	}
	files := map[string]FileEntry{}
	for _, entry := range manifest.Files {
		files[strings.ToLower(filepath.ToSlash(entry.RelativePath))] = entry
	}
	connectorEntries := []FileEntry{}
	colliderEntries := []FileEntry{}
	for _, part := range parts {
		base := strings.TrimSuffix(strings.ToLower(part.LDrawPartNum), ".dat")
		connectorPath := "connectivity/" + base + ".conn"
		if entry, ok := files[connectorPath]; ok {
			result.connectorFiles++
			connectorEntries = append(connectorEntries, entry)
			data, err := readVerifiedManifestFile(ldrawRoot, entry)
			if err == nil {
				var definitions []StudioConnectorDefinition
				definitions, err = ParseStudioConnectivity(data)
				if err == nil {
					rows := make([]importConnectorRow, 0, len(definitions))
					for _, definition := range definitions {
						sourceID := deterministicSourceID("connector", part.LDrawPartNum, definition.SourceRecord, definition.SourceCell)
						rows = append(rows, importConnectorRow{
							SourceID: sourceID, Definition: definition,
							RawParams: mustMarshalJSON(map[string]any{
								"sourceGroup": definition.SourceGroup, "sourceSubtype": definition.SourceSubtype,
								"sourceRecord": definition.SourceRecord, "sourceCell": definition.SourceCell,
								"matrixItemType": definition.MatrixItemType, "matrixGridType": definition.MatrixGridType,
							}),
						})
					}
					result.connectors[part.LDrawPartNum] = rows
					result.connectorCount += len(rows)
				}
			}
			if err != nil {
				result.connectorFailures = append(result.connectorFailures, SidecarFailure{LDrawPartNum: part.LDrawPartNum, SourcePath: entry.RelativePath, FileKind: "connectivity", Error: err.Error()})
			}
		}

		colliderPath := "collider/" + base + ".col"
		if entry, ok := files[colliderPath]; ok {
			result.colliderFiles++
			colliderEntries = append(colliderEntries, entry)
			data, err := readVerifiedManifestFile(ldrawRoot, entry)
			if err == nil {
				var definitions []StudioColliderDefinition
				definitions, err = ParseStudioColliders(data)
				if err == nil {
					rows := make([]importColliderRow, 0, len(definitions))
					if storeColliderRows {
						for _, definition := range definitions {
							sourceID := deterministicSourceID("collider", part.LDrawPartNum, definition.SourceLine, definition.SourceID)
							rows = append(rows, importColliderRow{
								SourceID: sourceID, Definition: definition,
								RawParams: mustMarshalJSON(map[string]any{
									"sourceSystem": SourceSystem, "sourcePath": entry.RelativePath,
									"sourceFileHash": entry.SHA256, "parserVersion": StudioColliderParserVersion,
									"sourceLine": definition.SourceLine, "sourceType": definition.SourceType,
									"sourceId": definition.SourceID, "sourceHalfExtents": definition.SourceHalfExtents,
								}),
							})
						}
					}
					result.colliders[part.LDrawPartNum] = rows
					result.colliderCount += len(definitions)
					result.colliderStored += len(rows)
				}
			}
			if err != nil {
				result.colliderFailures = append(result.colliderFailures, SidecarFailure{LDrawPartNum: part.LDrawPartNum, SourcePath: entry.RelativePath, FileKind: "collider", Error: err.Error()})
			}
		}
	}
	result.connectorHash = sidecarDigest(connectorEntries)
	result.colliderHash = sidecarDigest(colliderEntries)
	result.relationReady = !partial && result.connectorFiles > 0 && result.connectorCount > 0 &&
		result.colliderFiles > 0 && result.colliderCount > 0 &&
		len(result.connectorFailures) == 0 && len(result.colliderFailures) == 0
	return result
}

func (result studioSidecarImport) failureSample() []SidecarFailure {
	failures := append([]SidecarFailure{}, result.connectorFailures...)
	failures = append(failures, result.colliderFailures...)
	if len(failures) > 25 {
		failures = failures[:25]
	}
	return failures
}

func readVerifiedManifestFile(root string, entry FileEntry) ([]byte, error) {
	data, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(entry.RelativePath)))
	if err != nil {
		return nil, err
	}
	if int64(len(data)) != entry.SizeBytes {
		return nil, fmt.Errorf("size mismatch: got %d want %d", len(data), entry.SizeBytes)
	}
	sum := sha256.Sum256(data)
	if hex.EncodeToString(sum[:]) != entry.SHA256 {
		return nil, errors.New("sha256 mismatch")
	}
	return data, nil
}

func sidecarDigest(entries []FileEntry) string {
	sort.Slice(entries, func(i, j int) bool { return entries[i].RelativePath < entries[j].RelativePath })
	digest := sha256.New()
	for _, entry := range entries {
		for _, value := range []string{entry.RelativePath, entry.SHA256, fmt.Sprintf("%d", entry.SizeBytes)} {
			encoded := []byte(value)
			fmt.Fprintf(digest, "%d:", len(encoded))
			digest.Write(encoded)
		}
	}
	return hex.EncodeToString(digest.Sum(nil))
}

func deterministicSourceID(kind, part string, primary, secondary int) int64 {
	sum := sha256.Sum256([]byte(fmt.Sprintf("%s:%s:%d:%d", kind, part, primary, secondary)))
	value := binary.BigEndian.Uint64(sum[:8]) & uint64(^uint64(0)>>1)
	if value == 0 {
		value = 1
	}
	return int64(value)
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

func floatArray9(values [9]float64) []float64 {
	return []float64{values[0], values[1], values[2], values[3], values[4], values[5], values[6], values[7], values[8]}
}

func nullableString(value string) *string {
	if value == "" {
		return nil
	}
	return &value
}

func nullableHash(value string) *string {
	if value == "" || value == strings.Repeat("0", 64) {
		return nil
	}
	return &value
}

func capsText(values []bool) *string {
	if len(values) == 0 {
		return nil
	}
	encoded := string(mustMarshalJSON(values))
	return &encoded
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
