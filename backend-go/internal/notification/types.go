package notification

import (
	"errors"
	"time"

	"github.com/jackc/pgx/v5/pgtype"
)

const (
	// BatchSize 是 WATCH-3 冻结的单事务 recipient 上限；提高前必须重新执行 SQL 与容量门禁。
	BatchSize = 250
	// VersionPublishedNotification 与领域事件机器类型一致，不包含最终展示文案。
	VersionPublishedNotification = "component.version.published.v1"
	versionPublishedCode         = "component_repo.notification.version_published"
	versionPublishedUnavailable  = "component_repo.notification.version_published_unavailable"
)

var ErrOwnershipLost = errors.New("notification delivery ownership lost")

// ClaimedDelivery 是 Notification Worker 的 lease fence；EventID + Attempt 唯一标识本次执行权。
type ClaimedDelivery struct {
	EventID     pgtype.UUID
	Attempt     int16
	MaxAttempts int16
	OccurredAt  time.Time
}

// BatchResult 描述一个已提交批次；Completed 只在 cursor 后确认空页时为 true。
type BatchResult struct {
	Recipients   int
	Created      int
	Deduplicated int
	Completed    bool
	OccurredAt   time.Time
}

// Failure 保存稳定机器错误和重试分类；详细数据库异常只进入内部日志。
type Failure struct {
	Code       string
	Retryable  bool
	ErrorClass string
}

func (f *Failure) Error() string {
	if f == nil {
		return "notification delivery failure"
	}
	return f.Code
}

// Backlog 是从 PostgreSQL 权威 Delivery 状态采样的 Gauge 输入。
type Backlog struct {
	PendingEvents         uint64
	OldestPendingAge      time.Duration
	UnresolvedDeadLetters uint64
	OldestDeadLetterAge   time.Duration
}
