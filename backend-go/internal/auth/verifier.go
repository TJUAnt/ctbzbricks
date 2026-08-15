package auth

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"math/big"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5/pgtype"
)

const (
	jwksCacheTTL       = 10 * time.Minute
	jwksRefreshBackoff = 30 * time.Second
	maxJWKSBytes       = 1 << 20
)

type Actor struct {
	ID          pgtype.UUID
	accessToken string
}

func (a Actor) AccessToken() string { return a.accessToken }

type Failure struct {
	Code string
}

func (f *Failure) Error() string { return f.Code }

type TokenVerifier interface {
	VerifyAuthorization(context.Context, string) (Actor, error)
}

type Verifier struct {
	config config.AuthConfig
	now    func() time.Time
	client *http.Client

	keysMu        sync.Mutex
	keys          map[string]*ecdsa.PublicKey
	keysExpiresAt time.Time
	keysLoadedAt  time.Time
}

type tokenHeader struct {
	Algorithm string `json:"alg"`
	KeyID     string `json:"kid"`
}

type tokenClaims struct {
	Subject   string          `json:"sub"`
	ExpiresAt int64           `json:"exp"`
	NotBefore int64           `json:"nbf"`
	Issuer    string          `json:"iss"`
	Audience  json.RawMessage `json:"aud"`
}

type jwksDocument struct {
	Keys []jsonWebKey `json:"keys"`
}

type jsonWebKey struct {
	KeyID     string `json:"kid"`
	Algorithm string `json:"alg"`
	KeyType   string `json:"kty"`
	Curve     string `json:"crv"`
	X         string `json:"x"`
	Y         string `json:"y"`
}

func NewVerifier(cfg config.AuthConfig) *Verifier {
	return &Verifier{
		config: cfg,
		now:    time.Now,
		client: &http.Client{Timeout: 5 * time.Second},
		keys:   make(map[string]*ecdsa.PublicKey),
	}
}

func (v *Verifier) VerifyAuthorization(ctx context.Context, authorization string) (Actor, error) {
	if v.config.JWTSecret == "" && v.config.JWKSURL == "" {
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
	if err := decodeTokenPart(parts[0], &header); err != nil {
		return Actor{}, invalidSession()
	}
	unsigned := parts[0] + "." + parts[1]
	provided, err := base64.RawURLEncoding.DecodeString(parts[2])
	if err != nil || !v.verifySignature(ctx, header, unsigned, provided) {
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
	return Actor{ID: actorID, accessToken: token}, nil
}

func (v *Verifier) verifySignature(ctx context.Context, header tokenHeader, unsigned string, provided []byte) bool {
	switch header.Algorithm {
	case "HS256":
		if v.config.JWTSecret == "" {
			return false
		}
		expected := hmac.New(sha256.New, []byte(v.config.JWTSecret))
		_, _ = expected.Write([]byte(unsigned))
		return hmac.Equal(expected.Sum(nil), provided)
	case "ES256":
		if v.config.JWKSURL == "" || header.KeyID == "" || len(provided) != 64 {
			return false
		}
		key, err := v.signingKey(ctx, header.KeyID)
		if err != nil {
			return false
		}
		digest := sha256.Sum256([]byte(unsigned))
		return ecdsa.Verify(key, digest[:], new(big.Int).SetBytes(provided[:32]), new(big.Int).SetBytes(provided[32:]))
	default:
		return false
	}
}

func (v *Verifier) signingKey(ctx context.Context, keyID string) (*ecdsa.PublicKey, error) {
	v.keysMu.Lock()
	defer v.keysMu.Unlock()

	now := v.now()
	if key := v.keys[keyID]; key != nil && now.Before(v.keysExpiresAt) {
		return key, nil
	}
	shouldRefresh := now.After(v.keysExpiresAt) || v.keysLoadedAt.IsZero() || now.Sub(v.keysLoadedAt) >= jwksRefreshBackoff
	if shouldRefresh {
		if err := v.refreshKeys(ctx, now); err != nil {
			return nil, err
		}
	}
	key := v.keys[keyID]
	if key == nil {
		return nil, errors.New("JWT signing key was not found")
	}
	return key, nil
}

func (v *Verifier) refreshKeys(ctx context.Context, now time.Time) error {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, v.config.JWKSURL, nil)
	if err != nil {
		return err
	}
	response, err := v.client.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return errors.New("JWKS endpoint returned a non-success status")
	}
	var document jwksDocument
	decoder := json.NewDecoder(io.LimitReader(response.Body, maxJWKSBytes))
	if err := decoder.Decode(&document); err != nil {
		return err
	}
	keys := make(map[string]*ecdsa.PublicKey)
	for _, candidate := range document.Keys {
		key, keyErr := es256PublicKey(candidate)
		if keyErr == nil {
			keys[candidate.KeyID] = key
		}
	}
	if len(keys) == 0 {
		return errors.New("JWKS endpoint contains no supported signing keys")
	}
	v.keys = keys
	v.keysLoadedAt = now
	v.keysExpiresAt = now.Add(jwksCacheTTL)
	return nil
}

func es256PublicKey(key jsonWebKey) (*ecdsa.PublicKey, error) {
	if key.KeyID == "" || key.Algorithm != "ES256" || key.KeyType != "EC" || key.Curve != "P-256" {
		return nil, errors.New("unsupported JSON web key")
	}
	xBytes, xErr := base64.RawURLEncoding.DecodeString(key.X)
	yBytes, yErr := base64.RawURLEncoding.DecodeString(key.Y)
	if xErr != nil || yErr != nil || len(xBytes) != 32 || len(yBytes) != 32 {
		return nil, errors.New("invalid JSON web key coordinates")
	}
	publicKey := &ecdsa.PublicKey{Curve: elliptic.P256(), X: new(big.Int).SetBytes(xBytes), Y: new(big.Int).SetBytes(yBytes)}
	if !publicKey.Curve.IsOnCurve(publicKey.X, publicKey.Y) {
		return nil, errors.New("JSON web key is not on P-256")
	}
	return publicKey, nil
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
