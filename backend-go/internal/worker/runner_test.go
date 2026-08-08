package worker

import (
	"context"
	"io"
	"log/slog"
	"sync/atomic"
	"testing"
	"time"
)

type countingPinger struct{ calls atomic.Int32 }

func (p *countingPinger) Ping(context.Context) error {
	p.calls.Add(1)
	return nil
}

func TestRunChecksDatabaseAndStopsWithContext(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	pinger := &countingPinger{}
	done := make(chan error, 1)
	go func() {
		done <- Run(ctx, "worker-test", 5*time.Millisecond, pinger, nil, slog.New(slog.NewTextHandler(io.Discard, nil)))
	}()

	deadline := time.After(time.Second)
	for pinger.calls.Load() == 0 {
		select {
		case <-deadline:
			t.Fatal("worker never checked database")
		default:
			time.Sleep(time.Millisecond)
		}
	}
	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("run returned error: %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("worker did not stop")
	}
}
