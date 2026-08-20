package component

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/storage"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5/pgxpool"
)

const componentPurgeVersion = "component-purge-v1"

type componentPurgeStorageObject struct {
	Provider string `json:"provider"`
	Bucket   string `json:"bucket"`
	Key      string `json:"key"`
}

type componentPurgePayload struct {
	ComponentID          string                        `json:"componentId"`
	DeleteStorageObjects bool                          `json:"deleteStorageObjects"`
	StorageObjects       []componentPurgeStorageObject `json:"storageObjects"`
	PurgeVersion         string                        `json:"purgeVersion"`
}

type PurgeTaskHandler struct {
	q     *db.Queries
	store storage.Store
}

func NewPurgeTaskHandler(pool *pgxpool.Pool, store storage.Store) *PurgeTaskHandler {
	return &PurgeTaskHandler{q: db.New(pool), store: store}
}

func (h *PurgeTaskHandler) Handle(ctx context.Context, claimed task.ClaimedTask) (task.Result, error) {
	var payload componentPurgePayload
	if err := strictPurgePayload(claimed.Payload, &payload); err != nil ||
		payload.ComponentID == "" || payload.PurgeVersion != componentPurgeVersion {
		return task.Result{}, &task.Failure{Code: "component_repo.component_purge_failed", Params: map[string]any{}, Retryable: false}
	}
	componentID, err := uuidutil.Parse(payload.ComponentID)
	if err != nil {
		return task.Result{}, &task.Failure{Code: "component_repo.component_purge_failed", Params: map[string]any{"componentId": payload.ComponentID}, Retryable: false}
	}
	deletedStorageObjects := 0
	if payload.DeleteStorageObjects {
		for _, object := range payload.StorageObjects {
			if object.Provider != h.store.Provider() || object.Bucket != h.store.Bucket() || object.Key == "" {
				continue
			}
			if err := h.store.Delete(ctx, object.Key); err != nil {
				if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
					return task.Result{}, err
				}
				return task.Result{}, &task.Failure{
					Code: "component_repo.component_purge_storage_failed",
					Params: map[string]any{
						"componentId": payload.ComponentID,
					},
					Retryable: true,
				}
			}
			deletedStorageObjects++
		}
	}
	result, err := h.q.RedactOwnedComponent(ctx, db.RedactOwnedComponentParams{
		ActorID: claimed.OwnerID, ComponentID: componentID, CurrentTaskID: claimed.ID,
	})
	if err != nil {
		return task.Result{}, err
	}
	if err := h.q.RedactComponentPurgeTaskPayload(ctx, db.RedactComponentPurgeTaskPayloadParams{
		TaskID: claimed.ID, ActorID: claimed.OwnerID, ComponentID: payload.ComponentID,
	}); err != nil {
		return task.Result{}, err
	}
	return task.Result{Payload: mustPurgeJSON(map[string]any{
		"componentId":           payload.ComponentID,
		"componentRedacted":     result.ComponentRedacted,
		"versionsRedacted":      result.VersionsRedacted,
		"artifactsTombstoned":   result.ArtifactsTombstoned,
		"relatedTasksRedacted":  result.RelatedTasksRedacted,
		"storageObjectsDeleted": deletedStorageObjects,
	})}, nil
}

func strictPurgePayload(raw json.RawMessage, target any) error {
	decoder := json.NewDecoder(bytes.NewReader(raw))
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

func mustPurgeJSON(value any) json.RawMessage {
	data, err := json.Marshal(value)
	if err != nil {
		return json.RawMessage(`{}`)
	}
	return data
}
