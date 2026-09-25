//go:build integration

package httpapi_test

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
	. "github.com/ctbzbricks/brickbuilder/backend-go/internal/httpapi"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5/pgxpool"
)

const integrationJWTSecret = "0123456789abcdef0123456789abcdef"

func testConfig() config.Config {
	return config.Config{
		Environment: config.TestEnvironment,
		HTTP: config.HTTPConfig{
			RequestTimeout:  time.Second,
			MaxBodyBytes:    1024,
			ShutdownTimeout: time.Second,
		},
		Database: config.DatabaseConfig{ConnectTimeout: time.Second},
	}
}

func TestPartSearchHTTPContract(t *testing.T) {
	databaseURL := os.Getenv("TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatalf("connect PostgreSQL: %v", err)
	}
	defer pool.Close()
	if _, err := pool.Exec(ctx, `
		TRUNCATE component_repo.part_library_versions CASCADE;
		INSERT INTO component_repo.part_library_versions
			(id,source_name,source_hash,connector_count,status,created_by)
		VALUES ('31000000-0000-0000-0000-000000000001','fixture',repeat('a',64),0,'active',
			'31000000-0000-0000-0000-000000000002');
		INSERT INTO component_repo.parts
			(part_library_version_id,ldraw_part_num,source_name,content_locale)
		VALUES
			('31000000-0000-0000-0000-000000000001','3001.dat','Brick 2 x 4','en-US'),
			('31000000-0000-0000-0000-000000000001','sticker.dat','Sticker irregular outline','en-US');
		INSERT INTO component_repo.part_geometries
			(part_library_version_id,ldraw_part_num,source_relative_path,source_file_hash,
			 bbox_min,bbox_max,logical_width_stud,logical_depth_stud,logical_height_plate,
			 vertex_count,face_count,logical_size_derivation_status)
		VALUES
			('31000000-0000-0000-0000-000000000001','3001.dat','parts/3001.dat',repeat('b',64),
			 ARRAY[0,0,0]::float8[],ARRAY[40,24,80]::float8[],2,4,3,3,1,'derived_exact'),
			('31000000-0000-0000-0000-000000000001','sticker.dat','parts/sticker.dat',repeat('c',64),
			 ARRAY[0,0,0]::float8[],ARRAY[44,28,64]::float8[],2.2,3.2,3.5,3,1,'derived_approximate')`); err != nil {
		t.Fatalf("seed Part search fixture: %v", err)
	}

	cfg := testConfig()
	cfg.Auth = config.AuthConfig{JWTSecret: integrationJWTSecret, JWTIssuer: "g3-test", JWTAudience: "authenticated"}
	router := NewApplicationRouter(cfg, pool, slog.New(slog.NewTextHandler(io.Discard, nil)))

	unauthorized := httptest.NewRecorder()
	router.ServeHTTP(unauthorized, httptest.NewRequest(http.MethodPost, "/api/v1/parts/search", strings.NewReader(`{"partNumber":"3001"}`)))
	assertPublicError(t, unauthorized, http.StatusUnauthorized, "auth.authentication_required")

	request := httptest.NewRequest(http.MethodPost, "/api/v1/parts/search", strings.NewReader(`{"description":"brick","partNumber":"3001","widthStud":4,"depthStud":2,"heightPlate":3,"locale":"en-US","page":1,"pageSize":20}`))
	request.Header.Set("Authorization", "Bearer "+integrationToken(t, "31000000-0000-0000-0000-000000000003"))
	request.Header.Set("Content-Type", "application/json")
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	if response.Code != http.StatusOK || !strings.Contains(response.Body.String(), `"partLibraryVersionId":"31000000-0000-0000-0000-000000000001"`) ||
		!strings.Contains(response.Body.String(), `"ldrawPartNum":"3001.dat"`) {
		t.Fatalf("Part search status/body = %d %s", response.Code, response.Body.String())
	}

	request = httptest.NewRequest(http.MethodPost, "/api/v1/parts/search", strings.NewReader(`{"description":"sticker outline","widthStud":3.45,"depthStud":2.45,"heightPlate":4.125,"locale":"en-US","page":1,"pageSize":20}`))
	request.Header.Set("Authorization", "Bearer "+integrationToken(t, "31000000-0000-0000-0000-000000000003"))
	request.Header.Set("Content-Type", "application/json")
	response = httptest.NewRecorder()
	router.ServeHTTP(response, request)
	if response.Code != http.StatusOK || !strings.Contains(response.Body.String(), `"ldrawPartNum":"sticker.dat"`) ||
		!strings.Contains(response.Body.String(), `"logicalSizeDerivationStatus":"derived_approximate"`) {
		t.Fatalf("Part bbox search status/body = %d %s", response.Code, response.Body.String())
	}

	unknownRequest := httptest.NewRequest(http.MethodPost, "/api/v1/parts/search", strings.NewReader(`{"partNumber":"3001","candidateTypes":["part"]}`))
	unknownRequest.Header.Set("Authorization", "Bearer "+integrationToken(t, "31000000-0000-0000-0000-000000000003"))
	unknownResponse := httptest.NewRecorder()
	router.ServeHTTP(unknownResponse, unknownRequest)
	assertPublicError(t, unknownResponse, http.StatusUnprocessableEntity, "request.validation_failed")
}

func TestG3HTTPAuthenticationAndErrorContract(t *testing.T) {
	databaseURL := os.Getenv("TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatalf("connect PostgreSQL: %v", err)
	}
	defer pool.Close()
	if _, err := pool.Exec(ctx, `
		TRUNCATE component_repo.components, component_repo.artifacts,
		         component_repo.component_groups, component_repo.tasks
		RESTART IDENTITY CASCADE`); err != nil {
		t.Fatalf("reset HTTP fixtures: %v", err)
	}

	cfg := testConfig()
	cfg.Auth = config.AuthConfig{JWTSecret: integrationJWTSecret, JWTIssuer: "g3-test", JWTAudience: "authenticated"}
	router := NewApplicationRouter(cfg, pool, slog.New(slog.NewTextHandler(io.Discard, nil)))

	unauthorized := httptest.NewRecorder()
	router.ServeHTTP(unauthorized, httptest.NewRequest(http.MethodGet, "/api/v1/components", nil))
	assertPublicError(t, unauthorized, http.StatusUnauthorized, "auth.authentication_required")

	actorAToken := integrationToken(t, "30000000-0000-0000-0000-000000000001")
	catalog := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/api/v1/components?limit=20&locale=en-US", nil)
	request.Header.Set("Authorization", "Bearer "+actorAToken)
	router.ServeHTTP(catalog, request)
	if catalog.Code != http.StatusOK || !strings.Contains(catalog.Body.String(), `"items":[]`) ||
		!strings.Contains(catalog.Body.String(), `"nextCursor":null`) || strings.Contains(catalog.Body.String(), `"total"`) {
		t.Fatalf("Component catalog status/body = %d %s", catalog.Code, catalog.Body.String())
	}

	// Star 公共分页只返回可见结果的精确总数；删除清理中的内部关系量不得泄露到 HTTP 契约。
	stars := httptest.NewRecorder()
	request = httptest.NewRequest(http.MethodGet, "/api/v1/component-stars?page=1&pageSize=20&locale=en-US", nil)
	request.Header.Set("Authorization", "Bearer "+actorAToken)
	router.ServeHTTP(stars, request)
	if stars.Code != http.StatusOK || !strings.Contains(stars.Body.String(), `"items":[]`) ||
		!strings.Contains(stars.Body.String(), `"total":0`) || strings.Contains(stars.Body.String(), `"relationshipTotal"`) {
		t.Fatalf("Star list status/body = %d %s", stars.Code, stars.Body.String())
	}

	importHistory := httptest.NewRecorder()
	request = httptest.NewRequest(http.MethodGet, "/api/v1/component-imports?page=1&pageSize=20", nil)
	request.Header.Set("Authorization", "Bearer "+actorAToken)
	router.ServeHTTP(importHistory, request)
	if importHistory.Code != http.StatusOK || !strings.Contains(importHistory.Body.String(), `"items":[]`) {
		t.Fatalf("import history status/body = %d %s", importHistory.Code, importHistory.Body.String())
	}

	watchFeed := httptest.NewRecorder()
	request = httptest.NewRequest(http.MethodGet, "/api/v1/component-watch-feed?since=2026-09-01T00:00:00Z&limit=20", nil)
	request.Header.Set("Authorization", "Bearer "+actorAToken)
	router.ServeHTTP(watchFeed, request)
	if watchFeed.Code != http.StatusOK || !strings.Contains(watchFeed.Body.String(), `"items":[]`) ||
		!strings.Contains(watchFeed.Body.String(), `"windowStart":"2026-09-01T00:00:00Z"`) {
		t.Fatalf("Watch Feed status/body = %d %s", watchFeed.Code, watchFeed.Body.String())
	}

	publicFeed := httptest.NewRecorder()
	request = httptest.NewRequest(http.MethodGet, "/api/v1/component-public-feed?limit=20", nil)
	request.Header.Set("Authorization", "Bearer "+actorAToken)
	router.ServeHTTP(publicFeed, request)
	if publicFeed.Code != http.StatusOK || !strings.Contains(publicFeed.Body.String(), `"items":[]`) ||
		!strings.Contains(publicFeed.Body.String(), `"nextCursor":null`) {
		t.Fatalf("public Feed status/body = %d %s", publicFeed.Code, publicFeed.Body.String())
	}
	invalidStructuredFilter := httptest.NewRecorder()
	request = httptest.NewRequest(http.MethodGet, "/api/v1/component-public-feed?widthStud=bad", nil)
	request.Header.Set("Authorization", "Bearer "+actorAToken)
	router.ServeHTTP(invalidStructuredFilter, request)
	assertPublicError(t, invalidStructuredFilter, http.StatusUnprocessableEntity, "request.validation_failed")

	clientSuppliedKey := httptest.NewRecorder()
	request = httptest.NewRequest(http.MethodPost, "/api/v1/component-imports/upload-sessions", strings.NewReader(`{
		"sourceFile":{"filename":"model.ldr","contentType":"text/plain","fileSize":10,"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","objectPath":"client/chosen/key"},
		"contentLocale":"en-US","timezone":"UTC"
	}`))
	request.Header.Set("Authorization", "Bearer "+actorAToken)
	request.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(clientSuppliedKey, request)
	assertPublicError(t, clientSuppliedKey, http.StatusUnprocessableEntity, "request.validation_failed")

	disabledStorage := httptest.NewRecorder()
	request = httptest.NewRequest(http.MethodPost, "/api/v1/component-imports/upload-sessions", strings.NewReader(`{
		"sourceFile":{"filename":"model.ldr","contentType":"text/plain","fileSize":10,"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
		"contentLocale":"en-US","timezone":"UTC"
	}`))
	request.Header.Set("Authorization", "Bearer "+actorAToken)
	request.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(disabledStorage, request)
	assertPublicError(t, disabledStorage, http.StatusBadGateway, "component_repo.storage_unavailable")

	// Component 与初始 Draft Version 只能由 Import Parse Worker 原子创建，公开 HTTP 不再暴露拆分写入口。
	removedCreate := httptest.NewRecorder()
	request = httptest.NewRequest(http.MethodPost, "/api/v1/components", strings.NewReader(`{
		"name":"API component","contentLocale":"en-US","tags":[]
	}`))
	request.Header.Set("Authorization", "Bearer "+actorAToken)
	request.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(removedCreate, request)
	assertPublicError(t, removedCreate, http.StatusMethodNotAllowed, "request.method_not_allowed")
	removedVersionCreate := httptest.NewRecorder()
	request = httptest.NewRequest(http.MethodPost, "/api/v1/components/30000000-0000-0000-0000-000000000010/versions", strings.NewReader(`{
		"componentCandidateId":"30000000-0000-0000-0000-000000000010",
		"version":"1.0.0","revision":1,
		"sourceArtifactId":"30000000-0000-0000-0000-000000000011"
	}`))
	request.Header.Set("Authorization", "Bearer "+actorAToken)
	request.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(removedVersionCreate, request)
	assertPublicError(t, removedVersionCreate, http.StatusMethodNotAllowed, "request.method_not_allowed")

	actorBToken := integrationToken(t, "30000000-0000-0000-0000-000000000002")
	crossUser := httptest.NewRecorder()
	request = httptest.NewRequest(http.MethodPatch, "/api/v1/components/30000000-0000-0000-0000-000000000010", strings.NewReader(`{"name":"forbidden"}`))
	request.Header.Set("Authorization", "Bearer "+actorBToken)
	router.ServeHTTP(crossUser, request)
	assertPublicError(t, crossUser, http.StatusNotFound, "component_repo.component_not_found")
}

func TestG5TaskHTTPContract(t *testing.T) {
	databaseURL := os.Getenv("TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatalf("connect PostgreSQL: %v", err)
	}
	defer pool.Close()
	if _, err := pool.Exec(ctx, `TRUNCATE component_repo.tasks, component_repo.outbox_events RESTART IDENTITY CASCADE`); err != nil {
		t.Fatalf("reset task HTTP fixtures: %v", err)
	}

	cfg := testConfig()
	cfg.Auth = config.AuthConfig{JWTSecret: integrationJWTSecret, JWTIssuer: "g3-test", JWTAudience: "authenticated"}
	router := NewApplicationRouter(cfg, pool, slog.New(slog.NewTextHandler(io.Discard, nil)))
	actorID, _ := uuidutil.Parse("30000000-0000-0000-0000-000000000001")
	created, _, err := task.NewService(pool).Enqueue(ctx, task.EnqueueInput{
		OwnerID: actorID, TaskType: task.ArtifactVerifyType,
		Payload: json.RawMessage(`{"artifactId":"30000000-0000-0000-0000-000000000099"}`),
		Locale:  "en-US", Timezone: "UTC", CreatedBy: actorID,
		IdempotencyKey: "http-task", MaxAttempts: 3, AvailableAt: time.Now().UTC(),
	})
	if err != nil {
		t.Fatalf("enqueue HTTP task fixture: %v", err)
	}
	actorToken := integrationToken(t, uuidutil.String(actorID))

	get := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/api/v1/tasks/"+created.ID, nil)
	request.Header.Set("Authorization", "Bearer "+actorToken)
	router.ServeHTTP(get, request)
	if get.Code != http.StatusOK || !strings.Contains(get.Body.String(), `"status":"queued"`) || strings.Contains(get.Body.String(), `"payload"`) {
		t.Fatalf("task GET status/body = %d %s", get.Code, get.Body.String())
	}

	other := httptest.NewRecorder()
	request = httptest.NewRequest(http.MethodGet, "/api/v1/tasks/"+created.ID, nil)
	request.Header.Set("Authorization", "Bearer "+integrationToken(t, "30000000-0000-0000-0000-000000000002"))
	router.ServeHTTP(other, request)
	assertPublicError(t, other, http.StatusNotFound, "request.not_found")

	cancel := httptest.NewRecorder()
	request = httptest.NewRequest(http.MethodPost, "/api/v1/tasks/"+created.ID+"/cancel", nil)
	request.Header.Set("Authorization", "Bearer "+actorToken)
	router.ServeHTTP(cancel, request)
	if cancel.Code != http.StatusOK || !strings.Contains(cancel.Body.String(), `"status":"cancelled"`) {
		t.Fatalf("task cancel status/body = %d %s", cancel.Code, cancel.Body.String())
	}
}

func assertPublicError(t *testing.T, recorder *httptest.ResponseRecorder, status int, code string) {
	t.Helper()
	if recorder.Code != status {
		t.Fatalf("status/body = %d %s, want %d", recorder.Code, recorder.Body.String(), status)
	}
	var response apierror.Response
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("decode public error: %v", err)
	}
	if response.Error.Code != code || response.Error.TraceID == "" {
		t.Fatalf("unexpected public error: %+v", response)
	}
}

func integrationToken(t *testing.T, subject string) string {
	t.Helper()
	header, _ := json.Marshal(map[string]any{"alg": "HS256", "typ": "JWT"})
	claims, _ := json.Marshal(map[string]any{
		"sub": subject, "exp": time.Now().Add(time.Minute).Unix(),
		"iss": "g3-test", "aud": "authenticated",
	})
	unsigned := base64.RawURLEncoding.EncodeToString(header) + "." + base64.RawURLEncoding.EncodeToString(claims)
	signature := hmac.New(sha256.New, []byte(integrationJWTSecret))
	_, _ = signature.Write([]byte(unsigned))
	return unsigned + "." + base64.RawURLEncoding.EncodeToString(signature.Sum(nil))
}
