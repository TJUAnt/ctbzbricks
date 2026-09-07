package observability

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestComponentDomainEventMetricIsBoundedAndConcurrentSafe(t *testing.T) {
	registry := NewRegistry()
	var wait sync.WaitGroup
	for range 100 {
		wait.Add(1)
		go func() {
			defer wait.Done()
			registry.RecordComponentDomainEvent(ComponentVersionPublishedEvent, DomainEventCommitted)
		}()
	}
	wait.Wait()
	registry.RecordComponentDomainEvent(ComponentVersionPublishedEvent, DomainEventFailed)
	registry.RecordComponentDomainEvent("user-controlled-event", DomainEventCommitted)
	registry.RecordComponentDomainEvent(ComponentVersionPublishedEvent, "user-controlled-result")

	committed, failed := registry.ComponentDomainEventCounts()
	if committed != 100 || failed != 1 {
		t.Fatalf("domain event counts = committed %d failed %d", committed, failed)
	}
}

func TestComponentWatchMutationMetricAcceptsOnlyFixedLabels(t *testing.T) {
	registry := NewRegistry()
	registry.RecordComponentWatchMutation(ComponentWatchActionWatch, ComponentWatchMutationSucceeded)
	registry.RecordComponentWatchMutation(ComponentWatchActionWatch, ComponentWatchMutationFailed)
	registry.RecordComponentWatchMutation(ComponentWatchActionUnwatch, ComponentWatchMutationSucceeded)
	registry.RecordComponentWatchMutation(ComponentWatchActionUnwatch, ComponentWatchMutationFailed)
	registry.RecordComponentWatchMutation("component-id", ComponentWatchMutationSucceeded)
	registry.RecordComponentWatchMutation(ComponentWatchActionWatch, "dynamic-error")

	watchSucceeded, watchFailed, unwatchSucceeded, unwatchFailed := registry.ComponentWatchMutationCounts()
	if watchSucceeded != 1 || watchFailed != 1 || unwatchSucceeded != 1 || unwatchFailed != 1 {
		t.Fatalf("watch mutation counts = %d %d %d %d", watchSucceeded, watchFailed, unwatchSucceeded, unwatchFailed)
	}
}

func TestComponentNotificationFanoutMetricsAreBoundedAndConcurrentSafe(t *testing.T) {
	registry := NewRegistry()
	var wait sync.WaitGroup
	for range 100 {
		wait.Add(1)
		go func() {
			defer wait.Done()
			registry.RecordComponentNotificationFanout(
				ComponentVersionPublishedEvent,
				ComponentNotificationFanoutCompleted,
				10*time.Second,
			)
		}()
	}
	wait.Wait()
	registry.RecordComponentNotificationFanout(ComponentVersionPublishedEvent, ComponentNotificationFanoutDeadLettered, 10*time.Minute)
	registry.RecordComponentNotificationFanout("dynamic-event", ComponentNotificationFanoutCompleted, time.Second)
	registry.RecordComponentNotificationFanout(ComponentVersionPublishedEvent, "dynamic-result", time.Second)
	registry.RecordComponentNotificationFanout(ComponentVersionPublishedEvent, ComponentNotificationFanoutCompleted, -time.Second)

	registry.RecordComponentNotificationFanoutAttempt(ComponentNotificationAttemptCommitted)
	registry.RecordComponentNotificationFanoutAttempt(ComponentNotificationAttemptRetryScheduled)
	registry.RecordComponentNotificationFanoutAttempt(ComponentNotificationAttemptDeadLettered)
	registry.RecordComponentNotificationFanoutAttempt("dynamic-result")
	registry.AddComponentNotificationRecipients(ComponentNotificationRecipientCreated, 200)
	registry.AddComponentNotificationRecipients(ComponentNotificationRecipientDeduplicated, 3)
	registry.AddComponentNotificationRecipients(ComponentNotificationRecipientSkippedIneligible, 2)
	registry.AddComponentNotificationRecipients("actor-id", 99)
	registry.RecordComponentNotificationDeadLetter(ComponentNotificationDeadLetterRetryExhausted)
	registry.RecordComponentNotificationDeadLetter(ComponentNotificationDeadLetterPermanentData)
	registry.RecordComponentNotificationDeadLetter(ComponentNotificationDeadLetterInvariantViolation)
	registry.RecordComponentNotificationDeadLetter("database-error-text")
	registry.ObserveComponentNotificationBatch(250)
	registry.ObserveComponentNotificationBatch(0)
	registry.ObserveComponentNotificationBatch(251)
	registry.SetComponentNotificationBacklog(7, 42*time.Second)
	registry.SetComponentNotificationDeadLetterBacklog(2, 25*time.Hour)

	recorder := httptest.NewRecorder()
	registry.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/metrics", nil))
	body := recorder.Body.String()
	for _, expected := range []string{
		`component_notification_fanout_total{event_type="component.version.published.v1",result="completed"} 101`,
		`component_notification_fanout_total{event_type="component.version.published.v1",result="dead_lettered"} 1`,
		`component_notification_delivery_attempts_total{result="committed"} 1`,
		`component_notification_delivery_attempts_total{result="retry_scheduled"} 1`,
		`component_notification_recipient_total{result="created"} 200`,
		`component_notification_dead_letter_total{error_class="invariant_violation"} 1`,
		`component_notification_fanout_lag_seconds_bucket{le="15"} 100`,
		`component_notification_fanout_lag_seconds_bucket{le="+Inf"} 101`,
		`component_notification_batch_size_bucket{le="250"} 1`,
		`component_notification_batch_size_count 1`,
		`component_notification_backlog_events 7`,
		`component_notification_oldest_pending_seconds 42.000000`,
		`component_notification_unresolved_dead_letters 2`,
		`component_notification_oldest_dead_letter_seconds 90000.000000`,
	} {
		if !strings.Contains(body, expected) {
			t.Fatalf("fan-out metrics body missing %q: %s", expected, body)
		}
	}
	for _, forbidden := range []string{"dynamic-event", "dynamic-result", "actor-id", "database-error-text"} {
		if strings.Contains(body, forbidden) {
			t.Fatalf("fan-out metrics exposed dynamic label %q: %s", forbidden, body)
		}
	}
}

func TestMetricsHandlerUsesPrometheusTextWithoutDynamicLabels(t *testing.T) {
	registry := NewRegistry()
	registry.RecordComponentDomainEvent(ComponentVersionPublishedEvent, DomainEventCommitted)
	recorder := httptest.NewRecorder()
	registry.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/metrics", nil))

	if recorder.Code != http.StatusOK || recorder.Header().Get("Content-Type") != "text/plain; version=0.0.4; charset=utf-8" {
		t.Fatalf("metrics response = %d %q", recorder.Code, recorder.Header().Get("Content-Type"))
	}
	body := recorder.Body.String()
	for _, expected := range []string{
		"# TYPE component_domain_event_total counter",
		`component_domain_event_total{event_type="component.version.published.v1",result="committed"} 1`,
		`component_domain_event_total{event_type="component.version.published.v1",result="failed"} 0`,
		"# TYPE component_watch_mutation_total counter",
		`component_watch_mutation_total{action="watch",result="succeeded"} 0`,
		`component_watch_mutation_total{action="watch",result="failed"} 0`,
		`component_watch_mutation_total{action="unwatch",result="succeeded"} 0`,
		`component_watch_mutation_total{action="unwatch",result="failed"} 0`,
		`component_notification_fanout_total{event_type="component.version.published.v1",result="completed"} 0`,
		`component_notification_delivery_attempts_total{result="retry_scheduled"} 0`,
		`component_notification_recipient_total{result="created"} 0`,
		`component_notification_dead_letter_total{error_class="retry_exhausted"} 0`,
		`component_notification_fanout_lag_seconds_count 0`,
		`component_notification_batch_size_count 0`,
		`component_notification_backlog_events 0`,
		`component_notification_oldest_pending_seconds 0.000000`,
		`component_notification_unresolved_dead_letters 0`,
		`component_notification_oldest_dead_letter_seconds 0.000000`,
	} {
		if !strings.Contains(body, expected) {
			t.Fatalf("metrics body missing %q: %s", expected, body)
		}
	}
}
