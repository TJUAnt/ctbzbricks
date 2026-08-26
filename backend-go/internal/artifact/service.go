package artifact

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"mime"
	"net/http"
	"path"
	"regexp"
	"strings"
	"time"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/component"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/storage"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

var sha256Pattern = regexp.MustCompile(`^[0-9a-fA-F]{64}$`)

type Service struct {
	pool    *pgxpool.Pool
	q       *db.Queries
	store   storage.Store
	config  config.StorageConfig
	imports config.ImportConfig
	logger  *slog.Logger
	now     func() time.Time
}

func NewService(pool *pgxpool.Pool, store storage.Store, cfg config.StorageConfig) *Service {
	return &Service{
		pool: pool, q: db.New(pool), store: store, config: cfg,
		imports: config.ImportConfig{
			ParserVersion: "component-repo-ldraw-parser-v2", SnapshotSchema: "component-repo-v2", MaxAttempts: 3,
		},
		logger: slog.Default(),
		now:    time.Now,
	}
}

func (s *Service) WithImportConfig(cfg config.ImportConfig) *Service {
	s.imports = cfg
	return s
}

func (s *Service) WithLogger(logger *slog.Logger) *Service {
	if logger != nil {
		s.logger = logger
	}
	return s
}

func (s *Service) CreateUploadSession(ctx context.Context, actor pgtype.UUID, input CreateUploadSessionInput) (UploadSession, error) {
	if s.store.Provider() == "disabled" {
		return UploadSession{}, storageError()
	}
	locale, ok := component.NormalizeLocale(input.ContentLocale)
	if !ok {
		return UploadSession{}, validationError("contentLocale")
	}
	timezone, err := normalizeTimezone(input.Timezone)
	if err != nil {
		return UploadSession{}, validationError("timezone")
	}
	targetID, err := optionalUUID(input.TargetComponentID, "targetComponentId")
	if err != nil {
		return UploadSession{}, err
	}
	baseID, err := optionalUUID(input.BaseVersionID, "baseVersionId")
	if err != nil {
		return UploadSession{}, err
	}
	if baseID.Valid && !targetID.Valid {
		return UploadSession{}, validationError("targetComponentId")
	}
	sessionID, err := uuidutil.New()
	if err != nil {
		return UploadSession{}, err
	}
	specs := []FileSpec{input.SourceFile}
	if input.ExchangeFile != nil {
		specs = append(specs, *input.ExchangeFile)
	}
	targets := make([]uploadTargetData, 0, len(specs))
	for ordinal, spec := range specs {
		role := "source"
		if ordinal == 1 {
			role = "exchange"
		}
		target, err := s.prepareTarget(actor, sessionID, int32(ordinal), role, spec)
		if err != nil {
			return UploadSession{}, err
		}
		targets = append(targets, target)
	}

	return withTx(ctx, s.pool, func(q *db.Queries) (UploadSession, error) {
		if targetID.Valid {
			if _, err := q.LockOwnedComponent(ctx, db.LockOwnedComponentParams{ComponentID: targetID, ActorID: actor}); errors.Is(err, pgx.ErrNoRows) {
				return UploadSession{}, notFound("component_repo.component_not_found", "componentId", *input.TargetComponentID)
			} else if err != nil {
				return UploadSession{}, err
			}
		}
		if baseID.Valid {
			base, err := q.LockOwnedComponentVersion(ctx, db.LockOwnedComponentVersionParams{VersionID: baseID, ActorID: actor})
			if errors.Is(err, pgx.ErrNoRows) {
				return UploadSession{}, notFound("component_repo.version_not_found", "versionId", *input.BaseVersionID)
			}
			if err != nil {
				return UploadSession{}, err
			}
			if !uuidutil.Equal(base.ComponentID, targetID) {
				return UploadSession{}, validationError("baseVersionId")
			}
		}
		row, err := q.CreateUploadSession(ctx, db.CreateUploadSessionParams{
			ID: sessionID, OwnerID: actor, TargetComponentID: targetID, BaseVersionID: baseID,
			Locale: locale, Timezone: timezone, Metadata: json.RawMessage(`{}`), CreatedBy: actor,
			ExpiresAt: pgtype.Timestamptz{Time: s.now().UTC().Add(s.config.UploadSessionTTL), Valid: true},
		})
		if err != nil {
			return UploadSession{}, err
		}
		files := make([]db.ComponentRepoUploadSessionFile, 0, len(targets))
		for _, target := range targets {
			file, err := q.CreateUploadSessionFile(ctx, db.CreateUploadSessionFileParams{
				ID: target.id, UploadSessionID: sessionID, Ordinal: target.ordinal,
				ArtifactType: target.artifactType, OriginalFilename: target.filename,
				ExpectedSize: target.size, ExpectedSha256: &target.sha256,
				StorageProvider: s.store.Provider(), StorageBucket: s.store.Bucket(), StorageKey: target.key,
			})
			if err != nil {
				return UploadSession{}, err
			}
			files = append(files, file)
		}
		return sessionFromDB(row, files), nil
	})
}

func (s *Service) CompleteUploadSession(ctx context.Context, actor pgtype.UUID, accessToken, sessionID string) (UploadCompletion, error) {
	id, err := parseUUID(sessionID, "sessionId")
	if err != nil {
		return UploadCompletion{}, err
	}
	session, err := s.q.GetOwnedUploadSession(ctx, db.GetOwnedUploadSessionParams{SessionID: id, ActorID: actor})
	if errors.Is(err, pgx.ErrNoRows) {
		return UploadCompletion{}, notFound("component_repo.upload_session_complete_failed", "uploadSessionId", sessionID)
	}
	if err != nil {
		return UploadCompletion{}, err
	}
	if session.Status == "completed" {
		return s.completedResult(ctx, actor, id)
	}
	if session.Status != "pending" || !session.ExpiresAt.Valid || !s.now().UTC().Before(session.ExpiresAt.Time) {
		return UploadCompletion{}, conflict("component_repo.upload_session_complete_failed", "uploadSessionId", sessionID)
	}
	files, err := s.q.ListUploadSessionFiles(ctx, id)
	if err != nil {
		return UploadCompletion{}, err
	}
	if len(files) == 0 {
		s.logUploadCompleteFailure(ctx, sessionID, nil, "no_files")
		return UploadCompletion{}, s.failAndCompensate(ctx, actor, id, files)
	}
	for _, file := range files {
		if file.StorageProvider != s.store.Provider() || file.StorageBucket != s.store.Bucket() {
			s.logUploadCompleteFailure(ctx, sessionID, &file, "storage_provider_bucket_mismatch",
				"expectedProvider", s.store.Provider(),
				"actualProvider", file.StorageProvider,
				"expectedBucket", s.store.Bucket(),
				"actualBucket", file.StorageBucket,
			)
			return UploadCompletion{}, storageError()
		}
		metadata, headErr := s.store.HeadForUser(ctx, file.StorageKey, accessToken)
		if headErr != nil {
			if errors.Is(headErr, storage.ErrNotFound) {
				s.logUploadCompleteFailure(ctx, sessionID, &file, "storage_object_not_found")
				return UploadCompletion{}, s.failAndCompensate(ctx, actor, id, files)
			}
			s.logUploadCompleteFailure(ctx, sessionID, &file, "storage_head_unavailable", "error", headErr)
			return UploadCompletion{}, storageError()
		}
		expectedContentTypes := acceptableMimeTypesFor(file.ArtifactType)
		if metadata.Size != file.ExpectedSize || !contentTypeMatches(metadata.ContentType, expectedContentTypes...) {
			s.logUploadCompleteFailure(ctx, sessionID, &file, "storage_metadata_mismatch",
				"expectedSize", file.ExpectedSize,
				"actualSize", metadata.Size,
				"expectedContentTypes", expectedContentTypes,
				"actualContentType", metadata.ContentType,
			)
			return UploadCompletion{}, s.failAndCompensate(ctx, actor, id, files)
		}
	}

	return withTx(ctx, s.pool, func(q *db.Queries) (UploadCompletion, error) {
		locked, err := q.LockOwnedUploadSession(ctx, db.LockOwnedUploadSessionParams{SessionID: id, ActorID: actor})
		if errors.Is(err, pgx.ErrNoRows) {
			return UploadCompletion{}, notFound("component_repo.upload_session_complete_failed", "uploadSessionId", sessionID)
		}
		if err != nil {
			return UploadCompletion{}, err
		}
		if locked.Status == "completed" {
			return completionFromQueries(ctx, q, actor, id)
		}
		if locked.Status != "pending" || !locked.ExpiresAt.Valid || !s.now().UTC().Before(locked.ExpiresAt.Time) {
			return UploadCompletion{}, conflict("component_repo.upload_session_complete_failed", "uploadSessionId", sessionID)
		}
		lockedFiles, err := q.ListUploadSessionFiles(ctx, id)
		if err != nil {
			return UploadCompletion{}, err
		}
		artifacts := make([]db.ComponentRepoArtifact, 0, len(lockedFiles))
		verificationTasks := make([]db.ComponentRepoTask, 0, len(lockedFiles))
		for _, file := range lockedFiles {
			if file.ExpectedSha256 == nil {
				return UploadCompletion{}, validationError("sha256")
			}
			metadata, _ := json.Marshal(map[string]any{
				"uploadSessionId": sessionID, "uploadRole": roleForOrdinal(file.Ordinal),
				"uploadMethod": "direct_storage", "verification": map[string]any{"status": "pending"},
			})
			artifactRow, err := q.CreateSourceArtifact(ctx, db.CreateSourceArtifactParams{
				ID: file.ID, OwnerID: actor, ArtifactType: file.ArtifactType,
				OriginalFilename: file.OriginalFilename, StorageProvider: file.StorageProvider,
				StorageBucket: file.StorageBucket, StorageKey: file.StorageKey,
				Sha256: *file.ExpectedSha256, FileSize: file.ExpectedSize,
				MimeType: mimeTypeFor(file.ArtifactType), UploadedBy: actor, Metadata: metadata,
			})
			if err != nil {
				return UploadCompletion{}, err
			}
			if _, err := q.MarkUploadSessionFileUploaded(ctx, db.MarkUploadSessionFileUploadedParams{
				ArtifactID: file.ID, FileID: file.ID, SessionID: id,
			}); err != nil {
				return UploadCompletion{}, err
			}
			verificationPayload, _ := json.Marshal(map[string]string{"artifactId": uuidutil.String(file.ID)})
			verificationTask, _, err := task.EnqueueWithQueries(ctx, q, task.EnqueueInput{
				OwnerID: actor, TaskType: task.ArtifactVerifyType, Payload: verificationPayload,
				Locale: locked.Locale, Timezone: locked.Timezone, CreatedBy: actor,
				IdempotencyKey: "artifact:" + uuidutil.String(file.ID), MaxAttempts: 3,
				AvailableAt: s.now().UTC(),
			})
			if err != nil {
				return UploadCompletion{}, err
			}
			verificationTasks = append(verificationTasks, verificationTask)
			artifacts = append(artifacts, artifactRow)
		}
		if len(artifacts) == 0 {
			return UploadCompletion{}, validationError("files")
		}
		importID, err := uuidutil.New()
		if err != nil {
			return UploadCompletion{}, err
		}
		parsePayload, _ := json.Marshal(map[string]string{
			"importId": uuidutil.String(importID), "parserVersion": s.imports.ParserVersion,
			"snapshotSchema": s.imports.SnapshotSchema,
		})
		parseTask, _, err := task.EnqueueWithQueries(ctx, q, task.EnqueueInput{
			OwnerID: actor, TaskType: task.ImportParseType, Payload: parsePayload,
			Locale: locked.Locale, Timezone: locked.Timezone, CreatedBy: actor,
			IdempotencyKey: "import:" + uuidutil.String(importID), MaxAttempts: s.imports.MaxAttempts,
			AvailableAt: s.now().UTC(),
		})
		if err != nil {
			return UploadCompletion{}, err
		}
		for _, prerequisite := range verificationTasks {
			if err := q.CreateTaskDependency(ctx, db.CreateTaskDependencyParams{
				TaskID: parseTask.ID, PrerequisiteTaskID: prerequisite.ID, OwnerID: actor,
			}); err != nil {
				return UploadCompletion{}, err
			}
		}
		var exchangeID pgtype.UUID
		if len(artifacts) > 1 {
			exchangeID = artifacts[1].ID
		}
		partLibraryID, err := q.GetActivePartLibraryVersion(ctx)
		if errors.Is(err, pgx.ErrNoRows) {
			partLibraryID = pgtype.UUID{}
		} else if err != nil {
			return UploadCompletion{}, err
		}
		importMetadata, _ := json.Marshal(map[string]any{
			"uploadMethod": "direct_storage", "snapshotSchema": s.imports.SnapshotSchema,
		})
		parserVersion := s.imports.ParserVersion
		if _, err := q.CreateComponentImport(ctx, db.CreateComponentImportParams{
			ID: importID, OwnerID: actor, SourceArtifactID: artifacts[0].ID,
			ExchangeArtifactID: exchangeID, TargetComponentID: locked.TargetComponentID,
			BaseVersionID: locked.BaseVersionID, ParserVersion: &parserVersion,
			PartLibraryVersionID: partLibraryID, Locale: locked.Locale, Timezone: locked.Timezone,
			Metadata: importMetadata, CreatedBy: actor, UploadSessionID: id, ParseTaskID: parseTask.ID,
		}); err != nil {
			return UploadCompletion{}, err
		}
		sessionMetadata, _ := json.Marshal(map[string]any{
			"importId": uuidutil.String(importID), "taskId": uuidutil.String(parseTask.ID),
			"verification": map[string]any{"status": "pending"},
		})
		if _, err := q.CompleteUploadSession(ctx, db.CompleteUploadSessionParams{
			Metadata: sessionMetadata, SessionID: id, ActorID: actor,
		}); err != nil {
			return UploadCompletion{}, err
		}
		return UploadCompletion{
			ImportID: uuidutil.String(importID), TaskID: uuidutil.String(parseTask.ID), Status: parseTask.Status,
		}, nil
	})
}

func (s *Service) VerifyOwnedArtifact(ctx context.Context, actor pgtype.UUID, artifactID string) (Artifact, error) {
	id, err := parseUUID(artifactID, "artifactId")
	if err != nil {
		return Artifact{}, err
	}
	row, err := s.q.GetOwnedArtifact(ctx, db.GetOwnedArtifactParams{ArtifactID: id, ActorID: actor})
	if errors.Is(err, pgx.ErrNoRows) {
		return Artifact{}, notFound("component_repo.artifact_not_found", "artifactId", artifactID)
	}
	if err != nil {
		return Artifact{}, err
	}
	if row.VerificationStatus == "verified" {
		return artifactFromDB(row), nil
	}
	if row.VerificationStatus != "pending" {
		return Artifact{}, apierror.New("component_repo.hash_mismatch", http.StatusUnprocessableEntity, nil)
	}
	if row.StorageProvider != s.store.Provider() || row.StorageBucket != s.store.Bucket() {
		return Artifact{}, storageError()
	}
	body, err := s.store.Open(ctx, row.StorageKey)
	if err != nil {
		return Artifact{}, storageError()
	}
	defer body.Close()
	hash := sha256.New()
	read, err := io.Copy(hash, io.LimitReader(body, row.FileSize+1))
	if err != nil {
		return Artifact{}, storageError()
	}
	actualHash := hex.EncodeToString(hash.Sum(nil))
	if read != row.FileSize || actualHash != row.Sha256 {
		metadata := verificationMetadata(row.Metadata, "failed", actualHash)
		if err := withTxError(ctx, s.pool, func(q *db.Queries) error {
			if _, err := q.MarkArtifactFailed(ctx, db.MarkArtifactFailedParams{Metadata: metadata, ArtifactID: id}); err != nil {
				return err
			}
			return q.MarkUploadSessionFileFailed(ctx, id)
		}); err != nil {
			return Artifact{}, err
		}
		return Artifact{}, apierror.New("component_repo.hash_mismatch", http.StatusUnprocessableEntity, map[string]any{"artifactId": artifactID})
	}
	updated, err := withTx(ctx, s.pool, func(q *db.Queries) (db.ComponentRepoArtifact, error) {
		updated, err := q.MarkArtifactVerified(ctx, db.MarkArtifactVerifiedParams{
			Metadata: verificationMetadata(row.Metadata, "verified", actualHash), ArtifactID: id,
		})
		if err != nil {
			return db.ComponentRepoArtifact{}, err
		}
		if err := q.MarkUploadSessionFileVerified(ctx, id); err != nil {
			return db.ComponentRepoArtifact{}, err
		}
		return updated, nil
	})
	if errors.Is(err, pgx.ErrNoRows) {
		updated, err = s.q.GetOwnedArtifact(ctx, db.GetOwnedArtifactParams{ArtifactID: id, ActorID: actor})
	}
	return artifactFromDB(updated), err
}

func (s *Service) CreateDownload(ctx context.Context, actor pgtype.UUID, accessToken, artifactID string) (Download, error) {
	id, err := parseUUID(artifactID, "artifactId")
	if err != nil {
		return Download{}, err
	}
	row, err := s.q.GetOwnedArtifact(ctx, db.GetOwnedArtifactParams{ArtifactID: id, ActorID: actor})
	if errors.Is(err, pgx.ErrNoRows) {
		return Download{}, notFound("component_repo.artifact_not_found", "artifactId", artifactID)
	}
	if err != nil {
		return Download{}, err
	}
	return s.signArtifact(ctx, accessToken, row, "component_repo.artifact_not_found_failed", "artifactId", artifactID)
}

func (s *Service) CreateVersionSourceDownload(ctx context.Context, actor pgtype.UUID, accessToken, versionID string) (Download, error) {
	id, err := parseUUID(versionID, "versionId")
	if err != nil {
		return Download{}, err
	}
	row, err := s.q.GetVisibleVersionSourceArtifact(ctx, db.GetVisibleVersionSourceArtifactParams{VersionID: id, ActorID: actor})
	if errors.Is(err, pgx.ErrNoRows) {
		return Download{}, notFound("component_repo.version_source_not_found_failed", "versionId", versionID)
	}
	if err != nil {
		return Download{}, err
	}
	return s.signArtifact(ctx, accessToken, row, "component_repo.version_source_not_found_failed", "versionId", versionID)
}

func (s *Service) signArtifact(ctx context.Context, accessToken string, row db.ComponentRepoArtifact, unavailableCode, parameter, value string) (Download, error) {
	if row.VerificationStatus != "verified" || row.StorageProvider != s.store.Provider() || row.StorageBucket != s.store.Bucket() {
		return Download{}, conflict(unavailableCode, parameter, value)
	}
	url, err := s.store.SignDownloadForUser(ctx, row.StorageKey, s.config.SignedURLTTL, accessToken)
	if err != nil {
		return Download{}, storageError()
	}
	return Download{ArtifactID: uuidutil.String(row.ID), URL: url, ExpiresAt: s.now().UTC().Add(s.config.SignedURLTTL)}, nil
}

func (s *Service) CleanupExpired(ctx context.Context, before time.Time, batchSize int32) (int, error) {
	if batchSize < 1 || batchSize > 1000 {
		batchSize = 100
	}
	sessions, err := s.q.ListExpiredUploadSessions(ctx, db.ListExpiredUploadSessionsParams{
		ExpiredBefore: pgtype.Timestamptz{Time: before.UTC(), Valid: true}, BatchSize: batchSize,
	})
	if err != nil {
		return 0, err
	}
	cleaned := 0
	for _, session := range sessions {
		files, err := s.q.ListUploadSessionFiles(ctx, session.ID)
		if err != nil {
			return cleaned, err
		}
		allDeleted := true
		for _, file := range files {
			if err := s.store.Delete(ctx, file.StorageKey); err != nil {
				allDeleted = false
				break
			}
		}
		if !allDeleted {
			continue
		}
		rows, err := s.q.ExpireUploadSession(ctx, session.ID)
		if err != nil {
			return cleaned, err
		}
		if rows == 1 {
			cleaned++
		}
	}
	return cleaned, nil
}

type uploadTargetData struct {
	id                                  pgtype.UUID
	ordinal                             int32
	artifactType, filename, key, sha256 string
	size                                int64
}

func (s *Service) prepareTarget(actor, sessionID pgtype.UUID, ordinal int32, role string, spec FileSpec) (uploadTargetData, error) {
	filename := cleanFilename(spec.Filename)
	artifactType, extension, ok := artifactTypeForFilename(filename)
	if !ok || (role == "exchange" && artifactType == "studio_io") {
		return uploadTargetData{}, apierror.New("component_repo.invalid_artifact_type", http.StatusUnprocessableEntity, nil)
	}
	if spec.FileSize <= 0 || spec.FileSize > s.config.MaxArtifactBytes {
		return uploadTargetData{}, validationError(role + "File.fileSize")
	}
	if !sha256Pattern.MatchString(spec.SHA256) {
		return uploadTargetData{}, validationError(role + "File.sha256")
	}
	id, err := uuidutil.New()
	if err != nil {
		return uploadTargetData{}, err
	}
	parts := []string{uuidutil.String(actor)}
	if s.config.KeyPrefix != "" {
		parts = append(parts, s.config.KeyPrefix)
	}
	parts = append(parts, "uploads", uuidutil.String(sessionID), role, uuidutil.String(id)+extension)
	return uploadTargetData{id: id, ordinal: ordinal, artifactType: artifactType, filename: filename,
		key: strings.Join(parts, "/"), sha256: strings.ToLower(spec.SHA256), size: spec.FileSize}, nil
}

func (s *Service) failAndCompensate(ctx context.Context, actor, sessionID pgtype.UUID, files []db.ComponentRepoUploadSessionFile) error {
	cleanupFailed := false
	for _, file := range files {
		if err := s.store.Delete(ctx, file.StorageKey); err != nil {
			cleanupFailed = true
		}
	}
	if cleanupFailed {
		return storageError()
	}
	params, _ := json.Marshal(map[string]any{"uploadSessionId": uuidutil.String(sessionID)})
	code := "component_repo.upload_session_complete_failed"
	if err := withTxError(ctx, s.pool, func(q *db.Queries) error {
		if err := q.FailUploadSessionFiles(ctx, sessionID); err != nil {
			return err
		}
		return q.FailUploadSession(ctx, db.FailUploadSessionParams{
			FailureCode: &code, FailureParams: params, SessionID: sessionID, ActorID: actor,
		})
	}); err != nil {
		return err
	}
	return apierror.New(code, http.StatusUnprocessableEntity, map[string]any{"uploadSessionId": uuidutil.String(sessionID)})
}

func (s *Service) completedResult(ctx context.Context, actor, sessionID pgtype.UUID) (UploadCompletion, error) {
	return completionFromQueries(ctx, s.q, actor, sessionID)
}

func (s *Service) logUploadCompleteFailure(ctx context.Context, sessionID string, file *db.ComponentRepoUploadSessionFile, reason string, attrs ...any) {
	if s.logger == nil {
		return
	}
	fields := []any{
		"reason", reason,
		"uploadSessionId", sessionID,
	}
	if file != nil {
		fields = append(fields,
			"ordinal", file.Ordinal,
			"artifactId", uuidutil.String(file.ID),
			"artifactType", file.ArtifactType,
		)
	}
	fields = append(fields, attrs...)
	s.logger.WarnContext(ctx, "Component upload completion failed preflight", fields...)
}

func completionFromQueries(ctx context.Context, q *db.Queries, actor, sessionID pgtype.UUID) (UploadCompletion, error) {
	importJob, err := q.GetOwnedImportByUploadSession(ctx, db.GetOwnedImportByUploadSessionParams{
		UploadSessionID: sessionID, ActorID: actor,
	})
	if err != nil {
		return UploadCompletion{}, err
	}
	parseTask, err := q.GetOwnedTask(ctx, db.GetOwnedTaskParams{TaskID: importJob.ParseTaskID, ActorID: actor})
	if err != nil {
		return UploadCompletion{}, err
	}
	return UploadCompletion{
		ImportID: uuidutil.String(importJob.ID), TaskID: uuidutil.String(parseTask.ID), Status: parseTask.Status,
	}, nil
}

func sessionFromDB(row db.ComponentRepoUploadSession, files []db.ComponentRepoUploadSessionFile) UploadSession {
	uploads := make([]UploadTarget, 0, len(files))
	for _, file := range files {
		uploads = append(uploads, UploadTarget{
			Role: roleForOrdinal(file.Ordinal), ArtifactID: uuidutil.String(file.ID), ArtifactType: file.ArtifactType,
			OriginalFilename: file.OriginalFilename, Bucket: file.StorageBucket, ObjectPath: file.StorageKey,
			ContentType: mimeTypeFor(file.ArtifactType), FileSize: file.ExpectedSize,
			ExpectedSHA256: valueOrEmpty(file.ExpectedSha256), UploadSessionID: uuidutil.String(row.ID),
		})
	}
	var completedAt *time.Time
	if row.CompletedAt.Valid {
		completedAt = &row.CompletedAt.Time
	}
	var failure *Failure
	if row.FailureCode != nil {
		failure = &Failure{Code: *row.FailureCode, Params: nonEmptyJSON(row.FailureParams)}
	}
	return UploadSession{
		ID: uuidutil.String(row.ID), OwnerID: uuidutil.String(row.OwnerID), Status: row.Status,
		Bucket: filesBucket(files), Uploads: uploads, CreatedBy: uuidutil.String(row.CreatedBy),
		CreatedAt: row.CreatedAt.Time, ExpiresAt: row.ExpiresAt.Time, CompletedAt: completedAt,
		Failure: failure, Metadata: nonEmptyJSON(row.Metadata),
	}
}

func artifactFromDB(row db.ComponentRepoArtifact) Artifact {
	var verifiedAt *time.Time
	if row.VerifiedAt.Valid {
		verifiedAt = &row.VerifiedAt.Time
	}
	return Artifact{
		ID: uuidutil.String(row.ID), OwnerID: uuidutil.String(row.OwnerID), ArtifactType: row.ArtifactType,
		SourceKind: row.SourceKind, OriginalFilename: row.OriginalFilename, SHA256: row.Sha256,
		FileSize: row.FileSize, MimeType: row.MimeType, Immutable: row.Immutable,
		VerificationStatus: row.VerificationStatus, VerifiedAt: verifiedAt,
		UploadedBy: uuidutil.String(row.UploadedBy), UploadedAt: row.UploadedAt.Time,
		Metadata: nonEmptyJSON(row.Metadata),
	}
}

func artifactTypeForFilename(filename string) (string, string, bool) {
	extension := strings.ToLower(path.Ext(filename))
	switch extension {
	case ".io":
		return "studio_io", extension, true
	case ".ldr":
		return "ldraw_ldr", extension, true
	case ".mpd":
		return "ldraw_mpd", extension, true
	default:
		return "", "", false
	}
}

func mimeTypeFor(artifactType string) string {
	if artifactType == "ldraw_ldr" || artifactType == "ldraw_mpd" {
		return "text/plain"
	}
	if artifactType == "studio_io" {
		return "application/x-studioformat"
	}
	return "application/octet-stream"
}

func acceptableMimeTypesFor(artifactType string) []string {
	primary := mimeTypeFor(artifactType)
	if artifactType == "studio_io" {
		return []string{primary, "application/octet-stream"}
	}
	return []string{primary}
}

func contentTypeMatches(actual string, expected ...string) bool {
	if strings.TrimSpace(actual) == "" {
		return true
	}
	mediaType, _, err := mime.ParseMediaType(actual)
	if err != nil {
		return false
	}
	for _, candidate := range expected {
		if strings.EqualFold(mediaType, candidate) {
			return true
		}
	}
	return false
}

func cleanFilename(value string) string {
	value = strings.ReplaceAll(strings.TrimSpace(value), "\\", "/")
	clean := path.Base(value)
	if clean == "." || clean == "/" {
		return ""
	}
	return clean
}

func normalizeTimezone(value string) (string, error) {
	value = strings.TrimSpace(value)
	if value == "" || len(value) > 128 {
		return "", errors.New("invalid timezone")
	}
	if _, err := time.LoadLocation(value); err != nil {
		return "", errors.New("invalid timezone")
	}
	return value, nil
}

func verificationMetadata(raw []byte, status, actualHash string) []byte {
	metadata := map[string]any{}
	_ = json.Unmarshal(raw, &metadata)
	metadata["verification"] = map[string]any{
		"status": status, "actualSha256": actualHash, "checkedAt": time.Now().UTC().Format(time.RFC3339Nano),
	}
	encoded, _ := json.Marshal(metadata)
	return encoded
}

func parseUUID(value, field string) (pgtype.UUID, error) {
	id, err := uuidutil.Parse(value)
	if err != nil {
		return pgtype.UUID{}, validationError(field)
	}
	return id, nil
}

func optionalUUID(value *string, field string) (pgtype.UUID, error) {
	if value == nil {
		return pgtype.UUID{}, nil
	}
	return parseUUID(*value, field)
}

func validationError(field string) *apierror.Error {
	return apierror.New("request.validation_failed", http.StatusUnprocessableEntity, map[string]any{"field": field})
}

func notFound(code, field, value string) *apierror.Error {
	return apierror.New(code, http.StatusNotFound, map[string]any{field: value})
}

func conflict(code, field, value string) *apierror.Error {
	return apierror.New(code, http.StatusConflict, map[string]any{field: value})
}

func storageError() *apierror.Error {
	return apierror.New("component_repo.storage_unavailable", http.StatusBadGateway, nil)
}

func roleForOrdinal(ordinal int32) string {
	if ordinal == 0 {
		return "source"
	}
	return "exchange"
}

func filesBucket(files []db.ComponentRepoUploadSessionFile) string {
	if len(files) == 0 {
		return ""
	}
	return files[0].StorageBucket
}

func valueOrEmpty(value *string) string {
	if value == nil {
		return ""
	}
	return *value
}

func nonEmptyJSON(value []byte) json.RawMessage {
	if len(value) == 0 || !json.Valid(value) {
		return json.RawMessage(`{}`)
	}
	return value
}

func withTx[T any](ctx context.Context, pool *pgxpool.Pool, fn func(*db.Queries) (T, error)) (T, error) {
	var zero T
	for attempt := 0; attempt < 3; attempt++ {
		tx, err := pool.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.Serializable})
		if err != nil {
			return zero, err
		}
		value, runErr := fn(db.New(tx))
		if runErr != nil {
			_ = tx.Rollback(ctx)
			if retryableTransaction(runErr) {
				continue
			}
			return zero, runErr
		}
		if err = tx.Commit(ctx); err == nil {
			return value, nil
		}
		if !retryableTransaction(err) {
			return zero, err
		}
	}
	return zero, apierror.New("request.conflict", http.StatusConflict, nil)
}

func withTxError(ctx context.Context, pool *pgxpool.Pool, fn func(*db.Queries) error) error {
	_, err := withTx(ctx, pool, func(q *db.Queries) (struct{}, error) { return struct{}{}, fn(q) })
	return err
}

func retryableTransaction(err error) bool {
	var pgError *pgconn.PgError
	return errors.As(err, &pgError) && (pgError.Code == "40001" || pgError.Code == "40P01")
}
