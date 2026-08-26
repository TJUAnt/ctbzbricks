package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/workbench"
	"github.com/jackc/pgx/v5/pgxpool"
)

// main 是 Preview Box 历史回填入口；这里只调度 durable task，不在维护进程内执行几何计算。
func main() {
	var databaseURL string
	var batchSize int
	var maxVersions int
	var dryRun bool
	flag.StringVar(&databaseURL, "database-url", os.Getenv("DATABASE_URL"), "PostgreSQL database URL")
	flag.IntVar(&batchSize, "batch-size", 100, "versions selected per batch")
	flag.IntVar(&maxVersions, "max-versions", 0, "optional scheduling limit; zero means all")
	flag.BoolVar(&dryRun, "dry-run", false, "count candidates without scheduling tasks")
	flag.Parse()

	if strings.TrimSpace(databaseURL) == "" {
		fmt.Fprintln(os.Stderr, "preview-bounds-backfill: DATABASE_URL is required")
		os.Exit(2)
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		fmt.Fprintf(os.Stderr, "preview-bounds-backfill: connect database: %v\n", err)
		os.Exit(1)
	}
	defer pool.Close()

	result, err := workbench.SchedulePreviewBoundsBackfill(ctx, pool, batchSize, maxVersions, dryRun)
	if err != nil {
		fmt.Fprintf(os.Stderr, "preview-bounds-backfill: %v\n", err)
		os.Exit(1)
	}
	payload, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		fmt.Fprintf(os.Stderr, "preview-bounds-backfill: marshal result: %v\n", err)
		os.Exit(1)
	}
	fmt.Println(string(payload))
}
