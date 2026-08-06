package httpapi

import (
	"log/slog"
	"net/http"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/database"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/health"
	"github.com/gin-gonic/gin"
)

func NewRouter(cfg config.Config, databasePinger database.Pinger, logger *slog.Logger) *gin.Engine {
	if cfg.Environment == config.ProductionEnvironment {
		gin.SetMode(gin.ReleaseMode)
	} else {
		gin.SetMode(gin.TestMode)
	}

	router := gin.New()
	router.HandleMethodNotAllowed = true
	router.Use(
		traceMiddleware(),
		requestLoggerMiddleware(logger),
		recoveryMiddleware(logger),
		bodyLimitMiddleware(cfg.HTTP.MaxBodyBytes),
		requestTimeoutMiddleware(cfg.HTTP.RequestTimeout),
	)

	healthHandler := health.NewHandler(databasePinger, cfg.Database.ConnectTimeout, logger)
	router.GET("/health/live", healthHandler.Live)
	router.GET("/health/ready", healthHandler.Ready)

	router.NoRoute(func(c *gin.Context) {
		apierror.Write(c, apierror.New("request.not_found", http.StatusNotFound, nil))
	})
	router.NoMethod(func(c *gin.Context) {
		apierror.Write(c, apierror.New("request.method_not_allowed", http.StatusMethodNotAllowed, nil))
	})
	return router
}
