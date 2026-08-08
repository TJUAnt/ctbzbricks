package worker

import (
	"context"
	"log/slog"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/database"
)

// Run keeps the independent Worker process alive and verifies its database
// dependency. Durable task claiming is introduced in migration phase G5.
type UploadMaintenance interface {
	CleanupExpired(context.Context, time.Time, int32) (int, error)
}

func Run(ctx context.Context, workerID string, interval time.Duration, databasePinger database.Pinger, maintenance UploadMaintenance, logger *slog.Logger) error {
	check := func() {
		checkCtx, cancel := context.WithTimeout(ctx, interval)
		defer cancel()
		if err := databasePinger.Ping(checkCtx); err != nil {
			logger.WarnContext(checkCtx, "worker database health check failed",
				"workerId", workerID,
				"check", "database",
			)
			return
		}
		logger.DebugContext(checkCtx, "worker database health check passed", "workerId", workerID)
		if maintenance == nil {
			return
		}
		cleaned, err := maintenance.CleanupExpired(checkCtx, time.Now().UTC(), 100)
		if err != nil {
			logger.WarnContext(checkCtx, "expired upload cleanup failed",
				"workerId", workerID, "errorCode", "component_repo.storage_unavailable")
			return
		}
		if cleaned > 0 {
			logger.InfoContext(checkCtx, "expired uploads cleaned", "workerId", workerID, "count", cleaned)
		}
	}

	check()
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
			check()
		}
	}
}
