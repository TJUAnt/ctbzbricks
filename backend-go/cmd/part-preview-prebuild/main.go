package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"net/url"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/database"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/workbench"
)

// main 是 Part GLB 全库预生成维护入口；默认仅盘点，--execute 只调度 durable task，不在命令进程内计算模型。
func main() {
	var execute bool
	var force bool
	var libraryID string
	flag.BoolVar(&execute, "execute", false, "schedule the durable prebuild task")
	flag.BoolVar(&force, "force", false, "create a new execution when the same logical task already succeeded")
	flag.StringVar(&libraryID, "part-library-version-id", "", "explicit active/building Part Library; active is used when omitted")
	flag.Parse()

	cfg, err := config.Load()
	if err != nil {
		fatal(err)
	}
	if cfg.Storage.Provider != "supabase" || cfg.Storage.ServiceRoleKey == "" {
		fatal(fmt.Errorf("supabase server-side Storage configuration is required"))
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	pool, err := database.NewPool(ctx, cfg.Database)
	if err != nil {
		fatal(err)
	}
	defer pool.Close()

	result, err := workbench.SchedulePartPreviewPrebuild(ctx, pool, strings.TrimSpace(libraryID), !execute, force)
	if err != nil {
		fatal(err)
	}
	target, _ := url.Parse(cfg.Database.URL)
	output := map[string]any{
		"database":        strings.TrimPrefix(target.EscapedPath(), "/") + "@" + target.Host,
		"storageProvider": cfg.Storage.Provider, "storageBucket": cfg.Storage.Bucket,
		"storagePrefix": cfg.Storage.KeyPrefix, "execute": execute, "result": result,
	}
	encoded, err := json.MarshalIndent(output, "", "  ")
	if err != nil {
		fatal(err)
	}
	fmt.Println(string(encoded))
}

func fatal(err error) {
	fmt.Fprintf(os.Stderr, "part-preview-prebuild: %v\n", err)
	os.Exit(1)
}
