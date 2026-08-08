//go:build integration

package httpapi

import (
	"bytes"
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
	"github.com/jackc/pgx/v5/pgxpool"
)

const integrationJWTSecret = "0123456789abcdef0123456789abcdef"

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
	create := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodPost, "/api/v1/components", bytes.NewBufferString(`{
		"name":"API component","contentLocale":"en-US","tags":[]
	}`))
	request.Header.Set("Authorization", "Bearer "+actorAToken)
	request.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(create, request)
	if create.Code != http.StatusCreated {
		t.Fatalf("create status/body = %d %s", create.Code, create.Body.String())
	}
	var created struct {
		ID string `json:"id"`
	}
	if err := json.Unmarshal(create.Body.Bytes(), &created); err != nil || created.ID == "" {
		t.Fatalf("decode created component: %+v, %v", created, err)
	}

	unknownField := httptest.NewRecorder()
	request = httptest.NewRequest(http.MethodPost, "/api/v1/components", strings.NewReader(`{
		"name":"bad","contentLocale":"en-US","unexpected":"internal detail"
	}`))
	request.Header.Set("Authorization", "Bearer "+actorAToken)
	router.ServeHTTP(unknownField, request)
	assertPublicError(t, unknownField, http.StatusUnprocessableEntity, "request.validation_failed")
	if strings.Contains(unknownField.Body.String(), "unexpected") || strings.Contains(unknownField.Body.String(), "internal detail") {
		t.Fatalf("validation response leaked decoder details: %s", unknownField.Body.String())
	}

	actorBToken := integrationToken(t, "30000000-0000-0000-0000-000000000002")
	crossUser := httptest.NewRecorder()
	request = httptest.NewRequest(http.MethodPatch, "/api/v1/components/"+created.ID, strings.NewReader(`{"name":"forbidden"}`))
	request.Header.Set("Authorization", "Bearer "+actorBToken)
	router.ServeHTTP(crossUser, request)
	assertPublicError(t, crossUser, http.StatusNotFound, "component_repo.component_not_found")
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
