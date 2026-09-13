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

func TestDedicatedNonPreviewWorkersDoNotRequireLDraw(t *testing.T) {
	cfg := config.Config{}
	cfg.Storage.Provider = "supabase"
	cfg.Storage.ServiceRoleKey = "fixture"
	cfg.Worker.TaskTypes = []string{"pixel_2d.generate", "pixel_2d.edit", "pixel_2d.design"}
	if err := validateWorkerConfig(cfg); err != nil {
		t.Fatal(err)
	}
	cfg.Worker.TaskTypes = []string{"component.feed_render.materialize"}
	if err := validateWorkerConfig(cfg); err != nil {
		t.Fatal(err)
	}
	cfg.Worker.TaskTypes = append(cfg.Worker.TaskTypes, "component.preview.materialize")
	if err := validateWorkerConfig(cfg); err == nil {
		t.Fatal("worker with a GLB preview capability must retain LDraw prerequisites")
	}
}

func TestGeneralWorkerWithFeedExclusionStillRequiresLDraw(t *testing.T) {
	cfg := config.Config{}
	cfg.Storage.Provider = "supabase"
	cfg.Storage.ServiceRoleKey = "fixture"
	cfg.Worker.ExcludedTaskTypes = []string{"component.feed_render.materialize"}
	if err := validateWorkerConfig(cfg); err == nil {
		t.Fatal("general worker still owns GLB preview tasks and must require LDRAW_ROOT")
	}
}

func TestClaimsTaskTypeHonorsAllowlistAndDenylist(t *testing.T) {
	if claimsTaskType(config.WorkerConfig{TaskTypes: []string{"component.validate"}}, "component.feed_render.materialize") {
		t.Fatal("allowlisted worker must not claim an omitted task type")
	}
	if claimsTaskType(config.WorkerConfig{ExcludedTaskTypes: []string{"component.feed_render.materialize"}}, "component.feed_render.materialize") {
		t.Fatal("general worker must honor the deployment exclusion")
	}
	if !claimsTaskType(config.WorkerConfig{ExcludedTaskTypes: []string{"component.feed_render.materialize"}}, "component.validate") {
		t.Fatal("general worker must retain non-excluded capabilities")
	}
}
