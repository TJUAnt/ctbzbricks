package ingestion

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"time"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Service struct {
	q *db.Queries
}

func NewService(pool *pgxpool.Pool) *Service {
	return &Service{q: db.New(pool)}
}

func (s *Service) GetImport(ctx context.Context, actor pgtype.UUID, importID string) (Import, error) {
	id, err := uuidutil.Parse(importID)
	if err != nil {
		return Import{}, validationError("importId")
	}
	row, err := s.q.GetOwnedImport(ctx, db.GetOwnedImportParams{ImportID: id, ActorID: actor})
	if errors.Is(err, pgx.ErrNoRows) {
		return Import{}, apierror.New("component_repo.import_not_found", http.StatusNotFound, map[string]any{"importId": importID})
	}
	if err != nil {
		return Import{}, err
	}
	return importFromDB(row), nil
}

// ListImports 返回当前用户的持久化导入历史；可选 ComponentID 同时匹配更新目标和导入后生成的组件。
func (s *Service) ListImports(ctx context.Context, actor pgtype.UUID, request ImportListRequest) (ImportPage, error) {
	request = normalizeImportListRequest(request)
	query := strings.TrimSpace(request.Query)
	if len(query) > 200 {
		return ImportPage{}, validationError("query")
	}
	if request.ProcessingStatus != "" && request.ProcessingStatus != "processing" &&
		request.ProcessingStatus != "ready" && request.ProcessingStatus != "failed" {
		return ImportPage{}, validationError("processingStatus")
	}
	var componentID pgtype.UUID
	if request.ComponentID != "" {
		parsed, err := uuidutil.Parse(request.ComponentID)
		if err != nil {
			return ImportPage{}, validationError("componentId")
		}
		componentID = parsed
	}
	rows, err := s.q.ListOwnedImports(ctx, db.ListOwnedImportsParams{
		ActorID: actor, ComponentID: componentID, ProcessingStatus: request.ProcessingStatus,
		SearchQuery: query, PageOffset: int32((request.Page - 1) * request.PageSize),
		PageSize: int32(request.PageSize),
	})
	if err != nil {
		return ImportPage{}, err
	}
	items := make([]ImportRecord, 0, len(rows))
	for _, row := range rows {
		items = append(items, importRecordFromDB(row))
	}
	counts, err := s.q.CountOwnedImportProcessingStatuses(ctx, db.CountOwnedImportProcessingStatusesParams{
		ActorID: actor, ComponentID: componentID, SearchQuery: query,
	})
	if err != nil {
		return ImportPage{}, err
	}
	statusCounts := map[string]int64{"processing": 0, "ready": 0, "failed": 0}
	for _, count := range counts {
		statusCounts[count.ProcessingStatus] = count.ImportCount
	}
	var total int64
	if request.ProcessingStatus == "" {
		for _, count := range statusCounts {
			total += count
		}
	} else {
		total = statusCounts[request.ProcessingStatus]
	}
	totalPages := 0
	if total > 0 {
		totalPages = int((total + int64(request.PageSize) - 1) / int64(request.PageSize))
	}
	return ImportPage{
		Items: items, Total: total, Page: request.Page, PageSize: request.PageSize,
		TotalPages: totalPages, StatusCounts: statusCounts,
	}, nil
}

func (s *Service) GetCandidate(ctx context.Context, actor pgtype.UUID, candidateID string) (Candidate, error) {
	id, err := uuidutil.Parse(candidateID)
	if err != nil {
		return Candidate{}, validationError("candidateId")
	}
	row, err := s.q.GetOwnedCandidate(ctx, db.GetOwnedCandidateParams{CandidateID: id, ActorID: actor})
	if errors.Is(err, pgx.ErrNoRows) {
		return Candidate{}, apierror.New("component_repo.candidate_id_not_found", http.StatusNotFound, map[string]any{"candidateId": candidateID})
	}
	if err != nil {
		return Candidate{}, err
	}
	return candidateFromDB(row), nil
}

func importFromDB(row db.GetOwnedImportRow) Import {
	var failure *Failure
	if row.FailureCode != nil {
		failure = &Failure{Code: *row.FailureCode, Params: objectJSON(row.FailureParams)}
	} else if row.PreviewFailureCode != nil {
		failure = &Failure{Code: *row.PreviewFailureCode, Params: objectJSON(row.PreviewFailureParams)}
	} else if row.PreviewTaskErrorCode != nil {
		failure = &Failure{Code: *row.PreviewTaskErrorCode, Params: objectJSON(row.PreviewTaskErrorParams)}
	}
	return Import{
		ID: uuidutil.String(row.ID), SourceArtifactID: uuidutil.String(row.SourceArtifactID),
		ExchangeArtifactID: optionalUUID(row.ExchangeArtifactID), TargetComponentID: optionalUUID(row.TargetComponentID),
		BaseVersionID: optionalUUID(row.BaseVersionID), Status: row.Status,
		ParserVersion: stringValue(row.ParserVersion), PartLibraryVersionID: optionalUUID(row.PartLibraryVersionID),
		TaskID: uuidutil.String(row.ParseTaskID), CandidateID: optionalUUID(row.CandidateID),
		DraftVersionID: optionalUUID(row.DraftVersionID), ProcessingStatus: importProcessingStatus(row),
		PreviewTaskID: optionalUUID(row.PreviewTaskID), Locale: row.Locale, Timezone: row.Timezone,
		Failure: failure, Metadata: objectJSON(row.Metadata), CreatedAt: row.CreatedAt.Time,
		StartedAt: optionalTime(row.StartedAt), CompletedAt: optionalTime(row.CompletedAt),
	}
}

func importRecordFromDB(row db.ListOwnedImportsRow) ImportRecord {
	var failure *Failure
	if row.FailureCode != nil {
		failure = &Failure{Code: *row.FailureCode, Params: objectJSON(row.FailureParams)}
	} else if row.PreviewFailureCode != nil {
		failure = &Failure{Code: *row.PreviewFailureCode, Params: objectJSON(row.PreviewFailureParams)}
	} else if row.PreviewTaskErrorCode != nil {
		failure = &Failure{Code: *row.PreviewTaskErrorCode, Params: objectJSON(row.PreviewTaskErrorParams)}
	}
	componentID := optionalUUID(row.ComponentID)
	if componentID == nil {
		componentID = optionalUUID(row.TargetComponentID)
	}
	importKind := "create"
	if row.TargetComponentID.Valid {
		importKind = "update"
	}
	return ImportRecord{
		ID: uuidutil.String(row.ID), SourceArtifactID: uuidutil.String(row.SourceArtifactID),
		OriginalFilename: row.OriginalFilename, FileSize: row.FileSize, MimeType: row.MimeType,
		ImportKind: importKind, TargetComponentID: optionalUUID(row.TargetComponentID),
		ComponentID: componentID, BaseVersionID: optionalUUID(row.BaseVersionID), Status: row.Status,
		ProcessingStatus: row.ProcessingStatus, ParserVersion: stringValue(row.ParserVersion),
		PartLibraryVersionID: optionalUUID(row.PartLibraryVersionID), TaskID: uuidutil.String(row.ParseTaskID),
		CandidateID: optionalUUID(row.CandidateID), DraftVersionID: optionalUUID(row.DraftVersionID),
		PreviewTaskID: optionalUUID(row.PreviewTaskID), Failure: failure, CreatedAt: row.CreatedAt.Time,
		StartedAt: optionalTime(row.StartedAt), CompletedAt: optionalTime(row.CompletedAt),
	}
}

// importProcessingStatus 汇总解析、BOM 和 GLB 制品状态；只有全部持久化且预览制品已验证时才对前端声明 ready。
func importProcessingStatus(row db.GetOwnedImportRow) string {
	if row.Status == "failed" || row.Status == "cancelled" ||
		row.PreviewStatus == "failed" ||
		stringValue(row.PreviewTaskStatus) == "failed" || stringValue(row.PreviewTaskStatus) == "cancelled" {
		return "failed"
	}
	if row.Status == "succeeded" && row.CandidateID.Valid && row.DraftVersionID.Valid &&
		row.SceneSnapshotID.Valid && row.PreviewArtifactID.Valid &&
		row.PreviewStatus == "ready" &&
		stringValue(row.PreviewArtifactVerificationStatus) == "verified" {
		return "ready"
	}
	return "processing"
}

func candidateFromDB(row db.GetOwnedCandidateRow) Candidate {
	return Candidate{
		ID: uuidutil.String(row.ID), ImportID: uuidutil.String(row.ImportID), Status: row.Status,
		Summary: objectJSON(row.Summary), ReviewDecisions: objectJSON(row.ReviewDecisions),
		InterfaceSignature: row.InterfaceSignature, StructureHash: row.StructureHash,
		GeometryHash: row.GeometryHash, ComponentID: optionalUUID(row.ComponentID),
		DraftVersionID: optionalUUID(row.DraftVersionID), CreatedAt: row.CreatedAt.Time,
		UpdatedAt: row.UpdatedAt.Time,
		SceneSnapshot: SceneSnapshot{
			ID: uuidutil.String(row.SceneSnapshotID), SchemaVersion: row.SchemaVersion,
			ParserVersion: row.ParserVersion, RootModelID: row.RootModelID,
			Document: objectJSON(row.Document), BOM: objectJSON(row.Bom),
			ParseIssues: arrayJSON(row.ParseIssues), CreatedAt: row.SnapshotCreatedAt.Time,
		},
	}
}

func optionalUUID(value pgtype.UUID) *string {
	if !value.Valid {
		return nil
	}
	text := uuidutil.String(value)
	return &text
}

func optionalTime(value pgtype.Timestamptz) *time.Time {
	if !value.Valid {
		return nil
	}
	result := value.Time
	return &result
}

func objectJSON(value []byte) json.RawMessage {
	if len(value) == 0 {
		return json.RawMessage(`{}`)
	}
	return value
}

func arrayJSON(value []byte) json.RawMessage {
	if len(value) == 0 {
		return json.RawMessage(`[]`)
	}
	return value
}

func stringValue(value *string) string {
	if value == nil {
		return ""
	}
	return *value
}

func validationError(field string) *apierror.Error {
	return apierror.New("request.validation_failed", http.StatusUnprocessableEntity, map[string]any{"field": field})
}

func normalizeImportListRequest(request ImportListRequest) ImportListRequest {
	if request.Page < 1 {
		request.Page = 1
	}
	if request.PageSize < 1 {
		request.PageSize = 20
	}
	if request.PageSize > 100 {
		request.PageSize = 100
	}
	if request.Page > 1_000_000 {
		request.Page = 1_000_000
	}
	return request
}
