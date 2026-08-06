package requestmeta

import (
	"crypto/rand"
	"encoding/hex"
	"regexp"
	"strconv"
	"sync/atomic"
	"time"

	"github.com/gin-gonic/gin"
)

const (
	TraceIDHeader = "X-Trace-Id"
	TraceIDKey    = "traceId"
)

var (
	validTraceID = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`)
	fallbackID   atomic.Uint64
)

func NewTraceID() string {
	buffer := make([]byte, 16)
	if _, err := rand.Read(buffer); err == nil {
		return "req_" + hex.EncodeToString(buffer)
	}
	return "req_" + strconv.FormatInt(time.Now().UTC().UnixNano(), 36) + "_" + strconv.FormatUint(fallbackID.Add(1), 36)
}

func ResolveTraceID(candidate string) string {
	if validTraceID.MatchString(candidate) {
		return candidate
	}
	return NewTraceID()
}

func FromGin(c *gin.Context) string {
	if value, ok := c.Get(TraceIDKey); ok {
		if traceID, ok := value.(string); ok && traceID != "" {
			return traceID
		}
	}
	traceID := NewTraceID()
	c.Set(TraceIDKey, traceID)
	return traceID
}
