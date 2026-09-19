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
		"00014_component_stars.sql",
		"00015_component_watches.sql",
		"00016_component_domain_events.sql",
		"00017_component_relationship_lifecycle.sql",
		"00018_component_current_logical_size.sql",
		"00019_pixel_2d.sql",
		"00020_component_watch_feed.sql",
		"00021_component_official_publish_events.sql",
		"00022_component_public_feed.sql",
		"00023_component_feed_rendering.sql",
		"00024_component_catalog_projection.sql",
		"00025_part_library_search.sql",
	} {
		if !slices.Contains(names, expected) {
			t.Fatalf("migration %q is not embedded: %v", expected, names)
		}
	}
}
