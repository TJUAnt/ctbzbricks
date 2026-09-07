package notification

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"sync"
	"sync/atomic"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/database"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/observability"
)

// RunnerOptions 只控制 Notification Worker；它与 GLB/通用 Task Worker 的并发和 lease 配置完全独立。
type RunnerOptions struct {
	PollInterval           time.Duration
	LeaseDuration          time.Duration
	HeartbeatInterval      time.Duration
	HealthCheckInterval    time.Duration
	MetricsRefreshInterval time.Duration
	Concurrency            int
}

// Run 启动 PostgreSQL Notification Delivery 消费循环；进程退出会等待当前批次结束，未完成 lease 可超时接管。
func Run(
	ctx context.Context,
	workerID string,
	options RunnerOptions,
	databasePinger database.Pinger,
	service *Service,
	metrics *observability.Registry,
	logger *slog.Logger,
) error {
	if err := validateRunnerOptions(options); err != nil {
		return err
	}
	refreshBacklog(ctx, service, metrics, logger)
	semaphore := make(chan struct{}, options.Concurrency)
	var running sync.WaitGroup
	process := func() {
		for recovered := 0; recovered < 100; recovered++ {
			found, err := service.RecoverExpired(ctx)
			if err != nil {
				logger.WarnContext(ctx, "expired notification delivery recovery failed", "workerId", workerID, "errorCode", "common.internal_error")
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
			claimed, found, err := service.Claim(ctx, workerID, options.LeaseDuration)
			if err != nil {
				<-semaphore
				logger.WarnContext(ctx, "notification delivery claim failed", "workerId", workerID, "errorCode", "common.internal_error")
				return
			}
			if !found {
				<-semaphore
				return
			}
			running.Add(1)
			go func() {
				defer running.Done()
				defer func() { <-semaphore }()
				execute(ctx, workerID, options, service, claimed, logger)
			}()
		}
	}

	process()
	pollTicker := time.NewTicker(options.PollInterval)
	healthTicker := time.NewTicker(options.HealthCheckInterval)
	metricsTicker := time.NewTicker(options.MetricsRefreshInterval)
	defer pollTicker.Stop()
	defer healthTicker.Stop()
	defer metricsTicker.Stop()
	for {
		select {
		case <-ctx.Done():
			running.Wait()
			return nil
		case <-pollTicker.C:
			process()
		case <-healthTicker.C:
			checkDatabase(ctx, options.HealthCheckInterval, databasePinger, workerID, logger)
		case <-metricsTicker.C:
			refreshBacklog(ctx, service, metrics, logger)
		}
	}
}

func execute(
	parent context.Context,
	workerID string,
	options RunnerOptions,
	service *Service,
	claimed ClaimedDelivery,
	logger *slog.Logger,
) {
	deliveryCtx, cancel := context.WithCancel(parent)
	defer cancel()
	var ownershipLost atomic.Bool
	heartbeatDone := make(chan struct{})
	heartbeatExited := make(chan struct{})
	go func() {
		defer close(heartbeatExited)
		ticker := time.NewTicker(options.HeartbeatInterval)
		defer ticker.Stop()
		for {
			select {
			case <-heartbeatDone:
				return
			case <-deliveryCtx.Done():
				return
			case <-ticker.C:
				owned, err := service.Heartbeat(deliveryCtx, workerID, claimed, options.LeaseDuration)
				if err != nil || !owned {
					ownershipLost.Store(true)
					cancel()
					return
				}
			}
		}
	}()

	var runErr error
	for deliveryCtx.Err() == nil {
		result, err := service.ProcessNextBatch(deliveryCtx, workerID, claimed)
		if err != nil {
			runErr = err
			break
		}
		if result.Completed {
			break
		}
	}
	close(heartbeatDone)
	<-heartbeatExited
	if parent.Err() != nil || ownershipLost.Load() || runErr == nil || errors.Is(runErr, ErrOwnershipLost) {
		return
	}
	failure := &Failure{Code: "common.internal_error", Retryable: true}
	var classified *Failure
	if errors.As(runErr, &classified) {
		failure = classified
	}
	finishCtx, finishCancel := context.WithTimeout(context.Background(), options.HeartbeatInterval)
	defer finishCancel()
	if err := service.FinishFailure(finishCtx, workerID, claimed, failure); err != nil && !errors.Is(err, ErrOwnershipLost) {
		logger.Warn("notification delivery finalization failed", "workerId", workerID, "errorCode", "common.internal_error")
	}
}

func refreshBacklog(ctx context.Context, service *Service, metrics *observability.Registry, logger *slog.Logger) {
	backlog, err := service.SampleBacklog(ctx)
	if err != nil {
		logger.WarnContext(ctx, "notification backlog sampling failed", "errorCode", "common.internal_error")
		return
	}
	metrics.SetComponentNotificationBacklog(backlog.PendingEvents, backlog.OldestPendingAge)
	metrics.SetComponentNotificationDeadLetterBacklog(backlog.UnresolvedDeadLetters, backlog.OldestDeadLetterAge)
}

func checkDatabase(ctx context.Context, timeout time.Duration, pinger database.Pinger, workerID string, logger *slog.Logger) {
	checkCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	if err := pinger.Ping(checkCtx); err != nil {
		logger.WarnContext(checkCtx, "notification worker database health check failed", "workerId", workerID, "check", "database")
	}
}

func validateRunnerOptions(options RunnerOptions) error {
	if options.PollInterval <= 0 || options.LeaseDuration <= 0 || options.HeartbeatInterval <= 0 ||
		options.HealthCheckInterval <= 0 || options.MetricsRefreshInterval <= 0 ||
		options.Concurrency < 1 || options.Concurrency > 4 {
		return fmt.Errorf("invalid notification worker options")
	}
	if options.HeartbeatInterval*2 >= options.LeaseDuration {
		return fmt.Errorf("notification heartbeat must be less than half the lease duration")
	}
	return nil
}
