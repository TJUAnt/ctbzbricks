package storage

import (
	"context"
	"errors"
	"io"
	"net/http"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
)

var (
	ErrNotFound    = errors.New("storage object not found")
	ErrUnavailable = errors.New("storage unavailable")
)

type ObjectMetadata struct {
	Size        int64
	ContentType string
	ETag        string
}

type Store interface {
	Provider() string
	Bucket() string
	Head(context.Context, string) (ObjectMetadata, error)
	Open(context.Context, string) (io.ReadCloser, error)
	Delete(context.Context, string) error
	SignDownload(context.Context, string, time.Duration) (string, error)
}

func New(cfg config.StorageConfig) Store {
	if cfg.Provider != "supabase" {
		return disabledStore{bucket: cfg.Bucket}
	}
	return NewSupabase(cfg, &http.Client{Timeout: cfg.RequestTimeout})
}

type disabledStore struct{ bucket string }

func (s disabledStore) Provider() string { return "disabled" }
func (s disabledStore) Bucket() string   { return s.bucket }
func (disabledStore) Head(context.Context, string) (ObjectMetadata, error) {
	return ObjectMetadata{}, ErrUnavailable
}
func (disabledStore) Open(context.Context, string) (io.ReadCloser, error) {
	return nil, ErrUnavailable
}
func (disabledStore) Delete(context.Context, string) error { return ErrUnavailable }
func (disabledStore) SignDownload(context.Context, string, time.Duration) (string, error) {
	return "", ErrUnavailable
}
