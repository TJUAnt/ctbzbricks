package httpapi

import (
	"log/slog"
	"net/http"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/artifact"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/auth"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/component"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/componentwatch"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/database"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/health"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/ingestion"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/observability"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/pixel2d"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/storage"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/workbench"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
)

func NewRouter(cfg config.Config, databasePinger database.Pinger, logger *slog.Logger) *gin.Engine {
	return newRouter(cfg, databasePinger, logger, observability.NewRegistry(), nil, nil, nil, nil, nil, nil, nil)
}

func NewApplicationRouter(cfg config.Config, pool *pgxpool.Pool, logger *slog.Logger) *gin.Engine {
	objectStore := storage.New(cfg.Storage)
	metrics := observability.NewRegistry()
	return newRouter(
		cfg,
		pool,
		logger,
		metrics,
		component.NewHandler(component.NewService(pool).WithMetrics(metrics), logger),
		componentwatch.NewHandler(componentwatch.NewService(pool).WithMetrics(metrics), logger),
		artifact.NewHandler(artifact.NewService(pool, objectStore, cfg.Storage).WithImportConfig(cfg.Import).WithLogger(logger), logger),
		ingestion.NewHandler(ingestion.NewService(pool), logger),
		task.NewHTTPHandler(task.NewService(pool), logger),
		auth.NewVerifier(cfg.Auth),
		workbench.NewHandler(workbench.NewService(pool, objectStore, cfg.Storage.SignedURLTTL), logger),
		pixel2d.NewHandler(pixel2d.NewService(pool, objectStore, cfg.Storage), logger),
	)
}

func newRouter(
	cfg config.Config,
	databasePinger database.Pinger,
	logger *slog.Logger,
	metrics *observability.Registry,
	componentHandler *component.Handler,
	componentWatchHandler *componentwatch.Handler,
	artifactHandler *artifact.Handler,
	ingestionHandler *ingestion.Handler,
	taskHandler *task.HTTPHandler,
	verifier auth.TokenVerifier,
	workbenchHandler *workbench.Handler,
	pixelHandlers ...*pixel2d.Handler,
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
	// 指标只包含冻结机器标签；生产入口仍必须把该路径限制在内部监控网络。
	router.GET("/metrics", gin.WrapH(metrics))
	observability.NewI18nTelemetry().Register(router)
	if verifier != nil {
		apiV1 := router.Group("/api/v1", authenticationMiddleware(verifier))
		// 新领域复用认证与共享任务，业务查询仍在独立 schema 中。
		for _, handler := range pixelHandlers {
			if handler != nil {
				handler.Register(apiV1)
			}
		}
		// 页面刷新只通过这个 Go 入口二次确认 Supabase 会话；普通业务 API 仍只承担本地 JWT 校验。
		auth.NewSessionHandler(auth.NewSupabaseSessionValidator(cfg.Auth), logger).Register(apiV1)
		if componentHandler != nil {
			componentHandler.Register(apiV1)
		}
		if componentWatchHandler != nil {
			componentWatchHandler.Register(apiV1)
		}
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
