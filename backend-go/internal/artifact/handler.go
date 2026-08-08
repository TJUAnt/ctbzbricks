package artifact

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
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
	group.POST("/component-imports/upload-sessions", h.createUploadSession)
	group.POST("/component-imports/upload-sessions/:sessionId/complete", h.completeUploadSession)
	group.GET("/artifacts/:artifactId/download", h.createDownload)
	group.GET("/component-versions/:versionId/source", h.createVersionSourceDownload)
}

func (h *Handler) createUploadSession(c *gin.Context) {
	actor, ok := auth.ActorFromGin(c)
	if !ok {
		apierror.WriteInternal(c)
		return
	}
	var input CreateUploadSessionInput
	if err := decodeJSON(c, &input); err != nil {
		h.writeError(c, validationError("body"))
		return
	}
	result, err := h.service.CreateUploadSession(c.Request.Context(), actor.ID, input)
	h.writeJSON(c, http.StatusCreated, result, err)
}

func (h *Handler) completeUploadSession(c *gin.Context) {
	actor, _ := auth.ActorFromGin(c)
	result, err := h.service.CompleteUploadSession(c.Request.Context(), actor.ID, c.Param("sessionId"))
	h.writeJSON(c, http.StatusOK, result, err)
}

func (h *Handler) createDownload(c *gin.Context) {
	actor, _ := auth.ActorFromGin(c)
	result, err := h.service.CreateDownload(c.Request.Context(), actor.ID, c.Param("artifactId"))
	h.writeJSON(c, http.StatusOK, result, err)
}

func (h *Handler) createVersionSourceDownload(c *gin.Context) {
	actor, _ := auth.ActorFromGin(c)
	result, err := h.service.CreateVersionSourceDownload(c.Request.Context(), actor.ID, c.Param("versionId"))
	h.writeJSON(c, http.StatusOK, result, err)
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
	h.logger.ErrorContext(c.Request.Context(), "Artifact request failed",
		"errorCode", "common.internal_error", "traceId", requestmeta.FromGin(c),
		"errorType", fmt.Sprintf("%T", err),
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
