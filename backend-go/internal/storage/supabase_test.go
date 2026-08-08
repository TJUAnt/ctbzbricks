package storage

import (
	"context"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (fn roundTripFunc) Do(request *http.Request) (*http.Response, error) { return fn(request) }

func TestSupabaseHeadUsesMetadataEndpointWithoutReadingObject(t *testing.T) {
	store := testSupabase(roundTripFunc(func(request *http.Request) (*http.Response, error) {
		if request.Method != http.MethodGet || request.URL.EscapedPath() != "/storage/v1/object/info/artifacts/owners/a/file%20name.io" {
			t.Fatalf("unexpected request: %s %s", request.Method, request.URL.String())
		}
		if request.Header.Get("apikey") != "key" || request.Header.Get("Authorization") != "Bearer token" {
			t.Fatalf("missing storage authorization headers")
		}
		return response(http.StatusOK, `{"size":42,"content_type":"application/octet-stream","etag":"v1"}`), nil
	}))
	metadata, err := store.Head(context.Background(), "owners/a/file name.io")
	if err != nil || metadata.Size != 42 || metadata.ContentType != "application/octet-stream" {
		t.Fatalf("unexpected metadata/error: %+v %v", metadata, err)
	}
}

func TestSupabaseSignedURLAndDelete(t *testing.T) {
	requests := 0
	store := testSupabase(roundTripFunc(func(request *http.Request) (*http.Response, error) {
		requests++
		switch request.Method {
		case http.MethodPost:
			return response(http.StatusOK, `{"signedURL":"/object/sign/artifacts/key?token=abc"}`), nil
		case http.MethodDelete:
			body, _ := io.ReadAll(request.Body)
			if string(body) != `{"prefixes":["key"]}` {
				t.Fatalf("unexpected delete body: %s", body)
			}
			return response(http.StatusNotFound, `{}`), nil
		default:
			t.Fatalf("unexpected method %s", request.Method)
			return nil, nil
		}
	}))
	signed, err := store.SignDownload(context.Background(), "key", 5*time.Minute)
	if err != nil || signed != "https://project.supabase.co/storage/v1/object/sign/artifacts/key?token=abc" {
		t.Fatalf("unexpected signed URL/error: %q %v", signed, err)
	}
	if err := store.Delete(context.Background(), "key"); err != nil {
		t.Fatalf("idempotent delete: %v", err)
	}
	if requests != 2 {
		t.Fatalf("requests = %d", requests)
	}
}

func testSupabase(client HTTPDoer) *Supabase {
	return NewSupabase(config.StorageConfig{
		SupabaseURL: "https://project.supabase.co", APIKey: "key",
		Authorization: "token", Bucket: "artifacts",
	}, client)
}

func response(status int, body string) *http.Response {
	return &http.Response{StatusCode: status, Body: io.NopCloser(strings.NewReader(body)), Header: make(http.Header)}
}
