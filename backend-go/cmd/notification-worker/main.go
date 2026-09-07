package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/database"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/logging"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/notification"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/observability"
)

func main() {
	bootstrapLogger := logging.New(os.Stdout, config.ProductionEnvironment)
	cfg, err := config.Load()
	if err != nil {
		bootstrapLogger.Error("invalid notification worker configuration", "errorCode", "config.invalid", "reason", err.Error())
		os.Exit(1)
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	logger := logging.New(os.Stdout, cfg.Environment)
	if err := run(ctx, cfg, logger); err != nil {
		logger.Error("Notification Worker stopped", "errorCode", "notification.worker.stopped", "reason", err.Error())
		os.Exit(1)
	}
}

// run 启动仅处理 Component 通知 Delivery 的独立进程；它拥有独立数据库连接池和运维端点，
// 不注册通用 Task/GLB Handler，也不访问对象存储。
func run(parent context.Context, cfg config.Config, logger *slog.Logger) error {
	ctx, cancel := context.WithCancel(parent)
	defer cancel()
	pool, err := database.NewPool(ctx, cfg.Database)
	if err != nil {
		return err
	}
	defer pool.Close()

	workerID := cfg.NotificationWorker.ID
	if workerID == "" {
		hostname, hostnameErr := os.Hostname()
		if hostnameErr != nil {
			hostname = "unknown-host"
		}
		workerID = fmt.Sprintf("notification-%s-%d", hostname, os.Getpid())
	}
	metrics := observability.NewRegistry()
	service := notification.NewService(pool, metrics)
	server := &http.Server{
		Addr:              cfg.NotificationWorker.MetricsAddress(),
		Handler:           newMonitoringHandler(pool, cfg.Database.ConnectTimeout, metrics, logger),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      10 * time.Second,
		IdleTimeout:       time.Minute,
	}
	serverErrors := make(chan error, 1)
	workerErrors := make(chan error, 1)
	go func() {
		logger.Info("Notification Worker monitoring listening", "address", cfg.NotificationWorker.MetricsAddress())
		serverErrors <- server.ListenAndServe()
	}()
	go func() {
		workerErrors <- notification.Run(ctx, workerID, notification.RunnerOptions{
			PollInterval:           cfg.NotificationWorker.PollInterval,
			LeaseDuration:          cfg.NotificationWorker.LeaseDuration,
			HeartbeatInterval:      cfg.NotificationWorker.HeartbeatInterval,
			HealthCheckInterval:    cfg.NotificationWorker.HealthCheckInterval,
			MetricsRefreshInterval: cfg.NotificationWorker.MetricsRefreshInterval,
			Concurrency:            cfg.NotificationWorker.Concurrency,
		}, pool, service, metrics, logger)
	}()
	logger.Info("Notification Worker started", "workerId", workerID)
	defer logger.Info("Notification Worker stopped", "workerId", workerID)

	var runErr error
	workerStopped := false
	select {
	case <-parent.Done():
	case err := <-serverErrors:
		if !errors.Is(err, http.ErrServerClosed) {
			runErr = err
		}
	case err := <-workerErrors:
		runErr = err
		workerStopped = true
	}
	cancel()
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), cfg.HTTP.ShutdownTimeout)
	defer shutdownCancel()
	if err := server.Shutdown(shutdownCtx); err != nil {
		runErr = errors.Join(runErr, errors.New("graceful notification monitoring shutdown failed"), err)
	}
	if !workerStopped {
		select {
		case err := <-workerErrors:
			runErr = errors.Join(runErr, err)
		case <-shutdownCtx.Done():
			runErr = errors.Join(runErr, errors.New("graceful notification worker shutdown timed out"))
		}
	}
	return runErr
}

type monitoringResponse struct {
	Status string            `json:"status"`
	Checks map[string]string `json:"checks,omitempty"`
}

// newMonitoringHandler 只暴露内部健康检查和低基数指标，不承载业务 API。
func newMonitoringHandler(databasePinger database.Pinger, timeout time.Duration, metrics *observability.Registry, logger *slog.Logger) http.Handler {
	mux := http.NewServeMux()
	mux.Handle("/metrics", metrics)
	mux.HandleFunc("/health/live", func(response http.ResponseWriter, _ *http.Request) {
		writeMonitoringJSON(response, http.StatusOK, monitoringResponse{Status: "ok"})
	})
	mux.HandleFunc("/health/ready", func(response http.ResponseWriter, request *http.Request) {
		ctx, cancel := context.WithTimeout(request.Context(), timeout)
		defer cancel()
		if err := databasePinger.Ping(ctx); err != nil {
			logger.WarnContext(ctx, "notification readiness check failed", "check", "database")
			writeMonitoringJSON(response, http.StatusServiceUnavailable, monitoringResponse{
				Status: "not_ready", Checks: map[string]string{"database": "unavailable"},
			})
			return
		}
		writeMonitoringJSON(response, http.StatusOK, monitoringResponse{
			Status: "ready", Checks: map[string]string{"database": "ok"},
		})
	})
	return mux
}

func writeMonitoringJSON(response http.ResponseWriter, status int, body monitoringResponse) {
	response.Header().Set("Content-Type", "application/json; charset=utf-8")
	response.WriteHeader(status)
	_ = json.NewEncoder(response).Encode(body)
}
