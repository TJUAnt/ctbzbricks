package migrations

import (
	"embed"
	"io/fs"
)

// Files contains the versioned Goose migrations and their operator notes.
//
//go:embed README.md *.sql
var Files embed.FS

func SQLFiles() ([]fs.DirEntry, error) {
	return fs.ReadDir(Files, ".")
}
