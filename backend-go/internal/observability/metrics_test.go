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

func TestMetricsExposeDomainEventWatchMutationAndDynamicFeedContracts(t *testing.T) {
	registry := NewRegistry()
	registry.RecordComponentDomainEvent(ComponentVersionPublishedEvent, DomainEventCommitted)
	registry.RecordComponentWatchMutation(ComponentWatchActionWatch, ComponentWatchMutationSucceeded)
	registry.RecordComponentWatchFeed(ComponentWatchFeedSucceeded, 25*time.Millisecond)
	registry.RecordComponentWatchFeed("dynamic-result", time.Second)
	feedSucceeded, feedFailed := registry.ComponentWatchFeedCounts()
	if feedSucceeded != 1 || feedFailed != 0 {
		t.Fatalf("Watch Feed counts = succeeded %d failed %d", feedSucceeded, feedFailed)
	}

	response := httptest.NewRecorder()
	registry.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/metrics", nil))
	body := response.Body.String()
	for _, expected := range []string{
		"# TYPE component_domain_event_total counter",
		`component_domain_event_total{event_type="component.version.published.v1",result="committed"} 1`,
		"# TYPE component_watch_mutation_total counter",
		`component_watch_mutation_total{action="watch",result="succeeded"} 1`,
		"# TYPE component_watch_feed_requests_total counter",
		`component_watch_feed_requests_total{result="succeeded"} 1`,
		"# TYPE component_watch_feed_duration_seconds histogram",
		`component_watch_feed_duration_seconds_count 1`,
	} {
		if !strings.Contains(body, expected) {
			t.Fatalf("metrics body missing %q: %s", expected, body)
		}
	}
	if strings.Contains(body, "component_notification_") {
		t.Fatalf("dynamic Feed must not expose obsolete fan-out metrics: %s", body)
	}
}
