//go:build integration

package task_test

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"sync"
	"testing"
	"time"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	. "github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

func TestDurableTaskLifecycle(t *testing.T) {
	databaseURL := os.Getenv("TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatalf("connect PostgreSQL: %v", err)
	}
	defer pool.Close()
	actor := mustTaskUUID(t, "50000000-0000-0000-0000-000000000001")
	baseTime := time.Date(2026, 8, 9, 10, 0, 0, 0, time.UTC)

	t.Run("idempotency is owner scoped and emits event plus outbox", func(t *testing.T) {
		resetTaskFixtures(t, pool)
		service := NewService(pool)
		service.WithClock(func() time.Time { return baseTime })
		input := taskFixture(actor, "same-request", 3, baseTime)
		first, created, err := service.Enqueue(ctx, input)
		if err != nil || !created {
			t.Fatalf("first enqueue = created %v, error %v", created, err)
		}
		restartedView, err := NewService(pool).GetOwned(ctx, actor, first.ID)
		if err != nil || restartedView.Status != StatusQueued {
			t.Fatalf("task did not survive service restart: %+v, %v", restartedView, err)
		}
		second, created, err := service.Enqueue(ctx, input)
		if err != nil || created || second.ID != first.ID {
			t.Fatalf("idempotent enqueue = %+v created %v error %v", second, created, err)
		}
		otherOwner := mustTaskUUID(t, "50000000-0000-0000-0000-000000000002")
		other, created, err := service.Enqueue(ctx, taskFixture(otherOwner, "same-request", 3, baseTime))
		if err != nil || !created || other.ID == first.ID {
			t.Fatalf("owner-scoped enqueue = %+v created %v error %v", other, created, err)
		}
		assertTaskCounts(t, pool, 2, 2, 2)
	})

	t.Run("lease recovery retry cancellation and terminal failure", func(t *testing.T) {
		resetTaskFixtures(t, pool)
		current := time.Now().UTC().Add(time.Second)
		service := NewService(pool)
		service.WithClock(func() time.Time { return current })
		queued, _, err := service.Enqueue(ctx, taskFixture(actor, "recoverable", 2, current))
		if err != nil {
			t.Fatalf("enqueue recoverable task: %v", err)
		}
		claimed, found, err := service.Claim(ctx, "worker-a", []string{ArtifactVerifyType}, time.Minute)
		if err != nil || !found || claimed.Attempt != 1 {
			t.Fatalf("first claim = %+v found %v error %v", claimed, found, err)
		}
		progressCode, progressPercent := "terrain.progress.processing", 42.0
		if err := service.UpdateProgress(ctx, "worker-a", claimed, ProgressUpdate{
			Code: &progressCode, Percent: &progressPercent, Params: map[string]any{"percent": 42},
		}); err != nil {
			t.Fatalf("update task progress: %v", err)
		}
		current = current.Add(2 * time.Minute)
		if recovered, err := service.RecoverExpired(ctx); err != nil || !recovered {
			t.Fatalf("recover expired = %v, %v", recovered, err)
		}
		requeued, err := service.GetOwned(ctx, actor, queued.ID)
		if err != nil || requeued.Status != StatusQueued || requeued.Attempts != 1 {
			t.Fatalf("recovered task = %+v, %v", requeued, err)
		}
		claimed, found, err = service.Claim(ctx, "worker-b", []string{ArtifactVerifyType}, time.Minute)
		if err != nil || !found || claimed.Attempt != 2 {
			t.Fatalf("second claim = %+v found %v error %v", claimed, found, err)
		}
		cancelledView, err := service.Cancel(ctx, actor, queued.ID)
		if err != nil || cancelledView.Status != StatusRunning || cancelledView.CancelRequestedAt == nil {
			t.Fatalf("request cancellation = %+v, %v", cancelledView, err)
		}
		owned, cancelRequested, err := service.Heartbeat(ctx, "worker-b", claimed, time.Minute)
		if err != nil || !owned || !cancelRequested {
			t.Fatalf("cancellation heartbeat = owned %v cancel %v error %v", owned, cancelRequested, err)
		}
		if err := service.FinishFailure(ctx, "worker-b", claimed, &Failure{Code: "common.internal_error", Params: map[string]any{}, Retryable: true}, time.Second); err != nil {
			t.Fatalf("finalize cancellation: %v", err)
		}
		cancelled, err := service.GetOwned(ctx, actor, queued.ID)
		if err != nil || cancelled.Status != StatusCancelled {
			t.Fatalf("cancelled task = %+v, %v", cancelled, err)
		}

		current = current.Add(time.Minute)
		failedTask, _, err := service.Enqueue(ctx, taskFixture(actor, "retry-then-fail", 2, current))
		if err != nil {
			t.Fatalf("enqueue failure task: %v", err)
		}
		firstAttempt, _, _ := service.Claim(ctx, "worker-c", []string{ArtifactVerifyType}, time.Minute)
		failure := &Failure{Code: "component_repo.storage_unavailable", Params: map[string]any{}, Retryable: true}
		if err := service.FinishFailure(ctx, "worker-c", firstAttempt, failure, time.Second); err != nil {
			t.Fatalf("schedule retry: %v", err)
		}
		current = current.Add(2 * time.Second)
		secondAttempt, found, err := service.Claim(ctx, "worker-c", []string{ArtifactVerifyType}, time.Minute)
		if err != nil || !found || secondAttempt.Attempt != 2 {
			t.Fatalf("claim retry = %+v found %v error %v", secondAttempt, found, err)
		}
		if err := service.FinishFailure(ctx, "worker-c", secondAttempt, failure, time.Second); err != nil {
			t.Fatalf("finish exhausted task: %v", err)
		}
		failed, err := service.GetOwned(ctx, actor, failedTask.ID)
		if err != nil || failed.Status != StatusFailed || failed.Error == nil || failed.Error.Code != failure.Code {
			t.Fatalf("failed task = %+v, %v", failed, err)
		}
	})

	t.Run("skip locked claims never duplicate a task", func(t *testing.T) {
		resetTaskFixtures(t, pool)
		service := NewService(pool)
		service.WithClock(func() time.Time { return baseTime })
		const count = 12
		for index := 0; index < count; index++ {
			if _, _, err := service.Enqueue(ctx, taskFixture(actor, fmt.Sprintf("claim-%d", index), 3, baseTime)); err != nil {
				t.Fatalf("enqueue claim fixture %d: %v", index, err)
			}
		}
		ids := make(chan string, count)
		var group sync.WaitGroup
		for index := 0; index < count; index++ {
			group.Add(1)
			go func(worker int) {
				defer group.Done()
				claimed, found, err := service.Claim(ctx, fmt.Sprintf("worker-%d", worker), []string{ArtifactVerifyType}, time.Minute)
				if err != nil {
					t.Errorf("claim %d: %v", worker, err)
					return
				}
				if found {
					ids <- uuidutil.String(claimed.ID)
				}
			}(index)
		}
		group.Wait()
		close(ids)
		unique := map[string]struct{}{}
		for id := range ids {
			if _, exists := unique[id]; exists {
				t.Fatalf("task claimed twice: %s", id)
			}
			unique[id] = struct{}{}
		}
		if len(unique) != count {
			t.Fatalf("claimed %d tasks, want %d", len(unique), count)
		}
	})

	t.Run("retry attempts fence stale workers and terminal completion is idempotent", func(t *testing.T) {
		resetTaskFixtures(t, pool)
		current := time.Now().UTC().Add(time.Second)
		service := NewService(pool)
		service.WithClock(func() time.Time { return current })
		queued, _, err := service.Enqueue(ctx, taskFixture(actor, "attempt-fence", 3, current))
		if err != nil {
			t.Fatalf("enqueue fenced task: %v", err)
		}
		first, found, err := service.Claim(ctx, "reused-worker", []string{ArtifactVerifyType}, time.Minute)
		if err != nil || !found || first.Attempt != 1 {
			t.Fatalf("first claim = %+v found=%v error=%v", first, found, err)
		}
		current = current.Add(2 * time.Minute)
		if recovered, recoverErr := service.RecoverExpired(ctx); recoverErr != nil || !recovered {
			t.Fatalf("recover first attempt = %v, %v", recovered, recoverErr)
		}
		second, found, err := service.Claim(ctx, "reused-worker", []string{ArtifactVerifyType}, time.Minute)
		if err != nil || !found || second.Attempt != 2 || uuidutil.String(second.ID) != queued.ID {
			t.Fatalf("second claim = %+v found=%v error=%v", second, found, err)
		}
		owned, _, heartbeatErr := service.Heartbeat(ctx, "reused-worker", first, time.Minute)
		if heartbeatErr != nil || owned {
			t.Fatalf("stale heartbeat = owned=%v error=%v", owned, heartbeatErr)
		}
		result := Result{Payload: json.RawMessage(`{"verified":true}`)}
		if err := service.Complete(ctx, "reused-worker", first, result); err == nil {
			t.Fatal("stale attempt completed the newer lease")
		}
		running, err := service.GetOwned(ctx, actor, queued.ID)
		if err != nil || running.Status != StatusRunning || running.Attempts != 2 {
			t.Fatalf("newer attempt changed by stale completion: %+v error=%v", running, err)
		}
		if err := service.Complete(ctx, "reused-worker", second, result); err != nil {
			t.Fatalf("complete current attempt: %v", err)
		}
		if err := service.Complete(ctx, "reused-worker", second, result); err != nil {
			t.Fatalf("repeat terminal completion should be a no-op: %v", err)
		}
		var succeededEvents int
		if err := pool.QueryRow(ctx, `SELECT count(*) FROM component_repo.task_events WHERE task_id=$1 AND status='succeeded'`, second.ID).Scan(&succeededEvents); err != nil || succeededEvents != 1 {
			t.Fatalf("succeeded event count = %d error=%v", succeededEvents, err)
		}
	})

	t.Run("logical jobs reuse active and successful executions but rerun terminal failure", func(t *testing.T) {
		resetTaskFixtures(t, pool)
		current := time.Now().UTC().Add(time.Second)
		service := NewService(pool)
		service.WithClock(func() time.Time { return current })
		input := taskFixture(actor, "logical-computation", 1, current)

		first, created, err := service.Enqueue(ctx, input)
		if err != nil || !created || first.ExecutionNumber != 1 {
			t.Fatalf("first execution = %+v created=%v error=%v", first, created, err)
		}
		active, created, err := service.Enqueue(ctx, input)
		if err != nil || created || active.ID != first.ID {
			t.Fatalf("active execution not reused: %+v created=%v error=%v", active, created, err)
		}
		claimed, found, err := service.Claim(ctx, "logical-worker", []string{ArtifactVerifyType}, time.Minute)
		if err != nil || !found {
			t.Fatalf("claim first logical execution: %v found=%v", err, found)
		}
		if err := service.FinishFailure(ctx, "logical-worker", claimed, &Failure{Code: "common.internal_error", Params: map[string]any{}, Retryable: false}, time.Second); err != nil {
			t.Fatalf("fail logical execution: %v", err)
		}
		second, created, err := service.Enqueue(ctx, input)
		if err != nil || !created || second.ID == first.ID || second.TaskJobID != first.TaskJobID || second.ExecutionNumber != 2 {
			t.Fatalf("terminal failure did not create execution 2: %+v created=%v error=%v", second, created, err)
		}
		claimed, found, err = service.Claim(ctx, "logical-worker", []string{ArtifactVerifyType}, time.Minute)
		if err != nil || !found || uuidutil.String(claimed.ID) != second.ID {
			t.Fatalf("claim second logical execution: %+v found=%v error=%v", claimed, found, err)
		}
		if err := service.Complete(ctx, "logical-worker", claimed, Result{Payload: json.RawMessage(`{"verified":true}`)}); err != nil {
			t.Fatalf("complete second logical execution: %v", err)
		}
		succeeded, created, err := service.Enqueue(ctx, input)
		if err != nil || created || succeeded.ID != second.ID || succeeded.Status != StatusSucceeded {
			t.Fatalf("successful execution not reused: %+v created=%v error=%v", succeeded, created, err)
		}
		var executionCount int
		if err := pool.QueryRow(ctx, `SELECT execution_count FROM component_repo.task_jobs WHERE id=$1`, mustTaskUUID(t, first.TaskJobID)).Scan(&executionCount); err != nil || executionCount != 2 {
			t.Fatalf("logical job execution count = %d error=%v", executionCount, err)
		}
	})

	t.Run("concurrent scheduling creates one logical job execution", func(t *testing.T) {
		resetTaskFixtures(t, pool)
		service := NewService(pool)
		service.WithClock(func() time.Time { return baseTime })
		input := taskFixture(actor, "concurrent-logical-computation", 3, baseTime)
		const callers = 8
		ids := make(chan string, callers)
		var group sync.WaitGroup
		for index := 0; index < callers; index++ {
			group.Add(1)
			go func() {
				defer group.Done()
				queued, _, err := service.Enqueue(ctx, input)
				if err != nil {
					t.Errorf("concurrent schedule: %v", err)
					return
				}
				ids <- queued.ID
			}()
		}
		group.Wait()
		close(ids)
		unique := map[string]struct{}{}
		for id := range ids {
			unique[id] = struct{}{}
		}
		if len(unique) != 1 {
			t.Fatalf("concurrent scheduling created %d executions, want 1", len(unique))
		}
		var jobs, executions int
		if err := pool.QueryRow(ctx, `SELECT (SELECT count(*) FROM component_repo.task_jobs), (SELECT count(*) FROM component_repo.tasks)`).Scan(&jobs, &executions); err != nil {
			t.Fatal(err)
		}
		if jobs != 1 || executions != 1 {
			t.Fatalf("logical scheduling rows = jobs %d executions %d, want 1/1", jobs, executions)
		}
	})

	t.Run("dependencies block claims and propagate terminal failure", func(t *testing.T) {
		resetTaskFixtures(t, pool)
		service := NewService(pool)
		service.WithClock(func() time.Time { return baseTime })
		prerequisite, _, err := service.Enqueue(ctx, taskFixture(actor, "dependency-artifact", 1, baseTime))
		if err != nil {
			t.Fatalf("enqueue prerequisite: %v", err)
		}
		parseInput := taskFixture(actor, "dependency-parse", 3, baseTime)
		parseInput.TaskType = ImportParseType
		parseInput.Payload = json.RawMessage(`{"importId":"50000000-0000-0000-0000-000000000088"}`)
		dependent, _, err := service.Enqueue(ctx, parseInput)
		if err != nil {
			t.Fatalf("enqueue dependent: %v", err)
		}
		if err := db.New(pool).CreateTaskDependency(ctx, db.CreateTaskDependencyParams{
			TaskID: mustTaskUUID(t, dependent.ID), PrerequisiteTaskID: mustTaskUUID(t, prerequisite.ID), OwnerID: actor,
		}); err != nil {
			t.Fatalf("create dependency: %v", err)
		}
		if _, found, err := service.Claim(ctx, "parser", []string{ImportParseType}, time.Minute); err != nil || found {
			t.Fatalf("blocked parse claim = found %v error %v", found, err)
		}
		claimed, found, err := service.Claim(ctx, "artifact", []string{ArtifactVerifyType}, time.Minute)
		if err != nil || !found {
			t.Fatalf("claim prerequisite = found %v error %v", found, err)
		}
		failure := &Failure{Code: "component_repo.hash_mismatch", Params: map[string]any{"artifactId": "fixture"}, Retryable: false}
		if err := service.FinishFailure(ctx, "artifact", claimed, failure, time.Second); err != nil {
			t.Fatalf("fail prerequisite: %v", err)
		}
		blocked, err := service.GetOwned(ctx, actor, dependent.ID)
		if err != nil || blocked.Status != StatusFailed || blocked.Error == nil || blocked.Error.Code != failure.Code {
			t.Fatalf("propagated dependent = %+v error=%v", blocked, err)
		}
	})

	t.Run("outbox supports lease retry and publish", func(t *testing.T) {
		resetTaskFixtures(t, pool)
		current := time.Now().UTC().Add(time.Second)
		service := NewService(pool)
		service.WithClock(func() time.Time { return current })
		if _, _, err := service.Enqueue(ctx, taskFixture(actor, "outbox", 3, current)); err != nil {
			t.Fatalf("enqueue outbox fixture: %v", err)
		}
		event, found, err := service.ClaimOutbox(ctx, "publisher-a", time.Minute)
		if err != nil || !found {
			t.Fatalf("claim outbox = found %v error %v", found, err)
		}
		if err := service.RetryOutbox(ctx, "publisher-a", event.ID, "common.internal_error", nil, time.Minute); err != nil {
			t.Fatalf("retry outbox: %v", err)
		}
		if _, found, err := service.ClaimOutbox(ctx, "publisher-b", time.Minute); err != nil || found {
			t.Fatalf("early outbox claim = found %v error %v", found, err)
		}
		current = current.Add(2 * time.Minute)
		event, found, err = service.ClaimOutbox(ctx, "publisher-b", time.Minute)
		if err != nil || !found || event.Attempts != 2 {
			t.Fatalf("retry outbox claim = %+v found %v error %v", event, found, err)
		}
		if err := service.MarkOutboxPublished(ctx, "publisher-b", event.ID); err != nil {
			t.Fatalf("publish outbox: %v", err)
		}
		if _, found, err := service.ClaimOutbox(ctx, "publisher-c", time.Minute); err != nil || found {
			t.Fatalf("published outbox reclaimed = found %v error %v", found, err)
		}
	})
}

func taskFixture(owner pgtype.UUID, key string, maxAttempts int32, availableAt time.Time) EnqueueInput {
	payload, _ := json.Marshal(map[string]string{"artifactId": "50000000-0000-0000-0000-000000000099"})
	return EnqueueInput{
		OwnerID: owner, TaskType: ArtifactVerifyType, Payload: payload,
		Locale: "en-US", Timezone: "UTC", CreatedBy: owner,
		IdempotencyKey: key, MaxAttempts: maxAttempts, AvailableAt: availableAt,
	}
}

func mustTaskUUID(t *testing.T, value string) pgtype.UUID {
	t.Helper()
	id, err := uuidutil.Parse(value)
	if err != nil {
		t.Fatalf("parse UUID %q: %v", value, err)
	}
	return id
}

func resetTaskFixtures(t *testing.T, pool *pgxpool.Pool) {
	t.Helper()
	if _, err := pool.Exec(context.Background(), "TRUNCATE component_repo.tasks, component_repo.outbox_events RESTART IDENTITY CASCADE"); err != nil {
		t.Fatalf("reset task fixtures: %v", err)
	}
}

func assertTaskCounts(t *testing.T, pool *pgxpool.Pool, tasks, events, outbox int) {
	t.Helper()
	var actualTasks, actualEvents, actualOutbox int
	if err := pool.QueryRow(context.Background(), `
		SELECT (SELECT count(*) FROM component_repo.tasks),
		       (SELECT count(*) FROM component_repo.task_events),
		       (SELECT count(*) FROM component_repo.outbox_events)`).Scan(&actualTasks, &actualEvents, &actualOutbox); err != nil {
		t.Fatalf("count task records: %v", err)
	}
	if actualTasks != tasks || actualEvents != events || actualOutbox != outbox {
		t.Fatalf("counts = tasks %d events %d outbox %d, want %d/%d/%d", actualTasks, actualEvents, actualOutbox, tasks, events, outbox)
	}
}
