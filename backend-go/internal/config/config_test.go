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
	if cfg.Storage.Provider != "disabled" || cfg.Storage.Bucket != "component-artifacts" || cfg.Storage.KeyPrefix != "component-repo" {
		t.Fatalf("unexpected storage defaults: %+v", cfg.Storage)
	}
	if cfg.Worker.PollInterval != 500*time.Millisecond || cfg.Worker.LeaseDuration != 30*time.Second ||
		cfg.Worker.HeartbeatInterval != 10*time.Second || cfg.Worker.Concurrency != 4 {
		t.Fatalf("unexpected worker defaults: %+v", cfg.Worker)
	}
	if cfg.Import.ParserVersion != "component-repo-ldraw-parser-v2" ||
		cfg.Import.SnapshotSchema != "component-repo-v2" || cfg.Import.MaxAttempts != 3 {
		t.Fatalf("unexpected import defaults: %+v", cfg.Import)
	}
	if cfg.Auth.SessionVerificationTimeout != 5*time.Second {
		t.Fatalf("unexpected auth session verification timeout: %s", cfg.Auth.SessionVerificationTimeout)
	}
	if cfg.FeedRender.BlenderPath != "" || cfg.FeedRender.Timeout != 5*time.Minute {
		t.Fatalf("unexpected Feed renderer defaults: %+v", cfg.FeedRender)
	}
}

func TestLoadValidatesWorkerLeaseTiming(t *testing.T) {
	_, err := load(mapLookup(map[string]string{
		"DATABASE_URL":              "postgresql://localhost/brickbuilder",
		"WORKER_LEASE_DURATION":     "10s",
		"WORKER_HEARTBEAT_INTERVAL": "5s",
	}))
	if err == nil || !strings.Contains(err.Error(), "HEARTBEAT_INTERVAL") {
		t.Fatalf("expected worker lease timing error, got %v", err)
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
		"APP_ENV":                    ProductionEnvironment,
		"DATABASE_URL":               "postgres://localhost/brickbuilder",
		"GO_BACKEND_HOST":            "0.0.0.0",
		"GO_BACKEND_PORT":            "9090",
		"HTTP_REQUEST_TIMEOUT":       "7s",
		"HTTP_MAX_BODY_BYTES":        "4096",
		"WORKER_ID":                  "worker-a",
		"WORKER_EXCLUDED_TASK_TYPES": "component.feed_render.materialize, component.feed_render.materialize",
		"FEED_RENDER_BLENDER_PATH":   "/opt/blender/blender",
		"FEED_RENDER_TIMEOUT":        "9m",
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
	if len(cfg.Worker.ExcludedTaskTypes) != 1 || cfg.Worker.ExcludedTaskTypes[0] != "component.feed_render.materialize" {
		t.Fatalf("unexpected excluded worker task types: %#v", cfg.Worker.ExcludedTaskTypes)
	}
	if cfg.FeedRender.BlenderPath != "/opt/blender/blender" || cfg.FeedRender.Timeout != 9*time.Minute {
		t.Fatalf("unexpected Feed renderer override: %+v", cfg.FeedRender)
	}
}

func TestLoadRejectsWorkerTaskAllowlistAndDenylistTogether(t *testing.T) {
	_, err := load(mapLookup(map[string]string{
		"DATABASE_URL":               "postgresql://localhost/brickbuilder",
		"WORKER_TASK_TYPES":          "component.validate",
		"WORKER_EXCLUDED_TASK_TYPES": "component.feed_render.materialize",
	}))
	if err == nil || !strings.Contains(err.Error(), "mutually exclusive") {
		t.Fatalf("expected mutually exclusive worker task filters, got %v", err)
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

func TestLoadDerivesJWKSURLFromIssuer(t *testing.T) {
	cfg, err := load(mapLookup(map[string]string{
		"DATABASE_URL":    "postgresql://localhost/brickbuilder",
		"AUTH_JWT_ISSUER": "https://project.supabase.co/auth/v1/",
	}))
	if err != nil {
		t.Fatalf("load config: %v", err)
	}
	if cfg.Auth.JWTIssuer != "https://project.supabase.co/auth/v1" ||
		cfg.Auth.JWKSURL != "https://project.supabase.co/auth/v1/.well-known/jwks.json" {
		t.Fatalf("unexpected auth config: %+v", cfg.Auth)
	}
}

func TestLoadBuildsSupabaseSessionVerificationConfig(t *testing.T) {
	cfg, err := load(mapLookup(map[string]string{
		"APP_ENV":                           TestEnvironment,
		"DATABASE_URL":                      "postgresql://localhost/brickbuilder",
		"AUTH_JWT_ISSUER":                   "https://project.supabase.co/auth/v1",
		"SUPABASE_PUBLISHABLE_KEY":          "publishable-key",
		"AUTH_SESSION_VERIFICATION_TIMEOUT": "3s",
	}))
	if err != nil {
		t.Fatalf("load config: %v", err)
	}
	if cfg.Auth.SessionVerificationURL != "https://project.supabase.co/auth/v1/user" ||
		cfg.Auth.PublishableKey != "publishable-key" || cfg.Auth.SessionVerificationTimeout != 3*time.Second {
		t.Fatalf("unexpected session verification config: %+v", cfg.Auth)
	}
}

func TestLoadAllowsLocalSupabaseOutsideProduction(t *testing.T) {
	cfg, err := load(mapLookup(map[string]string{
		"DATABASE_URL":             "postgresql://localhost/brickbuilder",
		"SUPABASE_URL":             "http://127.0.0.1:54321",
		"SUPABASE_PUBLISHABLE_KEY": "publishable-key",
	}))
	if err != nil {
		t.Fatalf("load local Supabase config: %v", err)
	}
	if cfg.Auth.SessionVerificationURL != "http://127.0.0.1:54321/auth/v1/user" {
		t.Fatalf("unexpected local session URL: %q", cfg.Auth.SessionVerificationURL)
	}

	_, err = load(mapLookup(map[string]string{
		"APP_ENV":      ProductionEnvironment,
		"DATABASE_URL": "postgresql://localhost/brickbuilder",
		"SUPABASE_URL": "http://127.0.0.1:54321",
	}))
	if err == nil || !strings.Contains(err.Error(), "SUPABASE_URL") {
		t.Fatalf("expected production Supabase HTTPS error, got %v", err)
	}
}

func TestLoadRejectsInsecureJWKSURLOutsideTests(t *testing.T) {
	_, err := load(mapLookup(map[string]string{
		"DATABASE_URL":  "postgresql://localhost/brickbuilder",
		"AUTH_JWKS_URL": "http://keys.example/jwks.json",
	}))
	if err == nil || !strings.Contains(err.Error(), "AUTH_JWKS_URL") {
		t.Fatalf("expected JWKS URL error, got %v", err)
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
		"DATABASE_URL":                      "postgresql://localhost/brickbuilder",
		"STORAGE_PROVIDER":                  "supabase",
		"STORAGE_BUCKET":                    "artifacts",
		"STORAGE_KEY_PREFIX":                "/component-repo/",
		"SUPABASE_URL":                      "https://example.supabase.co/",
		"SUPABASE_PUBLISHABLE_KEY":          "publishable-key",
		"SUPABASE_STORAGE_SERVICE_ROLE_KEY": "service-key",
		"STORAGE_UPLOAD_SESSION_TTL":        "45m",
		"STORAGE_SIGNED_URL_TTL":            "5m",
		"STORAGE_MAX_ARTIFACT_BYTES":        "2048",
	}))
	if err != nil {
		t.Fatalf("load Supabase storage: %v", err)
	}
	if cfg.Storage.KeyPrefix != "component-repo" || cfg.Storage.UploadSessionTTL != 45*time.Minute || cfg.Storage.MaxArtifactBytes != 2048 {
		t.Fatalf("unexpected Supabase storage config: %+v", cfg.Storage)
	}
	if cfg.Storage.PublishableKey != "publishable-key" || cfg.Storage.ServiceRoleKey != "service-key" {
		t.Fatalf("unexpected Supabase credentials")
	}

	secretKey, err := load(mapLookup(map[string]string{
		"DATABASE_URL":             "postgresql://localhost/brickbuilder",
		"STORAGE_PROVIDER":         "supabase",
		"SUPABASE_URL":             "https://example.supabase.co",
		"SUPABASE_PUBLISHABLE_KEY": "sb_publishable_browser",
		"SUPABASE_SECRET_KEY":      "sb_secret_worker",
	}))
	if err != nil {
		t.Fatalf("load modern Supabase secret key: %v", err)
	}
	if secretKey.Storage.ServiceRoleKey != "sb_secret_worker" {
		t.Fatalf("modern secret key was not selected")
	}

	apiOnly, err := load(mapLookup(map[string]string{
		"DATABASE_URL":             "postgresql://localhost/brickbuilder",
		"STORAGE_PROVIDER":         "supabase",
		"SUPABASE_URL":             "https://example.supabase.co",
		"SUPABASE_PUBLISHABLE_KEY": "publishable-key",
	}))
	if err != nil {
		t.Fatalf("load API-only Supabase storage: %v", err)
	}
	if apiOnly.Storage.ServiceRoleKey != "" {
		t.Fatal("API-only storage unexpectedly configured a service-role credential")
	}

	_, err = load(mapLookup(map[string]string{
		"DATABASE_URL":                      "postgresql://localhost/brickbuilder",
		"STORAGE_PROVIDER":                  "supabase",
		"SUPABASE_URL":                      "https://example.supabase.co",
		"SUPABASE_PUBLISHABLE_KEY":          "sb_publishable_browser",
		"SUPABASE_STORAGE_SERVICE_ROLE_KEY": "sb_publishable_not_server",
	}))
	if err == nil || !strings.Contains(err.Error(), "must not be a publishable key") {
		t.Fatalf("expected publishable service-role rejection, got %v", err)
	}

	_, err = load(mapLookup(map[string]string{
		"DATABASE_URL":             "postgresql://localhost/brickbuilder",
		"STORAGE_PROVIDER":         "supabase",
		"SUPABASE_URL":             "https://example.supabase.co",
		"SUPABASE_PUBLISHABLE_KEY": "sb_publishable_browser",
		"SUPABASE_SECRET_KEY":      "sb_publishable_not_server",
	}))
	if err == nil || !strings.Contains(err.Error(), "must not be a publishable key") {
		t.Fatalf("expected publishable secret-key rejection, got %v", err)
	}
}

func mapLookup(values map[string]string) lookupFunc {
	return func(key string) string { return values[key] }
}
