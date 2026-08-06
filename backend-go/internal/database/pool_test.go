package database

import (
	"context"
	"testing"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
)

func TestNewPoolAppliesBoundedConfigurationWithoutConnecting(t *testing.T) {
	pool, err := NewPool(context.Background(), config.DatabaseConfig{
		URL:               "postgresql://localhost/brickbuilder?sslmode=disable",
		MinConns:          0,
		MaxConns:          7,
		MaxConnLifetime:   20 * time.Minute,
		MaxConnIdleTime:   4 * time.Minute,
		HealthCheckPeriod: 45 * time.Second,
		ConnectTimeout:    3 * time.Second,
	})
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	poolConfig := pool.Config()
	if poolConfig.MaxConns != 7 || poolConfig.MinConns != 0 {
		t.Fatalf("pool bounds = %d/%d", poolConfig.MinConns, poolConfig.MaxConns)
	}
	if poolConfig.ConnConfig.ConnectTimeout != 3*time.Second {
		t.Fatalf("connect timeout = %s", poolConfig.ConnConfig.ConnectTimeout)
	}
}
