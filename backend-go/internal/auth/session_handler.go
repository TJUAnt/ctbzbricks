package auth

import (
	"errors"
	"log/slog"
	"net/http"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/requestmeta"
	"github.com/gin-gonic/gin"
)

// SessionHandler 暴露 Go 系统后端的页面刷新会话确认入口。
// JWT 校验由外层 middleware 完成，本 handler 只负责 provider 二次确认和最小用户响应。
type SessionHandler struct {
	validator SessionValidator
	logger    *slog.Logger
}

// NewSessionHandler 创建会话确认 HTTP 入口，validator 可在测试中替换为受控实现。
func NewSessionHandler(validator SessionValidator, logger *slog.Logger) *SessionHandler {
	return &SessionHandler{validator: validator, logger: logger}
}

// Register 将会话接口注册在已认证的 /api/v1 group 下。
func (h *SessionHandler) Register(group *gin.RouterGroup) {
	group.GET("/auth/session", h.current)
}

// current 返回经 provider 确认的最小用户投影；认证失败始终使用稳定 code，内部原因只写结构化日志。
func (h *SessionHandler) current(c *gin.Context) {
	actor, ok := ActorFromGin(c)
	if !ok {
		apierror.WriteInternal(c)
		return
	}
	user, err := h.validator.Validate(c.Request.Context(), actor)
	if err == nil {
		c.JSON(http.StatusOK, gin.H{"authenticated": true, "user": user})
		return
	}
	var validationError *SessionValidationError
	if !errors.As(err, &validationError) {
		h.logger.WarnContext(c.Request.Context(), "session verification failed",
			"errorCode", "auth.session_verification_unavailable",
			"traceId", requestmeta.FromGin(c),
		)
		apierror.Write(c, apierror.New("auth.session_verification_unavailable", http.StatusServiceUnavailable, nil))
		return
	}
	if validationError.Cause != nil {
		h.logger.WarnContext(c.Request.Context(), "session verification failed",
			"errorCode", validationError.Code,
			"traceId", requestmeta.FromGin(c),
		)
	}
	apierror.Write(c, apierror.New(validationError.Code, validationError.Status, validationError.Params))
}
