package main

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/observability"
)

type testPinger struct{ err error }

func (p testPinger) Ping(context.Context) error { return p.err }

func TestMonitoringHandlerSeparatesLivenessReadinessAndMetrics(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	handler := newMonitoringHandler(testPinger{}, time.Second, observability.NewRegistry(), logger)

	for _, path := range []string{"/health/live", "/health/ready", "/metrics"} {
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, path, nil))
		if response.Code != http.StatusOK {
			t.Fatalf("%s status = %d", path, response.Code)
		}
	}
}

func TestMonitoringReadinessFailsClosedWhenDatabaseIsUnavailable(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	handler := newMonitoringHandler(testPinger{err: errors.New("database unavailable")}, time.Second, observability.NewRegistry(), logger)
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/health/ready", nil))
	if response.Code != http.StatusServiceUnavailable || !strings.Contains(response.Body.String(), `"database":"unavailable"`) {
		t.Fatalf("unexpected readiness response: status=%d body=%s", response.Code, response.Body.String())
	}
}
