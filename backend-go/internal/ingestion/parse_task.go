package ingestion

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"path"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/storage"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/workbench"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

const importFailureCode = "component_repo.import_parse_failed"

var (
	importParseNamespace = mustParseUUID("f45f8cb9-337a-4d70-89e4-5020bdd0d9e5")
	errImportLeaseLost   = errors.New("component import parse lease lost")
)

type ImportParseTaskHandler struct {
	pool   *pgxpool.Pool
	store  storage.Store
	config config.ImportConfig
}

type importParsePayload struct {
	ImportID       string `json:"importId"`
	ParserVersion  string `json:"parserVersion"`
	SnapshotSchema string `json:"snapshotSchema"`
}

type importParseResult struct {
	ImportID        string `json:"importId"`
	CandidateID     string `json:"candidateId"`
	ComponentID     string `json:"componentId"`
	DraftVersionID  string `json:"draftVersionId"`
	SceneSnapshotID string `json:"sceneSnapshotId"`
}

type derivedExchange struct {
	ID               pgtype.UUID
	OriginalFilename string
	StorageKey       string
	SHA256           string
	FileSize         int64
}

func NewImportParseTaskHandler(pool *pgxpool.Pool, store storage.Store, cfg config.ImportConfig) *ImportParseTaskHandler {
	return &ImportParseTaskHandler{pool: pool, store: store, config: cfg}
}

func (h *ImportParseTaskHandler) Handle(ctx context.Context, claimed task.ClaimedTask) (task.Result, error) {
	payload, err := decodeImportParsePayload(claimed.Payload)
	if err != nil {
		return task.Result{}, parseFailure("")
	}
	if payload.ParserVersion != h.config.ParserVersion || payload.SnapshotSchema != h.config.SnapshotSchema {
		return task.Result{}, parseFailure(payload.ImportID)
	}
	importID, err := uuidutil.Parse(payload.ImportID)
	if err != nil {
		return task.Result{}, parseFailure(payload.ImportID)
	}
	q := db.New(h.pool)
	input, err := q.GetImportParseInput(ctx, db.GetImportParseInputParams{
		ImportID: importID, OwnerID: claimed.OwnerID, ParseTaskID: claimed.ID,
	})
	if errors.Is(err, pgx.ErrNoRows) {
		return task.Result{}, parseFailure(payload.ImportID)
	}
	if err != nil {
		return task.Result{}, internalFailure()
	}
	if existing, ok, err := h.existingResult(ctx, q, input.ID, input.OwnerID); err != nil {
		return task.Result{}, internalFailure()
	} else if ok {
		if err := h.ensureExistingPreview(ctx, input.OwnerID, input.ParseTaskID, existing.DraftVersionID); err != nil {
			return task.Result{}, internalFailure()
		}
		return resultPayload(existing)
	}
	if !validImportParseInput(input, claimed, payload) {
		return task.Result{}, parseFailure(payload.ImportID)
	}
	content, err := h.readStorageObject(ctx, input.ParseStorageKey)
	if err != nil {
		return task.Result{}, storageFailure(payload.ImportID)
	}
	if sha256Hex(content) != input.ParseSha256 {
		return task.Result{}, &task.Failure{
			Code:      "component_repo.hash_mismatch",
			Params:    map[string]any{"artifactId": uuidutil.String(input.ParseArtifactID)},
			Retryable: false,
		}
	}
	materialized, err := materializeImport(content, input.ParseArtifactType, input.ParseFilename, h.config.ParserVersion)
	if err != nil {
		return task.Result{}, parseFailure(payload.ImportID)
	}
	var derived *derivedExchange
	if len(materialized.ExchangeBytes) > 0 {
		derived, err = h.storeDerivedExchange(ctx, input, materialized)
		if err != nil {
			return task.Result{}, storageFailure(payload.ImportID)
		}
	}
	committed, err := h.commitSuccess(ctx, payload, input, materialized, derived)
	if errors.Is(err, errImportLeaseLost) {
		return task.Result{}, internalFailure()
	}
	if err != nil {
		return task.Result{}, internalFailure()
	}
	return resultPayload(committed)
}

func decodeImportParsePayload(raw json.RawMessage) (importParsePayload, error) {
	var object map[string]json.RawMessage
	if err := json.Unmarshal(raw, &object); err != nil || len(object) != 3 {
		return importParsePayload{}, errors.New("invalid parse payload")
	}
	for _, key := range []string{"importId", "parserVersion", "snapshotSchema"} {
		if _, ok := object[key]; !ok {
			return importParsePayload{}, errors.New("invalid parse payload")
		}
	}
	var payload importParsePayload
	if err := json.Unmarshal(raw, &payload); err != nil {
		return importParsePayload{}, err
	}
	if payload.ImportID == "" || payload.ParserVersion == "" || payload.SnapshotSchema == "" {
		return importParsePayload{}, errors.New("invalid parse payload")
	}
	return payload, nil
}

func validImportParseInput(row db.GetImportParseInputRow, claimed task.ClaimedTask, payload importParsePayload) bool {
	return row.Status == task.StatusRunning &&
		row.ParserVersion != nil &&
		*row.ParserVersion == payload.ParserVersion &&
		row.Locale == claimed.Locale &&
		row.Timezone == claimed.Timezone &&
		row.SourceVerificationStatus == "verified" &&
		row.SourceImmutable &&
		!row.SourceDeletedAt.Valid &&
		row.ParseVerificationStatus == "verified" &&
		!row.ParseDeletedAt.Valid
}

func (h *ImportParseTaskHandler) readStorageObject(ctx context.Context, key string) ([]byte, error) {
	body, err := h.store.Open(ctx, key)
	if err != nil {
		return nil, err
	}
	defer body.Close()
	return io.ReadAll(body)
}

func (h *ImportParseTaskHandler) storeDerivedExchange(ctx context.Context, row db.GetImportParseInputRow, materialized materializedImport) (*derivedExchange, error) {
	artifactID := uuidutil.NameSHA1(importParseNamespace, uuidutil.String(row.ID)+":studio-exchange")
	sourceDirectory := path.Dir(row.SourceStorageKey)
	if sourceDirectory == "." {
		sourceDirectory = ""
	}
	storageKey := "derived/" + uuidutil.String(artifactID) + ".ldr"
	if sourceDirectory != "" {
		storageKey = sourceDirectory + "/" + storageKey
	}
	if err := h.store.Put(ctx, storageKey, "text/plain", bytes.NewReader(materialized.ExchangeBytes), int64(len(materialized.ExchangeBytes))); err != nil {
		metadata, headErr := h.store.Head(ctx, storageKey)
		if headErr != nil || metadata.Size != int64(len(materialized.ExchangeBytes)) {
			return nil, err
		}
	}
	return &derivedExchange{
		ID: artifactID, OriginalFilename: materialized.ExchangeFilename,
		StorageKey: storageKey, SHA256: sha256Hex(materialized.ExchangeBytes),
		FileSize: int64(len(materialized.ExchangeBytes)),
	}, nil
}

func (h *ImportParseTaskHandler) existingResult(ctx context.Context, q *db.Queries, importID, ownerID pgtype.UUID) (importParseResult, bool, error) {
	row, err := q.GetExistingCandidateVersionForImport(ctx, db.GetExistingCandidateVersionForImportParams{ImportID: importID, OwnerID: ownerID})
	if errors.Is(err, pgx.ErrNoRows) {
		return importParseResult{}, false, nil
	}
	if err != nil {
		return importParseResult{}, false, err
	}
	return importParseResult{
		ImportID: uuidutil.String(importID), CandidateID: uuidutil.String(row.CandidateID),
		ComponentID: uuidutil.String(row.ComponentID), DraftVersionID: uuidutil.String(row.VersionID),
		SceneSnapshotID: uuidutil.String(row.SceneSnapshotID),
	}, true, nil
}

func (h *ImportParseTaskHandler) commitSuccess(
	ctx context.Context,
	payload importParsePayload,
	input db.GetImportParseInputRow,
	materialized materializedImport,
	derived *derivedExchange,
) (importParseResult, error) {
	tx, err := h.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return importParseResult{}, err
	}
	defer tx.Rollback(ctx)
	q := db.New(tx)
	currentImport, err := q.LockImportForParse(ctx, input.ID)
	if err != nil {
		return importParseResult{}, err
	}
	if existing, ok, err := h.existingResult(ctx, q, input.ID, input.OwnerID); err != nil {
		return importParseResult{}, err
	} else if ok {
		if currentImport.Status != task.StatusSucceeded {
			return importParseResult{}, errImportLeaseLost
		}
		versionID, err := uuidutil.Parse(existing.DraftVersionID)
		if err != nil {
			return importParseResult{}, err
		}
		if _, err := workbench.EnsureInitialPreviewWithQueries(
			ctx, q, currentImport.OwnerID, versionID, currentImport.ParseTaskID,
		); err != nil {
			return importParseResult{}, err
		}
		if err := tx.Commit(ctx); err != nil {
			return importParseResult{}, err
		}
		return existing, nil
	}
	if currentImport.Status != task.StatusRunning {
		return importParseResult{}, errImportLeaseLost
	}

	importIDText := uuidutil.String(input.ID)
	snapshotID := uuidutil.NameSHA1(importParseNamespace, importIDText+":snapshot")
	candidateID := uuidutil.NameSHA1(importParseNamespace, importIDText+":candidate")
	componentID := currentImport.TargetComponentID
	if !componentID.Valid {
		componentID = uuidutil.NameSHA1(importParseNamespace, importIDText+":component")
	}
	versionID := uuidutil.NameSHA1(importParseNamespace, importIDText+":draft-version")
	exchangeArtifactID := currentImport.ExchangeArtifactID
	if derived != nil {
		metadata := mustJSON(map[string]any{"derivedBy": task.ImportParseType, "parserVersion": valueOrEmpty(currentImport.ParserVersion)})
		if err := q.CreateDerivedExchangeArtifact(ctx, db.CreateDerivedExchangeArtifactParams{
			ID: derived.ID, OwnerID: currentImport.OwnerID, OriginalFilename: derived.OriginalFilename,
			StorageProvider: input.SourceStorageProvider, StorageBucket: input.SourceStorageBucket,
			StorageKey: derived.StorageKey, Sha256: derived.SHA256, FileSize: derived.FileSize,
			UploadedBy: currentImport.CreatedBy, Metadata: metadata, DerivedFromArtifactID: currentImport.SourceArtifactID,
		}); err != nil {
			return importParseResult{}, err
		}
		exchangeArtifactID = derived.ID
	}
	if !currentImport.TargetComponentID.Valid {
		componentName := stem(input.SourceFilename)
		if err := q.CreateImportComponentForParse(ctx, db.CreateImportComponentForParseParams{
			ID: componentID, OwnerID: currentImport.OwnerID, ContentLocale: currentImport.Locale,
			Name: componentName, CreatedBy: currentImport.CreatedBy,
		}); err != nil {
			return importParseResult{}, err
		}
	}
	updated, err := q.MarkImportParseSucceeded(ctx, db.MarkImportParseSucceededParams{
		TargetComponentID: componentID, ExchangeArtifactID: exchangeArtifactID, ImportID: currentImport.ID,
	})
	if err != nil {
		return importParseResult{}, err
	}
	if updated != 1 {
		return importParseResult{}, errImportLeaseLost
	}
	rootModelID := materialized.RootModelID
	if err := q.CreateSceneSnapshotForParse(ctx, db.CreateSceneSnapshotForParseParams{
		ID: snapshotID, ImportID: currentImport.ID, SchemaVersion: payload.SnapshotSchema,
		ParserVersion: valueOrEmpty(currentImport.ParserVersion), RootModelID: rootModelID,
		Document: mustJSON(materialized.Document), Bom: mustJSON(materialized.BOM),
		ParseIssues: mustJSON(materialized.ParseIssues),
	}); err != nil {
		return importParseResult{}, err
	}
	decisions := map[string]any{"componentId": uuidutil.String(componentID), "draftVersionId": uuidutil.String(versionID)}
	if err := q.CreateCandidateForParse(ctx, db.CreateCandidateForParseParams{
		ID: candidateID, OwnerID: currentImport.OwnerID, ImportID: currentImport.ID,
		SceneSnapshotID: snapshotID, Summary: mustJSON(materialized.Summary),
		ReviewDecisions: mustJSON(decisions), InterfaceSignature: materialized.InterfaceSignature,
		StructureHash: materialized.StructureHash, GeometryHash: materialized.GeometryHash,
	}); err != nil {
		return importParseResult{}, err
	}
	versionLabel, revision, err := draftIdentity(ctx, q, currentImport, componentID)
	if err != nil {
		return importParseResult{}, err
	}
	versionMetadata := map[string]any{"summary": materialized.Summary, "baseVersionId": uuidutil.NullableString(currentImport.BaseVersionID)}
	if _, err := q.CreateComponentVersion(ctx, db.CreateComponentVersionParams{
		ID: versionID, ComponentID: componentID, ComponentCandidateID: candidateID,
		VersionLabel: versionLabel, Revision: revision, SourceArtifactID: currentImport.SourceArtifactID,
		ExchangeArtifactID: exchangeArtifactID, SceneSnapshotID: snapshotID,
		ParserVersion:        valueOrEmpty(currentImport.ParserVersion),
		PartLibraryVersionID: currentImport.PartLibraryVersionID,
		InterfaceSignature:   materialized.InterfaceSignature, StructureHash: materialized.StructureHash,
		GeometryHash: materialized.GeometryHash, Metadata: mustJSON(versionMetadata),
		CreatedBy: currentImport.CreatedBy,
	}); err != nil {
		return importParseResult{}, err
	}
	// 首次 GLB 生成属于 Worker 异步链路；在解析事务中持久化任务，避免 API 或前端补发。
	if _, err := workbench.EnsureInitialPreviewWithQueries(
		ctx, q, currentImport.OwnerID, versionID, currentImport.ParseTaskID,
	); err != nil {
		return importParseResult{}, err
	}
	result := importParseResult{
		ImportID: importIDText, CandidateID: uuidutil.String(candidateID),
		ComponentID: uuidutil.String(componentID), DraftVersionID: uuidutil.String(versionID),
		SceneSnapshotID: uuidutil.String(snapshotID),
	}
	if err := tx.Commit(ctx); err != nil {
		return importParseResult{}, err
	}
	return result, nil
}

// ensureExistingPreview 修复部署切换或 Worker 重领时已存在 Draft、但首个 Preview continuation 缺失的状态。
func (h *ImportParseTaskHandler) ensureExistingPreview(
	ctx context.Context,
	ownerID pgtype.UUID,
	parseTaskID pgtype.UUID,
	versionIDText string,
) error {
	versionID, err := uuidutil.Parse(versionIDText)
	if err != nil {
		return err
	}
	tx, err := h.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if _, err := workbench.EnsureInitialPreviewWithQueries(
		ctx, db.New(tx), ownerID, versionID, parseTaskID,
	); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

func draftIdentity(ctx context.Context, q *db.Queries, importRow db.ComponentRepoImport, componentID pgtype.UUID) (string, int32, error) {
	versionLabel := "0.1.0"
	if importRow.BaseVersionID.Valid {
		label, err := q.GetDraftVersionLabelForBase(ctx, db.GetDraftVersionLabelForBaseParams{
			BaseVersionID: importRow.BaseVersionID, ComponentID: componentID,
		})
		if err != nil {
			return "", 0, err
		}
		versionLabel = label
	}
	revision, err := q.GetNextComponentVersionRevision(ctx, db.GetNextComponentVersionRevisionParams{
		ComponentID: componentID, VersionLabel: versionLabel,
	})
	return versionLabel, int32(revision), err
}

func resultPayload(result importParseResult) (task.Result, error) {
	payload, err := json.Marshal(result)
	if err != nil {
		return task.Result{}, err
	}
	return task.Result{Payload: payload}, nil
}

func parseFailure(importID string) *task.Failure {
	params := map[string]any{}
	if importID != "" {
		params["importId"] = importID
	}
	return &task.Failure{Code: importFailureCode, Params: params, Retryable: false}
}

func storageFailure(importID string) *task.Failure {
	return &task.Failure{Code: "component_repo.storage_unavailable", Params: map[string]any{"importId": importID}, Retryable: true}
}

func internalFailure() *task.Failure {
	return &task.Failure{Code: "common.internal_error", Params: map[string]any{}, Retryable: true}
}

func sha256Hex(content []byte) string {
	digest := sha256.Sum256(content)
	return hex.EncodeToString(digest[:])
}

func mustJSON(value any) []byte {
	encoded, err := json.Marshal(value)
	if err != nil {
		panic(fmt.Sprintf("marshal import parse JSON: %v", err))
	}
	return encoded
}

func valueOrEmpty(value *string) string {
	if value == nil {
		return ""
	}
	return *value
}

func mustParseUUID(value string) pgtype.UUID {
	id, err := uuidutil.Parse(value)
	if err != nil {
		panic(err)
	}
	return id
}
