package workbench

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
	group.GET("/component-candidates/:candidateId/relations", h.listRelations)
	group.POST("/component-candidates/:candidateId/relations/detect", h.detectRelations)
	group.POST("/component-candidates/:candidateId/relations/:relationId/confirm", h.confirmRelation)
	group.POST("/component-candidates/:candidateId/relations/:relationId/reject", h.rejectRelation)
	group.GET("/component-candidates/:candidateId/connectors", h.listConnectors)
	group.GET("/component-candidates/:candidateId/interfaces", h.listInterfaces)
	group.POST("/component-candidates/:candidateId/validate", h.validate)
	group.GET("/validation-reports/:reportId", h.validationReport)
	group.GET("/component-versions/:versionId/parts", h.parts)
	group.GET("/component-versions/:versionId/preview", h.preview)
	group.POST("/component-versions/:versionId/preview/materialize", h.materializePreview)
	group.GET("/part-library-versions/active", h.activePartLibraryVersion)
	group.GET("/part-library-versions/:partLibraryVersionId/parts/:ldrawPartNum/preview", h.partPreview)
	group.POST("/part-library-versions/:partLibraryVersionId/parts/:ldrawPartNum/preview/materialize", h.materializePartPreview)
}

func (h *Handler) detectRelations(c *gin.Context) {
	actor, _ := auth.ActorFromGin(c)
	value, err := h.service.DetectRelations(c.Request.Context(), actor.ID, c.Param("candidateId"))
	h.write(c, http.StatusAccepted, value, err)
}
func (h *Handler) listRelations(c *gin.Context) {
	actor, _ := auth.ActorFromGin(c)
	value, err := h.service.ListRelations(c.Request.Context(), actor.ID, c.Param("candidateId"))
	h.write(c, http.StatusOK, gin.H{"items": value}, err)
}
func (h *Handler) confirmRelation(c *gin.Context) {
	actor, _ := auth.ActorFromGin(c)
	value, err := h.service.ConfirmRelation(c.Request.Context(), actor.ID, c.Param("candidateId"), c.Param("relationId"))
	h.write(c, http.StatusOK, value, err)
}
func (h *Handler) rejectRelation(c *gin.Context) {
	actor, _ := auth.ActorFromGin(c)
	value, err := h.service.RejectRelation(c.Request.Context(), actor.ID, c.Param("candidateId"), c.Param("relationId"))
	h.write(c, http.StatusOK, value, err)
}
func (h *Handler) listConnectors(c *gin.Context) {
	actor, _ := auth.ActorFromGin(c)
	value, err := h.service.ListConnectors(c.Request.Context(), actor.ID, c.Param("candidateId"))
	h.write(c, http.StatusOK, gin.H{"items": value}, err)
}
func (h *Handler) listInterfaces(c *gin.Context) {
	actor, _ := auth.ActorFromGin(c)
	value, err := h.service.ListInterfaces(c.Request.Context(), actor.ID, c.Param("candidateId"))
	h.write(c, http.StatusOK, gin.H{"items": value}, err)
}
func (h *Handler) validate(c *gin.Context) {
	actor, _ := auth.ActorFromGin(c)
	value, err := h.service.Validate(c.Request.Context(), actor.ID, c.Param("candidateId"))
	h.write(c, http.StatusAccepted, value, err)
}
func (h *Handler) validationReport(c *gin.Context) {
	actor, _ := auth.ActorFromGin(c)
	value, err := h.service.GetValidationReport(c.Request.Context(), actor.ID, c.Param("reportId"))
	h.write(c, http.StatusOK, value, err)
}
func (h *Handler) parts(c *gin.Context) {
	actor, _ := auth.ActorFromGin(c)
	value, err := h.service.GetVersionParts(c.Request.Context(), actor.ID, c.Param("versionId"), c.Query("locale"))
	h.write(c, http.StatusOK, value, err)
}
func (h *Handler) preview(c *gin.Context) {
	actor, _ := auth.ActorFromGin(c)
	value, err := h.service.GetPreview(c.Request.Context(), actor.ID, actor.AccessToken(), c.Param("versionId"))
	h.write(c, http.StatusOK, value, err)
}
func (h *Handler) materializePreview(c *gin.Context) {
	actor, _ := auth.ActorFromGin(c)
	value, err := h.service.MaterializePreview(c.Request.Context(), actor.ID, actor.AccessToken(), c.Param("versionId"))
	h.write(c, http.StatusAccepted, value, err)
}

func (h *Handler) activePartLibraryVersion(c *gin.Context) {
	value, err := h.service.GetActivePartLibraryVersion(c.Request.Context())
	h.write(c, http.StatusOK, value, err)
}

func (h *Handler) partPreview(c *gin.Context) {
	value, err := h.service.GetPartPreview(
		c.Request.Context(), c.Param("partLibraryVersionId"), c.Param("ldrawPartNum"), c.Query("locale"),
	)
	h.write(c, http.StatusOK, value, err)
}

func (h *Handler) materializePartPreview(c *gin.Context) {
	actor, _ := auth.ActorFromGin(c)
	var input PartPreviewMaterializeInput
	if err := c.ShouldBindJSON(&input); err != nil {
		apierror.Write(c, apierror.New("request.validation_failed", http.StatusUnprocessableEntity, map[string]any{"field": "body"}))
		return
	}
	value, err := h.service.MaterializePartPreview(
		c.Request.Context(), actor.ID, c.Param("partLibraryVersionId"), c.Param("ldrawPartNum"), input,
	)
	h.write(c, http.StatusAccepted, value, err)
}

func (h *Handler) write(c *gin.Context, status int, value any, err error) {
	if err == nil {
		c.JSON(status, value)
		return
	}
	var public *apierror.Error
	if errors.As(err, &public) {
		apierror.Write(c, public)
		return
	}
	h.logger.ErrorContext(c.Request.Context(), "Component workbench request failed", "errorCode", "common.internal_error", "traceId", requestmeta.FromGin(c), "errorType", fmt.Sprintf("%T", err))
	apierror.WriteInternal(c)
}
