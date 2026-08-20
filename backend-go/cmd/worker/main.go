package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/artifact"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/component"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/database"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/logging"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/storage"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/workbench"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/worker"
)

func main() {
	bootstrapLogger := logging.New(os.Stdout, config.ProductionEnvironment)
	cfg, err := config.Load()
	if err != nil {
		bootstrapLogger.Error("invalid worker configuration", "errorCode", "config.invalid", "reason", err.Error())
		os.Exit(1)
	}
	if err := validateWorkerConfig(cfg); err != nil {
		bootstrapLogger.Error("invalid worker configuration", "errorCode", "config.invalid", "reason", err.Error())
		os.Exit(1)
	}
	logger := logging.New(os.Stdout, cfg.Environment)
	if err := run(cfg, logger); err != nil {
		logger.Error("Worker stopped", "errorCode", "worker.stopped", "reason", err.Error())
		os.Exit(1)
	}
}

func validateWorkerConfig(cfg config.Config) error {
	if cfg.Storage.Provider == "supabase" && cfg.Storage.ServiceRoleKey == "" {
		return errors.New("SUPABASE_STORAGE_SERVICE_ROLE_KEY or SUPABASE_SECRET_KEY is required by the worker for server-side storage operations")
	}
	return nil
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
	var maintenance worker.UploadMaintenance
	handlers := map[string]task.Handler{}
	objectStore := storage.New(cfg.Storage)
	handlers[task.ComponentPurgeType] = component.NewPurgeTaskHandler(pool, objectStore)
	if cfg.Storage.Provider != "disabled" {
		artifactService := artifact.NewService(pool, objectStore, cfg.Storage).WithImportConfig(cfg.Import)
		maintenance = artifactService
		handlers[task.ArtifactVerifyType] = artifact.NewVerificationTaskHandler(artifactService)
		if cfg.PartPreview.LDrawRoot != "" {
			previewHandler, handlerErr := workbench.NewPreviewTaskHandler(
				pool, objectStore, cfg.Storage.KeyPrefix, cfg.PartPreview.LDrawRoot,
			)
			if handlerErr != nil {
				return handlerErr
			}
			handlers[task.PreviewMaterializeType] = previewHandler
			partPreviewHandler, handlerErr := workbench.NewPartPreviewTaskHandler(
				pool, objectStore, cfg.Storage.KeyPrefix, cfg.PartPreview.LDrawRoot,
			)
			if handlerErr != nil {
				return handlerErr
			}
			handlers[task.PartPreviewMaterializeType] = partPreviewHandler
		} else {
			logger.Warn("Component and Part preview capabilities disabled", "errorCode", "worker.preview_disabled")
		}
	}
	handlers[task.ComponentValidateType] = workbench.NewValidationTaskHandler(pool)
	return worker.Run(ctx, workerID, worker.Options{
		PollInterval: cfg.Worker.PollInterval, LeaseDuration: cfg.Worker.LeaseDuration,
		HeartbeatInterval: cfg.Worker.HeartbeatInterval, RetryDelay: cfg.Worker.RetryDelay,
		MaintenanceInterval: cfg.Worker.HealthCheckInterval, Concurrency: cfg.Worker.Concurrency,
	}, pool, maintenance, task.NewService(pool), handlers, logger)
}
