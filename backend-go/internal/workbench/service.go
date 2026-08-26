package workbench

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/storage"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Service struct {
	pool         *pgxpool.Pool
	q            *db.Queries
	store        storage.Store
	signedURLTTL time.Duration
}

func NewService(pool *pgxpool.Pool, store storage.Store, signedURLTTL time.Duration) *Service {
	return &Service{pool: pool, q: db.New(pool), store: store, signedURLTTL: signedURLTTL}
}

func (s *Service) DetectRelations(ctx context.Context, actor pgtype.UUID, candidateID string) (AcceptedTask, error) {
	id, err := parseID(candidateID, "candidateId")
	if err != nil {
		return AcceptedTask{}, err
	}
	return txValue(ctx, s.pool, func(q *db.Queries) (AcceptedTask, error) {
		candidate, err := q.GetOwnedCandidateWorkbench(ctx, db.GetOwnedCandidateWorkbenchParams{CandidateID: id, ActorID: actor})
		if errors.Is(err, pgx.ErrNoRows) {
			return AcceptedTask{}, notFound("component_repo.candidate_id_not_found", "candidateId", candidateID)
		}
		if err != nil {
			return AcceptedTask{}, err
		}
		if !candidate.PartLibraryVersionID.Valid || candidate.DraftVersionStatus == nil || *candidate.DraftVersionStatus != "draft" ||
			candidate.PartLibraryRelationReady == nil || !*candidate.PartLibraryRelationReady ||
			candidate.ConnectorSourceHash == nil || candidate.ConnectorParserVersion == nil {
			return AcceptedTask{}, conflict("component_repo.relation_detect_failed", "candidateId", candidateID)
		}
		inputHash := relationInputHash(candidate.StructureHash, candidate.GeometryHash,
			candidate.SchemaVersion, candidate.SnapshotParserVersion, uuidutil.String(candidate.PartLibraryVersionID),
			valueOrEmpty(candidate.PartLibrarySourceHash), *candidate.ConnectorSourceHash,
			*candidate.ConnectorParserVersion, RelationDetectionVersion)
		payload := mustJSON(map[string]any{"candidateId": candidateID, "detectionVersion": RelationDetectionVersion, "partLibraryVersionId": uuidutil.String(candidate.PartLibraryVersionID), "inputHash": inputHash})
		scheduled, err := task.ScheduleWithQueries(ctx, q, task.ScheduleInput{
			OwnerID: actor, TaskType: RelationDetectionType, Payload: payload,
			Locale: candidate.Locale, Timezone: candidate.Timezone, CreatedBy: actor,
			LogicalKey: candidateID, InputHash: inputHash, MaxAttempts: 3,
		})
		if err != nil {
			return AcceptedTask{}, err
		}
		if err := q.SetCandidateRelationDetectionTask(ctx, db.SetCandidateRelationDetectionTaskParams{
			TaskID: scheduled.Task.ID, DetectionVersion: stringPointer(RelationDetectionVersion), CandidateID: id, ActorID: actor,
		}); err != nil {
			return AcceptedTask{}, err
		}
		return AcceptedTask{TaskID: uuidutil.String(scheduled.Task.ID), Status: scheduled.Task.Status}, nil
	})
}

func (s *Service) ListRelations(ctx context.Context, actor pgtype.UUID, candidateID string) ([]RelationCandidate, error) {
	id, err := s.ownedCandidate(ctx, actor, candidateID)
	if err != nil {
		return nil, err
	}
	rows, err := s.q.ListOwnedRelationCandidates(ctx, db.ListOwnedRelationCandidatesParams{CandidateID: id, ActorID: actor})
	if err != nil {
		return nil, err
	}
	items := make([]RelationCandidate, 0, len(rows))
	for _, row := range rows {
		confidence, _ := row.Confidence.Float64Value()
		items = append(items, RelationCandidate{
			ID: uuidutil.String(row.ID), ComponentCandidateID: uuidutil.String(row.ComponentCandidateID),
			PartLibraryVersionID: uuidutil.String(row.PartLibraryVersionID), EndpointA: object(row.EndpointA), EndpointB: object(row.EndpointB),
			ConnectionType: row.ConnectionType, JointType: row.JointType, PositionResidual: row.PositionResidual,
			RotationResidual: row.RotationResidual, VerifiedByTolerance: row.VerifiedByTolerance,
			Confidence: confidence.Float64, Status: row.Status, DetectionMethod: row.DetectionMethod,
			Metadata: object(row.Metadata), CreatedAt: row.CreatedAt.Time, UpdatedAt: row.UpdatedAt.Time,
		})
	}
	return items, nil
}

// GetValidationReport 按 Version 可见性读取报告：Draft 仅 owner，公开发布版本允许可见用户读取质量标识。
func (s *Service) GetValidationReport(ctx context.Context, actor pgtype.UUID, reportID string) (ValidationReport, error) {
	id, err := parseID(reportID, "reportId")
	if err != nil {
		return ValidationReport{}, err
	}
	row, err := s.q.GetVisibleValidationReport(ctx, db.GetVisibleValidationReportParams{ReportID: id, ActorID: actor})
	if errors.Is(err, pgx.ErrNoRows) {
		return ValidationReport{}, notFound("request.not_found", "reportId", reportID)
	}
	if err != nil {
		return ValidationReport{}, err
	}
	return ValidationReport{
		ID: uuidutil.String(row.ID), ComponentCandidateID: uuidutil.NullableString(row.ComponentCandidateID),
		ComponentVersionID: uuidutil.NullableString(row.ComponentVersionID), ValidationLevel: row.ValidationLevel,
		Passed: row.Passed, Checks: array(row.Checks), Issues: array(row.Issues),
		ValidatorVersion: row.ValidatorVersion, CreatedAt: row.CreatedAt.Time,
	}, nil
}

func (s *Service) ConfirmRelation(ctx context.Context, actor pgtype.UUID, candidateID, relationID string) (AssemblyRelation, error) {
	candidateUUID, err := parseID(candidateID, "candidateId")
	if err != nil {
		return AssemblyRelation{}, err
	}
	relationUUID, err := parseID(relationID, "relationId")
	if err != nil {
		return AssemblyRelation{}, err
	}
	return txValue(ctx, s.pool, func(q *db.Queries) (AssemblyRelation, error) {
		relation, err := q.LockOwnedRelationCandidate(ctx, db.LockOwnedRelationCandidateParams{RelationID: relationUUID, CandidateID: candidateUUID, ActorID: actor})
		if errors.Is(err, pgx.ErrNoRows) {
			return AssemblyRelation{}, notFound("component_repo.relation_confirm_failed", "relationId", relationID)
		}
		if err != nil {
			return AssemblyRelation{}, err
		}
		if relation.Status == "rejected" {
			return AssemblyRelation{}, conflict("component_repo.relation_confirm_failed", "relationId", relationID)
		}
		if existing, existingErr := q.GetAssemblyRelationBySource(ctx, relationUUID); existingErr == nil {
			return assemblyFromExisting(existing), nil
		} else if !errors.Is(existingErr, pgx.ErrNoRows) {
			return AssemblyRelation{}, existingErr
		}
		id, err := uuidutil.New()
		if err != nil {
			return AssemblyRelation{}, err
		}
		placement := mustJSON(map[string]any{"positionResidual": relation.PositionResidual, "rotationResidual": relation.RotationResidual, "verifiedByTolerance": relation.VerifiedByTolerance})
		created, err := q.CreateAssemblyRelation(ctx, db.CreateAssemblyRelationParams{
			ID: id, ComponentCandidateID: candidateUUID, OwnerID: actor, RelationCandidateID: relationUUID,
			EndpointA: relation.EndpointA, EndpointB: relation.EndpointB, ConnectionType: relation.ConnectionType,
			JointType: relation.JointType, Placement: placement, ConfirmedBy: actor,
		})
		if err != nil {
			return AssemblyRelation{}, mapRelationError(err)
		}
		connectorIDs, err := endpoints(relation.EndpointA, relation.EndpointB)
		if err != nil {
			return AssemblyRelation{}, err
		}
		if err := q.MarkConfirmedConnectorsInternal(ctx, db.MarkConfirmedConnectorsInternalParams{CandidateID: candidateUUID, ActorID: actor, WorldConnectorIds: connectorIDs}); err != nil {
			return AssemblyRelation{}, err
		}
		if err := q.DeleteConfirmedConnectorInterfaces(ctx, db.DeleteConfirmedConnectorInterfacesParams{CandidateID: candidateUUID, ActorID: actor, WorldConnectorIds: connectorIDs}); err != nil {
			return AssemblyRelation{}, err
		}
		if err := refreshInterfaceSignature(ctx, q, actor, candidateUUID); err != nil {
			return AssemblyRelation{}, err
		}
		return assemblyFromCreated(created), nil
	})
}

func (s *Service) RejectRelation(ctx context.Context, actor pgtype.UUID, candidateID, relationID string) (RelationCandidate, error) {
	candidateUUID, err := parseID(candidateID, "candidateId")
	if err != nil {
		return RelationCandidate{}, err
	}
	relationUUID, err := parseID(relationID, "relationId")
	if err != nil {
		return RelationCandidate{}, err
	}
	return txValue(ctx, s.pool, func(q *db.Queries) (RelationCandidate, error) {
		if _, err := q.LockOwnedRelationCandidate(ctx, db.LockOwnedRelationCandidateParams{RelationID: relationUUID, CandidateID: candidateUUID, ActorID: actor}); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return RelationCandidate{}, notFound("component_repo.relation_reject_failed", "relationId", relationID)
			}
			return RelationCandidate{}, err
		}
		row, err := q.RejectOwnedRelationCandidate(ctx, db.RejectOwnedRelationCandidateParams{RelationID: relationUUID, CandidateID: candidateUUID, ActorID: actor})
		if errors.Is(err, pgx.ErrNoRows) {
			return RelationCandidate{}, conflict("component_repo.confirmed_relation_cannot_be_rejected", "relationId", relationID)
		}
		if err != nil {
			return RelationCandidate{}, err
		}
		confidence, _ := row.Confidence.Float64Value()
		return RelationCandidate{ID: uuidutil.String(row.ID), ComponentCandidateID: uuidutil.String(row.ComponentCandidateID), PartLibraryVersionID: uuidutil.String(row.PartLibraryVersionID), EndpointA: object(row.EndpointA), EndpointB: object(row.EndpointB), ConnectionType: row.ConnectionType, JointType: row.JointType, PositionResidual: row.PositionResidual, RotationResidual: row.RotationResidual, VerifiedByTolerance: row.VerifiedByTolerance, Confidence: confidence.Float64, Status: row.Status, DetectionMethod: row.DetectionMethod, Metadata: object(row.Metadata), CreatedAt: row.CreatedAt.Time, UpdatedAt: row.UpdatedAt.Time}, nil
	})
}

func (s *Service) ListConnectors(ctx context.Context, actor pgtype.UUID, candidateID string) ([]Connector, error) {
	id, err := s.ownedCandidate(ctx, actor, candidateID)
	if err != nil {
		return nil, err
	}
	rows, err := s.q.ListOwnedCandidateConnectors(ctx, db.ListOwnedCandidateConnectorsParams{CandidateID: id, ActorID: actor})
	if err != nil {
		return nil, err
	}
	items := make([]Connector, 0, len(rows))
	for _, row := range rows {
		eligibility := mustJSON(map[string]bool{"unoccupied": row.EligibilityUnoccupied, "supportedType": row.EligibilitySupportedType, "outwardFacing": row.EligibilityOutwardFacing, "clearanceDataAvailable": row.EligibilityClearanceDataAvailable, "clearanceAvailable": row.EligibilityClearanceAvailable})
		items = append(items, Connector{ID: uuidutil.String(row.ID), WorldConnectorID: row.WorldConnectorID, PartInstanceID: row.PartInstanceID, PartRef: row.PartRef, ConnectorType: row.ConnectorType, ConnectorKind: row.ConnectorKind, ConnectorGender: row.ConnectorGender, State: row.State, Position: row.Position, Axis: row.Axis, Matrix: row.Matrix, AccessAxis: row.AccessAxis, ExternalInterfaceID: uuidutil.NullableString(row.ExternalInterfaceID), Capacity: row.Capacity, OccupiedSlots: row.OccupiedSlots, AvailableCapacity: max(0, row.Capacity-row.OccupiedSlots), Eligibility: eligibility})
	}
	return items, nil
}

func (s *Service) ListInterfaces(ctx context.Context, actor pgtype.UUID, candidateID string) ([]Interface, error) {
	id, err := s.ownedCandidate(ctx, actor, candidateID)
	if err != nil {
		return nil, err
	}
	rows, err := s.q.ListOwnedCandidateInterfaces(ctx, db.ListOwnedCandidateInterfacesParams{CandidateID: id, ActorID: actor})
	if err != nil {
		return nil, err
	}
	items := make([]Interface, 0, len(rows))
	for _, row := range rows {
		items = append(items, interfaceFromDB(row))
	}
	return items, nil
}

// Validate 为 Candidate 当前唯一版本调度可选异步质量验证；Draft 与 Published 均可验证，发布本身不依赖此任务。
func (s *Service) Validate(ctx context.Context, actor pgtype.UUID, candidateID string) (AcceptedTask, error) {
	id, err := parseID(candidateID, "candidateId")
	if err != nil {
		return AcceptedTask{}, err
	}
	return txValue(ctx, s.pool, func(q *db.Queries) (AcceptedTask, error) {
		candidate, err := q.GetOwnedCandidateWorkbench(ctx, db.GetOwnedCandidateWorkbenchParams{CandidateID: id, ActorID: actor})
		if errors.Is(err, pgx.ErrNoRows) {
			return AcceptedTask{}, notFound("component_repo.candidate_id_not_found", "candidateId", candidateID)
		}
		if err != nil {
			return AcceptedTask{}, err
		}
		if !candidate.DraftVersionID.Valid || candidate.DraftVersionStatus == nil ||
			(*candidate.DraftVersionStatus != "draft" && *candidate.DraftVersionStatus != "published") {
			return AcceptedTask{}, conflict("component_repo.validation_unavailable", "candidateId", candidateID)
		}
		versionID := uuidutil.String(candidate.DraftVersionID)
		inputHash := hashStrings(candidate.InterfaceSignature, candidate.StructureHash,
			candidate.GeometryHash, valueOrEmpty(candidate.PartLibrarySourceHash), ValidatorVersion)
		payload := mustJSON(map[string]any{"candidateId": candidateID, "versionId": versionID, "validationLevel": "publish", "validatorVersion": ValidatorVersion, "inputHash": inputHash})
		scheduled, err := task.ScheduleWithQueries(ctx, q, task.ScheduleInput{
			OwnerID: actor, TaskType: ValidationType, LogicalKey: versionID,
			InputHash: inputHash, Payload: payload, Locale: candidate.Locale,
			Timezone: candidate.Timezone, CreatedBy: actor, MaxAttempts: 3,
		})
		if err != nil {
			return AcceptedTask{}, err
		}
		return AcceptedTask{TaskID: uuidutil.String(scheduled.Task.ID), Status: scheduled.Task.Status}, nil
	})
}

func (s *Service) MaterializePreview(ctx context.Context, actor pgtype.UUID, accessToken, versionID string) (AcceptedTask, error) {
	return s.materializePreview(ctx, actor, accessToken, versionID, false)
}

// materializePreview 统一处理 API 请求与维护回填的 durable task 调度。
// force=true 只供受控维护入口使用：它跳过对象缓存探测并递增 generation，确保旧 GLB 能由当前 Worker 重算 Box。
func (s *Service) materializePreview(ctx context.Context, actor pgtype.UUID, accessToken, versionID string, force bool) (AcceptedTask, error) {
	id, err := parseID(versionID, "versionId")
	if err != nil {
		return AcceptedTask{}, err
	}
	state, err := s.q.GetOwnedVersionPreviewState(ctx, db.GetOwnedVersionPreviewStateParams{VersionID: id, ActorID: actor})
	if errors.Is(err, pgx.ErrNoRows) {
		return AcceptedTask{}, notFound("component_repo.version_not_found", "versionId", versionID)
	}
	if err != nil {
		return AcceptedTask{}, err
	}
	cacheMissing := false
	staleGenerator := previewGeneratorStale(state.PreviewStatus, state.PreviewGeneratorVersion)
	if !force && state.PreviewStatus == "ready" && state.PreviewArtifactID.Valid && !staleGenerator {
		preview, previewErr := s.q.GetVisibleVersionPreview(ctx, db.GetVisibleVersionPreviewParams{VersionID: id, ActorID: actor})
		if previewErr == nil && preview.StorageKey != nil {
			if _, headErr := s.store.HeadForUser(ctx, *preview.StorageKey, accessToken); headErr == nil {
				return AcceptedTask{TaskID: uuidutil.String(state.PreviewTaskID), Status: "succeeded"}, nil
			} else if !errors.Is(headErr, storage.ErrNotFound) {
				return AcceptedTask{}, apierror.New("component_repo.storage_unavailable", http.StatusServiceUnavailable, nil)
			}
			cacheMissing = true
		}
	}
	return txValue(ctx, s.pool, func(q *db.Queries) (AcceptedTask, error) {
		locked, err := q.LockOwnedVersionPreviewState(ctx, db.LockOwnedVersionPreviewStateParams{VersionID: id, ActorID: actor})
		if err != nil {
			return AcceptedTask{}, err
		}
		generation := locked.PreviewGeneration
		lockedStaleGenerator := previewGeneratorStale(locked.PreviewStatus, locked.PreviewGeneratorVersion)
		if force || cacheMissing || locked.PreviewStatus == "failed" || lockedStaleGenerator {
			generation++
		}
		if !force && !lockedStaleGenerator && (locked.PreviewStatus == "pending" || locked.PreviewStatus == "running") && locked.PreviewTaskID.Valid {
			existing, taskErr := q.GetOwnedTask(ctx, db.GetOwnedTaskParams{TaskID: locked.PreviewTaskID, ActorID: actor})
			if taskErr == nil && (existing.Status == "queued" || existing.Status == "running") {
				return AcceptedTask{TaskID: uuidutil.String(existing.ID), Status: existing.Status}, nil
			}
			generation++
		}
		inputHash := componentPreviewInputHash(
			uuidutil.String(locked.ID), uuidutil.String(locked.SceneSnapshotID),
			locked.StructureHash, locked.GeometryHash,
			uuidutil.String(locked.PartLibraryVersionID), locked.PartLibrarySourceHash,
			PreviewGeneratorVersion,
		)
		payload := mustJSON(map[string]any{"versionId": versionID, "generatorVersion": PreviewGeneratorVersion, "generation": generation, "inputHash": inputHash})
		scheduled, err := task.ScheduleWithQueries(ctx, q, task.ScheduleInput{
			OwnerID: actor, TaskType: PreviewMaterializeType, LogicalKey: versionID,
			InputHash: inputHash, Payload: payload, Locale: locked.ContentLocale,
			Timezone: locked.Timezone, CreatedBy: actor, MaxAttempts: 3,
			ForceNew: force || cacheMissing || locked.PreviewStatus == "failed" || lockedStaleGenerator,
		})
		if err != nil {
			return AcceptedTask{}, err
		}
		if err := q.SetVersionPreviewTask(ctx, db.SetVersionPreviewTaskParams{TaskID: scheduled.Task.ID, GeneratorVersion: stringPointer(PreviewGeneratorVersion), PreviewGeneration: generation, VersionID: id}); err != nil {
			return AcceptedTask{}, err
		}
		return AcceptedTask{TaskID: uuidutil.String(scheduled.Task.ID), Status: scheduled.Task.Status}, nil
	})
}

// PreviewBoundsBackfillResult 描述维护命令发现及实际调度的版本数量。
type PreviewBoundsBackfillResult struct {
	Matched   int64 `json:"matched"`
	Scheduled int64 `json:"scheduled"`
	DryRun    bool  `json:"dryRun"`
}

// SchedulePreviewBoundsBackfill 为已有 ready Preview 创建可重试、可审计的异步重算任务。
// 命令不直接解析文件或写 Box，实际计算仍由 Go Preview Worker 完成。
func SchedulePreviewBoundsBackfill(ctx context.Context, pool *pgxpool.Pool, batchSize, maxVersions int, dryRun bool) (PreviewBoundsBackfillResult, error) {
	if batchSize <= 0 {
		batchSize = 100
	}
	q := db.New(pool)
	matched, err := q.CountPreviewBoundsBackfillCandidates(ctx, stringPointer(PreviewGeneratorVersion))
	if err != nil {
		return PreviewBoundsBackfillResult{}, err
	}
	result := PreviewBoundsBackfillResult{Matched: matched, DryRun: dryRun}
	if dryRun || matched == 0 {
		return result, nil
	}
	service := NewService(pool, nil, 0)
	for maxVersions <= 0 || int(result.Scheduled) < maxVersions {
		limit := batchSize
		if maxVersions > 0 && limit > maxVersions-int(result.Scheduled) {
			limit = maxVersions - int(result.Scheduled)
		}
		rows, listErr := q.ListPreviewBoundsBackfillCandidates(ctx, db.ListPreviewBoundsBackfillCandidatesParams{
			GeneratorVersion: stringPointer(PreviewGeneratorVersion),
			BatchSize:        int32(limit),
		})
		if listErr != nil {
			return result, listErr
		}
		if len(rows) == 0 {
			break
		}
		for _, row := range rows {
			if _, scheduleErr := service.materializePreview(ctx, row.OwnerID, "", uuidutil.String(row.VersionID), true); scheduleErr != nil {
				return result, scheduleErr
			}
			result.Scheduled++
		}
	}
	return result, nil
}

// EnsureInitialPreviewWithQueries 在组件解析事务内创建首个 GLB 预览任务。
// 调用方必须传入同一事务绑定的 Queries；预览任务依赖解析任务成功后才可被 Worker 领取，
// 从而保证组件版本、BOM 与预览任务要么一起提交，要么一起回滚。
func EnsureInitialPreviewWithQueries(
	ctx context.Context,
	q *db.Queries,
	actor pgtype.UUID,
	versionID pgtype.UUID,
	parseTaskID pgtype.UUID,
) (db.ComponentRepoTask, error) {
	state, err := q.GetOwnedVersionPreviewState(ctx, db.GetOwnedVersionPreviewStateParams{
		VersionID: versionID,
		ActorID:   actor,
	})
	if err != nil {
		return db.ComponentRepoTask{}, err
	}
	// 解析任务重领时可能遇到已经物化完成的预览；当前生成器的 ready 结果不可被重置为 pending。
	if state.PreviewStatus == "ready" && state.PreviewArtifactID.Valid && state.PreviewTaskID.Valid &&
		state.PreviewGeneratorVersion != nil && *state.PreviewGeneratorVersion == PreviewGeneratorVersion {
		existing, err := q.GetOwnedTask(ctx, db.GetOwnedTaskParams{
			TaskID:  state.PreviewTaskID,
			ActorID: actor,
		})
		if err != nil {
			return db.ComponentRepoTask{}, err
		}
		return existing, nil
	}
	inputHash := componentPreviewInputHash(
		uuidutil.String(state.ID),
		uuidutil.String(state.SceneSnapshotID),
		state.StructureHash,
		state.GeometryHash,
		uuidutil.String(state.PartLibraryVersionID),
		state.PartLibrarySourceHash,
		PreviewGeneratorVersion,
	)
	payload := mustJSON(map[string]any{
		"versionId":        uuidutil.String(versionID),
		"generatorVersion": PreviewGeneratorVersion,
		"generation":       state.PreviewGeneration,
		"inputHash":        inputHash,
	})
	scheduled, err := task.ScheduleWithQueries(ctx, q, task.ScheduleInput{
		OwnerID:     actor,
		TaskType:    PreviewMaterializeType,
		LogicalKey:  uuidutil.String(versionID),
		InputHash:   inputHash,
		Payload:     payload,
		Locale:      state.ContentLocale,
		Timezone:    state.Timezone,
		CreatedBy:   actor,
		MaxAttempts: 3,
	})
	if err != nil {
		return db.ComponentRepoTask{}, err
	}
	if err := q.SetVersionPreviewTask(ctx, db.SetVersionPreviewTaskParams{
		TaskID:            scheduled.Task.ID,
		GeneratorVersion:  stringPointer(PreviewGeneratorVersion),
		PreviewGeneration: state.PreviewGeneration,
		VersionID:         versionID,
	}); err != nil {
		return db.ComponentRepoTask{}, err
	}
	if err := q.CreateTaskDependency(ctx, db.CreateTaskDependencyParams{
		TaskID:             scheduled.Task.ID,
		PrerequisiteTaskID: parseTaskID,
		OwnerID:            actor,
	}); err != nil {
		return db.ComponentRepoTask{}, err
	}
	return scheduled.Task, nil
}

func (s *Service) GetPreview(ctx context.Context, actor pgtype.UUID, accessToken, versionID string) (Preview, error) {
	id, err := parseID(versionID, "versionId")
	if err != nil {
		return Preview{}, err
	}
	row, err := s.q.GetVisibleVersionPreview(ctx, db.GetVisibleVersionPreviewParams{VersionID: id, ActorID: actor})
	if errors.Is(err, pgx.ErrNoRows) {
		return Preview{}, notFound("component_repo.version_not_found", "versionId", versionID)
	}
	if err != nil {
		return Preview{}, err
	}
	status := row.PreviewStatus
	staleGenerator := previewGeneratorStale(row.PreviewStatus, row.PreviewGeneratorVersion)
	if staleGenerator {
		status = "stale"
	}
	result := Preview{VersionID: versionID, Status: status, GeneratorVersion: row.PreviewGeneratorVersion, ArtifactID: uuidutil.NullableString(row.PreviewArtifactID), SHA256: row.Sha256, FileSize: row.FileSize}
	if row.PreviewFailureCode != nil && !staleGenerator {
		result.Failure = &Failure{Code: *row.PreviewFailureCode, Params: object(row.PreviewFailureParams)}
	}
	if row.PreviewStatus == "ready" && row.StorageKey != nil && !staleGenerator {
		url, signErr := s.store.SignDownloadForUser(ctx, *row.StorageKey, s.signedURLTTL, accessToken)
		if signErr != nil {
			return Preview{}, apierror.New("component_repo.storage_unavailable", http.StatusServiceUnavailable, nil)
		}
		result.URL = &url
	}
	return result, nil
}

func (s *Service) GetActivePartLibraryVersion(ctx context.Context) (PartLibraryVersion, error) {
	row, err := s.q.GetPreviewActivePartLibraryVersion(ctx)
	if errors.Is(err, pgx.ErrNoRows) {
		return PartLibraryVersion{}, apierror.New("component_repo.part_library_not_found", http.StatusNotFound, nil)
	}
	if err != nil {
		return PartLibraryVersion{}, err
	}
	return PartLibraryVersion{
		ID: uuidutil.String(row.ID), SourceName: row.SourceName, SourceHash: row.SourceHash,
		Status: row.Status, PreviewReady: row.PreviewReady, RelationReady: row.RelationReady,
		ConnectorCount: row.ConnectorCount, ColliderCount: row.ColliderCount, CreatedAt: row.CreatedAt.Time,
	}, nil
}

var partSearchDimensionPattern = regexp.MustCompile(`^(\d+(?:\.\d+)?)[xX×](\d+(?:\.\d+)?)(?:[xX×](\d+(?:\.\d+)?))?$`)

// SearchParts 在当前 active Studio Part Library 上执行同步、有界且稳定分页的源内容搜索。
// API 不读取本地 LDraw 文件；名称、几何状态和尺寸都必须由离线 importer 预先持久化。
func (s *Service) SearchParts(ctx context.Context, input PartSearchRequest) (PartSearchPage, error) {
	if len([]rune(input.Query)) > 200 {
		return PartSearchPage{}, apierror.New("request.validation_failed", http.StatusUnprocessableEntity, map[string]any{"field": "query"})
	}
	page := input.Page
	if page == 0 {
		page = 1
	}
	pageSize := input.PageSize
	if pageSize == 0 {
		pageSize = 50
	}
	if page < 1 || page > 1_000_000 || pageSize < 1 || pageSize > 200 {
		return PartSearchPage{}, apierror.New("request.validation_failed", http.StatusUnprocessableEntity, map[string]any{"field": "page"})
	}
	keywords, dimensions, err := parsePartSearchQuery(input.Query)
	if err != nil {
		return PartSearchPage{}, err
	}
	dimensionsJSON, err := json.Marshal(dimensions)
	if err != nil {
		return PartSearchPage{}, err
	}
	library, err := s.q.GetPreviewActivePartLibraryVersion(ctx)
	if errors.Is(err, pgx.ErrNoRows) {
		return PartSearchPage{}, apierror.New("component_repo.part_library_not_found", http.StatusNotFound, nil)
	}
	if err != nil {
		return PartSearchPage{}, err
	}
	count, err := s.q.CountSearchableParts(ctx, db.CountSearchablePartsParams{
		PartLibraryVersionID: library.ID, Keywords: keywords, Dimensions: dimensionsJSON,
	})
	if err != nil {
		return PartSearchPage{}, err
	}
	offset := int32((page - 1) * pageSize)
	previewGeneratorVersion := PartPreviewGeneratorVersion
	rows, err := s.q.SearchParts(ctx, db.SearchPartsParams{
		PartLibraryVersionID: library.ID, Keywords: keywords, Dimensions: dimensionsJSON,
		GeneratorVersion: &previewGeneratorVersion, PageSize: int32(pageSize), PageOffset: offset,
	})
	if err != nil {
		return PartSearchPage{}, err
	}
	type previewCandidate struct {
		itemIndex int
		key       string
		model     PartSearchPreviewModel
	}
	items := make([]PartSearchItem, 0, len(rows))
	previewCandidates := make([]previewCandidate, 0, len(rows))
	previewKeys := make([]string, 0, len(rows))
	for _, row := range rows {
		item := PartSearchItem{
			LDrawPartNum: row.LdrawPartNum, Name: row.SourceName, ContentLocale: row.ContentLocale,
			TranslationStatus: "source", GeometryStatus: "ready",
			LogicalSizeDerivationStatus: row.LogicalSizeDerivationStatus,
		}
		if row.LogicalWidthStud != nil && row.LogicalDepthStud != nil && row.LogicalHeightPlate != nil {
			item.LogicalSize = &PartSearchLogicalSize{
				WidthStud: *row.LogicalWidthStud, DepthStud: *row.LogicalDepthStud, HeightPlate: *row.LogicalHeightPlate,
			}
		}
		items = append(items, item)
		if row.PreviewArtifactID.Valid && row.PreviewStorageKey != nil && row.PreviewSha256 != nil && row.PreviewFileSize != nil {
			// Search 只投影已经验证且属于当前 generator 的派生资产；签名失败时仍保留文本搜索结果。
			previewCandidates = append(previewCandidates, previewCandidate{
				itemIndex: len(items) - 1,
				key:       *row.PreviewStorageKey,
				model: PartSearchPreviewModel{
					ArtifactID: uuidutil.String(row.PreviewArtifactID), Format: "glb", Compression: "meshopt",
					SHA256: *row.PreviewSha256, ByteLength: *row.PreviewFileSize,
				},
			})
			previewKeys = append(previewKeys, *row.PreviewStorageKey)
		}
	}
	if len(previewKeys) > 0 {
		// 一页搜索结果只发起一次 Storage 批量签名，避免列表大小线性放大 provider 往返。
		if signedURLs, signErr := s.store.SignDownloads(ctx, previewKeys, s.signedURLTTL); signErr == nil {
			for _, candidate := range previewCandidates {
				if signedURL := signedURLs[candidate.key]; signedURL != "" {
					model := candidate.model
					model.URL = signedURL
					items[candidate.itemIndex].PreviewModel = &model
				}
			}
		}
	}
	totalPages := 0
	if count > 0 {
		totalPages = int((count + int64(pageSize) - 1) / int64(pageSize))
	}
	return PartSearchPage{
		PartLibraryVersionID: uuidutil.String(library.ID), Items: items, Total: count,
		Returned: len(items), Page: page, PageSize: pageSize, TotalPages: totalPages,
	}, nil
}

// parsePartSearchQuery 保留旧页面的一框语义：逗号/空格分段，尺寸片段精确匹配，名称关键词至少命中一个。
func parsePartSearchQuery(value string) ([]string, [][]float64, error) {
	fragments := strings.FieldsFunc(value, func(r rune) bool {
		return r == ',' || r == '，' || unicode.IsSpace(r)
	})
	keywords := make([]string, 0, len(fragments))
	dimensions := make([][]float64, 0, len(fragments))
	seenKeywords := map[string]struct{}{}
	seenDimensions := map[string]struct{}{}
	for _, fragment := range fragments {
		fragment = strings.TrimSpace(fragment)
		if match := partSearchDimensionPattern.FindStringSubmatch(fragment); match != nil {
			values := make([]float64, 0, 3)
			for _, raw := range match[1:] {
				if raw == "" {
					continue
				}
				parsed, parseErr := strconv.ParseFloat(raw, 64)
				if parseErr != nil {
					return nil, nil, apierror.New("request.validation_failed", http.StatusUnprocessableEntity, map[string]any{"field": "query"})
				}
				values = append(values, parsed)
			}
			sort.Float64s(values)
			key := fmt.Sprint(values)
			if _, exists := seenDimensions[key]; !exists {
				seenDimensions[key] = struct{}{}
				dimensions = append(dimensions, values)
			}
			continue
		}
		keyword := strings.ToLower(fragment)
		if keyword == "" {
			continue
		}
		if _, exists := seenKeywords[keyword]; !exists {
			seenKeywords[keyword] = struct{}{}
			keywords = append(keywords, keyword)
		}
	}
	return keywords, dimensions, nil
}

func (s *Service) GetPartPreview(ctx context.Context, partLibraryVersionID, partNumber, locale string) (PartPreview, error) {
	libraryID, err := parseID(partLibraryVersionID, "partLibraryVersionId")
	if err != nil {
		return PartPreview{}, err
	}
	partNumber, err = normalizePartNumber(partNumber)
	if err != nil {
		return PartPreview{}, err
	}
	row, err := s.q.GetPartPreview(ctx, db.GetPartPreviewParams{
		PartLibraryVersionID: libraryID, LdrawPartNum: partNumber, Locale: normalizeLocale(locale),
	})
	if errors.Is(err, pgx.ErrNoRows) {
		return PartPreview{}, notFound("component_repo.part_not_found", "ldrawPartNum", partNumber)
	}
	if err != nil {
		return PartPreview{}, err
	}
	name, contentLocale, translationStatus := row.SourceName, row.ContentLocale, "fallback"
	if row.TranslatedName != nil {
		name, contentLocale, translationStatus = *row.TranslatedName, *row.TranslatedLocale, "reviewed"
	}
	result := PartPreview{
		PartLibraryVersionID: partLibraryVersionID, LDrawPartNum: row.LdrawPartNum,
		Name: name, ContentLocale: contentLocale, TranslationStatus: translationStatus,
		Status: row.PreviewStatus, GeneratorVersion: row.GeneratorVersion,
		TaskID: uuidutil.NullableString(row.TaskID),
	}
	// 生成器升级后旧 Artifact 仍保留用于审计，但 API 只暴露当前版本；前端会据此触发新的异步物化任务。
	staleGenerator := row.GeneratorVersion == nil || *row.GeneratorVersion != PartPreviewGeneratorVersion
	if staleGenerator {
		result.Status = "pending"
		result.GeneratorVersion = stringPointer(PartPreviewGeneratorVersion)
		result.TaskID = nil
	}
	if len(row.BboxMin) == 3 && len(row.BboxMax) == 3 && row.LogicalSizeDerivationStatus != nil &&
		row.VertexCount != nil && row.FaceCount != nil {
		result.Geometry = &PartGeometry{
			BBox: PartBoundingBox{
				MinX: row.BboxMin[0], MinY: row.BboxMin[1], MinZ: row.BboxMin[2],
				MaxX: row.BboxMax[0], MaxY: row.BboxMax[1], MaxZ: row.BboxMax[2],
			},
			LogicalWidthStud: row.LogicalWidthStud, LogicalDepthStud: row.LogicalDepthStud,
			LogicalHeightPlate: row.LogicalHeightPlate, LogicalSizeDerivationStatus: *row.LogicalSizeDerivationStatus,
			VertexCount: *row.VertexCount, FaceCount: *row.FaceCount,
		}
	}
	if row.FailureCode != nil && !staleGenerator {
		result.Failure = &Failure{Code: *row.FailureCode, Params: object(row.FailureParams)}
	}
	if !staleGenerator && row.PreviewStatus == "ready" && row.ArtifactID.Valid && row.StorageKey != nil && row.Sha256 != nil && row.FileSize != nil {
		url, signErr := s.store.SignDownload(ctx, *row.StorageKey, s.signedURLTTL)
		if signErr != nil {
			return PartPreview{}, apierror.New("component_repo.storage_unavailable", http.StatusServiceUnavailable, nil)
		}
		result.Model = &PartPreviewModel{
			ArtifactID: uuidutil.String(row.ArtifactID), Format: "glb", URL: url,
			SHA256: *row.Sha256, ByteLength: *row.FileSize,
		}
	}
	return result, nil
}

func (s *Service) MaterializePartPreview(ctx context.Context, actor pgtype.UUID, partLibraryVersionID, partNumber string, input PartPreviewMaterializeInput) (AcceptedTask, error) {
	libraryID, err := parseID(partLibraryVersionID, "partLibraryVersionId")
	if err != nil {
		return AcceptedTask{}, err
	}
	partNumber, err = normalizePartNumber(partNumber)
	if err != nil {
		return AcceptedTask{}, err
	}
	locale := normalizeLocale(input.Locale)
	if _, err := time.LoadLocation(input.Timezone); err != nil {
		return AcceptedTask{}, apierror.New("request.validation_failed", http.StatusUnprocessableEntity, map[string]any{"field": "timezone"})
	}
	return txValue(ctx, s.pool, func(q *db.Queries) (AcceptedTask, error) {
		state, err := q.LockPartPreviewState(ctx, db.LockPartPreviewStateParams{PartLibraryVersionID: libraryID, LdrawPartNum: partNumber})
		if errors.Is(err, pgx.ErrNoRows) {
			return AcceptedTask{}, notFound("component_repo.part_not_found", "ldrawPartNum", partNumber)
		}
		if err != nil {
			return AcceptedTask{}, err
		}
		if state.SourceFileHash == nil || state.GeometryStatus == nil || *state.GeometryStatus != "ready" {
			return AcceptedTask{}, conflict("component_repo.part_preview_unavailable", "ldrawPartNum", partNumber)
		}
		generation := state.Generation
		forceNew := state.PreviewStatus == "failed"
		staleGenerator := state.GeneratorVersion == nil || *state.GeneratorVersion != PartPreviewGeneratorVersion
		if staleGenerator {
			// 旧任务和旧 Artifact 不能阻止新生成器运行；generation 隔离迟到的 v1 Worker 回填。
			generation++
			forceNew = true
		} else if state.PreviewStatus == "ready" && state.ArtifactID.Valid {
			preview, previewErr := q.GetPartPreview(ctx, db.GetPartPreviewParams{PartLibraryVersionID: libraryID, LdrawPartNum: partNumber, Locale: locale})
			if previewErr == nil && preview.StorageKey != nil {
				if _, headErr := s.store.Head(ctx, *preview.StorageKey); headErr == nil {
					return AcceptedTask{TaskID: uuidutil.String(state.TaskID), Status: "succeeded"}, nil
				} else if !errors.Is(headErr, storage.ErrNotFound) {
					return AcceptedTask{}, apierror.New("component_repo.storage_unavailable", http.StatusServiceUnavailable, nil)
				}
			}
			generation++
			forceNew = true
		}
		if !staleGenerator && (state.PreviewStatus == "pending" || state.PreviewStatus == "running") && state.TaskID.Valid {
			existing, taskErr := q.GetOwnedTask(ctx, db.GetOwnedTaskParams{TaskID: state.TaskID, ActorID: actor})
			if taskErr == nil && (existing.Status == "queued" || existing.Status == "running") {
				return AcceptedTask{TaskID: uuidutil.String(existing.ID), Status: existing.Status}, nil
			}
			generation++
			forceNew = true
		}
		inputHash := hashStrings(state.PartLibrarySourceHash, *state.SourceFileHash, PartPreviewGeneratorVersion)
		payload := mustJSON(map[string]any{
			"partLibraryVersionId": partLibraryVersionID, "ldrawPartNum": partNumber,
			"generatorVersion": PartPreviewGeneratorVersion, "generation": generation, "inputHash": inputHash,
		})
		scheduled, err := task.ScheduleWithQueries(ctx, q, task.ScheduleInput{
			OwnerID: actor, TaskType: PartPreviewMaterializeType,
			LogicalKey: partLibraryVersionID + ":" + partNumber, InputHash: inputHash,
			Payload: payload, Locale: locale, Timezone: input.Timezone, CreatedBy: actor,
			MaxAttempts: 3, ForceNew: forceNew,
		})
		if err != nil {
			return AcceptedTask{}, err
		}
		if err := q.SetPartPreviewTask(ctx, db.SetPartPreviewTaskParams{
			TaskID: scheduled.Task.ID, GeneratorVersion: stringPointer(PartPreviewGeneratorVersion),
			Generation: generation, PartLibraryVersionID: libraryID, LdrawPartNum: partNumber,
		}); err != nil {
			return AcceptedTask{}, err
		}
		return AcceptedTask{TaskID: uuidutil.String(scheduled.Task.ID), Status: scheduled.Task.Status}, nil
	})
}

// GetVersionParts 读取版本冻结的 BOM，并只在展示投影阶段选择已审核的官方 Part 译文。
func (s *Service) GetVersionParts(ctx context.Context, actor pgtype.UUID, versionID, locale string) (VersionParts, error) {
	id, err := parseID(versionID, "versionId")
	if err != nil {
		return VersionParts{}, err
	}
	row, err := s.q.GetVisibleVersionBOM(ctx, db.GetVisibleVersionBOMParams{VersionID: id, ActorID: actor})
	if errors.Is(err, pgx.ErrNoRows) {
		return VersionParts{}, notFound("component_repo.version_not_found", "versionId", versionID)
	}
	if err != nil {
		return VersionParts{}, err
	}
	var bom map[string]int
	if err := json.Unmarshal(row.Bom, &bom); err != nil {
		return VersionParts{}, err
	}
	refs := make([]string, 0, len(bom))
	for ref := range bom {
		refs = append(refs, strings.ToLower(ref))
	}
	sort.Strings(refs)
	localized := map[string]db.ListLocalizedPartsRow{}
	if row.PartLibraryVersionID.Valid && len(refs) > 0 {
		rows, queryErr := s.q.ListLocalizedParts(ctx, db.ListLocalizedPartsParams{LdrawPartNums: refs, PartLibraryVersionID: row.PartLibraryVersionID, Locale: normalizeLocale(locale)})
		if queryErr != nil {
			return VersionParts{}, queryErr
		}
		for _, part := range rows {
			localized[part.LdrawPartNum] = part
		}
	}
	result := VersionParts{
		VersionID: versionID, PartLibraryVersionID: uuidutil.NullableString(row.PartLibraryVersionID),
		Items: make([]PartItem, 0, len(refs)),
	}
	for _, ref := range refs {
		quantity := bom[ref]
		if quantity == 0 {
			for original, count := range bom {
				if strings.EqualFold(original, ref) {
					quantity = count
					break
				}
			}
		}
		item := PartItem{LDrawPartNum: ref, Quantity: quantity, TranslationStatus: "missing", GeometryStatus: "missing"}
		if part, ok := localized[ref]; ok {
			item.GeometryStatus = part.GeometryStatus
			if part.TranslatedName != nil {
				item.Name, item.ContentLocale, item.TranslationStatus = part.TranslatedName, part.TranslatedLocale, "reviewed"
			} else if part.SourceName != nil {
				item.Name, item.ContentLocale, item.TranslationStatus = part.SourceName, part.SourceLocale, "fallback"
			}
		}
		result.PartCount += quantity
		result.Items = append(result.Items, item)
	}
	return result, nil
}

func (s *Service) ownedCandidate(ctx context.Context, actor pgtype.UUID, candidateID string) (pgtype.UUID, error) {
	id, err := parseID(candidateID, "candidateId")
	if err != nil {
		return pgtype.UUID{}, err
	}
	_, err = s.q.GetOwnedCandidateWorkbench(ctx, db.GetOwnedCandidateWorkbenchParams{CandidateID: id, ActorID: actor})
	if errors.Is(err, pgx.ErrNoRows) {
		return pgtype.UUID{}, notFound("component_repo.candidate_id_not_found", "candidateId", candidateID)
	}
	return id, err
}

func refreshInterfaceSignature(ctx context.Context, q *db.Queries, actor, candidateID pgtype.UUID) error {
	rows, err := q.ListOwnedCandidateInterfaces(ctx, db.ListOwnedCandidateInterfacesParams{CandidateID: candidateID, ActorID: actor})
	if err != nil {
		return err
	}
	payload := make([]map[string]any, 0, len(rows))
	for _, row := range rows {
		var source map[string]any
		_ = json.Unmarshal(row.SourceConnector, &source)
		payload = append(payload, map[string]any{"worldConnectorId": row.WorldConnectorID, "name": row.Name, "exposure": row.Exposure, "defaultBehavior": row.DefaultBehavior, "connectorType": source["connectorType"], "connectorGender": source["connectorGender"]})
	}
	encoded, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	sum := sha256.Sum256(encoded)
	return q.UpdateCandidateAndDraftInterfaceSignature(ctx, db.UpdateCandidateAndDraftInterfaceSignatureParams{InterfaceSignature: hex.EncodeToString(sum[:]), CandidateID: candidateID, ActorID: actor})
}

func endpoints(left, right []byte) ([]string, error) {
	var a, b struct {
		WorldConnectorID string `json:"worldConnectorId"`
	}
	if json.Unmarshal(left, &a) != nil || json.Unmarshal(right, &b) != nil || a.WorldConnectorID == "" || b.WorldConnectorID == "" {
		return nil, errors.New("invalid relation endpoints")
	}
	return []string{a.WorldConnectorID, b.WorldConnectorID}, nil
}

func interfaceFromDB(row db.ListOwnedCandidateInterfacesRow) Interface {
	return Interface{ID: uuidutil.String(row.ID), ComponentCandidateID: uuidutil.String(row.ComponentCandidateID), WorldConnectorID: row.WorldConnectorID, Name: row.Name, Exposure: row.Exposure, DefaultBehavior: row.DefaultBehavior, SourceConnector: object(row.SourceConnector), MechanicalRoles: array(row.MechanicalRoles), BusinessRoles: array(row.BusinessRoles), Requirements: object(row.Requirements), ReviewStatus: row.ReviewStatus, CreatedAt: row.CreatedAt.Time, UpdatedAt: row.UpdatedAt.Time}
}
func assemblyFromCreated(row db.CreateAssemblyRelationRow) AssemblyRelation {
	return AssemblyRelation{ID: uuidutil.String(row.ID), ComponentCandidateID: uuidutil.String(row.ComponentCandidateID), RelationCandidateID: uuidutil.String(row.RelationCandidateID), EndpointA: object(row.EndpointA), EndpointB: object(row.EndpointB), ConnectionType: row.ConnectionType, JointType: row.JointType, Placement: object(row.Placement), ConfirmedBy: uuidutil.String(row.ConfirmedBy), ConfirmedAt: row.ConfirmedAt.Time}
}
func assemblyFromExisting(row db.GetAssemblyRelationBySourceRow) AssemblyRelation {
	return AssemblyRelation{ID: uuidutil.String(row.ID), ComponentCandidateID: uuidutil.String(row.ComponentCandidateID), RelationCandidateID: uuidutil.String(row.RelationCandidateID), EndpointA: object(row.EndpointA), EndpointB: object(row.EndpointB), ConnectionType: row.ConnectionType, JointType: row.JointType, Placement: object(row.Placement), ConfirmedBy: uuidutil.String(row.ConfirmedBy), ConfirmedAt: row.ConfirmedAt.Time}
}

func txValue[T any](ctx context.Context, pool *pgxpool.Pool, fn func(*db.Queries) (T, error)) (T, error) {
	var zero T
	for attempt := 0; attempt < 3; attempt++ {
		tx, err := pool.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.Serializable})
		if err != nil {
			return zero, err
		}
		value, callErr := fn(db.New(tx))
		if callErr == nil {
			callErr = tx.Commit(ctx)
		} else {
			_ = tx.Rollback(ctx)
		}
		if callErr == nil {
			return value, nil
		}
		var pgErr *pgconn.PgError
		if !errors.As(callErr, &pgErr) || (pgErr.Code != "40001" && pgErr.Code != "40P01") {
			return zero, callErr
		}
	}
	return zero, apierror.New("request.conflict", http.StatusConflict, nil)
}

func parseID(value, field string) (pgtype.UUID, error) {
	id, err := uuidutil.Parse(value)
	if err != nil {
		return pgtype.UUID{}, apierror.New("request.validation_failed", http.StatusUnprocessableEntity, map[string]any{"field": field})
	}
	return id, nil
}
func notFound(code, key, value string) *apierror.Error {
	return apierror.New(code, http.StatusNotFound, map[string]any{key: value})
}
func conflict(code, key, value string) *apierror.Error {
	return apierror.New(code, http.StatusConflict, map[string]any{key: value})
}
func mapRelationError(err error) error {
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) && strings.Contains(pgErr.Message, "connector capacity") {
		return apierror.New("component_repo.connector_capacity_exceeded", http.StatusConflict, nil)
	}
	return err
}
func mustJSON(value any) json.RawMessage {
	encoded, err := json.Marshal(value)
	if err != nil {
		panic(err)
	}
	return encoded
}
func object(value []byte) json.RawMessage {
	if len(value) == 0 {
		return json.RawMessage(`{}`)
	}
	return value
}
func array(value []byte) json.RawMessage {
	if len(value) == 0 {
		return json.RawMessage(`[]`)
	}
	return value
}
func normalizeLocale(value string) string {
	value = strings.ToLower(strings.TrimSpace(value))
	if strings.HasPrefix(value, "en") {
		return "en-US"
	}
	return "zh-CN"
}

func normalizePartNumber(value string) (string, error) {
	value = strings.ToLower(strings.TrimSpace(value))
	if value == "" || len(value) > 128 || strings.ContainsAny(value, "/\\") || strings.Contains(value, "..") {
		return "", apierror.New("request.validation_failed", http.StatusUnprocessableEntity, map[string]any{"field": "ldrawPartNum"})
	}
	return value, nil
}

func stringPointer(value string) *string { return &value }

func hashStrings(values ...string) string {
	hash := sha256.New()
	for _, value := range values {
		_, _ = hash.Write([]byte(fmt.Sprintf("%d:", len(value))))
		_, _ = hash.Write([]byte(value))
	}
	return hex.EncodeToString(hash.Sum(nil))
}

func valueOrEmpty(value *string) string {
	if value == nil {
		return ""
	}
	return *value
}
