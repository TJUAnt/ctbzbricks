package migrations

import (
	"embed"
	"io/fs"
)

// Files contains the migration package documentation during G1. G2 will add
// versioned SQL files to the embedded filesystem when Goose becomes authoritative.
//
//go:embed README.md
var Files embed.FS

func SQLFiles() ([]fs.DirEntry, error) {
	return fs.ReadDir(Files, ".")
}
