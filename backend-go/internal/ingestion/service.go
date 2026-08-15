package ingestion

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
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
	}
	return Import{
		ID: uuidutil.String(row.ID), SourceArtifactID: uuidutil.String(row.SourceArtifactID),
		ExchangeArtifactID: optionalUUID(row.ExchangeArtifactID), TargetComponentID: optionalUUID(row.TargetComponentID),
		BaseVersionID: optionalUUID(row.BaseVersionID), Status: row.Status,
		ParserVersion: stringValue(row.ParserVersion), PartLibraryVersionID: optionalUUID(row.PartLibraryVersionID),
		TaskID: uuidutil.String(row.ParseTaskID), CandidateID: optionalUUID(row.CandidateID),
		DraftVersionID: optionalUUID(row.DraftVersionID), Locale: row.Locale, Timezone: row.Timezone,
		Failure: failure, Metadata: objectJSON(row.Metadata), CreatedAt: row.CreatedAt.Time,
		StartedAt: optionalTime(row.StartedAt), CompletedAt: optionalTime(row.CompletedAt),
	}
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
