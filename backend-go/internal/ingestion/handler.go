package ingestion

import (
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"strconv"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/auth"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/requestmeta"
	"github.com/gin-gonic/gin"
)

type Handler struct {
	service *Service
	logger  *slog.Logger
}

func NewHandler(service *Service, logger *slog.Logger) *Handler {
	return &Handler{service: service, logger: logger}
}

func (h *Handler) Register(group *gin.RouterGroup) {
	group.GET("/component-imports", h.listImports)
	group.GET("/component-imports/:importId", h.getImport)
	group.GET("/component-candidates/:candidateId", h.getCandidate)
}

// listImports 提供 owner-scoped 导入历史；它只读取持久化状态，不触发 Worker、重试或制品生成。
func (h *Handler) listImports(c *gin.Context) {
	actor, _ := auth.ActorFromGin(c)
	page, err := positiveIntQuery(c.Query("page"), 1)
	if err != nil {
		h.writeJSON(c, nil, validationError("page"))
		return
	}
	pageSize, err := positiveIntQuery(c.Query("pageSize"), 20)
	if err != nil {
		h.writeJSON(c, nil, validationError("pageSize"))
		return
	}
	value, err := h.service.ListImports(c.Request.Context(), actor.ID, ImportListRequest{
		Page: page, PageSize: pageSize, ProcessingStatus: c.Query("processingStatus"),
		Query: c.Query("query"), ComponentID: c.Query("componentId"),
	})
	h.writeJSON(c, value, err)
}

func (h *Handler) getImport(c *gin.Context) {
	actor, _ := auth.ActorFromGin(c)
	value, err := h.service.GetImport(c.Request.Context(), actor.ID, c.Param("importId"))
	h.writeJSON(c, value, err)
}

func (h *Handler) getCandidate(c *gin.Context) {
	actor, _ := auth.ActorFromGin(c)
	value, err := h.service.GetCandidate(c.Request.Context(), actor.ID, c.Param("candidateId"))
	h.writeJSON(c, value, err)
}

func (h *Handler) writeJSON(c *gin.Context, value any, err error) {
	if err == nil {
		c.JSON(http.StatusOK, value)
		return
	}
	var publicError *apierror.Error
	if errors.As(err, &publicError) {
		apierror.Write(c, publicError)
		return
	}
	h.logger.ErrorContext(c.Request.Context(), "Component import request failed",
		"errorCode", "common.internal_error", "traceId", requestmeta.FromGin(c),
		"errorType", fmt.Sprintf("%T", err),
	)
	apierror.WriteInternal(c)
}

func positiveIntQuery(raw string, fallback int) (int, error) {
	if raw == "" {
		return fallback, nil
	}
	value, err := strconv.Atoi(raw)
	if err != nil || value < 1 || value > 1_000_000 {
		return 0, errors.New("invalid positive integer")
	}
	return value, nil
}
