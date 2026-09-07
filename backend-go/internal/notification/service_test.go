package notification

import (
	"testing"
	"time"
)

func TestRetryDelayUsesFrozenScheduleAndCap(t *testing.T) {
	want := map[int16]time.Duration{
		0: 5 * time.Second, 1: 5 * time.Second, 2: 30 * time.Second,
		3: 2 * time.Minute, 4: 10 * time.Minute, 5: 30 * time.Minute,
		8: 30 * time.Minute,
	}
	for attempt, expected := range want {
		if actual := retryDelay(attempt); actual != expected {
			t.Fatalf("attempt %d delay = %s, want %s", attempt, actual, expected)
		}
	}
}

func TestValidateRunnerOptionsKeepsNotificationWorkerBounded(t *testing.T) {
	valid := RunnerOptions{
		PollInterval: 500 * time.Millisecond, LeaseDuration: time.Minute,
		HeartbeatInterval: 20 * time.Second, HealthCheckInterval: 30 * time.Second,
		MetricsRefreshInterval: 15 * time.Second, Concurrency: 4,
	}
	if err := validateRunnerOptions(valid); err != nil {
		t.Fatalf("valid options rejected: %v", err)
	}
	invalidConcurrency := valid
	invalidConcurrency.Concurrency = 5
	if err := validateRunnerOptions(invalidConcurrency); err == nil {
		t.Fatal("notification concurrency above frozen maximum was accepted")
	}
	invalidHeartbeat := valid
	invalidHeartbeat.HeartbeatInterval = 30 * time.Second
	if err := validateRunnerOptions(invalidHeartbeat); err == nil {
		t.Fatal("unsafe heartbeat/lease ratio was accepted")
	}
}

func TestBatchSizeRemainsFrozen(t *testing.T) {
	if BatchSize != 250 {
		t.Fatalf("batch size = %d, want 250", BatchSize)
	}
}
