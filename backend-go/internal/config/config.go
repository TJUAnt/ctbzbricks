package config

import (
	"errors"
	"fmt"
	"net"
	"os"
	"strconv"
	"strings"
	"time"
)

const (
	DevelopmentEnvironment = "development"
	TestEnvironment        = "test"
	ProductionEnvironment  = "production"
)

type Config struct {
	Environment string
	HTTP        HTTPConfig
	Database    DatabaseConfig
	Auth        AuthConfig
	Storage     StorageConfig
	Worker      WorkerConfig
}

type HTTPConfig struct {
	Host              string
	Port              int
	ReadHeaderTimeout time.Duration
	ReadTimeout       time.Duration
	WriteTimeout      time.Duration
	IdleTimeout       time.Duration
	RequestTimeout    time.Duration
	ShutdownTimeout   time.Duration
	MaxBodyBytes      int64
}

func (c HTTPConfig) Address() string {
	return net.JoinHostPort(c.Host, strconv.Itoa(c.Port))
}

type DatabaseConfig struct {
	URL               string
	MinConns          int32
	MaxConns          int32
	MaxConnLifetime   time.Duration
	MaxConnIdleTime   time.Duration
	HealthCheckPeriod time.Duration
	ConnectTimeout    time.Duration
}

type WorkerConfig struct {
	ID                  string
	HealthCheckInterval time.Duration
}

type AuthConfig struct {
	JWTSecret   string
	JWTIssuer   string
	JWTAudience string
}

type StorageConfig struct {
	Provider         string
	Bucket           string
	KeyPrefix        string
	SupabaseURL      string
	APIKey           string
	Authorization    string
	RequestTimeout   time.Duration
	SignedURLTTL     time.Duration
	UploadSessionTTL time.Duration
	MaxArtifactBytes int64
}

type lookupFunc func(string) string

func Load() (Config, error) {
	return load(os.Getenv)
}

func load(lookup lookupFunc) (Config, error) {
	environment := valueOrDefault(lookup, "APP_ENV", DevelopmentEnvironment)
	if environment != DevelopmentEnvironment && environment != TestEnvironment && environment != ProductionEnvironment {
		return Config{}, fmt.Errorf("APP_ENV must be one of development, test, or production")
	}

	databaseURL := strings.TrimSpace(lookup("DATABASE_URL"))
	if databaseURL == "" {
		return Config{}, errors.New("DATABASE_URL is required")
	}
	if !strings.HasPrefix(databaseURL, "postgres://") && !strings.HasPrefix(databaseURL, "postgresql://") {
		return Config{}, errors.New("DATABASE_URL must use postgres:// or postgresql://")
	}
	jwtSecret := strings.TrimSpace(lookup("AUTH_JWT_SECRET"))
	if jwtSecret != "" && len(jwtSecret) < 32 {
		return Config{}, errors.New("AUTH_JWT_SECRET must contain at least 32 bytes")
	}

	httpPort, err := intValue(lookup, "GO_BACKEND_PORT", 8080, 1, 65535)
	if err != nil {
		return Config{}, err
	}
	maxBodyBytes, err := int64Value(lookup, "HTTP_MAX_BODY_BYTES", 2*1024*1024, 1)
	if err != nil {
		return Config{}, err
	}
	minConns, err := int32Value(lookup, "DATABASE_POOL_MIN_CONNS", 1, 0)
	if err != nil {
		return Config{}, err
	}
	maxConns, err := int32Value(lookup, "DATABASE_POOL_MAX_CONNS", 10, 1)
	if err != nil {
		return Config{}, err
	}
	if minConns > maxConns {
		return Config{}, errors.New("DATABASE_POOL_MIN_CONNS must not exceed DATABASE_POOL_MAX_CONNS")
	}

	readHeaderTimeout, err := durationValue(lookup, "HTTP_READ_HEADER_TIMEOUT", 5*time.Second)
	if err != nil {
		return Config{}, err
	}
	readTimeout, err := durationValue(lookup, "HTTP_READ_TIMEOUT", 30*time.Second)
	if err != nil {
		return Config{}, err
	}
	writeTimeout, err := durationValue(lookup, "HTTP_WRITE_TIMEOUT", 30*time.Second)
	if err != nil {
		return Config{}, err
	}
	idleTimeout, err := durationValue(lookup, "HTTP_IDLE_TIMEOUT", 2*time.Minute)
	if err != nil {
		return Config{}, err
	}
	requestTimeout, err := durationValue(lookup, "HTTP_REQUEST_TIMEOUT", 30*time.Second)
	if err != nil {
		return Config{}, err
	}
	shutdownTimeout, err := durationValue(lookup, "HTTP_SHUTDOWN_TIMEOUT", 10*time.Second)
	if err != nil {
		return Config{}, err
	}
	maxConnLifetime, err := durationValue(lookup, "DATABASE_POOL_MAX_CONN_LIFETIME", 30*time.Minute)
	if err != nil {
		return Config{}, err
	}
	maxConnIdleTime, err := durationValue(lookup, "DATABASE_POOL_MAX_CONN_IDLE_TIME", 5*time.Minute)
	if err != nil {
		return Config{}, err
	}
	healthCheckPeriod, err := durationValue(lookup, "DATABASE_POOL_HEALTH_CHECK_PERIOD", time.Minute)
	if err != nil {
		return Config{}, err
	}
	connectTimeout, err := durationValue(lookup, "DATABASE_CONNECT_TIMEOUT", 5*time.Second)
	if err != nil {
		return Config{}, err
	}
	workerHealthCheckInterval, err := durationValue(lookup, "WORKER_HEALTH_CHECK_INTERVAL", 30*time.Second)
	if err != nil {
		return Config{}, err
	}
	storageProvider := strings.ToLower(valueOrDefault(lookup, "STORAGE_PROVIDER", "disabled"))
	if storageProvider != "disabled" && storageProvider != "supabase" {
		return Config{}, errors.New("STORAGE_PROVIDER must be disabled or supabase")
	}
	storageBucket := valueOrDefault(lookup, "STORAGE_BUCKET", "component-artifacts")
	storagePrefix := strings.Trim(strings.TrimSpace(lookup("STORAGE_KEY_PREFIX")), "/")
	if storageBucket == "" || strings.ContainsAny(storageBucket, "/\\") {
		return Config{}, errors.New("STORAGE_BUCKET must be a bucket name without path separators")
	}
	if strings.Contains(storagePrefix, "..") || strings.Contains(storagePrefix, "\\") {
		return Config{}, errors.New("STORAGE_KEY_PREFIX contains an invalid path segment")
	}
	storageURL := strings.TrimRight(strings.TrimSpace(lookup("SUPABASE_URL")), "/")
	storageAPIKey := strings.TrimSpace(lookup("SUPABASE_STORAGE_API_KEY"))
	storageAuthorization := strings.TrimSpace(lookup("SUPABASE_STORAGE_AUTHORIZATION"))
	if storageProvider == "supabase" && (storageURL == "" || storageAPIKey == "") {
		return Config{}, errors.New("SUPABASE_URL and SUPABASE_STORAGE_API_KEY are required for supabase storage")
	}
	storageRequestTimeout, err := durationValue(lookup, "STORAGE_REQUEST_TIMEOUT", 30*time.Second)
	if err != nil {
		return Config{}, err
	}
	signedURLTTL, err := durationValue(lookup, "STORAGE_SIGNED_URL_TTL", 15*time.Minute)
	if err != nil {
		return Config{}, err
	}
	uploadSessionTTL, err := durationValue(lookup, "STORAGE_UPLOAD_SESSION_TTL", time.Hour)
	if err != nil {
		return Config{}, err
	}
	maxArtifactBytes, err := int64Value(lookup, "STORAGE_MAX_ARTIFACT_BYTES", 512*1024*1024, 1)
	if err != nil {
		return Config{}, err
	}

	return Config{
		Environment: environment,
		HTTP: HTTPConfig{
			Host:              valueOrDefault(lookup, "GO_BACKEND_HOST", "127.0.0.1"),
			Port:              httpPort,
			ReadHeaderTimeout: readHeaderTimeout,
			ReadTimeout:       readTimeout,
			WriteTimeout:      writeTimeout,
			IdleTimeout:       idleTimeout,
			RequestTimeout:    requestTimeout,
			ShutdownTimeout:   shutdownTimeout,
			MaxBodyBytes:      maxBodyBytes,
		},
		Database: DatabaseConfig{
			URL:               databaseURL,
			MinConns:          minConns,
			MaxConns:          maxConns,
			MaxConnLifetime:   maxConnLifetime,
			MaxConnIdleTime:   maxConnIdleTime,
			HealthCheckPeriod: healthCheckPeriod,
			ConnectTimeout:    connectTimeout,
		},
		Auth: AuthConfig{
			JWTSecret:   jwtSecret,
			JWTIssuer:   strings.TrimSpace(lookup("AUTH_JWT_ISSUER")),
			JWTAudience: strings.TrimSpace(lookup("AUTH_JWT_AUDIENCE")),
		},
		Storage: StorageConfig{
			Provider:         storageProvider,
			Bucket:           storageBucket,
			KeyPrefix:        storagePrefix,
			SupabaseURL:      storageURL,
			APIKey:           storageAPIKey,
			Authorization:    storageAuthorization,
			RequestTimeout:   storageRequestTimeout,
			SignedURLTTL:     signedURLTTL,
			UploadSessionTTL: uploadSessionTTL,
			MaxArtifactBytes: maxArtifactBytes,
		},
		Worker: WorkerConfig{
			ID:                  strings.TrimSpace(lookup("WORKER_ID")),
			HealthCheckInterval: workerHealthCheckInterval,
		},
	}, nil
}

func valueOrDefault(lookup lookupFunc, key, fallback string) string {
	value := strings.TrimSpace(lookup(key))
	if value == "" {
		return fallback
	}
	return value
}

func durationValue(lookup lookupFunc, key string, fallback time.Duration) (time.Duration, error) {
	raw := strings.TrimSpace(lookup(key))
	if raw == "" {
		return fallback, nil
	}
	value, err := time.ParseDuration(raw)
	if err != nil || value <= 0 {
		return 0, fmt.Errorf("%s must be a positive Go duration", key)
	}
	return value, nil
}

func intValue(lookup lookupFunc, key string, fallback, minimum, maximum int) (int, error) {
	raw := strings.TrimSpace(lookup(key))
	if raw == "" {
		return fallback, nil
	}
	value, err := strconv.Atoi(raw)
	if err != nil || value < minimum || value > maximum {
		return 0, fmt.Errorf("%s must be between %d and %d", key, minimum, maximum)
	}
	return value, nil
}

func int32Value(lookup lookupFunc, key string, fallback, minimum int32) (int32, error) {
	raw := strings.TrimSpace(lookup(key))
	if raw == "" {
		return fallback, nil
	}
	value, err := strconv.ParseInt(raw, 10, 32)
	if err != nil || value < int64(minimum) {
		return 0, fmt.Errorf("%s must be at least %d", key, minimum)
	}
	return int32(value), nil
}

func int64Value(lookup lookupFunc, key string, fallback, minimum int64) (int64, error) {
	raw := strings.TrimSpace(lookup(key))
	if raw == "" {
		return fallback, nil
	}
	value, err := strconv.ParseInt(raw, 10, 64)
	if err != nil || value < minimum {
		return 0, fmt.Errorf("%s must be at least %d", key, minimum)
	}
	return value, nil
}
