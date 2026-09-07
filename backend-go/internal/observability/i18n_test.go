package observability

import (
	"encoding/json"
	"fmt"
	"github.com/gin-gonic/gin"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// TestI18nTelemetryBoundary 覆盖匿名上报、结构化拒绝、容量限制及时间窗口，不依赖 Python。
func TestI18nTelemetryBoundary(t *testing.T) {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	m := NewI18nTelemetry()
	now := time.Date(2026, 9, 6, 0, 0, 0, 0, time.UTC)
	m.now = func() time.Time { return now }
	m.Register(r)
	post := func(body string) int {
		w := httptest.NewRecorder()
		r.ServeHTTP(w, httptest.NewRequest("POST", "/api/v1/i18n/events", strings.NewReader(body)))
		return w.Code
	}
	if post(`{"kind":"bad","locale":"en-US","namespace":"app","code":"x"}`) != 422 {
		t.Fatal("invalid event accepted")
	}
	for i := 0; i < 1001; i++ {
		if post(fmt.Sprintf(`{"kind":"unknown_key","locale":"en-US","namespace":"app","code":"key.%d"}`, i)) != 204 {
			t.Fatal("event rejected")
		}
	}
	if len(m.counts) != 1000 || m.overflow != 1 {
		t.Fatal("unbounded dimensions")
	}
	now = now.Add(25 * time.Hour)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/i18n/metrics", nil))
	var got struct {
		Unknown  uint64 `json:"unknownKeyCount"`
		Hourly   []any  `json:"hourly"`
		Overflow uint64 `json:"metricOverflowCount"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil {
		t.Fatal(err)
	}
	if got.Unknown != 1000 || got.Overflow != 1 || len(got.Hourly) != 0 {
		t.Fatal("invalid metrics snapshot", w.Body.String())
	}
}
