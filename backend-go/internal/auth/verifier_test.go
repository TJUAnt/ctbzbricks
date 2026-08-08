package auth

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"testing"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
)

const testJWTSecret = "0123456789abcdef0123456789abcdef"

func TestVerifierAcceptsValidHS256Token(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	verifier := NewVerifier(config.AuthConfig{
		JWTSecret: testJWTSecret, JWTIssuer: "issuer", JWTAudience: "authenticated",
	})
	verifier.now = func() time.Time { return now }
	token := signedToken(t, testJWTSecret, map[string]any{
		"sub": "00000000-0000-0000-0000-000000000001", "exp": now.Unix() + 60,
		"iss": "issuer", "aud": []string{"authenticated", "other"}, "role": "authenticated",
	})
	actor, err := verifier.VerifyAuthorization("Bearer " + token)
	if err != nil {
		t.Fatalf("verify valid token: %v", err)
	}
	if uuidutil.String(actor.ID) != "00000000-0000-0000-0000-000000000001" {
		t.Fatalf("actor = %s", uuidutil.String(actor.ID))
	}
}

func TestVerifierRejectsInvalidTokensWithoutDetails(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	verifier := NewVerifier(config.AuthConfig{JWTSecret: testJWTSecret, JWTAudience: "authenticated"})
	verifier.now = func() time.Time { return now }
	tests := map[string]string{
		"missing":    "",
		"bad scheme": "Basic abc",
		"tampered": "Bearer " + signedToken(t, "different-secret-different-secret", map[string]any{
			"sub": "00000000-0000-0000-0000-000000000001", "exp": now.Unix() + 60, "aud": "authenticated",
		}),
		"expired": "Bearer " + signedToken(t, testJWTSecret, map[string]any{
			"sub": "00000000-0000-0000-0000-000000000001", "exp": now.Unix() - 1, "aud": "authenticated",
		}),
		"invalid subject": "Bearer " + signedToken(t, testJWTSecret, map[string]any{
			"sub": "not-a-uuid", "exp": now.Unix() + 60, "aud": "authenticated",
		}),
		"wrong audience": "Bearer " + signedToken(t, testJWTSecret, map[string]any{
			"sub": "00000000-0000-0000-0000-000000000001", "exp": now.Unix() + 60, "aud": "other",
		}),
	}
	for name, authorization := range tests {
		t.Run(name, func(t *testing.T) {
			if _, err := verifier.VerifyAuthorization(authorization); err == nil {
				t.Fatal("expected verification failure")
			}
		})
	}
}

func TestVerifierFailsClosedWhenNotConfigured(t *testing.T) {
	_, err := NewVerifier(config.AuthConfig{}).VerifyAuthorization("Bearer token")
	if FailureCode(err) != "auth.verification_not_configured" {
		t.Fatalf("code = %q", FailureCode(err))
	}
}

func signedToken(t *testing.T, secret string, claims map[string]any) string {
	t.Helper()
	header, _ := json.Marshal(map[string]any{"alg": "HS256", "typ": "JWT"})
	payload, _ := json.Marshal(claims)
	unsigned := base64.RawURLEncoding.EncodeToString(header) + "." + base64.RawURLEncoding.EncodeToString(payload)
	signature := hmac.New(sha256.New, []byte(secret))
	_, _ = signature.Write([]byte(unsigned))
	return unsigned + "." + base64.RawURLEncoding.EncodeToString(signature.Sum(nil))
}
