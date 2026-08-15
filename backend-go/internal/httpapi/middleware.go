package httpapi

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"runtime/debug"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/auth"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/requestmeta"
	"github.com/gin-gonic/gin"
)

func traceMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		traceID := requestmeta.ResolveTraceID(c.GetHeader(requestmeta.TraceIDHeader))
		c.Set(requestmeta.TraceIDKey, traceID)
		c.Header(requestmeta.TraceIDHeader, traceID)
		c.Next()
	}
}

func authenticationMiddleware(verifier auth.TokenVerifier) gin.HandlerFunc {
	return func(c *gin.Context) {
		actor, err := verifier.VerifyAuthorization(c.Request.Context(), c.GetHeader("Authorization"))
		if err != nil {
			apierror.Write(c, apierror.New(auth.FailureCode(err), http.StatusUnauthorized, nil))
			return
		}
		auth.SetActor(c, actor)
		c.Next()
	}
}

func requestLoggerMiddleware(logger *slog.Logger) gin.HandlerFunc {
	return func(c *gin.Context) {
		started := time.Now()
		c.Next()
		route := c.FullPath()
		if route == "" {
			route = c.Request.URL.Path
		}
		logger.InfoContext(c.Request.Context(), "API request completed",
			"method", c.Request.Method,
			"route", route,
			"status", c.Writer.Status(),
			"durationMs", float64(time.Since(started).Microseconds())/1000,
			"traceId", requestmeta.FromGin(c),
		)
	}
}

func recoveryMiddleware(logger *slog.Logger) gin.HandlerFunc {
	return func(c *gin.Context) {
		defer func() {
			if recovered := recover(); recovered != nil {
				logger.ErrorContext(c.Request.Context(), "unhandled API panic",
					"errorCode", "common.internal_error",
					"traceId", requestmeta.FromGin(c),
					"panicType", panicType(recovered),
					"stack", string(debug.Stack()),
				)
				if !c.Writer.Written() {
					apierror.WriteInternal(c)
				} else {
					c.Abort()
				}
			}
		}()
		c.Next()
	}
}

func requestTimeoutMiddleware(timeout time.Duration) gin.HandlerFunc {
	return func(c *gin.Context) {
		ctx, cancel := context.WithTimeout(c.Request.Context(), timeout)
		defer cancel()
		c.Request = c.Request.WithContext(ctx)
		c.Next()
	}
}

func bodyLimitMiddleware(maxBodyBytes int64) gin.HandlerFunc {
	return func(c *gin.Context) {
		if c.Request.Body != nil {
			c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, maxBodyBytes)
		}
		c.Next()
	}
}

func panicType(value any) string {
	if value == nil {
		return "nil"
	}
	return fmtType(value)
}

func fmtType(value any) string {
	return fmt.Sprintf("%T", value)
}
