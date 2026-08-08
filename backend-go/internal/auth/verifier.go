package auth

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"strings"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5/pgtype"
)

type Actor struct {
	ID pgtype.UUID
}

type Failure struct {
	Code string
}

func (f *Failure) Error() string { return f.Code }

type TokenVerifier interface {
	VerifyAuthorization(string) (Actor, error)
}

type Verifier struct {
	config config.AuthConfig
	now    func() time.Time
}

type tokenHeader struct {
	Algorithm string `json:"alg"`
}

type tokenClaims struct {
	Subject   string          `json:"sub"`
	ExpiresAt int64           `json:"exp"`
	NotBefore int64           `json:"nbf"`
	Issuer    string          `json:"iss"`
	Audience  json.RawMessage `json:"aud"`
}

func NewVerifier(cfg config.AuthConfig) *Verifier {
	return &Verifier{config: cfg, now: time.Now}
}

func (v *Verifier) VerifyAuthorization(authorization string) (Actor, error) {
	if v.config.JWTSecret == "" {
		return Actor{}, &Failure{Code: "auth.verification_not_configured"}
	}
	scheme, token, ok := strings.Cut(strings.TrimSpace(authorization), " ")
	if !ok || !strings.EqualFold(scheme, "Bearer") || strings.TrimSpace(token) == "" || strings.Contains(token, " ") {
		if strings.TrimSpace(authorization) == "" {
			return Actor{}, &Failure{Code: "auth.authentication_required"}
		}
		return Actor{}, &Failure{Code: "auth.authorization_header_invalid"}
	}
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		return Actor{}, invalidSession()
	}
	var header tokenHeader
	if err := decodeTokenPart(parts[0], &header); err != nil || header.Algorithm != "HS256" {
		return Actor{}, invalidSession()
	}
	expected := hmac.New(sha256.New, []byte(v.config.JWTSecret))
	_, _ = expected.Write([]byte(parts[0] + "." + parts[1]))
	provided, err := base64.RawURLEncoding.DecodeString(parts[2])
	if err != nil || !hmac.Equal(expected.Sum(nil), provided) {
		return Actor{}, invalidSession()
	}
	var claims tokenClaims
	if err := decodeTokenPart(parts[1], &claims); err != nil {
		return Actor{}, invalidSession()
	}
	now := v.now().Unix()
	if claims.ExpiresAt == 0 || now >= claims.ExpiresAt || (claims.NotBefore != 0 && now < claims.NotBefore) {
		return Actor{}, invalidSession()
	}
	if v.config.JWTIssuer != "" && claims.Issuer != v.config.JWTIssuer {
		return Actor{}, invalidSession()
	}
	if v.config.JWTAudience != "" && !audienceContains(claims.Audience, v.config.JWTAudience) {
		return Actor{}, invalidSession()
	}
	actorID, err := uuidutil.Parse(claims.Subject)
	if err != nil {
		return Actor{}, invalidSession()
	}
	return Actor{ID: actorID}, nil
}

func decodeTokenPart(part string, target any) error {
	decoded, err := base64.RawURLEncoding.DecodeString(part)
	if err != nil {
		return err
	}
	return json.Unmarshal(decoded, target)
}

func audienceContains(raw json.RawMessage, expected string) bool {
	if len(raw) == 0 {
		return false
	}
	var single string
	if json.Unmarshal(raw, &single) == nil {
		return single == expected
	}
	var many []string
	if json.Unmarshal(raw, &many) != nil {
		return false
	}
	for _, audience := range many {
		if audience == expected {
			return true
		}
	}
	return false
}

func invalidSession() error {
	return &Failure{Code: "auth.session_invalid"}
}

func FailureCode(err error) string {
	var failure *Failure
	if errors.As(err, &failure) {
		return failure.Code
	}
	return "auth.session_invalid"
}
