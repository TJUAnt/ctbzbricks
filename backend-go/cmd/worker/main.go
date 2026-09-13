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
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/feedrender"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/ingestion"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/logging"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/pixel2d"
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
	// 只有会领取 GLB 预览任务的进程才依赖 LDraw 文件库；Feed 渲染从已验证 GLB 开始。
	if cfg.Storage.Provider != "disabled" && requiresPartPreview(cfg) && cfg.PartPreview.LDrawRoot == "" {
		return errors.New("LDRAW_ROOT is required by the worker for Component preview materialization")
	}
	return nil
}

// requiresPartPreview 判断当前部署能力是否包含必须读取 LDraw 文件库的 GLB 计算任务。
// 未限制类型表示通用 Worker，仍需保留完整预览能力。
func requiresPartPreview(cfg config.Config) bool {
	if len(cfg.Worker.TaskTypes) == 0 {
		return true
	}
	for _, kind := range cfg.Worker.TaskTypes {
		switch kind {
		case task.PreviewMaterializeType, task.PartPreviewMaterializeType, task.PartPreviewPrebuildType:
			return true
		}
	}
	return false
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
	// Component 关系清理不依赖对象存储；即使 Storage 被禁用，也必须消费删除事务原子创建的持久任务。
	handlers[task.RelationshipCleanupType] = component.NewRelationshipCleanupTaskHandler(pool)
	objectStore := storage.New(cfg.Storage)
	// Feed 任务即使在对象存储暂不可用时也必须被消费，让有限重试最终推进到 fallback，避免发布事件永久 pending。
	handlers[feedrender.TaskType] = feedrender.NewPathTracingHandler(
		pool, objectStore, cfg.Storage.KeyPrefix, cfg.FeedRender.BlenderPath, cfg.FeedRender.Timeout,
	)
	if claimsTaskType(cfg.Worker, feedrender.TaskType) {
		if cfg.FeedRender.BlenderPath == "" {
			logger.Warn("Feed path tracer unavailable; raster fallback active", "errorCode", "worker.feed_path_tracer_unavailable")
		} else {
			logger.Info("Feed path tracer requested", "engine", feedrender.PathTracerEngine)
		}
	}
	if cfg.Storage.Provider != "disabled" {
		// 2D 图片、编辑和拼接统一使用共享持久任务调度，不创建进程本地队列。
		pixelService := pixel2d.NewService(pool, objectStore, cfg.Storage)
		handlers[pixel2d.GenerateType] = pixelService
		handlers[pixel2d.EditType] = pixelService
		handlers[pixel2d.DesignType] = pixelService
		artifactService := artifact.NewService(pool, objectStore, cfg.Storage).WithImportConfig(cfg.Import)
		maintenance = artifactService
		handlers[task.ArtifactVerifyType] = artifact.NewVerificationTaskHandler(artifactService)
		handlers[task.ImportParseType] = ingestion.NewImportParseTaskHandler(pool, objectStore, cfg.Import)
		if requiresPartPreview(cfg) && cfg.PartPreview.LDrawRoot != "" {
			partOptimizer, optimizerErr := workbench.NewGLTFPackOptimizer(cfg.PartPreview.GLTFPackPath)
			if optimizerErr != nil {
				return optimizerErr
			}
			previewHandler, handlerErr := workbench.NewPreviewTaskHandler(
				pool, objectStore, cfg.Storage.KeyPrefix, cfg.PartPreview.LDrawRoot,
			)
			if handlerErr != nil {
				return handlerErr
			}
			handlers[task.PreviewMaterializeType] = previewHandler
			partPreviewHandler, handlerErr := workbench.NewPartPreviewTaskHandler(
				pool, objectStore, cfg.Storage.KeyPrefix, cfg.PartPreview.LDrawRoot, partOptimizer,
			)
			if handlerErr != nil {
				return handlerErr
			}
			handlers[task.PartPreviewMaterializeType] = partPreviewHandler
			handlers[task.PartPreviewPrebuildType] = workbench.NewPartPreviewPrebuildTaskHandler(partPreviewHandler)
		} else if requiresPartPreview(cfg) {
			logger.Warn("Component and Part preview capabilities disabled", "errorCode", "worker.preview_disabled")
		}
	}
	handlers[task.ComponentValidateType] = workbench.NewValidationTaskHandler(pool)
	handlers[workbench.RelationDetectionType] = workbench.NewRelationTaskHandler(pool)
	if len(cfg.Worker.TaskTypes) > 0 {
		// 专用 Worker 只 claim 显式能力，并关闭通用上传维护，避免 Part 批处理顺带改变其他业务状态。
		selected := make(map[string]task.Handler, len(cfg.Worker.TaskTypes))
		for _, taskType := range cfg.Worker.TaskTypes {
			handler, exists := handlers[taskType]
			if !exists {
				return fmt.Errorf("WORKER_TASK_TYPES contains unavailable task type %q", taskType)
			}
			selected[taskType] = handler
		}
		handlers = selected
		maintenance = nil
		logger.Info("Worker capabilities restricted", "taskTypes", cfg.Worker.TaskTypes)
	} else if len(cfg.Worker.ExcludedTaskTypes) > 0 {
		// 生产通用 Worker 只移交明确的重资源能力；上传过期清理等通用维护仍由它负责。
		for _, taskType := range cfg.Worker.ExcludedTaskTypes {
			if _, exists := handlers[taskType]; !exists {
				return fmt.Errorf("WORKER_EXCLUDED_TASK_TYPES contains unavailable task type %q", taskType)
			}
			delete(handlers, taskType)
		}
		logger.Info("Worker capabilities excluded", "taskTypes", cfg.Worker.ExcludedTaskTypes)
	}
	return worker.Run(ctx, workerID, worker.Options{
		PollInterval: cfg.Worker.PollInterval, LeaseDuration: cfg.Worker.LeaseDuration,
		HeartbeatInterval: cfg.Worker.HeartbeatInterval, RetryDelay: cfg.Worker.RetryDelay,
		MaintenanceInterval: cfg.Worker.HealthCheckInterval, Concurrency: cfg.Worker.Concurrency,
	}, pool, maintenance, task.NewService(pool), handlers, logger)
}

// claimsTaskType 仅用于启动期能力判断；真正的领取集合仍由下方 handler 过滤和数据库 claim 共同约束。
func claimsTaskType(cfg config.WorkerConfig, taskType string) bool {
	if len(cfg.TaskTypes) > 0 {
		for _, allowed := range cfg.TaskTypes {
			if allowed == taskType {
				return true
			}
		}
		return false
	}
	for _, excluded := range cfg.ExcludedTaskTypes {
		if excluded == taskType {
			return false
		}
	}
	return true
}
