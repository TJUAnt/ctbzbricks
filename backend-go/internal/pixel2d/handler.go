package pixel2d

import (
	"encoding/json"
	"errors"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/auth"
	"github.com/gin-gonic/gin"
	"io"
	"log/slog"
	"mime"
	"net/http"
	"net/url"
	"strconv"
)

// Handler 在已认证路由中处理有界 IO；所有计算和派生导出交给持久任务。
type Handler struct {
	service *Service
	logger  *slog.Logger
}

// NewHandler 注入服务和内部日志；客户端错误统一经结构化出口返回。
func NewHandler(s *Service, logger *slog.Logger) *Handler { return &Handler{s, logger} }

// Register 直接挂载 Go /api/v1 契约，无 Python 代理或双写。
func (h *Handler) Register(g *gin.RouterGroup) {
	g.GET("/pixel-art/projects", h.list)
	g.POST("/pixel-art/projects", h.create)
	g.GET("/pixel-art/projects/:projectId", h.get)
	g.PUT("/pixel-art/projects/:projectId/pixels", h.edit)
	g.GET("/lego-design/metadata", h.metadata)
	g.GET("/lego-design/candidates", h.candidates)
	g.POST("/lego-design/jobs", h.design)
	g.GET("/lego-design/jobs/:jobId", h.job)
	g.GET("/lego-design/jobs/:jobId/ldraw", h.download)
	g.GET("/lego-design/jobs/:jobId/plan", h.download)
}
func (h *Handler) reply(c *gin.Context, status int, v any, err error) {
	if err != nil {
		var public *apierror.Error
		if errors.As(err, &public) {
			apierror.Write(c, public)
		} else {
			h.logger.ErrorContext(c.Request.Context(), "pixel2d request failed", "error", err)
			apierror.WriteInternal(c)
		}
		return
	}
	c.JSON(status, v)
}
func decode(c *gin.Context, v any) error {
	d := json.NewDecoder(c.Request.Body)
	d.DisallowUnknownFields()
	if e := d.Decode(v); e != nil {
		return invalid("body")
	}
	if e := d.Decode(&struct{}{}); e != io.EOF {
		return invalid("body")
	}
	return nil
}

// create 限制上传正文与元数据长度；返回 202 仅表示源和任务已持久化。
func (h *Handler) create(c *gin.Context) {
	actor, _ := auth.ActorFromGin(c)
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 21*1024*1024)
	if e := c.Request.ParseMultipartForm(1 << 20); e != nil {
		h.reply(c, 0, nil, invalid("image"))
		return
	}
	defer c.Request.MultipartForm.RemoveAll()
	file, header, e := c.Request.FormFile("image")
	if e != nil {
		h.reply(c, 0, nil, invalid("image"))
		return
	}
	defer file.Close()
	data, e := io.ReadAll(io.LimitReader(file, 20*1024*1024+1))
	if e != nil {
		h.reply(c, 0, nil, e)
		return
	}
	var settings Settings
	if e = json.Unmarshal([]byte(c.PostForm("settings")), &settings); e != nil {
		h.reply(c, 0, nil, domain("pixel_art.invalid_settings"))
		return
	}
	mimeType, _, _ := mime.ParseMediaType(header.Header.Get("Content-Type"))
	a, e := h.service.Create(c.Request.Context(), actor.ID, c.PostForm("name"), header.Filename, mimeType, data, settings, c.PostForm("contentLocale"), c.PostForm("timezone"))
	h.reply(c, http.StatusAccepted, a, e)
}

// get 返回当前 actor 的修订或可恢复任务状态，未完成时不返回陈旧像素。
func (h *Handler) get(c *gin.Context) {
	a, _ := auth.ActorFromGin(c)
	v, e := h.service.Get(c.Request.Context(), a.ID, c.Param("projectId"))
	h.reply(c, 200, v, e)
}

// list 保留现有页码交互及 exact total，前端可恢复未完成的项目。
func (h *Handler) list(c *gin.Context) {
	a, _ := auth.ActorFromGin(c)
	page, e := strconv.Atoi(c.DefaultQuery("page", "1"))
	if e != nil {
		h.reply(c, 0, nil, invalid("page"))
		return
	}
	size, e := strconv.Atoi(c.DefaultQuery("page_size", "12"))
	if e != nil {
		h.reply(c, 0, nil, invalid("page_size"))
		return
	}
	v, e := h.service.List(c.Request.Context(), a.ID, page, size)
	h.reply(c, 200, v, e)
}

// edit 接受冻结父修订，过期编辑通过 409 拒绝，不静默丢失另一个会话的保存。
func (h *Handler) edit(c *gin.Context) {
	a, _ := auth.ActorFromGin(c)
	var input struct {
		RevisionID string         `json:"revisionId"`
		Palette    []PaletteColor `json:"palette"`
		Pixels     []Pixel        `json:"pixels"`
		Locale     string         `json:"locale"`
		Timezone   string         `json:"timezone"`
	}
	if e := decode(c, &input); e != nil {
		h.reply(c, 0, nil, e)
		return
	}
	v, e := h.service.Edit(c.Request.Context(), a.ID, c.Param("projectId"), input.RevisionID, input.Pixels, input.Locale, input.Timezone)
	h.reply(c, 202, v, e)
}

// metadata 和 candidates 读取冻结目录，不在 HTTP 请求里扫描 legacy 数据库。
func (h *Handler) metadata(c *gin.Context) {
	v, e := h.service.Metadata(c.Request.Context())
	h.reply(c, 200, v, e)
}
func (h *Handler) candidates(c *gin.Context) {
	if c.DefaultQuery("footprint", "rectangular") != "rectangular" {
		h.reply(c, 0, nil, invalid("footprint"))
		return
	}
	v, e := h.service.Metadata(c.Request.Context())
	h.reply(c, 200, map[string]any{"parts": v.Parts}, e)
}

// design 创建或复用相同输入哈希的逻辑任务，刷新页面不重新运行算法。
func (h *Handler) design(c *gin.Context) {
	a, _ := auth.ActorFromGin(c)
	var input struct {
		ProjectID string `json:"projectId"`
		Locale    string `json:"locale"`
		Timezone  string `json:"timezone"`
	}
	if e := decode(c, &input); e != nil {
		h.reply(c, 0, nil, e)
		return
	}
	v, e := h.service.CreateDesign(c.Request.Context(), a.ID, input.ProjectID, input.Locale, input.Timezone)
	h.reply(c, 202, v, e)
}

// job 仅投影 actor 自己的设计任务，不能借通用 UUID 读取其他任务的结果。
func (h *Handler) job(c *gin.Context) {
	a, _ := auth.ActorFromGin(c)
	v, e := h.service.Job(c.Request.Context(), a.ID, c.Param("jobId"))
	h.reply(c, 200, v, e)
}

// download 提供已生成文件，文件名使用任务创建时冻结的版本化词典。
func (h *Handler) download(c *gin.Context) {
	a, _ := auth.ActorFromGin(c)
	base, e := strconv.ParseBool(c.Query("include_base"))
	if e != nil {
		h.reply(c, 0, nil, invalid("include_base"))
		return
	}
	kind := "ldraw"
	contentType := "text/plain; charset=utf-8"
	if c.FullPath() == "/api/v1/lego-design/jobs/:jobId/plan" {
		kind = "plan"
		contentType = "application/json"
	}
	data, name, e := h.service.Download(c.Request.Context(), a.ID, c.Param("jobId"), kind, base)
	if e != nil {
		h.reply(c, 0, nil, e)
		return
	}
	c.Header("Content-Disposition", "attachment; filename=\"export."+map[string]string{"plan": "json", "ldraw": "ldr"}[kind]+"\"; filename*=UTF-8''"+url.PathEscape(name))
	c.Data(200, contentType, data)
}
