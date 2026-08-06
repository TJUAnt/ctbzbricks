package main

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/database"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/logging"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/worker"
)

func main() {
	bootstrapLogger := logging.New(os.Stdout, config.ProductionEnvironment)
	cfg, err := config.Load()
	if err != nil {
		bootstrapLogger.Error("invalid worker configuration", "errorCode", "config.invalid", "reason", err.Error())
		os.Exit(1)
	}
	logger := logging.New(os.Stdout, cfg.Environment)
	if err := run(cfg, logger); err != nil {
		logger.Error("Worker stopped", "errorCode", "worker.stopped", "reason", err.Error())
		os.Exit(1)
	}
}

func run(cfg config.Config, logger *slog.Logger) error {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	pool, err := database.NewPool(ctx, cfg.Database)
	if err != nil {
		return err
	}
	defer pool.Close()

	workerID := cfg.Worker.ID
	if workerID == "" {
		hostname, err := os.Hostname()
		if err != nil {
			hostname = "unknown-host"
		}
		workerID = fmt.Sprintf("%s-%d", hostname, os.Getpid())
	}
	logger.Info("Worker started", "workerId", workerID)
	defer logger.Info("Worker stopped", "workerId", workerID)
	return worker.Run(ctx, workerID, cfg.Worker.HealthCheckInterval, pool, logger)
}
