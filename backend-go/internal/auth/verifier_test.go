package auth

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"io"
	"math/big"
	"net/http"
	"strings"
	"sync/atomic"
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
	actor, err := verifier.VerifyAuthorization(context.Background(), "Bearer "+token)
	if err != nil {
		t.Fatalf("verify valid token: %v", err)
	}
	if uuidutil.String(actor.ID) != "00000000-0000-0000-0000-000000000001" {
		t.Fatalf("actor = %s", uuidutil.String(actor.ID))
	}
	if actor.AccessToken() != token {
		t.Fatal("verified actor did not retain the request access token")
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
			if _, err := verifier.VerifyAuthorization(context.Background(), authorization); err == nil {
				t.Fatal("expected verification failure")
			}
		})
	}
}

func TestVerifierFailsClosedWhenNotConfigured(t *testing.T) {
	_, err := NewVerifier(config.AuthConfig{}).VerifyAuthorization(context.Background(), "Bearer token")
	if FailureCode(err) != "auth.verification_not_configured" {
		t.Fatalf("code = %q", FailureCode(err))
	}
}

func TestVerifierAcceptsES256TokenAndCachesJWKS(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	privateKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatalf("generate key: %v", err)
	}
	var requests atomic.Int32
	document, _ := json.Marshal(map[string]any{"keys": []any{map[string]any{
		"kid": "current-key", "alg": "ES256", "kty": "EC", "crv": "P-256",
		"x": coordinate(privateKey.PublicKey.X), "y": coordinate(privateKey.PublicKey.Y),
	}}})
	transport := roundTripFunc(func(request *http.Request) (*http.Response, error) {
		requests.Add(1)
		return &http.Response{StatusCode: http.StatusOK, Body: io.NopCloser(strings.NewReader(string(document))), Header: make(http.Header)}, nil
	})

	verifier := NewVerifier(config.AuthConfig{
		JWKSURL: "https://keys.example/jwks.json", JWTIssuer: "issuer", JWTAudience: "authenticated",
	})
	verifier.client = &http.Client{Transport: transport}
	verifier.now = func() time.Time { return now }
	token := signedES256Token(t, privateKey, "current-key", map[string]any{
		"sub": "00000000-0000-0000-0000-000000000001", "exp": now.Unix() + 60,
		"iss": "issuer", "aud": "authenticated",
	})
	for index := 0; index < 2; index++ {
		actor, verifyErr := verifier.VerifyAuthorization(context.Background(), "Bearer "+token)
		if verifyErr != nil || uuidutil.String(actor.ID) != "00000000-0000-0000-0000-000000000001" {
			t.Fatalf("verify ES256 token: %+v, %v", actor, verifyErr)
		}
		if actor.AccessToken() != token {
			t.Fatal("verified actor did not retain the ES256 request access token")
		}
	}
	if requests.Load() != 1 {
		t.Fatalf("JWKS requests = %d, want 1", requests.Load())
	}
}

func TestVerifierRejectsUnsupportedOrTamperedES256Tokens(t *testing.T) {
	privateKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatalf("generate key: %v", err)
	}
	document, _ := json.Marshal(map[string]any{"keys": []any{map[string]any{
		"kid": "key-a", "alg": "ES256", "kty": "EC", "crv": "P-256",
		"x": coordinate(privateKey.PublicKey.X), "y": coordinate(privateKey.PublicKey.Y),
	}}})
	transport := roundTripFunc(func(request *http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: http.StatusOK, Body: io.NopCloser(strings.NewReader(string(document))), Header: make(http.Header)}, nil
	})
	verifier := NewVerifier(config.AuthConfig{JWKSURL: "https://keys.example/jwks.json"})
	verifier.client = &http.Client{Transport: transport}
	now := time.Now().Add(time.Minute).Unix()
	valid := signedES256Token(t, privateKey, "key-a", map[string]any{
		"sub": "00000000-0000-0000-0000-000000000001", "exp": now,
	})
	tokenParts := strings.Split(valid, ".")
	tamperedSignature, decodeErr := base64.RawURLEncoding.DecodeString(tokenParts[2])
	if decodeErr != nil {
		t.Fatalf("decode ES256 signature: %v", decodeErr)
	}
	tamperedSignature[0] ^= 0xff
	tampered := tokenParts[0] + "." + tokenParts[1] + "." + base64.RawURLEncoding.EncodeToString(tamperedSignature)
	unknownKey := signedES256Token(t, privateKey, "key-b", map[string]any{
		"sub": "00000000-0000-0000-0000-000000000001", "exp": now,
	})
	for _, token := range []string{tampered, unknownKey} {
		if _, verifyErr := verifier.VerifyAuthorization(context.Background(), "Bearer "+token); verifyErr == nil {
			t.Fatal("expected ES256 verification failure")
		}
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

func signedES256Token(t *testing.T, privateKey *ecdsa.PrivateKey, keyID string, claims map[string]any) string {
	t.Helper()
	header, _ := json.Marshal(map[string]any{"alg": "ES256", "typ": "JWT", "kid": keyID})
	payload, _ := json.Marshal(claims)
	unsigned := base64.RawURLEncoding.EncodeToString(header) + "." + base64.RawURLEncoding.EncodeToString(payload)
	digest := sha256.Sum256([]byte(unsigned))
	r, s, err := ecdsa.Sign(rand.Reader, privateKey, digest[:])
	if err != nil {
		t.Fatalf("sign token: %v", err)
	}
	signature := append(r.FillBytes(make([]byte, 32)), s.FillBytes(make([]byte, 32))...)
	return unsigned + "." + base64.RawURLEncoding.EncodeToString(signature)
}

func coordinate(value *big.Int) string {
	return base64.RawURLEncoding.EncodeToString(value.FillBytes(make([]byte, 32)))
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (function roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return function(request)
}
