package httpapi

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
	"github.com/gin-gonic/gin"
)

type stubPinger struct{ err error }

func (p stubPinger) Ping(context.Context) error { return p.err }

func TestLiveHealthIncludesTraceID(t *testing.T) {
	router := testRouter(t, stubPinger{})
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/health/live", nil)
	request.Header.Set("X-Trace-Id", "req_from_proxy")

	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d", recorder.Code)
	}
	if recorder.Header().Get("X-Trace-Id") != "req_from_proxy" {
		t.Fatalf("trace header = %q", recorder.Header().Get("X-Trace-Id"))
	}
}

func TestReadyHealthDoesNotExposeDatabaseError(t *testing.T) {
	router := testRouter(t, stubPinger{err: errors.New("password and host must stay internal")})
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/health/ready", nil)

	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d", recorder.Code)
	}
	if strings.Contains(recorder.Body.String(), "password") || strings.Contains(recorder.Body.String(), "host") {
		t.Fatalf("response leaked database error: %s", recorder.Body.String())
	}
	if !strings.Contains(recorder.Body.String(), `"database":"unavailable"`) {
		t.Fatalf("unexpected response: %s", recorder.Body.String())
	}
}

func TestPanicReturnsInternalErrorWithoutPanicText(t *testing.T) {
	router := testRouter(t, stubPinger{})
	router.GET("/panic", func(*gin.Context) { panic("secret panic detail") })
	recorder := httptest.NewRecorder()

	router.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/panic", nil))

	if recorder.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d", recorder.Code)
	}
	if strings.Contains(recorder.Body.String(), "secret") {
		t.Fatalf("response leaked panic: %s", recorder.Body.String())
	}
	var response apierror.Response
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if response.Error.Code != "common.internal_error" || response.Error.TraceID == "" {
		t.Fatalf("unexpected error response: %+v", response)
	}
}

func TestNoRouteUsesStructuredError(t *testing.T) {
	router := testRouter(t, stubPinger{})
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/missing", nil))

	if recorder.Code != http.StatusNotFound || !strings.Contains(recorder.Body.String(), `"code":"request.not_found"`) {
		t.Fatalf("unexpected response: %d %s", recorder.Code, recorder.Body.String())
	}
}

func TestMiddlewareAppliesDeadlineAndBodyLimit(t *testing.T) {
	cfg := testConfig()
	cfg.HTTP.MaxBodyBytes = 4
	router := NewRouter(cfg, stubPinger{}, slog.New(slog.NewTextHandler(io.Discard, nil)))
	router.POST("/inspect", func(c *gin.Context) {
		if _, ok := c.Request.Context().Deadline(); !ok {
			c.Status(http.StatusInternalServerError)
			return
		}
		_, err := io.ReadAll(c.Request.Body)
		if err == nil {
			c.Status(http.StatusNoContent)
			return
		}
		c.Status(http.StatusRequestEntityTooLarge)
	})
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, httptest.NewRequest(http.MethodPost, "/inspect", bytes.NewBufferString("12345")))
	if recorder.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("status = %d", recorder.Code)
	}
}

func TestGoSessionRouteConfirmsUserThroughSupabaseAuth(t *testing.T) {
	const actorID = "00000000-0000-0000-0000-000000000001"
	provider := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.Header.Get("apikey") != "publishable-key" || request.Header.Get("Authorization") == "" {
			t.Fatalf("unexpected provider headers: %+v", request.Header)
		}
		response.Header().Set("Content-Type", "application/json")
		_, _ = response.Write([]byte(`{"id":"` + actorID + `","email":"user@example.com"}`))
	}))
	defer provider.Close()

	cfg := testConfig()
	cfg.Auth = config.AuthConfig{
		JWTSecret:                  testRouterJWTSecret,
		JWTIssuer:                  "router-test",
		JWTAudience:                "authenticated",
		SessionVerificationURL:     provider.URL,
		PublishableKey:             "publishable-key",
		SessionVerificationTimeout: time.Second,
	}
	router := NewApplicationRouter(cfg, nil, slog.New(slog.NewTextHandler(io.Discard, nil)))
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/api/v1/auth/session", nil)
	request.Header.Set("Authorization", "Bearer "+routerToken(t, actorID))

	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK || !strings.Contains(recorder.Body.String(), `"authenticated":true`) ||
		!strings.Contains(recorder.Body.String(), `"email":"user@example.com"`) {
		t.Fatalf("session status/body = %d %s", recorder.Code, recorder.Body.String())
	}
}

func TestGoSessionRouteDoesNotConvertProviderOutageIntoLogout(t *testing.T) {
	provider := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, _ *http.Request) {
		response.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer provider.Close()

	cfg := testConfig()
	cfg.Auth = config.AuthConfig{
		JWTSecret:                  testRouterJWTSecret,
		JWTIssuer:                  "router-test",
		JWTAudience:                "authenticated",
		SessionVerificationURL:     provider.URL,
		PublishableKey:             "publishable-key",
		SessionVerificationTimeout: time.Second,
	}
	router := NewApplicationRouter(cfg, nil, slog.New(slog.NewTextHandler(io.Discard, nil)))
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/api/v1/auth/session", nil)
	request.Header.Set("Authorization", "Bearer "+routerToken(t, "00000000-0000-0000-0000-000000000001"))

	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusServiceUnavailable ||
		!strings.Contains(recorder.Body.String(), `"code":"auth.session_verification_unavailable"`) {
		t.Fatalf("session outage status/body = %d %s", recorder.Code, recorder.Body.String())
	}
}

func testRouter(t *testing.T, pinger stubPinger) *gin.Engine {
	t.Helper()
	return NewRouter(testConfig(), pinger, slog.New(slog.NewTextHandler(io.Discard, nil)))
}

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

const testRouterJWTSecret = "0123456789abcdef0123456789abcdef"

func routerToken(t *testing.T, subject string) string {
	t.Helper()
	header, _ := json.Marshal(map[string]any{"alg": "HS256", "typ": "JWT"})
	claims, _ := json.Marshal(map[string]any{
		"sub": subject,
		"exp": time.Now().Add(time.Minute).Unix(),
		"iss": "router-test",
		"aud": "authenticated",
	})
	unsigned := base64.RawURLEncoding.EncodeToString(header) + "." + base64.RawURLEncoding.EncodeToString(claims)
	signature := hmac.New(sha256.New, []byte(testRouterJWTSecret))
	_, _ = signature.Write([]byte(unsigned))
	return unsigned + "." + base64.RawURLEncoding.EncodeToString(signature.Sum(nil))
}
