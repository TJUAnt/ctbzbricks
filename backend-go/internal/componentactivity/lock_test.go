package componentactivity

import (
	"testing"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
)

func TestLockKeyIsStableAndComponentScoped(t *testing.T) {
	first, err := uuidutil.Parse("22000000-0000-0000-0000-000000000001")
	if err != nil {
		t.Fatalf("parse first UUID: %v", err)
	}
	second, err := uuidutil.Parse("22000000-0000-0000-0000-000000000002")
	if err != nil {
		t.Fatalf("parse second UUID: %v", err)
	}
	if LockKey(first) != LockKey(first) {
		t.Fatal("same Component produced different advisory lock keys")
	}
	if LockKey(first) == LockKey(second) {
		t.Fatal("fixture Components unexpectedly produced the same advisory lock key")
	}
}
