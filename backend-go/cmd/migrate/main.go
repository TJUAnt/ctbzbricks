package main

import (
	"context"
	"database/sql"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	"github.com/ctbzbricks/brickbuilder/backend-go/db/migrations"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/logging"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
)

const usage = `Usage: go run ./cmd/migrate <command>

Commands:
  status      Show migration status
  version     Show current migration version
  up          Apply all pending migrations
  up-by-one   Apply one pending migration
  down        Roll back one migration
  redo        Roll back and re-apply one migration
  reset       Roll back all migrations (destructive; drops component_repo)

Goose exclusively owns the component_repo schema. Alembic may only manage
unmigrated legacy objects outside that schema.`

var allowedCommands = map[string]struct{}{
	"status": {}, "version": {}, "up": {}, "up-by-one": {},
	"down": {}, "redo": {}, "reset": {},
}

func main() {
	if len(os.Args) != 2 || os.Args[1] == "--help" || os.Args[1] == "-h" || os.Args[1] == "help" {
		fmt.Println(usage)
		if len(os.Args) == 2 {
			return
		}
		os.Exit(2)
	}
	command := os.Args[1]
	if _, ok := allowedCommands[command]; !ok {
		fmt.Fprintln(os.Stderr, "unsupported migration command")
		fmt.Fprintln(os.Stderr, usage)
		os.Exit(2)
	}

	logger := logging.New(os.Stdout, config.ProductionEnvironment)
	cfg, err := config.Load()
	if err != nil {
		logger.Error("invalid migration configuration", "errorCode", "config.invalid", "reason", err.Error())
		os.Exit(1)
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	db, err := sql.Open("pgx", cfg.Database.URL)
	if err != nil {
		logger.Error("migration database open failed", "errorCode", "database.open_failed")
		os.Exit(1)
	}
	defer db.Close()
	pingCtx, cancel := context.WithTimeout(ctx, cfg.Database.ConnectTimeout)
	defer cancel()
	if err := db.PingContext(pingCtx); err != nil {
		logger.Error("migration database unavailable", "errorCode", "database.unavailable")
		os.Exit(1)
	}

	goose.SetBaseFS(migrations.Files)
	if err := goose.SetDialect("postgres"); err != nil {
		logger.Error("migration dialect configuration failed", "errorCode", "database.migration_config_invalid")
		os.Exit(1)
	}
	if err := goose.RunContext(ctx, command, db, "."); err != nil {
		logger.Error("migration command failed", "errorCode", "database.migration_failed", "command", command)
		os.Exit(1)
	}
}
