package worker

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"sort"
	"sync"
	"sync/atomic"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/database"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
)

type UploadMaintenance interface {
	CleanupExpired(context.Context, time.Time, int32) (int, error)
}

type Options struct {
	PollInterval        time.Duration
	LeaseDuration       time.Duration
	HeartbeatInterval   time.Duration
	RetryDelay          time.Duration
	MaintenanceInterval time.Duration
	Concurrency         int
}

func Run(
	ctx context.Context,
	workerID string,
	options Options,
	databasePinger database.Pinger,
	maintenance UploadMaintenance,
	queue *task.Service,
	handlers map[string]task.Handler,
	logger *slog.Logger,
) error {
	if err := validateOptions(options); err != nil {
		return err
	}
	taskTypes := make([]string, 0, len(handlers))
	for taskType := range handlers {
		taskTypes = append(taskTypes, taskType)
	}
	sort.Strings(taskTypes)
	// 启动日志必须给出实际可领取的能力，避免 API 正常但独立 Worker 缺失时只能从 pending 任务反推原因。
	logger.InfoContext(ctx, "Worker task capabilities ready", "workerId", workerID, "taskTypes", taskTypes)

	checkMaintenance(ctx, workerID, options.MaintenanceInterval, databasePinger, maintenance, logger)
	semaphore := make(chan struct{}, options.Concurrency)
	var running sync.WaitGroup
	process := func() {
		if queue == nil || len(taskTypes) == 0 {
			return
		}
		for recovered := 0; recovered < 100; recovered++ {
			found, err := queue.RecoverExpired(ctx)
			if err != nil {
				logger.WarnContext(ctx, "expired task recovery failed", "workerId", workerID, "errorCode", "common.internal_error")
				break
			}
			if !found {
				break
			}
		}
		for {
			select {
			case semaphore <- struct{}{}:
			default:
				return
			}
			claimed, found, err := queue.Claim(ctx, workerID, taskTypes, options.LeaseDuration)
			if err != nil {
				<-semaphore
				logger.WarnContext(ctx, "task claim failed", "workerId", workerID, "errorCode", "common.internal_error")
				return
			}
			if !found {
				<-semaphore
				return
			}
			handler := handlers[claimed.TaskType]
			running.Add(1)
			go func() {
				defer running.Done()
				defer func() { <-semaphore }()
				execute(ctx, workerID, options, queue, handler, claimed, logger)
			}()
		}
	}

	process()
	pollTicker := time.NewTicker(options.PollInterval)
	maintenanceTicker := time.NewTicker(options.MaintenanceInterval)
	defer pollTicker.Stop()
	defer maintenanceTicker.Stop()
	for {
		select {
		case <-ctx.Done():
			running.Wait()
			return nil
		case <-pollTicker.C:
			process()
		case <-maintenanceTicker.C:
			checkMaintenance(ctx, workerID, options.MaintenanceInterval, databasePinger, maintenance, logger)
		}
	}
}

func execute(
	parent context.Context,
	workerID string,
	options Options,
	queue *task.Service,
	handler task.Handler,
	claimed task.ClaimedTask,
	logger *slog.Logger,
) {
	startedAt := time.Now()
	taskID := uuidutil.String(claimed.ID)
	logger.InfoContext(parent, "task execution started",
		"workerId", workerID, "taskId", taskID, "taskType", claimed.TaskType, "attempt", claimed.Attempt,
	)
	handlerCtx, cancel := context.WithCancel(parent)
	defer cancel()
	var cancellationRequested atomic.Bool
	var ownershipLost atomic.Bool
	heartbeatDone := make(chan struct{})
	go func() {
		ticker := time.NewTicker(options.HeartbeatInterval)
		defer ticker.Stop()
		for {
			select {
			case <-heartbeatDone:
				return
			case <-handlerCtx.Done():
				return
			case <-ticker.C:
				owned, cancelRequested, err := queue.Heartbeat(handlerCtx, workerID, claimed, options.LeaseDuration)
				if err != nil || !owned {
					ownershipLost.Store(true)
					cancel()
					return
				}
				if cancelRequested {
					cancellationRequested.Store(true)
					cancel()
					return
				}
			}
		}
	}()

	result, err := handler.Handle(handlerCtx, claimed)
	close(heartbeatDone)
	if parent.Err() != nil || ownershipLost.Load() {
		return
	}
	if cancellationRequested.Load() {
		failure := &task.Failure{Code: "common.internal_error", Params: map[string]any{}, Retryable: true}
		finishCtx, finishCancel := context.WithTimeout(context.Background(), options.HeartbeatInterval)
		defer finishCancel()
		if finishErr := queue.FinishFailure(finishCtx, workerID, claimed, failure, options.RetryDelay); finishErr != nil {
			logger.Warn("task cancellation finalization failed", "workerId", workerID, "taskType", claimed.TaskType, "errorCode", "common.internal_error")
		} else {
			logger.Warn("task execution cancelled", "workerId", workerID, "taskId", taskID,
				"taskType", claimed.TaskType, "attempt", claimed.Attempt, "durationMs", time.Since(startedAt).Milliseconds())
		}
		return
	}
	if err == nil {
		if completeErr := queue.Complete(parent, workerID, claimed, result); completeErr != nil {
			logger.WarnContext(parent, "task completion failed", "workerId", workerID, "taskType", claimed.TaskType, "errorCode", "common.internal_error")
		} else {
			logger.InfoContext(parent, "task execution succeeded", "workerId", workerID, "taskId", taskID,
				"taskType", claimed.TaskType, "attempt", claimed.Attempt, "durationMs", time.Since(startedAt).Milliseconds())
		}
		return
	}
	var failure *task.Failure
	if !errors.As(err, &failure) {
		failure = &task.Failure{Code: "common.internal_error", Params: map[string]any{}, Retryable: true}
	}
	if finishErr := queue.FinishFailure(parent, workerID, claimed, failure, options.RetryDelay); finishErr != nil {
		logger.WarnContext(parent, "task failure finalization failed", "workerId", workerID, "taskType", claimed.TaskType, "errorCode", "common.internal_error")
	} else {
		// 失败日志只记录稳定 code 和机器标识，不泄露底层对象存储、SQL 或用户内容。
		logger.WarnContext(parent, "task execution attempt failed", "workerId", workerID, "taskId", taskID,
			"taskType", claimed.TaskType, "attempt", claimed.Attempt, "failureCode", failure.Code,
			"retryable", failure.Retryable, "durationMs", time.Since(startedAt).Milliseconds())
	}
}

func checkMaintenance(ctx context.Context, workerID string, timeout time.Duration, databasePinger database.Pinger, maintenance UploadMaintenance, logger *slog.Logger) {
	checkCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	if err := databasePinger.Ping(checkCtx); err != nil {
		logger.WarnContext(checkCtx, "worker database health check failed", "workerId", workerID, "check", "database")
		return
	}
	logger.DebugContext(checkCtx, "worker database health check passed", "workerId", workerID)
	if maintenance == nil {
		return
	}
	cleaned, err := maintenance.CleanupExpired(checkCtx, time.Now().UTC(), 100)
	if err != nil {
		logger.WarnContext(checkCtx, "expired upload cleanup failed", "workerId", workerID, "errorCode", "component_repo.storage_unavailable")
		return
	}
	if cleaned > 0 {
		logger.InfoContext(checkCtx, "expired uploads cleaned", "workerId", workerID, "count", cleaned)
	}
}

func validateOptions(options Options) error {
	if options.PollInterval <= 0 || options.LeaseDuration <= 0 || options.HeartbeatInterval <= 0 ||
		options.RetryDelay <= 0 || options.MaintenanceInterval <= 0 || options.Concurrency <= 0 {
		return fmt.Errorf("invalid worker task options")
	}
	if options.HeartbeatInterval*2 >= options.LeaseDuration {
		return fmt.Errorf("worker heartbeat must be less than half the lease duration")
	}
	return nil
}
