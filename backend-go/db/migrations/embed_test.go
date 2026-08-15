package migrations

import (
	"slices"
	"testing"
)

func TestMigrationFilesystemContainsBaseline(t *testing.T) {
	entries, err := SQLFiles()
	if err != nil {
		t.Fatalf("read embedded migration files: %v", err)
	}
	names := make([]string, 0, len(entries))
	for _, entry := range entries {
		names = append(names, entry.Name())
	}
	for _, expected := range []string{
		"00001_component_repo_baseline.sql",
		"00002_component_version_source_integrity.sql",
		"00003_source_artifact_immutability.sql",
		"00004_durable_task_system.sql",
		"00005_component_import_pipeline.sql",
		"00006_component_workbench.sql",
		"00007_logical_task_jobs.sql",
		"00008_part_preview.sql",
	} {
		if !slices.Contains(names, expected) {
			t.Fatalf("migration %q is not embedded: %v", expected, names)
		}
	}
}
