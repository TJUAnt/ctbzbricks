package observability

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
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
	} {
		if !strings.Contains(body, expected) {
			t.Fatalf("metrics body missing %q: %s", expected, body)
		}
	}
}
