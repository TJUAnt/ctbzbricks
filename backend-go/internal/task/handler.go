package task

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

type HTTPHandler struct {
	service *Service
	logger  *slog.Logger
}

func NewHTTPHandler(service *Service, logger *slog.Logger) *HTTPHandler {
	return &HTTPHandler{service: service, logger: logger}
}

func (h *HTTPHandler) Register(group *gin.RouterGroup) {
	group.GET("/tasks/:taskId", h.get)
	group.POST("/tasks/:taskId/cancel", h.cancel)
}

func (h *HTTPHandler) get(c *gin.Context) {
	actor, ok := auth.ActorFromGin(c)
	if !ok {
		apierror.WriteInternal(c)
		return
	}
	result, err := h.service.GetOwned(c.Request.Context(), actor.ID, c.Param("taskId"))
	h.write(c, http.StatusOK, result, err)
}

func (h *HTTPHandler) cancel(c *gin.Context) {
	actor, ok := auth.ActorFromGin(c)
	if !ok {
		apierror.WriteInternal(c)
		return
	}
	result, err := h.service.Cancel(c.Request.Context(), actor.ID, c.Param("taskId"))
	h.write(c, http.StatusOK, result, err)
}

func (h *HTTPHandler) write(c *gin.Context, status int, result Task, err error) {
	if err == nil {
		c.JSON(status, result)
		return
	}
	var publicError *apierror.Error
	if errors.As(err, &publicError) {
		apierror.Write(c, publicError)
		return
	}
	h.logger.ErrorContext(c.Request.Context(), "Task request failed",
		"errorCode", "common.internal_error", "traceId", requestmeta.FromGin(c),
		"errorType", fmt.Sprintf("%T", err),
	)
	apierror.WriteInternal(c)
}
