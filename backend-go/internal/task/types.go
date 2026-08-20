package task

import (
	"context"
	"encoding/json"
	"time"

	"github.com/jackc/pgx/v5/pgtype"
)

const (
	StatusQueued    = "queued"
	StatusRunning   = "running"
	StatusSucceeded = "succeeded"
	StatusFailed    = "failed"
	StatusCancelled = "cancelled"

	ArtifactVerifyType         = "component.artifact.verify"
	ImportParseType            = "component.import.parse"
	RelationDetectType         = "component.relations.detect"
	ComponentValidateType      = "component.validate"
	PreviewMaterializeType     = "component.preview.materialize"
	PartPreviewMaterializeType = "component.part_preview.materialize"
	ComponentPurgeType         = "component.purge"
)

type EnqueueInput struct {
	OwnerID        pgtype.UUID
	TaskType       string
	Payload        json.RawMessage
	Locale         string
	Timezone       string
	CreatedBy      pgtype.UUID
	IdempotencyKey string
	MaxAttempts    int32
	AvailableAt    time.Time
}

type ScheduleInput struct {
	OwnerID     pgtype.UUID
	TaskType    string
	LogicalKey  string
	InputHash   string
	Payload     json.RawMessage
	Locale      string
	Timezone    string
	CreatedBy   pgtype.UUID
	MaxAttempts int32
	AvailableAt time.Time
	ForceNew    bool
}

type Task struct {
	ID                string          `json:"id"`
	TaskJobID         string          `json:"taskJobId"`
	ExecutionNumber   int32           `json:"executionNumber"`
	TaskType          string          `json:"taskType"`
	Status            string          `json:"status"`
	Result            json.RawMessage `json:"result"`
	ResultArtifactID  *string         `json:"resultArtifactId"`
	Locale            string          `json:"locale"`
	Timezone          string          `json:"timezone"`
	Attempts          int32           `json:"attempts"`
	MaxAttempts       int32           `json:"maxAttempts"`
	Progress          *Progress       `json:"progress"`
	Error             *FailureView    `json:"error"`
	CancelRequestedAt *time.Time      `json:"cancelRequestedAt"`
	CreatedAt         time.Time       `json:"createdAt"`
	StartedAt         *time.Time      `json:"startedAt"`
	FinishedAt        *time.Time      `json:"finishedAt"`
	UpdatedAt         time.Time       `json:"updatedAt"`
}

type Progress struct {
	Percent *float64        `json:"percent"`
	Code    *string         `json:"code"`
	Params  json.RawMessage `json:"params"`
}

type ProgressUpdate struct {
	Percent *float64
	Code    *string
	Params  map[string]any
}

type FailureView struct {
	Code   string          `json:"code"`
	Params json.RawMessage `json:"params"`
}

type ClaimedTask struct {
	ID          pgtype.UUID
	OwnerID     pgtype.UUID
	TaskType    string
	Payload     json.RawMessage
	Locale      string
	Timezone    string
	Attempt     int32
	MaxAttempts int32
}

type Result struct {
	Payload    json.RawMessage
	ArtifactID pgtype.UUID
}

type Failure struct {
	Code      string
	Params    map[string]any
	Retryable bool
}

func (f *Failure) Error() string { return f.Code }

type Handler interface {
	Handle(context.Context, ClaimedTask) (Result, error)
}
