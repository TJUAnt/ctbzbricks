package storage

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
)

type HTTPDoer interface {
	Do(*http.Request) (*http.Response, error)
}

type Supabase struct {
	baseURL       string
	apiKey        string
	authorization string
	bucket        string
	client        HTTPDoer
}

func NewSupabase(cfg config.StorageConfig, client HTTPDoer) *Supabase {
	authorization := cfg.Authorization
	if authorization == "" {
		authorization = cfg.APIKey
	}
	return &Supabase{
		baseURL: strings.TrimRight(cfg.SupabaseURL, "/"), apiKey: cfg.APIKey,
		authorization: authorization, bucket: cfg.Bucket, client: client,
	}
}

func (*Supabase) Provider() string { return "supabase" }
func (s *Supabase) Bucket() string { return s.bucket }

func (s *Supabase) Head(ctx context.Context, key string) (ObjectMetadata, error) {
	response, err := s.do(ctx, http.MethodGet, s.objectURL("info", key), nil)
	if err != nil {
		return ObjectMetadata{}, err
	}
	defer response.Body.Close()
	if err := storageStatus(response.StatusCode); err != nil {
		return ObjectMetadata{}, err
	}
	var payload struct {
		Size         json.Number `json:"size"`
		ContentType  string      `json:"content_type"`
		ContentType2 string      `json:"contentType"`
		ETag         string      `json:"etag"`
		Metadata     struct {
			Size json.Number `json:"size"`
		} `json:"metadata"`
	}
	decoder := json.NewDecoder(io.LimitReader(response.Body, 64*1024))
	decoder.UseNumber()
	if err := decoder.Decode(&payload); err != nil {
		return ObjectMetadata{}, fmt.Errorf("decode storage metadata: %w", ErrUnavailable)
	}
	sizeValue := payload.Size
	if sizeValue == "" {
		sizeValue = payload.Metadata.Size
	}
	size, err := strconv.ParseInt(string(sizeValue), 10, 64)
	if err != nil || size < 0 {
		return ObjectMetadata{}, fmt.Errorf("invalid storage metadata: %w", ErrUnavailable)
	}
	contentType := payload.ContentType
	if contentType == "" {
		contentType = payload.ContentType2
	}
	return ObjectMetadata{Size: size, ContentType: contentType, ETag: payload.ETag}, nil
}

func (s *Supabase) Open(ctx context.Context, key string) (io.ReadCloser, error) {
	response, err := s.do(ctx, http.MethodGet, s.objectURL("", key), nil)
	if err != nil {
		return nil, err
	}
	if err := storageStatus(response.StatusCode); err != nil {
		response.Body.Close()
		return nil, err
	}
	return response.Body, nil
}

func (s *Supabase) Delete(ctx context.Context, key string) error {
	body, err := json.Marshal(map[string][]string{"prefixes": {key}})
	if err != nil {
		return err
	}
	response, err := s.do(ctx, http.MethodDelete, s.bucketURL(), bytes.NewReader(body))
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode == http.StatusNotFound {
		return nil
	}
	return storageStatus(response.StatusCode)
}

func (s *Supabase) SignDownload(ctx context.Context, key string, ttl time.Duration) (string, error) {
	seconds := int64(ttl / time.Second)
	body, err := json.Marshal(map[string]int64{"expiresIn": seconds})
	if err != nil {
		return "", err
	}
	response, err := s.do(ctx, http.MethodPost, s.objectURL("sign", key), bytes.NewReader(body))
	if err != nil {
		return "", err
	}
	defer response.Body.Close()
	if err := storageStatus(response.StatusCode); err != nil {
		return "", err
	}
	var payload struct {
		SignedURL  string `json:"signedURL"`
		SignedURL2 string `json:"signedUrl"`
	}
	if err := json.NewDecoder(io.LimitReader(response.Body, 64*1024)).Decode(&payload); err != nil {
		return "", fmt.Errorf("decode signed URL: %w", ErrUnavailable)
	}
	signed := payload.SignedURL
	if signed == "" {
		signed = payload.SignedURL2
	}
	if signed == "" {
		return "", fmt.Errorf("signed URL missing: %w", ErrUnavailable)
	}
	parsed, err := url.Parse(signed)
	if err != nil {
		return "", fmt.Errorf("invalid signed URL: %w", ErrUnavailable)
	}
	if parsed.IsAbs() {
		return signed, nil
	}
	if strings.HasPrefix(signed, "/storage/v1/") {
		return s.baseURL + signed, nil
	}
	return s.baseURL + "/storage/v1/" + strings.TrimLeft(signed, "/"), nil
}

func (s *Supabase) do(ctx context.Context, method, target string, body io.Reader) (*http.Response, error) {
	request, err := http.NewRequestWithContext(ctx, method, target, body)
	if err != nil {
		return nil, err
	}
	request.Header.Set("apikey", s.apiKey)
	request.Header.Set("Authorization", "Bearer "+s.authorization)
	if body != nil {
		request.Header.Set("Content-Type", "application/json")
	}
	response, err := s.client.Do(request)
	if err != nil {
		if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
			return nil, err
		}
		return nil, fmt.Errorf("storage request failed: %w", ErrUnavailable)
	}
	return response, nil
}

func (s *Supabase) objectURL(operation, key string) string {
	parts := []string{s.baseURL, "storage", "v1", "object"}
	if operation != "" {
		parts = append(parts, operation)
	}
	parts = append(parts, escapeSegment(s.bucket))
	for _, segment := range strings.Split(key, "/") {
		parts = append(parts, escapeSegment(segment))
	}
	return strings.Join(parts, "/")
}

func (s *Supabase) bucketURL() string {
	return strings.Join([]string{s.baseURL, "storage", "v1", "object", escapeSegment(s.bucket)}, "/")
}

func escapeSegment(value string) string {
	return url.PathEscape(value)
}

func storageStatus(status int) error {
	if status >= 200 && status < 300 {
		return nil
	}
	if status == http.StatusNotFound {
		return ErrNotFound
	}
	return ErrUnavailable
}
