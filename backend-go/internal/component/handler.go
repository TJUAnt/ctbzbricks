package component

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

type Handler struct {
	service *Service
	logger  *slog.Logger
}

func NewHandler(service *Service, logger *slog.Logger) *Handler {
	return &Handler{service: service, logger: logger}
}

func (h *Handler) Register(group *gin.RouterGroup) {
	group.GET("/components", h.listComponents)
	group.POST("/components", h.createComponent)
	group.GET("/components/:componentId", h.getComponent)
	group.PATCH("/components/:componentId", h.updateComponent)
	group.DELETE("/components/:componentId", h.deleteComponent)
	group.POST("/components/:componentId/purge", h.purgeComponent)

	group.GET("/components/:componentId/versions", h.listVersions)
	group.POST("/components/:componentId/versions", h.createVersion)
	group.GET("/component-versions/:versionId", h.getVersion)
	group.PATCH("/component-versions/:versionId", h.updateVersion)
	group.DELETE("/component-versions/:versionId", h.deleteVersion)
	group.POST("/component-versions/:versionId/publish", h.publishVersion)
	group.POST("/component-versions/:versionId/deprecate", h.deprecateVersion)
	group.POST("/component-versions/:versionId/archive", h.archiveVersion)

	group.GET("/component-groups", h.listGroups)
	group.POST("/component-groups/bootstrap", h.bootstrapGroups)
	group.POST("/component-groups", h.createGroup)
	group.PATCH("/component-groups/:groupId", h.updateGroup)
	group.DELETE("/component-groups/:groupId", h.deleteGroup)
	group.POST("/component-groups/:groupId/move", h.moveGroup)
	group.GET("/component-groups/:groupId/components", h.listGroupMembers)
	group.GET("/component-groups/:groupId/components/search", h.searchGroupComponents)
	group.POST("/component-groups/:groupId/components", h.addGroupMember)
	group.DELETE("/component-groups/:groupId/components/:componentId", h.removeGroupMember)
	group.GET("/components/:componentId/groups", h.listComponentGroupIDs)

	group.PUT("/components/:componentId/subscription", h.subscribe)
	group.DELETE("/components/:componentId/subscription", h.unsubscribe)
}

func (h *Handler) listComponents(c *gin.Context) {
	actor, ok := actorFromContext(c)
	if !ok {
		apierror.WriteInternal(c)
		return
	}
	page, err := pageFromQuery(c)
	if err != nil {
		h.writeError(c, err)
		return
	}
	result, err := h.service.ListComponents(c.Request.Context(), actor.ID, ComponentListRequest{
		PageRequest: page, Locale: c.Query("locale"), Query: c.Query("query"),
		Category: c.Query("category"), Status: c.Query("status"),
	})
	h.writeJSON(c, http.StatusOK, result, err)
}

func (h *Handler) createComponent(c *gin.Context) {
	actor, _ := actorFromContext(c)
	var input CreateComponentInput
	if err := decodeJSON(c, &input); err != nil {
		h.writeError(c, validationError("body"))
		return
	}
	result, err := h.service.CreateComponent(c.Request.Context(), actor.ID, input)
	h.writeJSON(c, http.StatusCreated, result, err)
}

func (h *Handler) getComponent(c *gin.Context) {
	actor, _ := actorFromContext(c)
	result, err := h.service.GetComponent(c.Request.Context(), actor.ID, c.Param("componentId"), c.Query("locale"))
	h.writeJSON(c, http.StatusOK, result, err)
}

func (h *Handler) updateComponent(c *gin.Context) {
	actor, _ := actorFromContext(c)
	var input UpdateComponentInput
	if err := decodeJSON(c, &input); err != nil {
		h.writeError(c, validationError("body"))
		return
	}
	result, err := h.service.UpdateComponent(c.Request.Context(), actor.ID, c.Param("componentId"), input)
	h.writeJSON(c, http.StatusOK, result, err)
}

func (h *Handler) deleteComponent(c *gin.Context) {
	actor, _ := actorFromContext(c)
	h.writeNoContent(c, h.service.DeleteComponent(c.Request.Context(), actor.ID, c.Param("componentId")))
}

func (h *Handler) purgeComponent(c *gin.Context) {
	actor, _ := actorFromContext(c)
	var input PurgeComponentInput
	if err := decodeJSON(c, &input); err != nil {
		h.writeError(c, validationError("body"))
		return
	}
	result, err := h.service.PurgeComponent(c.Request.Context(), actor.ID, c.Param("componentId"), input)
	h.writeJSON(c, http.StatusAccepted, result, err)
}

func (h *Handler) listVersions(c *gin.Context) {
	actor, _ := actorFromContext(c)
	page, err := pageFromQuery(c)
	if err != nil {
		h.writeError(c, err)
		return
	}
	result, err := h.service.ListVersions(c.Request.Context(), actor.ID, c.Param("componentId"), page)
	h.writeJSON(c, http.StatusOK, result, err)
}

func (h *Handler) createVersion(c *gin.Context) {
	actor, _ := actorFromContext(c)
	var input CreateVersionInput
	if err := decodeJSON(c, &input); err != nil {
		h.writeError(c, validationError("body"))
		return
	}
	result, err := h.service.CreateVersion(c.Request.Context(), actor.ID, c.Param("componentId"), input)
	h.writeJSON(c, http.StatusCreated, result, err)
}

func (h *Handler) getVersion(c *gin.Context) {
	actor, _ := actorFromContext(c)
	result, err := h.service.GetVersion(c.Request.Context(), actor.ID, c.Param("versionId"))
	h.writeJSON(c, http.StatusOK, result, err)
}

func (h *Handler) updateVersion(c *gin.Context) {
	actor, _ := actorFromContext(c)
	var input UpdateVersionInput
	if err := decodeJSON(c, &input); err != nil {
		h.writeError(c, validationError("body"))
		return
	}
	result, err := h.service.UpdateVersion(c.Request.Context(), actor.ID, c.Param("versionId"), input)
	h.writeJSON(c, http.StatusOK, result, err)
}

func (h *Handler) deleteVersion(c *gin.Context) {
	actor, _ := actorFromContext(c)
	h.writeNoContent(c, h.service.DeleteVersion(c.Request.Context(), actor.ID, c.Param("versionId")))
}

func (h *Handler) publishVersion(c *gin.Context) {
	actor, _ := actorFromContext(c)
	result, err := h.service.PublishVersion(c.Request.Context(), actor.ID, c.Param("versionId"))
	h.writeJSON(c, http.StatusOK, result, err)
}

func (h *Handler) deprecateVersion(c *gin.Context) {
	h.transitionVersion(c, "deprecated")
}

func (h *Handler) archiveVersion(c *gin.Context) {
	h.transitionVersion(c, "archived")
}

func (h *Handler) transitionVersion(c *gin.Context, target string) {
	actor, _ := actorFromContext(c)
	result, err := h.service.TransitionVersion(c.Request.Context(), actor.ID, c.Param("versionId"), target)
	h.writeJSON(c, http.StatusOK, result, err)
}

func (h *Handler) listGroups(c *gin.Context) {
	actor, _ := actorFromContext(c)
	result, err := h.service.ListGroups(c.Request.Context(), actor.ID)
	h.writeJSON(c, http.StatusOK, gin.H{"items": result}, err)
}

func (h *Handler) bootstrapGroups(c *gin.Context) {
	actor, _ := actorFromContext(c)
	h.writeNoContent(c, h.service.BootstrapGroups(c.Request.Context(), actor.ID))
}

func (h *Handler) createGroup(c *gin.Context) {
	actor, _ := actorFromContext(c)
	var input CreateGroupInput
	if err := decodeJSON(c, &input); err != nil {
		h.writeError(c, validationError("body"))
		return
	}
	result, err := h.service.CreateGroup(c.Request.Context(), actor.ID, input)
	h.writeJSON(c, http.StatusCreated, result, err)
}

func (h *Handler) updateGroup(c *gin.Context) {
	actor, _ := actorFromContext(c)
	var input UpdateGroupInput
	if err := decodeJSON(c, &input); err != nil {
		h.writeError(c, validationError("body"))
		return
	}
	result, err := h.service.UpdateGroup(c.Request.Context(), actor.ID, c.Param("groupId"), input)
	h.writeJSON(c, http.StatusOK, result, err)
}

func (h *Handler) moveGroup(c *gin.Context) {
	actor, _ := actorFromContext(c)
	var input MoveGroupInput
	if err := decodeJSON(c, &input); err != nil {
		h.writeError(c, validationError("body"))
		return
	}
	result, err := h.service.MoveGroup(c.Request.Context(), actor.ID, c.Param("groupId"), input)
	h.writeJSON(c, http.StatusOK, result, err)
}

func (h *Handler) deleteGroup(c *gin.Context) {
	actor, _ := actorFromContext(c)
	h.writeNoContent(c, h.service.DeleteGroup(c.Request.Context(), actor.ID, c.Param("groupId")))
}

func (h *Handler) listGroupMembers(c *gin.Context) {
	actor, _ := actorFromContext(c)
	page, err := pageFromQuery(c)
	if err != nil {
		h.writeError(c, err)
		return
	}
	result, err := h.service.ListGroupMembers(c.Request.Context(), actor.ID, c.Param("groupId"), c.Query("locale"), page)
	h.writeJSON(c, http.StatusOK, result, err)
}

func (h *Handler) searchGroupComponents(c *gin.Context) {
	actor, _ := actorFromContext(c)
	page, err := pageFromQuery(c)
	if err != nil {
		h.writeError(c, err)
		return
	}
	result, err := h.service.SearchGroupComponents(c.Request.Context(), actor.ID, c.Param("groupId"), ComponentGroupSearchRequest{
		PageRequest: page, Locale: c.Query("locale"), Query: c.Query("query"), Statuses: c.QueryArray("status"),
	})
	h.writeJSON(c, http.StatusOK, result, err)
}

func (h *Handler) listComponentGroupIDs(c *gin.Context) {
	actor, _ := actorFromContext(c)
	componentID := c.Param("componentId")
	ids, err := h.service.ListComponentGroupIDs(c.Request.Context(), actor.ID, componentID)
	h.writeJSON(c, http.StatusOK, gin.H{"componentId": componentID, "groupIds": ids}, err)
}

func (h *Handler) addGroupMember(c *gin.Context) {
	actor, _ := actorFromContext(c)
	var input MembershipInput
	if err := decodeJSON(c, &input); err != nil {
		h.writeError(c, validationError("body"))
		return
	}
	err := h.service.AddGroupMember(c.Request.Context(), actor.ID, c.Param("groupId"), input.ComponentID)
	h.writeNoContent(c, err)
}

func (h *Handler) removeGroupMember(c *gin.Context) {
	actor, _ := actorFromContext(c)
	err := h.service.RemoveGroupMember(c.Request.Context(), actor.ID, c.Param("groupId"), c.Param("componentId"))
	h.writeNoContent(c, err)
}

func (h *Handler) subscribe(c *gin.Context) {
	actor, _ := actorFromContext(c)
	result, err := h.service.Subscribe(c.Request.Context(), actor.ID, c.Param("componentId"))
	h.writeJSON(c, http.StatusOK, result, err)
}

func (h *Handler) unsubscribe(c *gin.Context) {
	actor, _ := actorFromContext(c)
	h.writeNoContent(c, h.service.Unsubscribe(c.Request.Context(), actor.ID, c.Param("componentId")))
}

func (h *Handler) writeJSON(c *gin.Context, status int, value any, err error) {
	if err != nil {
		h.writeError(c, err)
		return
	}
	c.JSON(status, value)
}

func (h *Handler) writeNoContent(c *gin.Context, err error) {
	if err != nil {
		h.writeError(c, err)
		return
	}
	c.Status(http.StatusNoContent)
}

func (h *Handler) writeError(c *gin.Context, err error) {
	var publicError *apierror.Error
	if errors.As(err, &publicError) {
		apierror.Write(c, publicError)
		return
	}
	h.logger.ErrorContext(c.Request.Context(), "Component Repo request failed",
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

func pageFromQuery(c *gin.Context) (PageRequest, error) {
	page, err := positiveIntQuery(c.Query("page"), 1)
	if err != nil {
		return PageRequest{}, validationError("page")
	}
	pageSize, err := positiveIntQuery(c.Query("pageSize"), defaultPageSize)
	if err != nil {
		return PageRequest{}, validationError("pageSize")
	}
	if page > 1_000_000 {
		return PageRequest{}, validationError("page")
	}
	return PageRequest{Page: page, PageSize: pageSize}, nil
}

func positiveIntQuery(raw string, fallback int) (int, error) {
	if raw == "" {
		return fallback, nil
	}
	value, err := strconv.Atoi(raw)
	if err != nil || value < 1 {
		return 0, errors.New("invalid positive integer")
	}
	return value, nil
}

func actorFromContext(c *gin.Context) (auth.Actor, bool) {
	return auth.ActorFromGin(c)
}

func errorType(err error) string {
	if err == nil {
		return "nil"
	}
	return fmt.Sprintf("%T", err)
}
