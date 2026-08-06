package database

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestAPIAndWorkerStartupDoNotImportMigrationsOrContainDDL(t *testing.T) {
	_, filename, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("locate startup contract test")
	}
	moduleRoot := filepath.Clean(filepath.Join(filepath.Dir(filename), "..", ".."))
	entrypoints := []string{
		filepath.Join(moduleRoot, "cmd", "api", "main.go"),
		filepath.Join(moduleRoot, "cmd", "worker", "main.go"),
	}
	for _, entrypoint := range entrypoints {
		source, err := os.ReadFile(entrypoint)
		if err != nil {
			t.Fatalf("read %s: %v", entrypoint, err)
		}
		upper := strings.ToUpper(string(source))
		for _, forbidden := range []string{
			"GITHUB.COM/PRESSLY/GOOSE",
			"/DB/MIGRATIONS",
			"CREATE TABLE",
			"ALTER TABLE",
			"DROP TABLE",
			"CREATE SCHEMA",
		} {
			if strings.Contains(upper, forbidden) {
				t.Errorf("%s contains forbidden startup migration marker %q", entrypoint, forbidden)
			}
		}
	}
}
