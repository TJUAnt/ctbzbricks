package ingestion

import (
	"errors"
	"fmt"
	"log/slog"
	"net/http"

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
	group.GET("/component-imports/:importId", h.getImport)
	group.GET("/component-candidates/:candidateId", h.getCandidate)
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
