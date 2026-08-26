package auth

import (
	"context"
	"errors"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
)

func TestSessionValidatorConfirmsMatchingSupabaseUser(t *testing.T) {
	actorID, _ := uuidutil.Parse("00000000-0000-0000-0000-000000000001")
	validator := NewSupabaseSessionValidator(config.AuthConfig{
		SessionVerificationURL:     "https://project.supabase.co/auth/v1/user",
		PublishableKey:             "publishable-key",
		SessionVerificationTimeout: time.Second,
	})
	validator.client = sessionRoundTripFunc(func(request *http.Request) (*http.Response, error) {
		if request.Header.Get("apikey") != "publishable-key" || request.Header.Get("Authorization") != "Bearer user-jwt" {
			t.Fatalf("unexpected session verification headers: %+v", request.Header)
		}
		return sessionResponse(http.StatusOK, `{"id":"00000000-0000-0000-0000-000000000001","email":"user@example.com"}`), nil
	})

	user, err := validator.Validate(context.Background(), Actor{ID: actorID, accessToken: "user-jwt"})
	if err != nil {
		t.Fatalf("validate session: %v", err)
	}
	if user.ID != "00000000-0000-0000-0000-000000000001" || user.Email != "user@example.com" {
		t.Fatalf("unexpected user: %+v", user)
	}
}

func TestSessionValidatorSeparatesInvalidSessionFromProviderOutage(t *testing.T) {
	actorID, _ := uuidutil.Parse("00000000-0000-0000-0000-000000000001")
	tests := []struct {
		name       string
		response   *http.Response
		requestErr error
		code       string
		status     int
	}{
		{name: "invalid", response: sessionResponse(http.StatusUnauthorized, `{}`), code: "auth.session_invalid", status: http.StatusUnauthorized},
		{name: "provider unavailable", response: sessionResponse(http.StatusServiceUnavailable, `{}`), code: "auth.session_verification_unavailable", status: http.StatusServiceUnavailable},
		{name: "network unavailable", requestErr: errors.New("network detail"), code: "auth.session_verification_unavailable", status: http.StatusServiceUnavailable},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			validator := NewSupabaseSessionValidator(config.AuthConfig{
				SessionVerificationURL:     "https://project.supabase.co/auth/v1/user",
				PublishableKey:             "publishable-key",
				SessionVerificationTimeout: time.Second,
			})
			validator.client = sessionRoundTripFunc(func(*http.Request) (*http.Response, error) {
				return test.response, test.requestErr
			})
			_, err := validator.Validate(context.Background(), Actor{ID: actorID, accessToken: "user-jwt"})
			var validationError *SessionValidationError
			if !errors.As(err, &validationError) {
				t.Fatalf("expected SessionValidationError, got %v", err)
			}
			if validationError.Code != test.code || validationError.Status != test.status {
				t.Fatalf("unexpected validation error: %+v", validationError)
			}
		})
	}
}

func TestSessionValidatorRejectsUserMismatchAndInvalidPayload(t *testing.T) {
	actorID, _ := uuidutil.Parse("00000000-0000-0000-0000-000000000001")
	tests := []struct {
		name string
		body string
		code string
	}{
		{name: "mismatched user", body: `{"id":"00000000-0000-0000-0000-000000000002"}`, code: "auth.session_invalid"},
		{name: "invalid json", body: `{`, code: "auth.user_payload_invalid"},
		{name: "multiple values", body: `{"id":"00000000-0000-0000-0000-000000000001"}{}`, code: "auth.user_payload_invalid"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			validator := NewSupabaseSessionValidator(config.AuthConfig{
				SessionVerificationURL:     "https://project.supabase.co/auth/v1/user",
				PublishableKey:             "publishable-key",
				SessionVerificationTimeout: time.Second,
			})
			validator.client = sessionRoundTripFunc(func(*http.Request) (*http.Response, error) {
				return sessionResponse(http.StatusOK, test.body), nil
			})
			_, err := validator.Validate(context.Background(), Actor{ID: actorID, accessToken: "user-jwt"})
			var validationError *SessionValidationError
			if !errors.As(err, &validationError) || validationError.Code != test.code {
				t.Fatalf("unexpected validation error: %v", err)
			}
		})
	}
}

func sessionResponse(status int, body string) *http.Response {
	return &http.Response{
		StatusCode: status,
		Body:       io.NopCloser(strings.NewReader(body)),
		Header:     make(http.Header),
	}
}

type sessionRoundTripFunc func(*http.Request) (*http.Response, error)

func (function sessionRoundTripFunc) Do(request *http.Request) (*http.Response, error) {
	return function(request)
}
