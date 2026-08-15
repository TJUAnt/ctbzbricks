//go:build integration

package worker

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"os"
	"sync/atomic"
	"testing"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5/pgxpool"
)

type integrationHandler struct{ calls atomic.Int32 }

func (h *integrationHandler) Handle(_ context.Context, claimed task.ClaimedTask) (task.Result, error) {
	h.calls.Add(1)
	result, _ := json.Marshal(map[string]any{
		"locale": claimed.Locale, "timezone": claimed.Timezone, "attempt": claimed.Attempt,
	})
	return task.Result{Payload: result}, nil
}

func TestRunnerClaimsAndCompletesDurableTask(t *testing.T) {
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
	if _, err := pool.Exec(ctx, `TRUNCATE component_repo.tasks, component_repo.outbox_events RESTART IDENTITY CASCADE`); err != nil {
		t.Fatalf("reset worker fixtures: %v", err)
	}
	actor, _ := uuidutil.Parse("51000000-0000-0000-0000-000000000001")
	queue := task.NewService(pool)
	created, _, err := queue.Enqueue(ctx, task.EnqueueInput{
		OwnerID: actor, TaskType: "component.validate", Payload: json.RawMessage(`{"candidateId":"fixture"}`),
		Locale: "zh-CN", Timezone: "Asia/Shanghai", CreatedBy: actor,
		IdempotencyKey: "runner-integration", MaxAttempts: 3, AvailableAt: time.Now().UTC(),
	})
	if err != nil {
		t.Fatalf("enqueue runner fixture: %v", err)
	}

	runCtx, cancel := context.WithCancel(ctx)
	handler := &integrationHandler{}
	done := make(chan error, 1)
	go func() {
		done <- Run(runCtx, "integration-worker", Options{
			PollInterval: 5 * time.Millisecond, LeaseDuration: 200 * time.Millisecond,
			HeartbeatInterval: 25 * time.Millisecond, RetryDelay: 10 * time.Millisecond,
			MaintenanceInterval: 100 * time.Millisecond, Concurrency: 2,
		}, pool, nil, queue, map[string]task.Handler{"component.validate": handler},
			slog.New(slog.NewTextHandler(io.Discard, nil)))
	}()

	deadline := time.Now().Add(2 * time.Second)
	for {
		view, err := queue.GetOwned(ctx, actor, created.ID)
		if err != nil {
			t.Fatalf("read runner task: %v", err)
		}
		if view.Status == task.StatusSucceeded {
			if view.Attempts != 1 || view.Locale != "zh-CN" || view.Timezone != "Asia/Shanghai" {
				t.Fatalf("completed runner task = %+v", view)
			}
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("runner task did not finish: %+v", view)
		}
		time.Sleep(10 * time.Millisecond)
	}
	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("runner stopped with error: %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("runner did not stop")
	}
	if handler.calls.Load() != 1 {
		t.Fatalf("handler calls = %d, want 1", handler.calls.Load())
	}
}
