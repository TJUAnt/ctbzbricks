package task

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"net/http"
	"regexp"
	"strings"
	"time"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

const outboxTopic = "component.task.events"

var taskTypePattern = regexp.MustCompile(`^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$`)

type Service struct {
	pool *pgxpool.Pool
	q    *db.Queries
	now  func() time.Time
}

func NewService(pool *pgxpool.Pool) *Service {
	return &Service{pool: pool, q: db.New(pool), now: time.Now}
}

func (s *Service) Enqueue(ctx context.Context, input EnqueueInput) (Task, bool, error) {
	row, created, err := withTx(ctx, s.pool, func(q *db.Queries) (db.ComponentRepoTask, bool, error) {
		return EnqueueWithQueries(ctx, q, input)
	})
	return taskFromDB(row), created, err
}

// EnqueueWithQueries lets a business mutation create its task and outbox event
// in the same PostgreSQL transaction.
func EnqueueWithQueries(ctx context.Context, q *db.Queries, input EnqueueInput) (db.ComponentRepoTask, bool, error) {
	if err := validateEnqueue(input); err != nil {
		return db.ComponentRepoTask{}, false, err
	}
	logicalKey := input.IdempotencyKey
	if logicalKey == "" {
		id, err := uuidutil.New()
		if err != nil {
			return db.ComponentRepoTask{}, false, err
		}
		logicalKey = uuidutil.String(id)
	}
	hash := sha256.Sum256(compactObject(input.Payload))
	result, err := ScheduleWithQueries(ctx, q, ScheduleInput{
		OwnerID: input.OwnerID, TaskType: input.TaskType, LogicalKey: logicalKey,
		InputHash: fmt.Sprintf("%x", hash[:]), Payload: input.Payload, Locale: input.Locale,
		Timezone: input.Timezone, CreatedBy: input.CreatedBy, MaxAttempts: input.MaxAttempts,
		AvailableAt: input.AvailableAt,
	})
	return result.Task, result.Created, err
}

type ScheduleResult struct {
	Task      db.ComponentRepoTask
	Job       db.ComponentRepoTaskJob
	Created   bool
	Succeeded bool
}

func ScheduleWithQueries(ctx context.Context, q *db.Queries, input ScheduleInput) (ScheduleResult, error) {
	if err := validateSchedule(input); err != nil {
		return ScheduleResult{}, err
	}
	jobID, err := uuidutil.New()
	if err != nil {
		return ScheduleResult{}, err
	}
	_, err = q.CreateTaskJob(ctx, db.CreateTaskJobParams{
		ID: jobID, OwnerID: input.OwnerID, TaskType: input.TaskType,
		LogicalKey: input.LogicalKey, InputHash: input.InputHash, CreatedBy: input.CreatedBy,
	})
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return ScheduleResult{}, err
	}
	job, err := q.LockTaskJobByIdentity(ctx, db.LockTaskJobByIdentityParams{
		OwnerID: input.OwnerID, TaskType: input.TaskType,
		LogicalKey: input.LogicalKey, InputHash: input.InputHash,
	})
	if err != nil {
		return ScheduleResult{}, err
	}
	if job.LatestTaskID.Valid {
		latest, getErr := q.GetOwnedTask(ctx, db.GetOwnedTaskParams{TaskID: job.LatestTaskID, ActorID: input.OwnerID})
		if getErr != nil {
			return ScheduleResult{}, getErr
		}
		if latest.Status == StatusQueued || latest.Status == StatusRunning {
			return ScheduleResult{Task: latest, Job: job}, nil
		}
		if job.SuccessfulTaskID.Valid && !input.ForceNew {
			succeeded, getErr := q.GetOwnedTask(ctx, db.GetOwnedTaskParams{TaskID: job.SuccessfulTaskID, ActorID: input.OwnerID})
			if getErr != nil {
				return ScheduleResult{}, getErr
			}
			return ScheduleResult{Task: succeeded, Job: job, Succeeded: true}, nil
		}
	}
	taskID, err := uuidutil.New()
	if err != nil {
		return ScheduleResult{}, err
	}
	executionNumber := job.ExecutionCount + 1
	availableAt := input.AvailableAt.UTC()
	if input.AvailableAt.IsZero() {
		availableAt = time.Now().UTC()
	}
	var retryOf pgtype.UUID
	if job.LatestTaskID.Valid {
		retryOf = job.LatestTaskID
	}
	row, err := q.CreateTask(ctx, db.CreateTaskParams{
		ID: taskID, OwnerID: input.OwnerID, TaskType: input.TaskType,
		Payload: compactObject(input.Payload), Locale: input.Locale, Timezone: input.Timezone,
		CreatedBy: input.CreatedBy, MaxAttempts: input.MaxAttempts,
		AvailableAt: timestamp(availableAt), TaskJobID: job.ID,
		ExecutionNumber: executionNumber, RetryOfTaskID: retryOf,
	})
	if err != nil {
		return ScheduleResult{}, err
	}
	job.ExecutionCount = executionNumber
	job.LatestTaskID = taskID
	if err := recordEvent(ctx, q, row, StatusQueued, nil, nil, nil); err != nil {
		return ScheduleResult{}, err
	}
	return ScheduleResult{Task: row, Job: job, Created: true}, nil
}

func (s *Service) GetOwned(ctx context.Context, actor pgtype.UUID, taskID string) (Task, error) {
	id, err := uuidutil.Parse(taskID)
	if err != nil {
		return Task{}, apierror.New("request.validation_failed", http.StatusUnprocessableEntity, map[string]any{"field": "taskId"})
	}
	row, err := s.q.GetOwnedTask(ctx, db.GetOwnedTaskParams{TaskID: id, ActorID: actor})
	if errors.Is(err, pgx.ErrNoRows) {
		return Task{}, apierror.New("request.not_found", http.StatusNotFound, nil)
	}
	return taskFromDB(row), err
}

func (s *Service) Cancel(ctx context.Context, actor pgtype.UUID, taskID string) (Task, error) {
	id, err := uuidutil.Parse(taskID)
	if err != nil {
		return Task{}, apierror.New("request.validation_failed", http.StatusUnprocessableEntity, map[string]any{"field": "taskId"})
	}
	row, _, err := withTx(ctx, s.pool, func(q *db.Queries) (db.ComponentRepoTask, bool, error) {
		locked, err := q.LockOwnedTask(ctx, db.LockOwnedTaskParams{TaskID: id, ActorID: actor})
		if errors.Is(err, pgx.ErrNoRows) {
			return db.ComponentRepoTask{}, false, apierror.New("request.not_found", http.StatusNotFound, nil)
		}
		if err != nil {
			return db.ComponentRepoTask{}, false, err
		}
		if locked.Status == StatusSucceeded || locked.Status == StatusFailed || locked.Status == StatusCancelled {
			return locked, false, nil
		}
		now := timestamp(s.now().UTC())
		var updated db.ComponentRepoTask
		var eventStatus string
		if locked.Status == StatusQueued {
			updated, err = q.CancelQueuedTask(ctx, db.CancelQueuedTaskParams{CancelledAt: now, ActorID: actor, TaskID: id})
			eventStatus = StatusCancelled
		} else {
			updated, err = q.RequestRunningTaskCancellation(ctx, db.RequestRunningTaskCancellationParams{RequestedAt: now, ActorID: actor, TaskID: id})
			eventStatus = "cancel_requested"
		}
		if err != nil {
			return db.ComponentRepoTask{}, false, err
		}
		if err := recordEvent(ctx, q, updated, eventStatus, nil, nil, nil); err != nil {
			return db.ComponentRepoTask{}, false, err
		}
		if eventStatus == StatusCancelled {
			if err := propagateTerminalDependencies(ctx, q, s.now().UTC()); err != nil {
				return db.ComponentRepoTask{}, false, err
			}
		}
		return updated, true, nil
	})
	return taskFromDB(row), err
}

func (s *Service) Claim(ctx context.Context, workerID string, taskTypes []string, leaseDuration time.Duration) (ClaimedTask, bool, error) {
	if workerID == "" || len(taskTypes) == 0 || leaseDuration <= 0 {
		return ClaimedTask{}, false, errors.New("invalid task claim configuration")
	}
	now := s.now().UTC()
	row, claimed, err := withTx(ctx, s.pool, func(q *db.Queries) (db.ComponentRepoTask, bool, error) {
		row, err := q.ClaimAvailableTask(ctx, db.ClaimAvailableTaskParams{
			LeaseOwner: stringPointer(workerID), LeaseExpiresAt: timestamp(now.Add(leaseDuration)),
			ClaimedAt: timestamp(now), TaskTypes: taskTypes,
		})
		if errors.Is(err, pgx.ErrNoRows) {
			return db.ComponentRepoTask{}, false, nil
		}
		if err != nil {
			return db.ComponentRepoTask{}, false, err
		}
		if err := recordEvent(ctx, q, row, StatusRunning, nil, nil, nil); err != nil {
			return db.ComponentRepoTask{}, false, err
		}
		return row, true, nil
	})
	if err != nil || !claimed {
		return ClaimedTask{}, claimed, err
	}
	return claimedFromDB(row), true, nil
}

func (s *Service) Heartbeat(ctx context.Context, workerID string, claimed ClaimedTask, leaseDuration time.Duration) (bool, bool, error) {
	now := s.now().UTC()
	cancelledAt, err := s.q.HeartbeatTask(ctx, db.HeartbeatTaskParams{
		LeaseExpiresAt: timestamp(now.Add(leaseDuration)), HeartbeatAt: timestamp(now),
		TaskID: claimed.ID, LeaseOwner: stringPointer(workerID), ClaimedAttempt: claimed.Attempt,
	})
	if errors.Is(err, pgx.ErrNoRows) {
		return false, false, nil
	}
	return true, cancelledAt.Valid, err
}

func (s *Service) UpdateProgress(ctx context.Context, workerID string, claimed ClaimedTask, progress ProgressUpdate) error {
	if progress.Percent != nil && (*progress.Percent < 0 || *progress.Percent > 100) {
		return errors.New("task progress percent must be between zero and one hundred")
	}
	if progress.Code != nil && !taskTypePattern.MatchString(*progress.Code) {
		return errors.New("task progress code must be a machine code")
	}
	var params []byte
	if progress.Code != nil {
		if progress.Params == nil {
			progress.Params = map[string]any{}
		}
		params, _ = json.Marshal(progress.Params)
	} else if len(progress.Params) > 0 {
		return errors.New("task progress params require a code")
	}
	_, _, err := withTx(ctx, s.pool, func(q *db.Queries) (db.ComponentRepoTask, bool, error) {
		now := timestamp(s.now().UTC())
		row, err := q.UpdateTaskProgress(ctx, db.UpdateTaskProgressParams{
			ProgressCode: progress.Code, ProgressParams: params, ProgressPercent: numeric(progress.Percent),
			UpdatedAt: now, TaskID: claimed.ID, LeaseOwner: stringPointer(workerID), ClaimedAttempt: claimed.Attempt,
		})
		if err != nil {
			return db.ComponentRepoTask{}, false, err
		}
		if err := recordEvent(ctx, q, row, StatusRunning, progress.Code, params, progress.Percent); err != nil {
			return db.ComponentRepoTask{}, false, err
		}
		return row, true, nil
	})
	return err
}

func (s *Service) Complete(ctx context.Context, workerID string, claimed ClaimedTask, result Result) error {
	payload := result.Payload
	if len(payload) == 0 {
		payload = json.RawMessage(`{}`)
	}
	_, _, err := withTx(ctx, s.pool, func(q *db.Queries) (db.ComponentRepoTask, bool, error) {
		now := timestamp(s.now().UTC())
		row, err := q.CompleteTask(ctx, db.CompleteTaskParams{
			Result: compactObject(payload), ResultArtifactID: result.ArtifactID,
			FinishedAt: now, TaskID: claimed.ID, LeaseOwner: stringPointer(workerID), ClaimedAttempt: claimed.Attempt,
		})
		eventStatus := StatusSucceeded
		if errors.Is(err, pgx.ErrNoRows) {
			row, err = q.CancelClaimedTask(ctx, db.CancelClaimedTaskParams{
				FinishedAt: now, TaskID: claimed.ID, LeaseOwner: stringPointer(workerID), ClaimedAttempt: claimed.Attempt,
			})
			if err == nil {
				eventStatus = StatusCancelled
			}
		}
		if errors.Is(err, pgx.ErrNoRows) {
			current, currentErr := q.GetOwnedTask(ctx, db.GetOwnedTaskParams{TaskID: claimed.ID, ActorID: claimed.OwnerID})
			if currentErr == nil && current.Status == StatusSucceeded {
				return current, false, nil
			}
			if currentErr != nil {
				return db.ComponentRepoTask{}, false, currentErr
			}
		}
		if err != nil {
			return db.ComponentRepoTask{}, false, err
		}
		var percent *float64
		if eventStatus == StatusSucceeded {
			percent = floatPointer(100)
		}
		if err := recordEvent(ctx, q, row, eventStatus, nil, nil, percent); err != nil {
			return db.ComponentRepoTask{}, false, err
		}
		if eventStatus == StatusCancelled {
			if err := propagateTerminalDependencies(ctx, q, s.now().UTC()); err != nil {
				return db.ComponentRepoTask{}, false, err
			}
		}
		return row, true, nil
	})
	return err
}

func (s *Service) FinishFailure(ctx context.Context, workerID string, claimed ClaimedTask, failure *Failure, retryDelay time.Duration) error {
	if failure == nil || !taskTypePattern.MatchString(failure.Code) {
		failure = &Failure{Code: "common.internal_error", Params: map[string]any{}, Retryable: true}
	}
	if failure.Params == nil {
		failure.Params = map[string]any{}
	}
	params, err := json.Marshal(failure.Params)
	if err != nil {
		params = []byte(`{}`)
	}
	_, _, err = withTx(ctx, s.pool, func(q *db.Queries) (db.ComponentRepoTask, bool, error) {
		now := s.now().UTC()
		var row db.ComponentRepoTask
		var eventStatus string
		var transitionErr error
		if failure.Retryable && claimed.Attempt < claimed.MaxAttempts {
			row, transitionErr = q.RetryTask(ctx, db.RetryTaskParams{
				AvailableAt: timestamp(now.Add(retryDelay)), ErrorCode: stringPointer(failure.Code),
				ErrorParams: params, UpdatedAt: timestamp(now), TaskID: claimed.ID,
				LeaseOwner: stringPointer(workerID), ClaimedAttempt: claimed.Attempt,
			})
			eventStatus = "retrying"
		} else {
			row, transitionErr = q.FailTask(ctx, db.FailTaskParams{
				ErrorCode: stringPointer(failure.Code), ErrorParams: params,
				FinishedAt: timestamp(now), TaskID: claimed.ID, LeaseOwner: stringPointer(workerID),
				ClaimedAttempt: claimed.Attempt,
			})
			eventStatus = StatusFailed
		}
		if errors.Is(transitionErr, pgx.ErrNoRows) {
			row, transitionErr = q.CancelClaimedTask(ctx, db.CancelClaimedTaskParams{
				FinishedAt: timestamp(now), TaskID: claimed.ID, LeaseOwner: stringPointer(workerID),
				ClaimedAttempt: claimed.Attempt,
			})
			if transitionErr == nil {
				eventStatus = StatusCancelled
			}
		}
		if transitionErr != nil {
			return db.ComponentRepoTask{}, false, transitionErr
		}
		var code *string
		var eventParams []byte
		if eventStatus != StatusCancelled {
			code, eventParams = stringPointer(failure.Code), params
		}
		if err := recordEvent(ctx, q, row, eventStatus, code, eventParams, nil); err != nil {
			return db.ComponentRepoTask{}, false, err
		}
		if eventStatus == StatusFailed || eventStatus == StatusCancelled {
			if err := propagateTerminalDependencies(ctx, q, now); err != nil {
				return db.ComponentRepoTask{}, false, err
			}
		}
		return row, true, nil
	})
	return err
}

func (s *Service) RecoverExpired(ctx context.Context) (bool, error) {
	_, recovered, err := withTx(ctx, s.pool, func(q *db.Queries) (db.ComponentRepoTask, bool, error) {
		row, err := q.RecoverExpiredTask(ctx, timestamp(s.now().UTC()))
		if errors.Is(err, pgx.ErrNoRows) {
			return db.ComponentRepoTask{}, false, nil
		}
		if err != nil {
			return db.ComponentRepoTask{}, false, err
		}
		eventStatus := row.Status
		if row.Status == StatusQueued {
			eventStatus = "retrying"
		}
		if err := recordEvent(ctx, q, row, eventStatus, row.ErrorCode, row.ErrorParams, nil); err != nil {
			return db.ComponentRepoTask{}, false, err
		}
		if row.Status == StatusFailed || row.Status == StatusCancelled {
			if err := propagateTerminalDependencies(ctx, q, s.now().UTC()); err != nil {
				return db.ComponentRepoTask{}, false, err
			}
		}
		return row, true, nil
	})
	return recovered, err
}

func propagateTerminalDependencies(ctx context.Context, q *db.Queries, now time.Time) error {
	for {
		rows, err := q.FailTasksWithTerminalDependencies(ctx, timestamp(now))
		if err != nil {
			return err
		}
		if len(rows) == 0 {
			return nil
		}
		for _, row := range rows {
			if err := recordEvent(ctx, q, row, row.Status, row.ErrorCode, row.ErrorParams, nil); err != nil {
				return err
			}
		}
	}
}

func (s *Service) ClaimOutbox(ctx context.Context, workerID string, leaseDuration time.Duration) (db.ComponentRepoOutboxEvent, bool, error) {
	now := s.now().UTC()
	row, err := s.q.ClaimOutboxEvent(ctx, db.ClaimOutboxEventParams{
		LeaseOwner: stringPointer(workerID), LeaseExpiresAt: timestamp(now.Add(leaseDuration)), ClaimedAt: timestamp(now),
	})
	if errors.Is(err, pgx.ErrNoRows) {
		return db.ComponentRepoOutboxEvent{}, false, nil
	}
	return row, err == nil, err
}

func (s *Service) MarkOutboxPublished(ctx context.Context, workerID string, eventID pgtype.UUID) error {
	_, err := s.q.MarkOutboxPublished(ctx, db.MarkOutboxPublishedParams{
		PublishedAt: timestamp(s.now().UTC()), EventID: eventID, LeaseOwner: stringPointer(workerID),
	})
	return err
}

func (s *Service) RetryOutbox(ctx context.Context, workerID string, eventID pgtype.UUID, code string, params map[string]any, delay time.Duration) error {
	now := s.now().UTC()
	if params == nil {
		params = map[string]any{}
	}
	encoded, _ := json.Marshal(params)
	_, err := s.q.RetryOutboxEvent(ctx, db.RetryOutboxEventParams{
		AvailableAt: timestamp(now.Add(delay)), ErrorCode: stringPointer(code), ErrorParams: encoded,
		UpdatedAt: timestamp(now), EventID: eventID, LeaseOwner: stringPointer(workerID),
	})
	return err
}

func recordEvent(ctx context.Context, q *db.Queries, row db.ComponentRepoTask, status string, code *string, params []byte, percent *float64) error {
	event, err := q.CreateTaskEvent(ctx, db.CreateTaskEventParams{
		TaskID: row.ID, Status: status, Code: code, Params: params, ProgressPercent: numeric(percent),
	})
	if err != nil {
		return err
	}
	payload, err := json.Marshal(map[string]any{
		"eventId": event.ID, "taskId": uuidutil.String(row.ID), "ownerId": uuidutil.String(row.OwnerID),
		"taskType": row.TaskType, "taskStatus": row.Status, "eventStatus": status,
		"taskJobId": uuidutil.String(row.TaskJobID), "executionNumber": row.ExecutionNumber,
		"attempt": row.Attempts, "code": codeValue(code), "params": rawObject(params),
	})
	if err != nil {
		return err
	}
	outboxID, err := uuidutil.New()
	if err != nil {
		return err
	}
	_, err = q.CreateOutboxEvent(ctx, db.CreateOutboxEventParams{
		ID: outboxID, AggregateType: "task", AggregateID: row.ID, Topic: outboxTopic,
		EventKey: fmt.Sprintf("%s:%d", uuidutil.String(row.ID), event.ID), Payload: payload,
		MaxAttempts: 10, AvailableAt: event.CreatedAt,
	})
	return err
}

func validateEnqueue(input EnqueueInput) error {
	if !input.OwnerID.Valid || !input.CreatedBy.Valid || !taskTypePattern.MatchString(input.TaskType) {
		return errors.New("invalid task identity or type")
	}
	if input.Locale != "zh-CN" && input.Locale != "en-US" {
		return errors.New("task locale must be normalized")
	}
	if _, err := time.LoadLocation(input.Timezone); err != nil {
		return errors.New("task timezone must be IANA")
	}
	if input.MaxAttempts < 1 || input.MaxAttempts > 20 || len(input.IdempotencyKey) > 300 {
		return errors.New("invalid task retry or idempotency configuration")
	}
	var object map[string]any
	if len(input.Payload) == 0 || json.Unmarshal(input.Payload, &object) != nil || object == nil {
		return errors.New("task payload must be a JSON object")
	}
	return nil
}

func validateSchedule(input ScheduleInput) error {
	if !input.OwnerID.Valid || !input.CreatedBy.Valid || !taskTypePattern.MatchString(input.TaskType) {
		return errors.New("invalid task identity or type")
	}
	if strings.TrimSpace(input.LogicalKey) != input.LogicalKey || input.LogicalKey == "" || len(input.LogicalKey) > 300 {
		return errors.New("invalid task logical key")
	}
	if len(input.InputHash) != 64 {
		return errors.New("task input hash must be sha256")
	}
	for _, character := range input.InputHash {
		if !strings.ContainsRune("0123456789abcdef", character) {
			return errors.New("task input hash must be lowercase sha256")
		}
	}
	return validateEnqueue(EnqueueInput{
		OwnerID: input.OwnerID, TaskType: input.TaskType, Payload: input.Payload,
		Locale: input.Locale, Timezone: input.Timezone, CreatedBy: input.CreatedBy,
		IdempotencyKey: input.LogicalKey, MaxAttempts: input.MaxAttempts,
		AvailableAt: input.AvailableAt,
	})
}

func taskFromDB(row db.ComponentRepoTask) Task {
	result := json.RawMessage(row.Result)
	if len(result) == 0 {
		result = nil
	}
	view := Task{
		ID: uuidutil.String(row.ID), TaskJobID: uuidutil.String(row.TaskJobID),
		ExecutionNumber: row.ExecutionNumber, TaskType: row.TaskType, Status: row.Status,
		Result: result, ResultArtifactID: uuidutil.NullableString(row.ResultArtifactID),
		Locale: row.Locale, Timezone: row.Timezone, Attempts: row.Attempts,
		MaxAttempts: row.MaxAttempts, CreatedAt: row.CreatedAt.Time,
		StartedAt: timePointer(row.StartedAt), FinishedAt: timePointer(row.FinishedAt),
		CancelRequestedAt: timePointer(row.CancelRequestedAt), UpdatedAt: row.UpdatedAt.Time,
	}
	if row.ProgressCode != nil || row.ProgressPercent.Valid {
		view.Progress = &Progress{Code: row.ProgressCode, Percent: numericFloat(row.ProgressPercent), Params: rawObject(row.ProgressParams)}
	}
	if row.ErrorCode != nil {
		view.Error = &FailureView{Code: *row.ErrorCode, Params: rawObject(row.ErrorParams)}
	}
	return view
}

func claimedFromDB(row db.ComponentRepoTask) ClaimedTask {
	return ClaimedTask{
		ID: row.ID, OwnerID: row.OwnerID, TaskType: row.TaskType,
		Payload: row.Payload, Locale: row.Locale, Timezone: row.Timezone,
		Attempt: row.Attempts, MaxAttempts: row.MaxAttempts,
	}
}

func withTx[T any](ctx context.Context, pool *pgxpool.Pool, fn func(*db.Queries) (T, bool, error)) (T, bool, error) {
	var zero T
	tx, err := pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return zero, false, err
	}
	value, changed, runErr := fn(db.New(tx))
	if runErr != nil {
		_ = tx.Rollback(ctx)
		return zero, false, runErr
	}
	if err := tx.Commit(ctx); err != nil {
		return zero, false, err
	}
	return value, changed, nil
}

func timestamp(value time.Time) pgtype.Timestamptz {
	return pgtype.Timestamptz{Time: value.UTC(), Valid: true}
}

func stringPointer(value string) *string  { return &value }
func floatPointer(value float64) *float64 { return &value }

func numeric(value *float64) pgtype.Numeric {
	if value == nil {
		return pgtype.Numeric{}
	}
	scaled := int64(*value * 100)
	return pgtype.Numeric{Int: big.NewInt(scaled), Exp: -2, Valid: true}
}

func numericFloat(value pgtype.Numeric) *float64 {
	if !value.Valid {
		return nil
	}
	converted, err := value.Float64Value()
	if err != nil || !converted.Valid {
		return nil
	}
	return &converted.Float64
}

func timePointer(value pgtype.Timestamptz) *time.Time {
	if !value.Valid {
		return nil
	}
	result := value.Time.UTC()
	return &result
}

func compactObject(raw []byte) []byte {
	var buffer bytes.Buffer
	if json.Compact(&buffer, raw) != nil {
		return raw
	}
	return buffer.Bytes()
}

func rawObject(value []byte) json.RawMessage {
	if len(value) == 0 || !json.Valid(value) {
		return json.RawMessage(`{}`)
	}
	return value
}

func codeValue(value *string) any {
	if value == nil {
		return nil
	}
	return strings.TrimSpace(*value)
}
