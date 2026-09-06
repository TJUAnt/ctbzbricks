package component

import (
	"context"
	"testing"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
)

func TestRelationshipCleanupTaskRejectsInvalidSnapshot(t *testing.T) {
	t.Parallel()
	handler := NewRelationshipCleanupTaskHandler(nil)
	for _, payload := range [][]byte{
		[]byte(`{}`),
		[]byte(`{"componentId":"not-a-uuid","endedSeq":1,"endedAt":"2026-09-04T00:00:00Z","endedReason":"component_deleted"}`),
		[]byte(`{"componentId":"20000000-0000-0000-0000-000000000001","endedSeq":1,"endedAt":"2026-09-04T00:00:00Z","endedReason":"unknown"}`),
		[]byte(`{"componentId":"20000000-0000-0000-0000-000000000001","endedSeq":1,"endedAt":"2026-09-04T00:00:00Z","endedReason":"component_deleted","extra":true}`),
	} {
		_, err := handler.Handle(context.Background(), task.ClaimedTask{Payload: payload})
		failure, ok := err.(*task.Failure)
		if !ok || failure.Retryable || failure.Code != "common.internal_error" {
			t.Fatalf("payload %s failure = %#v", payload, err)
		}
	}
}
