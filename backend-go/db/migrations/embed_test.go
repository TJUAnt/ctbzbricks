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
	if !slices.Contains(names, "00001_component_repo_baseline.sql") {
		t.Fatalf("baseline migration is not embedded: %v", names)
	}
}
