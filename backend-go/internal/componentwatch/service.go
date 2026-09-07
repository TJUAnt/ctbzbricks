package componentwatch

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"net/http"
	"regexp"
	"strings"
	"time"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/componentactivity"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/observability"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	defaultListLimit                  = 20
	maxListLimit                      = 100
	defaultNotificationLocale         = "zh-CN"
	defaultNotificationTimezone       = "UTC"
	defaultNotificationCatalogVersion = "frontend-2026.09.06.1"
)

var errRetryWatchTransaction = errors.New("retry concurrent watch transaction")
var catalogVersionPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`)

// Service 管理当前 actor 的 Watch 偏好与只读列表；它不负责发布事件或通知投递。
type Service struct {
	pool    *pgxpool.Pool
	q       *db.Queries
	metrics *observability.Registry
}

// NewService 创建使用 PostgreSQL 权威关系数据的 Watch 应用服务。
func NewService(pool *pgxpool.Pool) *Service {
	return &Service{pool: pool, q: db.New(pool)}
}

// WithMetrics 为 Watch mutation 接入进程级低基数指标；未配置时业务行为保持不变。
func (s *Service) WithMetrics(metrics *observability.Registry) *Service {
	s.metrics = metrics
	return s
}

// Watch 为内部调用提供默认通知上下文；HTTP 入口必须使用 WatchWithContext 保存浏览器的冻结上下文。
func (s *Service) Watch(ctx context.Context, actor pgtype.UUID, componentID, level string) (result Watch, err error) {
	return s.WatchWithContext(ctx, actor, componentID, level, NotificationContext{
		Locale: defaultNotificationLocale, Timezone: defaultNotificationTimezone,
		CatalogVersion: defaultNotificationCatalogVersion,
	})
}

// WatchWithContext 幂等建立 releases_only 订阅。资格检查、上下文冻结与写入位于同一可重试串行化事务；
// 重复 PUT 保留原 period 及原上下文，避免改变既有事件时点和未来通知审计语义。
func (s *Service) WatchWithContext(
	ctx context.Context,
	actor pgtype.UUID,
	componentID, level string,
	notificationContext NotificationContext,
) (result Watch, err error) {
	defer func() {
		s.recordMutation(observability.ComponentWatchActionWatch, err)
	}()
	if level != ReleasesOnlyLevel {
		return Watch{}, apierror.New("component_repo.watch_level_unsupported", http.StatusUnprocessableEntity, map[string]any{"level": level})
	}
	id, err := parseID(componentID, "componentId")
	if err != nil {
		return Watch{}, err
	}
	notificationContext, err = normalizeNotificationContext(notificationContext)
	if err != nil {
		return Watch{}, err
	}
	return withTx(ctx, s.pool, func(q *db.Queries) (Watch, error) {
		// 共享锁允许同一 Component 的偏好变更并发，但会与 Publish/删除的独占生命周期边界互斥。
		if err := q.AcquireSharedComponentActivityLock(ctx, componentactivity.LockKey(id)); err != nil {
			return Watch{}, err
		}
		target, err := q.GetComponentWatchTarget(ctx, db.GetComponentWatchTargetParams{ActorID: actor, ComponentID: id})
		if errors.Is(err, pgx.ErrNoRows) {
			return Watch{}, apierror.New("component_repo.component_not_found", http.StatusNotFound, map[string]any{"componentId": componentID})
		}
		if err != nil {
			return Watch{}, err
		}
		if uuidutil.Equal(target.OwnerID, actor) {
			return Watch{}, apierror.New("component_repo.watch_own_component_forbidden", http.StatusConflict, nil)
		}
		// 已 active 的相同级别是纯幂等读路径；保留原 watched_at，避免重复 PUT 改变事件时点语义。
		if target.WatchPeriodID != nil && target.WatchLevel != nil &&
			*target.WatchLevel == level && target.WatchedAt.Valid {
			return Watch{ComponentID: componentID, Watching: true, Level: level, WatchedAt: target.WatchedAt.Time}, nil
		}
		if target.Status != "active" || !target.PublicVersionAvailable {
			return Watch{}, apierror.New("component_repo.watch_component_unavailable", http.StatusConflict, nil)
		}
		row, err := q.CreateActiveComponentWatchPeriod(ctx, db.CreateActiveComponentWatchPeriodParams{
			ActorID: actor, ComponentID: id, WatchLevel: level,
			NotificationLocale: notificationContext.Locale, NotificationTimezone: notificationContext.Timezone,
			NotificationCatalogVersion: notificationContext.CatalogVersion,
		})
		if errors.Is(err, pgx.ErrNoRows) {
			// 并发请求已先创建 active period；回滚当前快照并重试，下一轮按重复 Watch 返回权威周期。
			return Watch{}, errRetryWatchTransaction
		}
		if err != nil {
			return Watch{}, err
		}
		return Watch{
			ComponentID: uuidutil.String(row.ComponentID), Watching: true,
			Level: row.WatchLevel, WatchedAt: row.WatchedAt.Time,
		}, nil
	})
}

func normalizeNotificationContext(value NotificationContext) (NotificationContext, error) {
	locale := displayLocale(value.Locale)
	normalizedInput := strings.ToLower(strings.TrimSpace(strings.ReplaceAll(value.Locale, "_", "-")))
	if normalizedInput == "" || (normalizedInput != "zh" && normalizedInput != "zh-cn" &&
		normalizedInput != "zh-hans" && !strings.HasPrefix(normalizedInput, "zh-hans-") && normalizedInput != "en" &&
		normalizedInput != "en-us" && !strings.HasPrefix(normalizedInput, "en-")) {
		return NotificationContext{}, validationError("locale")
	}
	zone := strings.TrimSpace(value.Timezone)
	if len(zone) > 128 {
		return NotificationContext{}, validationError("timezone")
	}
	if _, err := time.LoadLocation(zone); err != nil {
		return NotificationContext{}, validationError("timezone")
	}
	catalogVersion := strings.TrimSpace(value.CatalogVersion)
	if !catalogVersionPattern.MatchString(catalogVersion) {
		return NotificationContext{}, validationError("catalogVersion")
	}
	return NotificationContext{Locale: locale, Timezone: zone, CatalogVersion: catalogVersion}, nil
}

// Unwatch 在共享 Component activity lock 下幂等关闭当前订阅有效区间；Component 删除后由清理任务写统一边界，
// 因此延迟到达的 Unwatch 只返回成功，不会抢写或重开历史 period。
func (s *Service) Unwatch(ctx context.Context, actor pgtype.UUID, componentID string) (err error) {
	defer func() {
		s.recordMutation(observability.ComponentWatchActionUnwatch, err)
	}()
	id, err := parseID(componentID, "componentId")
	if err != nil {
		return err
	}
	_, err = withTx(ctx, s.pool, func(q *db.Queries) (struct{}, error) {
		if lockErr := q.AcquireSharedComponentActivityLock(ctx, componentactivity.LockKey(id)); lockErr != nil {
			return struct{}{}, lockErr
		}
		_, closeErr := q.CloseActiveComponentWatchPeriod(ctx, db.CloseActiveComponentWatchPeriodParams{ActorID: actor, ComponentID: id})
		return struct{}{}, closeErr
	})
	return err
}

// recordMutation 在全部事务重试结束后只计一次；幂等重复请求属于成功结果。
func (s *Service) recordMutation(action string, err error) {
	result := observability.ComponentWatchMutationSucceeded
	if err != nil {
		result = observability.ComponentWatchMutationFailed
	}
	s.metrics.RecordComponentWatchMutation(action, result)
}

// List 使用 actor active-time 索引和 keyset cursor 返回当前仍公开可见的订阅。
// 查询不返回 exact total，避免关系量增长后为每页附加 O(N) 计数工作。
func (s *Service) List(ctx context.Context, actor pgtype.UUID, request ListRequest) (WatchPage, error) {
	limit := request.Limit
	if limit == 0 {
		limit = defaultListLimit
	}
	if limit < 1 || limit > maxListLimit {
		return WatchPage{}, validationError("limit")
	}
	if len(request.Query) > 200 || len(request.Category) > 128 {
		return WatchPage{}, validationError("query")
	}
	cursor, err := decodeCursor(request.Cursor)
	if err != nil {
		return WatchPage{}, validationError("cursor")
	}
	rows, err := s.q.ListActiveComponentWatches(ctx, db.ListActiveComponentWatchesParams{
		Locale: displayLocale(request.Locale), ActorID: actor,
		CategoryFilter: strings.TrimSpace(request.Category), SearchQuery: strings.TrimSpace(request.Query),
		CursorWatchedAt:   cursor.WatchedAt,
		CursorComponentID: cursor.ComponentID, PageSize: int32(limit + 1),
	})
	if err != nil {
		return WatchPage{}, err
	}
	hasMore := len(rows) > limit
	if hasMore {
		rows = rows[:limit]
	}
	items := make([]WatchListItem, 0, len(rows))
	for _, row := range rows {
		items = append(items, WatchListItem{
			ComponentID: uuidutil.String(row.ComponentID), ContentKind: row.ContentKind,
			ContentLocale: row.SelectedContentLocale, Name: row.SelectedName, Category: row.Category,
			CurrentVersionID: uuidutil.NullableString(row.CurrentVersionID), VersionLabel: row.VersionLabel,
			Revision: row.Revision, PublishedAt: nullableTime(row.PublishedAt), Level: row.WatchLevel,
			WatchedAt: row.WatchedAt.Time, TranslationMissing: row.TranslationMissing,
		})
	}
	var next *string
	if hasMore && len(rows) > 0 {
		last := rows[len(rows)-1]
		encoded, encodeErr := encodeCursor(last.WatchedAt.Time, last.ComponentID)
		if encodeErr != nil {
			return WatchPage{}, encodeErr
		}
		next = &encoded
	}
	return WatchPage{Items: items, NextCursor: next}, nil
}

type cursorPayload struct {
	WatchedAt   string `json:"watchedAt"`
	ComponentID string `json:"componentId"`
}

type decodedCursor struct {
	WatchedAt   pgtype.Timestamptz
	ComponentID pgtype.UUID
}

func decodeCursor(raw string) (decodedCursor, error) {
	if strings.TrimSpace(raw) == "" {
		return decodedCursor{}, nil
	}
	data, err := base64.RawURLEncoding.DecodeString(raw)
	if err != nil {
		return decodedCursor{}, err
	}
	var payload cursorPayload
	if err := json.Unmarshal(data, &payload); err != nil {
		return decodedCursor{}, err
	}
	when, err := time.Parse(time.RFC3339Nano, payload.WatchedAt)
	if err != nil {
		return decodedCursor{}, err
	}
	id, err := uuidutil.Parse(payload.ComponentID)
	if err != nil {
		return decodedCursor{}, err
	}
	return decodedCursor{
		WatchedAt: pgtype.Timestamptz{Time: when.UTC(), Valid: true}, ComponentID: id,
	}, nil
}

func encodeCursor(watchedAt time.Time, componentID pgtype.UUID) (string, error) {
	payload, err := json.Marshal(cursorPayload{
		WatchedAt: watchedAt.UTC().Format(time.RFC3339Nano), ComponentID: uuidutil.String(componentID),
	})
	if err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(payload), nil
}

func displayLocale(input string) string {
	normalized := strings.ToLower(strings.TrimSpace(strings.ReplaceAll(input, "_", "-")))
	if normalized == "en" || normalized == "en-us" || strings.HasPrefix(normalized, "en-") {
		return "en-US"
	}
	return "zh-CN"
}

func parseID(value, field string) (pgtype.UUID, error) {
	id, err := uuidutil.Parse(value)
	if err != nil {
		return pgtype.UUID{}, validationError(field)
	}
	return id, nil
}

func nullableTime(value pgtype.Timestamptz) *time.Time {
	if !value.Valid {
		return nil
	}
	result := value.Time
	return &result
}

func validationError(field string) error {
	return apierror.New("request.validation_failed", http.StatusUnprocessableEntity, map[string]any{"field": field})
}

func withTx[T any](ctx context.Context, pool *pgxpool.Pool, fn func(*db.Queries) (T, error)) (T, error) {
	var zero T
	for attempt := 0; attempt < 3; attempt++ {
		tx, err := pool.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.Serializable})
		if err != nil {
			return zero, err
		}
		value, runErr := fn(db.New(tx))
		if runErr != nil {
			_ = tx.Rollback(ctx)
			if retryable(runErr) {
				continue
			}
			return zero, runErr
		}
		if err = tx.Commit(ctx); err == nil {
			return value, nil
		}
		if !retryable(err) {
			return zero, err
		}
	}
	return zero, apierror.New("request.conflict", http.StatusConflict, nil)
}

func retryable(err error) bool {
	if errors.Is(err, errRetryWatchTransaction) {
		return true
	}
	var pgError *pgconn.PgError
	return errors.As(err, &pgError) && (pgError.Code == "40001" || pgError.Code == "40P01")
}
