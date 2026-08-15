package main

import (
	"testing"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
)

func TestValidateWorkerConfigRequiresServiceRoleForSupabase(t *testing.T) {
	err := validateWorkerConfig(config.Config{Storage: config.StorageConfig{Provider: "supabase"}})
	if err == nil {
		t.Fatal("expected Supabase worker configuration to require a service-role key")
	}
}

func TestValidateWorkerConfigAllowsSupabaseWithServiceRole(t *testing.T) {
	cfg := config.Config{Storage: config.StorageConfig{
		Provider: "supabase", PublishableKey: "publishable", ServiceRoleKey: "service-role",
	}}
	if err := validateWorkerConfig(cfg); err != nil {
		t.Fatalf("validate worker configuration: %v", err)
	}
}
