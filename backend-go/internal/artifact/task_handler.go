package artifact

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
)

type VerificationTaskHandler struct {
	service *Service
}

func NewVerificationTaskHandler(service *Service) *VerificationTaskHandler {
	return &VerificationTaskHandler{service: service}
}

func (h *VerificationTaskHandler) Handle(ctx context.Context, claimed task.ClaimedTask) (task.Result, error) {
	var payload struct {
		ArtifactID string `json:"artifactId"`
	}
	decoder := json.NewDecoder(bytes.NewReader(claimed.Payload))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&payload); err != nil || payload.ArtifactID == "" {
		return task.Result{}, &task.Failure{Code: "common.internal_error", Params: map[string]any{}, Retryable: false}
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		return task.Result{}, &task.Failure{Code: "common.internal_error", Params: map[string]any{}, Retryable: false}
	}
	artifact, err := h.service.VerifyOwnedArtifact(ctx, claimed.OwnerID, payload.ArtifactID)
	if err != nil {
		if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
			return task.Result{}, err
		}
		var publicError *apierror.Error
		if errors.As(err, &publicError) {
			return task.Result{}, &task.Failure{
				Code: publicError.Code, Params: publicError.Params,
				Retryable: publicError.Code == "component_repo.storage_unavailable",
			}
		}
		return task.Result{}, &task.Failure{Code: "common.internal_error", Params: map[string]any{}, Retryable: true}
	}
	result, _ := json.Marshal(map[string]any{
		"artifactId": artifact.ID, "verificationStatus": artifact.VerificationStatus,
	})
	return task.Result{Payload: result}, nil
}
