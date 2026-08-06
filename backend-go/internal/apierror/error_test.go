package apierror

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/requestmeta"
	"github.com/gin-gonic/gin"
)

func TestWriteReturnsStableContract(t *testing.T) {
	gin.SetMode(gin.TestMode)
	recorder := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(recorder)
	c.Set(requestmeta.TraceIDKey, "req_test")

	Write(c, New("request.not_found", http.StatusNotFound, map[string]any{"resource": "component"}))

	if recorder.Code != http.StatusNotFound {
		t.Fatalf("status = %d", recorder.Code)
	}
	var body Response
	if err := json.Unmarshal(recorder.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if body.Error.Code != "request.not_found" || body.Error.TraceID != "req_test" {
		t.Fatalf("unexpected response: %+v", body)
	}
	if body.Error.Params["resource"] != "component" {
		t.Fatalf("unexpected params: %+v", body.Error.Params)
	}
}

func TestNewRejectsInvalidMachineCode(t *testing.T) {
	defer func() {
		if recover() == nil {
			t.Fatal("expected invalid code to panic")
		}
	}()
	New("not valid", http.StatusBadRequest, nil)
}
