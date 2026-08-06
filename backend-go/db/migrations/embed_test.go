package migrations

import "testing"

func TestG1MigrationFilesystemContainsOnlyDocumentation(t *testing.T) {
	entries, err := SQLFiles()
	if err != nil {
		t.Fatalf("read embedded migration files: %v", err)
	}
	if len(entries) != 1 || entries[0].Name() != "README.md" {
		t.Fatalf("unexpected G1 migration files: %+v", entries)
	}
}
