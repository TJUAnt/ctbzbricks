package httpapi

import (
	"log/slog"
	"net/http"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/artifact"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/auth"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/component"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/database"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/health"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/ingestion"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/storage"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/workbench"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
)

func NewRouter(cfg config.Config, databasePinger database.Pinger, logger *slog.Logger) *gin.Engine {
	return newRouter(cfg, databasePinger, logger, nil, nil, nil, nil, nil, nil)
}

func NewApplicationRouter(cfg config.Config, pool *pgxpool.Pool, logger *slog.Logger) *gin.Engine {
	objectStore := storage.New(cfg.Storage)
	return newRouter(
		cfg,
		pool,
		logger,
		component.NewHandler(component.NewService(pool), logger),
		artifact.NewHandler(artifact.NewService(pool, objectStore, cfg.Storage).WithImportConfig(cfg.Import), logger),
		ingestion.NewHandler(ingestion.NewService(pool), logger),
		task.NewHTTPHandler(task.NewService(pool), logger),
		auth.NewVerifier(cfg.Auth),
		workbench.NewHandler(workbench.NewService(pool, objectStore, cfg.Storage.SignedURLTTL), logger),
	)
}

func newRouter(
	cfg config.Config,
	databasePinger database.Pinger,
	logger *slog.Logger,
	componentHandler *component.Handler,
	artifactHandler *artifact.Handler,
	ingestionHandler *ingestion.Handler,
	taskHandler *task.HTTPHandler,
	verifier auth.TokenVerifier,
	workbenchHandler *workbench.Handler,
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
		if artifactHandler != nil {
			artifactHandler.Register(apiV1)
		}
		if ingestionHandler != nil {
			ingestionHandler.Register(apiV1)
		}
		if taskHandler != nil {
			taskHandler.Register(apiV1)
		}
		if workbenchHandler != nil {
			workbenchHandler.Register(apiV1)
		}
	}

	router.NoRoute(func(c *gin.Context) {
		apierror.Write(c, apierror.New("request.not_found", http.StatusNotFound, nil))
	})
	router.NoMethod(func(c *gin.Context) {
		apierror.Write(c, apierror.New("request.method_not_allowed", http.StatusMethodNotAllowed, nil))
	})
	return router
}
