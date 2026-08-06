package health

import (
	"context"
	"log/slog"
	"net/http"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/database"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/requestmeta"
	"github.com/gin-gonic/gin"
)

type Handler struct {
	database database.Pinger
	timeout  time.Duration
	logger   *slog.Logger
}

type response struct {
	Status  string            `json:"status"`
	Checks  map[string]string `json:"checks,omitempty"`
	TraceID string            `json:"traceId"`
}

func NewHandler(databasePinger database.Pinger, timeout time.Duration, logger *slog.Logger) *Handler {
	return &Handler{database: databasePinger, timeout: timeout, logger: logger}
}

func (h *Handler) Live(c *gin.Context) {
	c.JSON(http.StatusOK, response{
		Status:  "ok",
		TraceID: requestmeta.FromGin(c),
	})
}

func (h *Handler) Ready(c *gin.Context) {
	ctx, cancel := context.WithTimeout(c.Request.Context(), h.timeout)
	defer cancel()
	if err := h.database.Ping(ctx); err != nil {
		h.logger.WarnContext(ctx, "readiness check failed",
			"check", "database",
			"traceId", requestmeta.FromGin(c),
		)
		c.JSON(http.StatusServiceUnavailable, response{
			Status:  "not_ready",
			Checks:  map[string]string{"database": "unavailable"},
			TraceID: requestmeta.FromGin(c),
		})
		return
	}
	c.JSON(http.StatusOK, response{
		Status:  "ready",
		Checks:  map[string]string{"database": "ok"},
		TraceID: requestmeta.FromGin(c),
	})
}
