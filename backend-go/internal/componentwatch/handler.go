package componentwatch

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strconv"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/auth"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/requestmeta"
	"github.com/gin-gonic/gin"
)

// Handler 暴露有界的 Watch HTTP API，并把未知错误统一收敛为结构化内部错误。
type Handler struct {
	service *Service
	logger  *slog.Logger
}

// NewHandler 创建 Watch HTTP 入口；Service 保持授权、事务和幂等语义的唯一实现位置。
func NewHandler(service *Service, logger *slog.Logger) *Handler {
	return &Handler{service: service, logger: logger}
}

// Register 注册 Watch 偏好 API；这些 Handler 只执行有界查询和短事务，不做 watcher fan-out。
func (h *Handler) Register(group *gin.RouterGroup) {
	group.GET("/component-watches", h.list)
	group.PUT("/components/:componentId/watch", h.watch)
	group.DELETE("/components/:componentId/watch", h.unwatch)
}

// list 返回 actor 自己的 active Watch，使用不透明 keyset cursor 防止深分页退化。
func (h *Handler) list(c *gin.Context) {
	actor, ok := auth.ActorFromGin(c)
	if !ok {
		apierror.WriteInternal(c)
		return
	}
	limit := 0
	if raw := c.Query("limit"); raw != "" {
		parsed, err := strconv.Atoi(raw)
		if err != nil {
			h.writeError(c, validationError("limit"))
			return
		}
		limit = parsed
	}
	result, err := h.service.List(c.Request.Context(), actor.ID, ListRequest{
		Locale: c.Query("locale"), Limit: limit, Cursor: c.Query("cursor"),
		Query: c.Query("query"), Category: c.Query("category"),
	})
	h.writeJSON(c, http.StatusOK, result, err)
}

// watch 严格校验订阅级别；可用性、own-component 与幂等语义由 Service 在事务内复核。
func (h *Handler) watch(c *gin.Context) {
	actor, ok := auth.ActorFromGin(c)
	if !ok {
		apierror.WriteInternal(c)
		return
	}
	var input WatchInput
	if err := decodeJSON(c, &input); err != nil {
		h.writeError(c, validationError("body"))
		return
	}
	result, err := h.service.Watch(c.Request.Context(), actor.ID, c.Param("componentId"), input.Level)
	h.writeJSON(c, http.StatusOK, result, err)
}

// unwatch 幂等关闭 actor 自己的有效订阅区间，不改变 Star、Fork 或 Component 可见性。
func (h *Handler) unwatch(c *gin.Context) {
	actor, ok := auth.ActorFromGin(c)
	if !ok {
		apierror.WriteInternal(c)
		return
	}
	if err := h.service.Unwatch(c.Request.Context(), actor.ID, c.Param("componentId")); err != nil {
		h.writeError(c, err)
		return
	}
	c.Status(http.StatusNoContent)
}

func (h *Handler) writeJSON(c *gin.Context, status int, value any, err error) {
	if err != nil {
		h.writeError(c, err)
		return
	}
	c.JSON(status, value)
}

func (h *Handler) writeError(c *gin.Context, err error) {
	var publicError *apierror.Error
	if errors.As(err, &publicError) {
		apierror.Write(c, publicError)
		return
	}
	h.logger.ErrorContext(c.Request.Context(), "Component Watch request failed",
		"errorCode", "common.internal_error", "traceId", requestmeta.FromGin(c),
		"errorType", errorType(err),
	)
	apierror.WriteInternal(c)
}

func decodeJSON(c *gin.Context, target any) error {
	decoder := json.NewDecoder(c.Request.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		return errors.New("multiple JSON values")
	}
	return nil
}

func errorType(err error) string {
	if err == nil {
		return "nil"
	}
	return fmt.Sprintf("%T", err)
}
