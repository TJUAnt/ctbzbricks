//go:build integration

package artifact

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/ingestion"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/storage"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

func TestG4UploadLifecycleAndStorageBoundaries(t *testing.T) {
	databaseURL := os.Getenv("TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("TEST_DATABASE_URL is required")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatalf("connect PostgreSQL: %v", err)
	}
	defer pool.Close()
	if _, err := pool.Exec(ctx, `TRUNCATE component_repo.upload_sessions, component_repo.imports, component_repo.artifacts, component_repo.tasks, component_repo.outbox_events RESTART IDENTITY CASCADE`); err != nil {
		t.Fatalf("reset fixtures: %v", err)
	}

	store := newFakeStore()
	cfg := config.StorageConfig{
		Provider: "supabase", Bucket: "component-artifacts", KeyPrefix: "component-repo",
		SignedURLTTL: 5 * time.Minute, UploadSessionTTL: time.Hour, MaxArtifactBytes: 1024,
	}
	service := NewService(pool, store, cfg)
	actor := mustUUID(t, "41000000-0000-0000-0000-000000000001")
	otherActor := mustUUID(t, "41000000-0000-0000-0000-000000000002")

	content := []byte("0 FILE model.ldr\n1 16 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n")
	digest := sha256.Sum256(content)
	session, err := service.CreateUploadSession(ctx, actor, CreateUploadSessionInput{
		SourceFile:    FileSpec{Filename: "../用户模型.ldr", ContentType: "text/plain", FileSize: int64(len(content)), SHA256: hex.EncodeToString(digest[:])},
		ContentLocale: "zh_hans_CN", Timezone: "Asia/Shanghai",
	})
	if err != nil {
		t.Fatalf("create upload session: %v", err)
	}
	if len(session.Uploads) != 1 || session.Uploads[0].OriginalFilename != "用户模型.ldr" {
		t.Fatalf("unexpected upload response: %+v", session)
	}
	wantPrefix := uuidutil.String(actor) + "/component-repo/uploads/" + session.ID + "/source/"
	if !strings.HasPrefix(session.Uploads[0].ObjectPath, wantPrefix) || strings.Contains(session.Uploads[0].ObjectPath, "用户模型") {
		t.Fatalf("object key is not server-scoped and opaque: %q", session.Uploads[0].ObjectPath)
	}
	store.put(session.Uploads[0].ObjectPath, content, "text/plain")

	completed, err := service.CompleteUploadSession(ctx, actor, "user-jwt", session.ID)
	if err != nil {
		t.Fatalf("complete upload: %v", err)
	}
	if completed.Status != "queued" || completed.ImportID == "" || completed.TaskID == "" {
		t.Fatalf("unexpected completion: %+v", completed)
	}
	if store.openCount != 0 || store.headCount != 1 {
		t.Fatalf("completion must be metadata-only, heads=%d opens=%d", store.headCount, store.openCount)
	}
	var importCount, taskCount, eventCount, outboxCount int
	if err := pool.QueryRow(ctx, `
		SELECT (SELECT count(*) FROM component_repo.imports),
		       (SELECT count(*) FROM component_repo.tasks),
		       (SELECT count(*) FROM component_repo.task_events),
		       (SELECT count(*) FROM component_repo.outbox_events)`).Scan(
		&importCount, &taskCount, &eventCount, &outboxCount,
	); err != nil || importCount != 1 || taskCount != 2 || eventCount != 2 || outboxCount != 2 {
		t.Fatalf("upload completion records = imports/tasks/events/outbox %d/%d/%d/%d err=%v", importCount, taskCount, eventCount, outboxCount, err)
	}
	idempotent, err := service.CompleteUploadSession(ctx, actor, "user-jwt", session.ID)
	if err != nil || idempotent.ImportID != completed.ImportID || idempotent.TaskID != completed.TaskID || store.headCount != 1 {
		t.Fatalf("idempotent completion failed: %+v %v heads=%d", idempotent, err, store.headCount)
	}
	if _, err := service.CompleteUploadSession(ctx, otherActor, "other-jwt", session.ID); publicCode(err) != "component_repo.upload_session_complete_failed" {
		t.Fatalf("cross-owner completion error = %v", err)
	}

	taskService := task.NewService(pool)
	if _, found, err := taskService.Claim(ctx, "parser-too-early", []string{task.ImportParseType}, time.Minute); err != nil || found {
		t.Fatalf("parse task bypassed artifact dependency: found=%v error=%v", found, err)
	}
	claimed, found, err := taskService.Claim(ctx, "artifact-worker", []string{task.ArtifactVerifyType}, time.Minute)
	if err != nil || !found {
		t.Fatalf("claim artifact verification task = %+v found=%v error=%v", claimed, found, err)
	}
	_, err = NewVerificationTaskHandler(service).Handle(ctx, claimed)
	if err != nil {
		t.Fatalf("handle artifact verification task: %v", err)
	}
	if _, err := pool.Exec(ctx, `UPDATE component_repo.tasks SET lease_expires_at=now()-interval '1 second' WHERE id=$1`, claimed.ID); err != nil {
		t.Fatalf("expire crashed verification lease: %v", err)
	}
	if recovered, err := taskService.RecoverExpired(ctx); err != nil || !recovered {
		t.Fatalf("recover crashed verification task = %v, %v", recovered, err)
	}
	reclaimed, found, err := taskService.Claim(ctx, "artifact-worker-retry", []string{task.ArtifactVerifyType}, time.Minute)
	if err != nil || !found || reclaimed.Attempt != 2 {
		t.Fatalf("reclaim artifact verification task = %+v found=%v error=%v", reclaimed, found, err)
	}
	result, err := NewVerificationTaskHandler(service).Handle(ctx, reclaimed)
	if err != nil || store.openCount != 1 {
		t.Fatalf("idempotent verification retry = %v opens=%d", err, store.openCount)
	}
	if err := taskService.Complete(ctx, "artifact-worker-retry", reclaimed, result); err != nil {
		t.Fatalf("complete artifact verification task: %v", err)
	}
	parseTask, found, err := taskService.Claim(ctx, "go-parser", []string{task.ImportParseType}, time.Minute)
	if err != nil || !found || parseTask.Locale != "zh-CN" || parseTask.Timezone != "Asia/Shanghai" {
		t.Fatalf("claim unblocked parse task = %+v found=%v error=%v", parseTask, found, err)
	}
	var verificationStatus string
	artifactID := session.Uploads[0].ArtifactID
	if err := pool.QueryRow(ctx, `SELECT verification_status FROM component_repo.artifacts WHERE id=$1`, artifactID).Scan(&verificationStatus); err != nil || verificationStatus != "verified" || store.openCount != 1 {
		t.Fatalf("single-read task verification status=%q error=%v opens=%d", verificationStatus, err, store.openCount)
	}
	var uploadFileStatus string
	if err := pool.QueryRow(ctx, `SELECT status FROM component_repo.upload_session_files WHERE artifact_id=$1`, artifactID).Scan(&uploadFileStatus); err != nil || uploadFileStatus != "verified" {
		t.Fatalf("verified upload file state = %q %v", uploadFileStatus, err)
	}
	verifiedAgain, err := service.VerifyOwnedArtifact(ctx, actor, artifactID)
	if err != nil || verifiedAgain.VerificationStatus != "verified" || store.openCount != 1 {
		t.Fatalf("idempotent verification reread body: %+v %v opens=%d", verifiedAgain, err, store.openCount)
	}
	download, err := service.CreateDownload(ctx, actor, "user-jwt", artifactID)
	if err != nil || !strings.Contains(download.URL, artifactID) || store.signCount != 1 {
		t.Fatalf("signed download failed: %+v %v", download, err)
	}
	if _, err := service.CreateDownload(ctx, otherActor, "other-jwt", artifactID); publicCode(err) != "component_repo.artifact_not_found" {
		t.Fatalf("cross-owner download error = %v", err)
	}
	parseHandler := ingestion.NewImportParseTaskHandler(pool, store, config.ImportConfig{
		ParserVersion: "component-repo-ldraw-parser-v2", SnapshotSchema: "component-repo-v2",
	})
	parseResult, err := parseHandler.Handle(ctx, parseTask)
	if err != nil {
		t.Fatalf("handle Go import parse task: %v", err)
	}
	var previewTaskID, previewPrerequisiteID string
	var previewTaskStatus string
	if err := pool.QueryRow(ctx, `
		SELECT preview.id::text, preview.status, dependency.prerequisite_task_id::text
		FROM component_repo.imports import_job
		JOIN component_repo.candidates candidate ON candidate.import_id = import_job.id
		JOIN component_repo.component_versions version ON version.component_candidate_id = candidate.id
		JOIN component_repo.tasks preview ON preview.id = version.preview_task_id
		JOIN component_repo.task_dependencies dependency ON dependency.task_id = preview.id
		WHERE import_job.id = $1`, completed.ImportID).Scan(
		&previewTaskID, &previewTaskStatus, &previewPrerequisiteID,
	); err != nil || previewTaskStatus != "queued" || previewPrerequisiteID != uuidutil.String(parseTask.ID) {
		t.Fatalf("persisted preview continuation id=%q status=%q prerequisite=%q error=%v", previewTaskID, previewTaskStatus, previewPrerequisiteID, err)
	}
	if _, found, err := taskService.Claim(ctx, "preview-too-early", []string{task.PreviewMaterializeType}, time.Minute); err != nil || found {
		t.Fatalf("preview task bypassed parse dependency: found=%v error=%v", found, err)
	}
	if _, err := parseHandler.Handle(ctx, parseTask); err != nil {
		t.Fatalf("idempotent parse retry did not preserve preview continuation: %v", err)
	}
	var previewTaskCount int
	if err := pool.QueryRow(ctx, `SELECT count(*) FROM component_repo.tasks WHERE task_type=$1`, task.PreviewMaterializeType).Scan(&previewTaskCount); err != nil || previewTaskCount != 1 {
		t.Fatalf("idempotent preview continuation count=%d error=%v", previewTaskCount, err)
	}
	if err := taskService.Complete(ctx, "go-parser", parseTask, parseResult); err != nil {
		t.Fatalf("complete Go import parse task: %v", err)
	}
	if _, found, err := taskService.Claim(ctx, "preview-worker", []string{task.PreviewMaterializeType}, time.Minute); err != nil || !found {
		t.Fatalf("claim unblocked preview task: found=%v error=%v", found, err)
	}
	var importStatus string
	var candidateCount, versionCount int
	if err := pool.QueryRow(ctx, `
		SELECT import_job.status,
		       (SELECT count(*) FROM component_repo.candidates WHERE import_id = import_job.id),
		       (SELECT count(*) FROM component_repo.component_versions version
		        JOIN component_repo.candidates candidate ON candidate.id = version.component_candidate_id
		        WHERE candidate.import_id = import_job.id AND version.deleted_at IS NULL)
		FROM component_repo.imports import_job WHERE import_job.id=$1`, completed.ImportID).Scan(
		&importStatus, &candidateCount, &versionCount,
	); err != nil || importStatus != "succeeded" || candidateCount != 1 || versionCount != 1 {
		t.Fatalf("Go import parse result status=%q candidates=%d versions=%d err=%v", importStatus, candidateCount, versionCount, err)
	}
	importView, err := ingestion.NewService(pool).GetImport(ctx, actor, completed.ImportID)
	if err != nil || importView.ProcessingStatus != "processing" || importView.PreviewTaskID == nil || *importView.PreviewTaskID != previewTaskID {
		t.Fatalf("aggregate import state = %+v error=%v", importView, err)
	}

	testPartialFailureCompensation(t, ctx, pool, service, store, actor)
	testExpiredUploadCleanup(t, ctx, pool, service, store, actor)
}

func testPartialFailureCompensation(t *testing.T, ctx context.Context, pool *pgxpool.Pool, service *Service, store *fakeStore, actor pgtype.UUID) {
	t.Helper()
	content := []byte("bad-size")
	digest := sha256.Sum256(content)
	session, err := service.CreateUploadSession(ctx, actor, CreateUploadSessionInput{
		SourceFile:    FileSpec{Filename: "bad.io", FileSize: int64(len(content) + 1), SHA256: hex.EncodeToString(digest[:])},
		ContentLocale: "en-US", Timezone: "UTC",
	})
	if err != nil {
		t.Fatalf("create mismatch session: %v", err)
	}
	store.put(session.Uploads[0].ObjectPath, content, "application/octet-stream")
	_, err = service.CompleteUploadSession(ctx, actor, "user-jwt", session.ID)
	if publicCode(err) != "component_repo.upload_session_complete_failed" {
		t.Fatalf("mismatch completion error = %v", err)
	}
	if store.exists(session.Uploads[0].ObjectPath) {
		t.Fatalf("failed upload object was not compensated")
	}
	var status string
	if err := pool.QueryRow(ctx, `SELECT status FROM component_repo.upload_sessions WHERE id=$1`, session.ID).Scan(&status); err != nil || status != "failed" {
		t.Fatalf("failed session state = %q %v", status, err)
	}
	var artifactCount int
	if err := pool.QueryRow(ctx, `SELECT count(*) FROM component_repo.artifacts WHERE id=$1`, session.Uploads[0].ArtifactID).Scan(&artifactCount); err != nil || artifactCount != 0 {
		t.Fatalf("partial artifact metadata survived: count=%d err=%v", artifactCount, err)
	}
}

func testExpiredUploadCleanup(t *testing.T, ctx context.Context, pool *pgxpool.Pool, service *Service, store *fakeStore, actor pgtype.UUID) {
	t.Helper()
	content := []byte("expired")
	digest := sha256.Sum256(content)
	session, err := service.CreateUploadSession(ctx, actor, CreateUploadSessionInput{
		SourceFile:    FileSpec{Filename: "expired.mpd", FileSize: int64(len(content)), SHA256: hex.EncodeToString(digest[:])},
		ContentLocale: "en-US", Timezone: "UTC",
	})
	if err != nil {
		t.Fatalf("create expired session: %v", err)
	}
	store.put(session.Uploads[0].ObjectPath, content, "text/plain")
	if _, err := pool.Exec(ctx, `UPDATE component_repo.upload_sessions SET created_at=now()-interval '2 hours', expires_at=now()-interval '1 hour' WHERE id=$1`, session.ID); err != nil {
		t.Fatalf("expire fixture: %v", err)
	}
	cleaned, err := service.CleanupExpired(ctx, time.Now(), 10)
	if err != nil || cleaned != 1 || store.exists(session.Uploads[0].ObjectPath) {
		t.Fatalf("expired cleanup = %d, %v", cleaned, err)
	}
	var status string
	if err := pool.QueryRow(ctx, `SELECT status FROM component_repo.upload_sessions WHERE id=$1`, session.ID).Scan(&status); err != nil || status != "expired" {
		t.Fatalf("expired session state = %q %v", status, err)
	}
}

type fakeObject struct {
	content     []byte
	contentType string
}

type fakeStore struct {
	mu                                           sync.Mutex
	objects                                      map[string]fakeObject
	headCount, openCount, deleteCount, signCount int
}

func newFakeStore() *fakeStore      { return &fakeStore{objects: map[string]fakeObject{}} }
func (*fakeStore) Provider() string { return "supabase" }
func (*fakeStore) Bucket() string   { return "component-artifacts" }
func (s *fakeStore) Head(_ context.Context, key string) (storage.ObjectMetadata, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.headCount++
	object, ok := s.objects[key]
	if !ok {
		return storage.ObjectMetadata{}, storage.ErrNotFound
	}
	return storage.ObjectMetadata{Size: int64(len(object.content)), ContentType: object.contentType}, nil
}
func (s *fakeStore) HeadForUser(ctx context.Context, key, _ string) (storage.ObjectMetadata, error) {
	return s.Head(ctx, key)
}
func (s *fakeStore) Open(_ context.Context, key string) (io.ReadCloser, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.openCount++
	object, ok := s.objects[key]
	if !ok {
		return nil, storage.ErrNotFound
	}
	return io.NopCloser(bytes.NewReader(object.content)), nil
}

func (s *fakeStore) Put(_ context.Context, key, contentType string, body io.Reader, _ int64) error {
	content, err := io.ReadAll(body)
	if err != nil {
		return err
	}
	s.put(key, content, contentType)
	return nil
}
func (s *fakeStore) Delete(_ context.Context, key string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.deleteCount++
	delete(s.objects, key)
	return nil
}
func (s *fakeStore) SignDownload(_ context.Context, key string, _ time.Duration) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.signCount++
	return "https://storage.invalid/" + pathTail(key), nil
}
func (s *fakeStore) SignDownloads(_ context.Context, keys []string, _ time.Duration) (map[string]string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.signCount++
	result := make(map[string]string, len(keys))
	for _, key := range keys {
		result[key] = "https://storage.invalid/" + pathTail(key)
	}
	return result, nil
}
func (s *fakeStore) SignDownloadForUser(ctx context.Context, key string, ttl time.Duration, _ string) (string, error) {
	return s.SignDownload(ctx, key, ttl)
}
func (s *fakeStore) put(key string, content []byte, contentType string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.objects[key] = fakeObject{content: append([]byte(nil), content...), contentType: contentType}
}
func (s *fakeStore) exists(key string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	_, ok := s.objects[key]
	return ok
}

func pathTail(key string) string {
	parts := strings.Split(key, "/")
	return parts[len(parts)-1]
}

func mustUUID(t *testing.T, value string) pgtype.UUID {
	t.Helper()
	id, err := uuidutil.Parse(value)
	if err != nil {
		t.Fatalf("parse UUID: %v", err)
	}
	return id
}

func publicCode(err error) string {
	var public *apierror.Error
	if errors.As(err, &public) {
		return public.Code
	}
	return ""
}
