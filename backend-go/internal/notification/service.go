package notification

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/observability"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Service 封装 Component 通知专属 Delivery 协议；它不读取或修改通用 Task/outbox，也不承担 HTTP API。
type Service struct {
	pool    *pgxpool.Pool
	q       *db.Queries
	metrics *observability.Registry
	now     func() time.Time
}

// NewService 创建由 PostgreSQL 持久状态驱动的通知投递服务。
func NewService(pool *pgxpool.Pool, metrics *observability.Registry) *Service {
	return &Service{pool: pool, q: db.New(pool), metrics: metrics, now: time.Now}
}

// Claim 通过 SKIP LOCKED 领取一条可执行 Delivery，并把 attempts 作为 fencing token 返回。
func (s *Service) Claim(ctx context.Context, workerID string, leaseDuration time.Duration) (ClaimedDelivery, bool, error) {
	now := s.now().UTC()
	row, err := s.q.ClaimComponentEventDelivery(ctx, db.ClaimComponentEventDeliveryParams{
		LeaseOwner: stringPointer(workerID), LeaseExpiresAt: timestamp(now.Add(leaseDuration)), ClaimedAt: timestamp(now),
	})
	if errors.Is(err, pgx.ErrNoRows) {
		return ClaimedDelivery{}, false, nil
	}
	if err != nil {
		return ClaimedDelivery{}, false, err
	}
	return ClaimedDelivery{EventID: row.EventID, Attempt: row.Attempts, MaxAttempts: row.MaxAttempts, OccurredAt: row.OccurredAt.Time}, true, nil
}

// Heartbeat 只延长当前 owner/attempt 的未过期 lease；返回 false 表示执行权已经丢失。
func (s *Service) Heartbeat(ctx context.Context, workerID string, claimed ClaimedDelivery, leaseDuration time.Duration) (bool, error) {
	now := s.now().UTC()
	rows, err := s.q.HeartbeatComponentEventDelivery(ctx, db.HeartbeatComponentEventDeliveryParams{
		LeaseExpiresAt: timestamp(now.Add(leaseDuration)), HeartbeatAt: timestamp(now), EventID: claimed.EventID,
		LeaseOwner: stringPointer(workerID), ClaimedAttempt: claimed.Attempt,
	})
	return rows == 1, err
}

// ProcessNextBatch 在一个短事务中固定 event-time recipient 页面、批量幂等写通知并推进游标。
// 只有下一页为空时才完成 Delivery，因此 crash 后从已提交 cursor 恢复不会漏发或重复展示。
func (s *Service) ProcessNextBatch(ctx context.Context, workerID string, claimed ClaimedDelivery) (BatchResult, error) {
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return BatchResult{}, err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	q := db.New(tx)
	now := s.now().UTC()
	delivery, err := q.GetClaimedComponentEventDelivery(ctx, db.GetClaimedComponentEventDeliveryParams{
		EventID: claimed.EventID, LeaseOwner: stringPointer(workerID), ClaimedAttempt: claimed.Attempt,
		CheckedAt: timestamp(now),
	})
	if errors.Is(err, pgx.ErrNoRows) {
		return BatchResult{}, ErrOwnershipLost
	}
	if err != nil {
		return BatchResult{}, err
	}
	if delivery.EventType != VersionPublishedNotification {
		return BatchResult{}, &Failure{
			Code: "notification.delivery.unsupported_event", Retryable: false,
			ErrorClass: observability.ComponentNotificationDeadLetterPermanentData,
		}
	}
	recipients, err := q.ListEligibleComponentWatchRecipients(ctx, db.ListEligibleComponentWatchRecipientsParams{
		ComponentID: delivery.ComponentID, EventSeq: delivery.EventSeq,
		CursorActorID: delivery.CursorActorID, CursorPeriodID: delivery.CursorPeriodID, BatchSize: BatchSize,
	})
	if err != nil {
		return BatchResult{}, err
	}
	result := BatchResult{Recipients: len(recipients), OccurredAt: delivery.OccurredAt.Time}
	if len(recipients) == 0 {
		rows, completeErr := q.CompleteComponentEventDelivery(ctx, db.CompleteComponentEventDeliveryParams{
			CompletedAt: timestamp(now), EventID: claimed.EventID,
			LeaseOwner: stringPointer(workerID), ClaimedAttempt: claimed.Attempt,
		})
		if completeErr != nil {
			return BatchResult{}, completeErr
		}
		if rows != 1 {
			return BatchResult{}, ErrOwnershipLost
		}
		if err := tx.Commit(ctx); err != nil {
			return BatchResult{}, err
		}
		result.Completed = true
		s.metrics.RecordComponentNotificationFanout(
			VersionPublishedNotification, observability.ComponentNotificationFanoutCompleted, now.Sub(delivery.OccurredAt.Time),
		)
		s.metrics.RecordComponentNotificationFanoutAttempt(observability.ComponentNotificationAttemptCommitted)
		return result, nil
	}

	params, err := json.Marshal(map[string]string{
		"componentId":        uuidutil.String(delivery.ComponentID),
		"componentVersionId": uuidutil.String(delivery.ComponentVersionID),
	})
	if err != nil {
		return BatchResult{}, &Failure{
			Code: "notification.delivery.invalid_params", Retryable: false,
			ErrorClass: observability.ComponentNotificationDeadLetterInvariantViolation,
		}
	}
	insertParams := db.InsertComponentVersionNotificationsParams{
		EventID: delivery.EventID, NotificationCode: versionPublishedCode, NotificationParams: params,
		ComponentID: delivery.ComponentID, ComponentVersionID: delivery.ComponentVersionID, Tombstone: delivery.Tombstone,
		NotificationIds: make([]pgtype.UUID, 0, len(recipients)), RecipientIds: make([]pgtype.UUID, 0, len(recipients)),
		SourceWatchPeriodIds: make([]int64, 0, len(recipients)), Locales: make([]string, 0, len(recipients)),
		Timezones: make([]string, 0, len(recipients)), ResourceCatalogVersions: make([]string, 0, len(recipients)),
	}
	if delivery.Tombstone {
		insertParams.NotificationCode = versionPublishedUnavailable
	}
	for _, recipient := range recipients {
		notificationID, idErr := uuidutil.New()
		if idErr != nil {
			return BatchResult{}, fmt.Errorf("create notification id: %w", idErr)
		}
		insertParams.NotificationIds = append(insertParams.NotificationIds, notificationID)
		insertParams.RecipientIds = append(insertParams.RecipientIds, recipient.ActorID)
		insertParams.SourceWatchPeriodIds = append(insertParams.SourceWatchPeriodIds, recipient.PeriodID)
		insertParams.Locales = append(insertParams.Locales, recipient.NotificationLocale)
		insertParams.Timezones = append(insertParams.Timezones, recipient.NotificationTimezone)
		insertParams.ResourceCatalogVersions = append(insertParams.ResourceCatalogVersions, recipient.NotificationCatalogVersion)
	}
	created, err := q.InsertComponentVersionNotifications(ctx, insertParams)
	if err != nil {
		return BatchResult{}, err
	}
	last := recipients[len(recipients)-1]
	rows, err := q.AdvanceComponentEventDeliveryCursor(ctx, db.AdvanceComponentEventDeliveryCursorParams{
		CursorActorID: last.ActorID, CursorPeriodID: int64Pointer(last.PeriodID), UpdatedAt: timestamp(now),
		EventID: claimed.EventID, LeaseOwner: stringPointer(workerID), ClaimedAttempt: claimed.Attempt,
	})
	if err != nil {
		return BatchResult{}, err
	}
	if rows != 1 {
		return BatchResult{}, ErrOwnershipLost
	}
	if err := tx.Commit(ctx); err != nil {
		return BatchResult{}, err
	}
	result.Created = len(created)
	result.Deduplicated = len(recipients) - len(created)
	s.metrics.ObserveComponentNotificationBatch(uint64(len(recipients)))
	s.metrics.AddComponentNotificationRecipients(observability.ComponentNotificationRecipientCreated, uint64(result.Created))
	s.metrics.AddComponentNotificationRecipients(observability.ComponentNotificationRecipientDeduplicated, uint64(result.Deduplicated))
	s.metrics.RecordComponentNotificationFanoutAttempt(observability.ComponentNotificationAttemptCommitted)
	return result, nil
}

// FinishFailure 在仍持有 lease 时按冻结退避进入 retry_wait，或将确定性/耗尽错误持久化为 dead letter。
func (s *Service) FinishFailure(ctx context.Context, workerID string, claimed ClaimedDelivery, failure *Failure) error {
	if failure == nil {
		failure = &Failure{Code: "common.internal_error", Retryable: true}
	}
	if failure.Code == "" {
		failure.Code = "common.internal_error"
	}
	now := s.now().UTC()
	params := []byte(`{}`)
	if failure.Retryable && claimed.Attempt < claimed.MaxAttempts {
		rows, err := s.q.RetryComponentEventDelivery(ctx, db.RetryComponentEventDeliveryParams{
			AvailableAt: timestamp(now.Add(retryDelay(claimed.Attempt))), ErrorCode: stringPointer(failure.Code),
			ErrorParams: params, FailedAt: timestamp(now), EventID: claimed.EventID,
			LeaseOwner: stringPointer(workerID), ClaimedAttempt: claimed.Attempt,
		})
		if err != nil {
			return err
		}
		if rows != 1 {
			return ErrOwnershipLost
		}
		s.metrics.RecordComponentNotificationFanoutAttempt(observability.ComponentNotificationAttemptRetryScheduled)
		return nil
	}
	errorClass := failure.ErrorClass
	if errorClass == "" {
		errorClass = observability.ComponentNotificationDeadLetterRetryExhausted
	}
	rows, err := s.q.DeadLetterComponentEventDelivery(ctx, db.DeadLetterComponentEventDeliveryParams{
		ErrorCode: stringPointer(failure.Code), ErrorParams: params, FailedAt: timestamp(now), EventID: claimed.EventID,
		LeaseOwner: stringPointer(workerID), ClaimedAttempt: claimed.Attempt,
	})
	if err != nil {
		return err
	}
	if rows != 1 {
		return ErrOwnershipLost
	}
	s.metrics.RecordComponentNotificationFanoutAttempt(observability.ComponentNotificationAttemptDeadLettered)
	s.metrics.RecordComponentNotificationDeadLetter(errorClass)
	s.metrics.RecordComponentNotificationFanout(
		VersionPublishedNotification, observability.ComponentNotificationFanoutDeadLettered, now.Sub(claimed.OccurredAt),
	)
	return nil
}

// RecoverExpired 每次回收一条过期 lease；cursor 不回退，下一次领取会从最后已提交页面继续。
func (s *Service) RecoverExpired(ctx context.Context) (bool, error) {
	now := s.now().UTC()
	row, err := s.q.RecoverExpiredComponentEventDelivery(ctx, timestamp(now))
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if row.Status == "dead_lettered" {
		s.metrics.RecordComponentNotificationFanoutAttempt(observability.ComponentNotificationAttemptDeadLettered)
		s.metrics.RecordComponentNotificationDeadLetter(observability.ComponentNotificationDeadLetterRetryExhausted)
		s.metrics.RecordComponentNotificationFanout(
			VersionPublishedNotification, observability.ComponentNotificationFanoutDeadLettered, now.Sub(row.OccurredAt.Time),
		)
	} else {
		s.metrics.RecordComponentNotificationFanoutAttempt(observability.ComponentNotificationAttemptRetryScheduled)
	}
	return true, nil
}

// SampleBacklog 读取非终态与未确认 dead letter 的数据库权威数量和年龄。
func (s *Service) SampleBacklog(ctx context.Context) (Backlog, error) {
	row, err := s.q.GetComponentNotificationBacklog(ctx)
	if err != nil {
		return Backlog{}, err
	}
	return Backlog{
		PendingEvents: uint64(row.PendingEvents), OldestPendingAge: secondsDuration(row.OldestPendingSeconds),
		UnresolvedDeadLetters: uint64(row.UnresolvedDeadLetters), OldestDeadLetterAge: secondsDuration(row.OldestDeadLetterSeconds),
	}, nil
}

func retryDelay(attempt int16) time.Duration {
	delays := [...]time.Duration{5 * time.Second, 30 * time.Second, 2 * time.Minute, 10 * time.Minute, 30 * time.Minute}
	index := int(attempt) - 1
	if index < 0 {
		index = 0
	}
	if index >= len(delays) {
		return 30 * time.Minute
	}
	return delays[index]
}

func secondsDuration(value float64) time.Duration {
	if value <= 0 {
		return 0
	}
	return time.Duration(value * float64(time.Second))
}

func timestamp(value time.Time) pgtype.Timestamptz {
	return pgtype.Timestamptz{Time: value, Valid: true}
}

func stringPointer(value string) *string { return &value }
func int64Pointer(value int64) *int64    { return &value }
