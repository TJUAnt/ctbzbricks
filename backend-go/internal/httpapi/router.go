package httpapi

import (
	"log/slog"
	"net/http"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/auth"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/component"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/database"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/health"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
)

func NewRouter(cfg config.Config, databasePinger database.Pinger, logger *slog.Logger) *gin.Engine {
	return newRouter(cfg, databasePinger, logger, nil, nil)
}

func NewApplicationRouter(cfg config.Config, pool *pgxpool.Pool, logger *slog.Logger) *gin.Engine {
	return newRouter(
		cfg,
		pool,
		logger,
		component.NewHandler(component.NewService(pool), logger),
		auth.NewVerifier(cfg.Auth),
	)
}

func newRouter(
	cfg config.Config,
	databasePinger database.Pinger,
	logger *slog.Logger,
	componentHandler *component.Handler,
	verifier auth.TokenVerifier,
) *gin.Engine {
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
	if componentHandler != nil && verifier != nil {
		apiV1 := router.Group("/api/v1", authenticationMiddleware(verifier))
		componentHandler.Register(apiV1)
	}

	router.NoRoute(func(c *gin.Context) {
		apierror.Write(c, apierror.New("request.not_found", http.StatusNotFound, nil))
	})
	router.NoMethod(func(c *gin.Context) {
		apierror.Write(c, apierror.New("request.method_not_allowed", http.StatusMethodNotAllowed, nil))
	})
	return router
}
