package storage

import (
	"context"
	"encoding/json"
	"errors"
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
		if request.Header.Get("apikey") != "key" || request.Header.Get("Authorization") != "Bearer service-key" {
			t.Fatalf("missing storage authorization headers")
		}
		return response(http.StatusOK, `{"size":42,"content_type":"application/octet-stream","etag":"v1"}`), nil
	}))
	metadata, err := store.Head(context.Background(), "owners/a/file name.io")
	if err != nil || metadata.Size != 42 || metadata.ContentType != "application/octet-stream" {
		t.Fatalf("unexpected metadata/error: %+v %v", metadata, err)
	}
}

func TestSupabaseSecretKeyUsesAPIKeyHeaderWithoutBearer(t *testing.T) {
	store := NewSupabase(config.StorageConfig{
		SupabaseURL: "https://project.supabase.co", PublishableKey: "sb_publishable_browser",
		ServiceRoleKey: "sb_secret_worker", Bucket: "artifacts",
	}, roundTripFunc(func(request *http.Request) (*http.Response, error) {
		if request.Header.Get("apikey") != "sb_secret_worker" {
			t.Fatalf("server request did not use secret API key")
		}
		if authorization := request.Header.Get("Authorization"); authorization != "" {
			t.Fatalf("modern secret key must not be sent as Bearer authorization: %q", authorization)
		}
		return response(http.StatusOK, `{"size":42}`), nil
	}))

	if _, err := store.Head(context.Background(), "key"); err != nil {
		t.Fatalf("head with modern secret key: %v", err)
	}
}

func TestSupabaseSignedURLAndDelete(t *testing.T) {
	requests := 0
	store := testSupabase(roundTripFunc(func(request *http.Request) (*http.Response, error) {
		requests++
		switch request.Method {
		case http.MethodPost:
			if request.Header.Get("apikey") != "key" || request.Header.Get("Authorization") != "Bearer user-jwt" {
				t.Fatalf("signed URL must use publishable apikey and user JWT")
			}
			return response(http.StatusOK, `{"signedURL":"/object/sign/artifacts/key?token=abc"}`), nil
		case http.MethodDelete:
			if request.Header.Get("apikey") != "key" || request.Header.Get("Authorization") != "Bearer service-key" {
				t.Fatalf("server delete must use service credential")
			}
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
	signed, err := store.SignDownloadForUser(context.Background(), "key", 5*time.Minute, "user-jwt")
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

func TestSupabaseBatchSignUsesOneServerRequestAndKeepsPartialSuccess(t *testing.T) {
	requests := 0
	store := testSupabase(roundTripFunc(func(request *http.Request) (*http.Response, error) {
		requests++
		if request.Method != http.MethodPost || request.URL.EscapedPath() != "/storage/v1/object/sign/artifacts" {
			t.Fatalf("unexpected request: %s %s", request.Method, request.URL.String())
		}
		if request.Header.Get("apikey") != "key" || request.Header.Get("Authorization") != "Bearer service-key" {
			t.Fatalf("batch sign must use server credentials")
		}
		var body struct {
			ExpiresIn int64    `json:"expiresIn"`
			Paths     []string `json:"paths"`
		}
		if err := json.NewDecoder(request.Body).Decode(&body); err != nil {
			t.Fatal(err)
		}
		if body.ExpiresIn != 300 || len(body.Paths) != 2 || body.Paths[0] != "a.glb" || body.Paths[1] != "b.glb" {
			t.Fatalf("unexpected batch body: %+v", body)
		}
		return response(http.StatusOK, `[{"path":"a.glb","signedURL":"/object/sign/artifacts/a.glb?token=a"},{"path":"b.glb","error":"not_found"}]`), nil
	}))

	signed, err := store.SignDownloads(context.Background(), []string{"a.glb", "b.glb", "a.glb", ""}, 5*time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	if requests != 1 || len(signed) != 1 || signed["a.glb"] != "https://project.supabase.co/storage/v1/object/sign/artifacts/a.glb?token=a" {
		t.Fatalf("unexpected batch result/requests: %#v / %d", signed, requests)
	}
}

func TestSupabaseUserHeadUsesPublishableKeyAndJWT(t *testing.T) {
	store := testSupabase(roundTripFunc(func(request *http.Request) (*http.Response, error) {
		if request.Header.Get("apikey") != "key" || request.Header.Get("Authorization") != "Bearer user-jwt" {
			t.Fatalf("user head must use publishable apikey and user JWT")
		}
		return response(http.StatusOK, `{"size":42}`), nil
	}))
	metadata, err := store.HeadForUser(context.Background(), "key", "user-jwt")
	if err != nil || metadata.Size != 42 {
		t.Fatalf("unexpected user metadata/error: %+v %v", metadata, err)
	}
}

func TestSupabaseAPIOnlyConfigurationUsesJWTAndRejectsServerOperations(t *testing.T) {
	requests := 0
	store := NewSupabase(config.StorageConfig{
		SupabaseURL: "https://project.supabase.co", PublishableKey: "key", Bucket: "artifacts",
	}, roundTripFunc(func(request *http.Request) (*http.Response, error) {
		requests++
		if request.Header.Get("apikey") != "key" || request.Header.Get("Authorization") != "Bearer user-jwt" {
			t.Fatalf("request-scoped call must use publishable apikey and user JWT")
		}
		return response(http.StatusOK, `{"signedURL":"/object/sign/artifacts/key?token=abc"}`), nil
	}))

	if _, err := store.SignDownloadForUser(context.Background(), "key", time.Minute, "user-jwt"); err != nil {
		t.Fatalf("sign with user JWT: %v", err)
	}
	if _, err := store.SignDownload(context.Background(), "key", time.Minute); !errors.Is(err, ErrUnavailable) {
		t.Fatalf("server sign error = %v, want storage unavailable", err)
	}
	if _, err := store.Open(context.Background(), "key"); !errors.Is(err, ErrUnavailable) {
		t.Fatalf("server open error = %v, want storage unavailable", err)
	}
	if err := store.Put(context.Background(), "key", "application/octet-stream", strings.NewReader("x"), 1); !errors.Is(err, ErrUnavailable) {
		t.Fatalf("server put error = %v, want storage unavailable", err)
	}
	if requests != 1 {
		t.Fatalf("storage requests = %d, want only the request-scoped call", requests)
	}
}

func TestSupabasePutUsesServiceRoleUpsert(t *testing.T) {
	store := testSupabase(roundTripFunc(func(request *http.Request) (*http.Response, error) {
		if request.Method != http.MethodPost || request.URL.EscapedPath() != "/storage/v1/object/artifacts/owner/component-repo/previews/model.glb" {
			t.Fatalf("unexpected put request: %s %s", request.Method, request.URL.String())
		}
		if request.Header.Get("x-upsert") != "true" || request.Header.Get("Content-Type") != "model/gltf-binary" || request.ContentLength != 3 {
			t.Fatalf("invalid put headers: %+v length=%d", request.Header, request.ContentLength)
		}
		body, _ := io.ReadAll(request.Body)
		if string(body) != "glb" {
			t.Fatalf("put body = %q", body)
		}
		return response(http.StatusOK, `{}`), nil
	}))
	if err := store.Put(context.Background(), "owner/component-repo/previews/model.glb", "model/gltf-binary", strings.NewReader("glb"), 3); err != nil {
		t.Fatalf("put derived artifact: %v", err)
	}
}

func testSupabase(client HTTPDoer) *Supabase {
	return NewSupabase(config.StorageConfig{
		SupabaseURL: "https://project.supabase.co", PublishableKey: "key", ServiceRoleKey: "service-key", Bucket: "artifacts",
	}, client)
}

func response(status int, body string) *http.Response {
	return &http.Response{StatusCode: status, Body: io.NopCloser(strings.NewReader(body)), Header: make(http.Header)}
}
