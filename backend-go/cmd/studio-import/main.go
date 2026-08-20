package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/partlibrary"
)

func main() {
	var databaseURL string
	var manifestPath string
	var ldrawRoot string
	var libraryID string
	var createdBy string
	var status string
	var dryRun bool
	var limit int
	flag.StringVar(&databaseURL, "database-url", os.Getenv("DATABASE_URL"), "PostgreSQL database URL")
	flag.StringVar(&manifestPath, "manifest", "", "studio_manifest.json path")
	flag.StringVar(&ldrawRoot, "ldraw-root", "", "optional LDraw root override")
	flag.StringVar(&libraryID, "library-id", "", "optional Part Library Version UUID; defaults to deterministic manifest hash UUID")
	flag.StringVar(&createdBy, "created-by", "", "system actor UUID; defaults to a deterministic development system actor")
	flag.StringVar(&status, "status", "building", "Part Library Version status: building, active, retired, or failed")
	flag.BoolVar(&dryRun, "dry-run", false, "parse manifest and geometry without writing database")
	flag.IntVar(&limit, "limit", 0, "optional max canonical parts to import, for tests/smoke only")
	flag.Parse()

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	result, err := partlibrary.ImportStudioLibrary(ctx, partlibrary.ImportOptions{
		DatabaseURL:  databaseURL,
		ManifestPath: manifestPath,
		LDrawRoot:    ldrawRoot,
		LibraryID:    libraryID,
		CreatedBy:    createdBy,
		Status:       status,
		DryRun:       dryRun,
		Limit:        limit,
	})
	if err != nil {
		fmt.Fprintf(os.Stderr, "studio-import: %v\n", err)
		os.Exit(1)
	}
	payload, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		fmt.Fprintf(os.Stderr, "studio-import: marshal result: %v\n", err)
		os.Exit(1)
	}
	fmt.Println(string(payload))
}
