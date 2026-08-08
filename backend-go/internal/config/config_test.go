package config

import (
	"strings"
	"testing"
	"time"
)

func TestLoadRequiresPostgreSQLURL(t *testing.T) {
	_, err := load(func(string) string { return "" })
	if err == nil || !strings.Contains(err.Error(), "DATABASE_URL") {
		t.Fatalf("expected DATABASE_URL error, got %v", err)
	}
}

func TestLoadRejectsNonPostgreSQLURL(t *testing.T) {
	_, err := load(mapLookup(map[string]string{"DATABASE_URL": "mysql://localhost/test"}))
	if err == nil || !strings.Contains(err.Error(), "postgres") {
		t.Fatalf("expected PostgreSQL URL error, got %v", err)
	}
}

func TestLoadUsesDefaults(t *testing.T) {
	cfg, err := load(mapLookup(map[string]string{
		"DATABASE_URL": "postgresql://localhost/brickbuilder",
	}))
	if err != nil {
		t.Fatalf("load config: %v", err)
	}
	if cfg.Environment != DevelopmentEnvironment {
		t.Fatalf("environment = %q", cfg.Environment)
	}
	if cfg.HTTP.Address() != "127.0.0.1:8080" {
		t.Fatalf("address = %q", cfg.HTTP.Address())
	}
	if cfg.Database.MinConns != 1 || cfg.Database.MaxConns != 10 {
		t.Fatalf("pool bounds = %d/%d", cfg.Database.MinConns, cfg.Database.MaxConns)
	}
	if cfg.HTTP.RequestTimeout != 30*time.Second {
		t.Fatalf("request timeout = %s", cfg.HTTP.RequestTimeout)
	}
	if cfg.Storage.Provider != "disabled" || cfg.Storage.Bucket != "component-artifacts" {
		t.Fatalf("unexpected storage defaults: %+v", cfg.Storage)
	}
}

func TestLoadValidatesPoolBounds(t *testing.T) {
	_, err := load(mapLookup(map[string]string{
		"DATABASE_URL":            "postgresql://localhost/brickbuilder",
		"DATABASE_POOL_MIN_CONNS": "11",
		"DATABASE_POOL_MAX_CONNS": "10",
	}))
	if err == nil || !strings.Contains(err.Error(), "MIN_CONNS") {
		t.Fatalf("expected pool bounds error, got %v", err)
	}
}

func TestLoadParsesOverrides(t *testing.T) {
	cfg, err := load(mapLookup(map[string]string{
		"APP_ENV":              ProductionEnvironment,
		"DATABASE_URL":         "postgres://localhost/brickbuilder",
		"GO_BACKEND_HOST":      "0.0.0.0",
		"GO_BACKEND_PORT":      "9090",
		"HTTP_REQUEST_TIMEOUT": "7s",
		"HTTP_MAX_BODY_BYTES":  "4096",
		"WORKER_ID":            "worker-a",
	}))
	if err != nil {
		t.Fatalf("load config: %v", err)
	}
	if cfg.HTTP.Address() != "0.0.0.0:9090" || cfg.HTTP.RequestTimeout != 7*time.Second {
		t.Fatalf("unexpected HTTP config: %+v", cfg.HTTP)
	}
	if cfg.HTTP.MaxBodyBytes != 4096 || cfg.Worker.ID != "worker-a" {
		t.Fatalf("unexpected override config: %+v %+v", cfg.HTTP, cfg.Worker)
	}
}

func TestLoadRejectsShortJWTSecret(t *testing.T) {
	_, err := load(mapLookup(map[string]string{
		"DATABASE_URL":    "postgresql://localhost/brickbuilder",
		"AUTH_JWT_SECRET": "short",
	}))
	if err == nil || !strings.Contains(err.Error(), "AUTH_JWT_SECRET") {
		t.Fatalf("expected JWT secret error, got %v", err)
	}
}

func TestLoadValidatesSupabaseStorage(t *testing.T) {
	_, err := load(mapLookup(map[string]string{
		"DATABASE_URL":     "postgresql://localhost/brickbuilder",
		"STORAGE_PROVIDER": "supabase",
	}))
	if err == nil || !strings.Contains(err.Error(), "SUPABASE_URL") {
		t.Fatalf("expected Supabase configuration error, got %v", err)
	}

	cfg, err := load(mapLookup(map[string]string{
		"DATABASE_URL":               "postgresql://localhost/brickbuilder",
		"STORAGE_PROVIDER":           "supabase",
		"STORAGE_BUCKET":             "artifacts",
		"STORAGE_KEY_PREFIX":         "/component-repo/",
		"SUPABASE_URL":               "https://example.supabase.co/",
		"SUPABASE_STORAGE_API_KEY":   "service-key",
		"STORAGE_UPLOAD_SESSION_TTL": "45m",
		"STORAGE_SIGNED_URL_TTL":     "5m",
		"STORAGE_MAX_ARTIFACT_BYTES": "2048",
	}))
	if err != nil {
		t.Fatalf("load Supabase storage: %v", err)
	}
	if cfg.Storage.KeyPrefix != "component-repo" || cfg.Storage.UploadSessionTTL != 45*time.Minute || cfg.Storage.MaxArtifactBytes != 2048 {
		t.Fatalf("unexpected Supabase storage config: %+v", cfg.Storage)
	}
}

func mapLookup(values map[string]string) lookupFunc {
	return func(key string) string { return values[key] }
}
