package auth

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
)

const maxSessionUserResponseBytes = 64 << 10

// SessionUser 是经 Go JWT 校验和 Supabase Auth 二次确认后的最小用户投影。
// 这里只返回页面登录态所需字段，避免把 provider 原始用户 payload 暴露给前端。
type SessionUser struct {
	ID    string `json:"id"`
	Email string `json:"email,omitempty"`
}

// SessionValidationError 使用稳定 code 表达会话无效或认证服务暂不可用。
// HTTP handler 依据 Status 决定前端是否应清除本地会话，Cause 只用于服务端日志。
type SessionValidationError struct {
	Code   string
	Status int
	Params map[string]any
	Cause  error
}

func (e *SessionValidationError) Error() string { return e.Code }
func (e *SessionValidationError) Unwrap() error { return e.Cause }

type sessionHTTPClient interface {
	Do(*http.Request) (*http.Response, error)
}

// SessionValidator 在页面刷新边界向 Supabase Auth 确认当前用户 token 仍对应有效会话。
// 普通业务请求继续使用本地 JWT/JWKS 校验，不承担每次请求的 provider 网络开销。
type SessionValidator interface {
	Validate(context.Context, Actor) (SessionUser, error)
}

// SupabaseSessionValidator 只持有公开项目 key 和短超时 HTTP client，不使用 service-role 凭据。
type SupabaseSessionValidator struct {
	verificationURL string
	publishableKey  string
	client          sessionHTTPClient
}

// NewSupabaseSessionValidator 创建刷新页专用的会话确认边界。
// 配置缺失时保持 fail closed，由 handler 返回稳定的 verification_not_configured 错误。
func NewSupabaseSessionValidator(cfg config.AuthConfig) *SupabaseSessionValidator {
	return &SupabaseSessionValidator{
		verificationURL: strings.TrimSpace(cfg.SessionVerificationURL),
		publishableKey:  strings.TrimSpace(cfg.PublishableKey),
		client:          &http.Client{Timeout: cfg.SessionVerificationTimeout},
	}
}

// Validate 先使用 middleware 已验证的 actor/token，再向 Supabase Auth 查询最小用户身份。
// provider 返回的用户 ID 必须与 JWT sub 完全一致，避免本地缓存用户与服务端 actor 错配。
func (v *SupabaseSessionValidator) Validate(ctx context.Context, actor Actor) (SessionUser, error) {
	if v.verificationURL == "" || v.publishableKey == "" {
		return SessionUser{}, sessionValidationFailure(
			"auth.verification_not_configured",
			http.StatusServiceUnavailable,
			nil,
			nil,
		)
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, v.verificationURL, nil)
	if err != nil {
		return SessionUser{}, sessionValidationFailure(
			"auth.session_verification_unavailable",
			http.StatusServiceUnavailable,
			nil,
			err,
		)
	}
	request.Header.Set("apikey", v.publishableKey)
	request.Header.Set("Authorization", "Bearer "+actor.AccessToken())

	response, err := v.client.Do(request)
	if err != nil {
		return SessionUser{}, sessionValidationFailure(
			"auth.session_verification_unavailable",
			http.StatusServiceUnavailable,
			nil,
			err,
		)
	}
	defer response.Body.Close()

	if response.StatusCode == http.StatusUnauthorized || response.StatusCode == http.StatusForbidden {
		return SessionUser{}, sessionValidationFailure("auth.session_invalid", http.StatusUnauthorized, nil, nil)
	}
	if response.StatusCode == http.StatusTooManyRequests || response.StatusCode >= http.StatusInternalServerError {
		return SessionUser{}, sessionValidationFailure(
			"auth.session_verification_unavailable",
			http.StatusServiceUnavailable,
			nil,
			nil,
		)
	}
	if response.StatusCode < http.StatusOK || response.StatusCode >= http.StatusMultipleChoices {
		return SessionUser{}, sessionValidationFailure(
			"auth.session_verification_failed",
			http.StatusBadGateway,
			map[string]any{"status": response.StatusCode},
			nil,
		)
	}

	var payload struct {
		ID    string `json:"id"`
		Email string `json:"email"`
	}
	decoder := json.NewDecoder(io.LimitReader(response.Body, maxSessionUserResponseBytes))
	if err := decoder.Decode(&payload); err != nil {
		return SessionUser{}, sessionValidationFailure(
			"auth.user_payload_invalid",
			http.StatusBadGateway,
			nil,
			err,
		)
	}
	if err := ensureSessionResponseEOF(decoder); err != nil {
		return SessionUser{}, sessionValidationFailure(
			"auth.user_payload_invalid",
			http.StatusBadGateway,
			nil,
			err,
		)
	}
	actorID := uuidutil.String(actor.ID)
	if payload.ID == "" || payload.ID != actorID {
		return SessionUser{}, sessionValidationFailure("auth.session_invalid", http.StatusUnauthorized, nil, nil)
	}
	return SessionUser{ID: actorID, Email: payload.Email}, nil
}

func ensureSessionResponseEOF(decoder *json.Decoder) error {
	var extra any
	err := decoder.Decode(&extra)
	if errors.Is(err, io.EOF) {
		return nil
	}
	if err == nil {
		return errors.New("session response contains multiple JSON values")
	}
	return err
}

func sessionValidationFailure(code string, status int, params map[string]any, cause error) error {
	if params == nil {
		params = map[string]any{}
	}
	return &SessionValidationError{Code: code, Status: status, Params: params, Cause: cause}
}
