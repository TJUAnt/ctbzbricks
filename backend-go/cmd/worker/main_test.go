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
	}, PartPreview: config.PartPreviewConfig{LDrawRoot: "/fixtures/ldraw"}}
	if err := validateWorkerConfig(cfg); err != nil {
		t.Fatalf("validate worker configuration: %v", err)
	}
}

func TestValidateWorkerConfigRequiresLDrawRootForComponentPreview(t *testing.T) {
	cfg := config.Config{Storage: config.StorageConfig{
		Provider: "supabase", ServiceRoleKey: "service-role",
	}}
	if err := validateWorkerConfig(cfg); err == nil {
		t.Fatal("expected storage-enabled worker configuration to require LDRAW_ROOT")
	}
}

func TestDedicatedPixelWorkerDoesNotRequireLDraw(t *testing.T) {
	cfg := config.Config{}
	cfg.Storage.Provider = "supabase"
	cfg.Storage.ServiceRoleKey = "fixture"
	cfg.Worker.TaskTypes = []string{"pixel_2d.generate", "pixel_2d.edit", "pixel_2d.design"}
	if err := validateWorkerConfig(cfg); err != nil {
		t.Fatal(err)
	}
	cfg.Worker.TaskTypes = append(cfg.Worker.TaskTypes, "unknown")
	if err := validateWorkerConfig(cfg); err == nil {
		t.Fatal("mixed worker must retain preview prerequisites")
	}
}
