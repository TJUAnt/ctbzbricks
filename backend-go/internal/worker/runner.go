package worker

import (
	"context"
	"log/slog"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/database"
)

// Run keeps the independent Worker process alive and verifies its database
// dependency. Durable task claiming is introduced in migration phase G5.
func Run(ctx context.Context, workerID string, interval time.Duration, databasePinger database.Pinger, logger *slog.Logger) error {
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
