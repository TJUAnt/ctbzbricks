package componentwatch

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"time"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/componentactivity"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/feedrender"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/localeutil"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/observability"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/storage"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	defaultListLimit  = 20
	maxListLimit      = 100
	defaultFeedWindow = 30 * 24 * time.Hour
)

var errRetryWatchTransaction = errors.New("retry concurrent watch transaction")

// Service 管理当前 actor 的 Watch 偏好与只读列表；它不负责发布事件或通知投递。
type Service struct {
	pool            *pgxpool.Pool
	q               *db.Queries
	metrics         *observability.Registry
	now             func() time.Time
	feedImageStore  storage.Store
	feedImageURLTTL time.Duration
}

// NewService 创建使用 PostgreSQL 权威关系数据的 Watch 应用服务。
func NewService(pool *pgxpool.Pool) *Service {
	return &Service{pool: pool, q: db.New(pool), now: time.Now}
}

// WithMetrics 为 Watch mutation 接入进程级低基数指标；未配置时业务行为保持不变。
func (s *Service) WithMetrics(metrics *observability.Registry) *Service {
	s.metrics = metrics
	return s
}

// WithFeedImages 为个人订阅 Feed 当页终态图片批量签发短期 URL；签名失败时卡片稳定降级为无图。
func (s *Service) WithFeedImages(store storage.Store, ttl time.Duration) *Service {
	s.feedImageStore = store
	s.feedImageURLTTL = ttl
	return s
}

// Watch 幂等建立 releases_only 订阅；Feed 展示上下文在读取时确定，不写入 Watch period。
func (s *Service) Watch(ctx context.Context, actor pgtype.UUID, componentID, level string) (result Watch, err error) {
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
		// 已 active 的相同级别是纯幂等读路径；保留原 watched_at，避免重复 PUT 制造虚假 Rewatch。
		if target.WatchPeriodID != nil && target.WatchLevel != nil &&
			*target.WatchLevel == level && target.WatchedAt.Valid {
			return Watch{ComponentID: componentID, Watching: true, Level: level, WatchedAt: target.WatchedAt.Time}, nil
		}
		if target.Status != "active" || !target.PublicVersionAvailable {
			return Watch{}, apierror.New("component_repo.watch_component_unavailable", http.StatusConflict, nil)
		}
		row, err := q.CreateActiveComponentWatchPeriod(ctx, db.CreateActiveComponentWatchPeriodParams{
			ActorID: actor, ComponentID: id, WatchLevel: level,
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
	if len(request.Query) > 200 {
		return WatchPage{}, validationError("query")
	}
	if len(request.Category) > 128 {
		return WatchPage{}, validationError("category")
	}
	locale := localeutil.Display(request.Locale)
	query := strings.TrimSpace(request.Query)
	category := strings.TrimSpace(request.Category)
	cursor, err := decodeCursor(request.Cursor)
	if err != nil {
		return WatchPage{}, validationError("cursor")
	}
	// cursor 只允许继续原筛选集合，避免调用方换掉名称、分类或 locale 后从旧边界继续而静默漏项。
	if cursor.WatchedAt.Valid && (cursor.Locale != locale || cursor.Query != query || cursor.Category != category) {
		return WatchPage{}, validationError("cursor")
	}
	rows, err := s.q.ListActiveComponentWatches(ctx, db.ListActiveComponentWatchesParams{
		Locale: locale, ActorID: actor,
		CategoryFilter: category, SearchQuery: query,
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
		encoded, encodeErr := encodeCursor(last.WatchedAt.Time, last.ComponentID, locale, query, category)
		if encodeErr != nil {
			return WatchPage{}, encodeErr
		}
		next = &encoded
	}
	return WatchPage{Items: items, NextCursor: next}, nil
}

// ListFeed 从 actor 当前 active Watch 出发读取时间窗口内的发布事件。
// started/ended sequence 不参与资格判断，因此 Watch 可以回看窗口内的既有发布，Unwatch 会在下一次读取立即生效。
func (s *Service) ListFeed(ctx context.Context, actor pgtype.UUID, request FeedRequest) (page FeedPage, err error) {
	startedAt := time.Now()
	defer func() {
		result := observability.ComponentWatchFeedSucceeded
		if err != nil {
			result = observability.ComponentWatchFeedFailed
		}
		s.metrics.RecordComponentWatchFeed(result, time.Since(startedAt))
	}()
	limit := request.Limit
	if limit == 0 {
		limit = defaultListLimit
	}
	if limit < 1 || limit > maxListLimit {
		return FeedPage{}, validationError("limit")
	}
	cursor, err := decodeFeedCursor(request.Cursor)
	if err != nil {
		return FeedPage{}, validationError("cursor")
	}
	windowStart, err := resolveFeedWindowStart(request.Since, cursor, s.now().UTC())
	if err != nil {
		return FeedPage{}, validationError("since")
	}
	rows, err := s.q.ListCurrentComponentWatchFeed(ctx, db.ListCurrentComponentWatchFeedParams{
		ActorID: actor, Locale: localeutil.Display(request.Locale), WindowStart: timestamp(windowStart),
		CursorOccurredAt: cursor.OccurredAt, CursorEventID: cursor.EventID, PageSize: int32(limit + 1),
	})
	if err != nil {
		return FeedPage{}, err
	}
	hasMore := len(rows) > limit
	if hasMore {
		rows = rows[:limit]
	}
	imageURLs := map[string]string{}
	if s.feedImageStore != nil && s.feedImageURLTTL > 0 {
		keys := make([]string, 0, len(rows))
		for _, row := range rows {
			if row.RenderStatus == "ready" && row.ImageStorageKey != nil &&
				row.ImageStorageProvider != nil && *row.ImageStorageProvider == s.feedImageStore.Provider() &&
				row.ImageStorageBucket != nil && *row.ImageStorageBucket == s.feedImageStore.Bucket() {
				keys = append(keys, *row.ImageStorageKey)
			}
		}
		if len(keys) > 0 {
			if signed, signErr := s.feedImageStore.SignDownloads(ctx, keys, s.feedImageURLTTL); signErr == nil {
				imageURLs = signed
			}
		}
	}
	items := make([]FeedItem, 0, len(rows))
	for _, row := range rows {
		items = append(items, watchFeedItemFromDB(row, imageURLs))
	}
	var next *string
	if hasMore && len(rows) > 0 {
		last := rows[len(rows)-1]
		encoded, encodeErr := encodeFeedCursor(windowStart, last.OccurredAt.Time, last.EventID)
		if encodeErr != nil {
			return FeedPage{}, encodeErr
		}
		next = &encoded
	}
	return FeedPage{Items: items, NextCursor: next, WindowStart: windowStart}, nil
}

// watchFeedItemFromDB 把已固定的 Watch 事件页映射为共享大卡片契约；事件版本与当前 Component 投影不可混用。
func watchFeedItemFromDB(row db.ListCurrentComponentWatchFeedRow, imageURLs map[string]string) FeedItem {
	item := FeedItem{
		EventID: uuidutil.String(row.EventID), EventType: row.EventType, OccurredAt: row.OccurredAt.Time,
		ComponentVersionID: uuidutil.String(row.ComponentVersionID), VersionLabel: row.VersionLabel,
		Revision: row.Revision, PublishedAt: nullableTime(row.PublishedAt), ReleaseNote: row.ReleaseNote,
		ReleaseNoteLocale: row.ReleaseNoteLocale,
		Publisher:         FeedPublisher{ID: uuidutil.String(row.PublisherID)},
		Render:            FeedRender{Status: "fallback", AvailableAt: row.AvailableAt.Time},
		Component: FeedComponent{
			ID: uuidutil.String(row.ComponentID), OwnerID: uuidutil.NullableString(row.OwnerID),
			ContentKind: row.ContentKind, ContentLocale: row.SelectedContentLocale, Name: row.SelectedName,
			Description: selectedText(row.SelectedDescription, row.HasDescription), Tags: nonNilStrings(row.SelectedTags),
			Category: row.Category, Status: row.Status, CurrentVersionID: uuidutil.NullableString(row.CurrentVersionID),
			LogicalSize: watchLogicalSize(row.LogicalWidthStud, row.LogicalDepthStud, row.LogicalHeightPlate),
			Metadata:    validJSON(row.Metadata), OwnedByActor: row.OwnedByActor,
			StarredByActor: row.StarredByActor, StarCount: row.StarCount,
			Watch:              &FeedWatchState{Watching: true, Level: &row.WatchLevel, WatchedAt: nullableTime(row.WatchedAt)},
			TranslationMissing: row.TranslationMissing, CreatedAt: row.CreatedAt.Time, UpdatedAt: row.UpdatedAt.Time,
		},
	}
	if row.RenderStatus == "ready" && row.ImageArtifactID.Valid && row.ImageStorageKey != nil {
		if url := imageURLs[*row.ImageStorageKey]; url != "" {
			item.Render.Status = "ready"
			item.Render.Image = &FeedImage{
				ArtifactID: uuidutil.String(row.ImageArtifactID), URL: url, Format: "png",
				SHA256: stringValue(row.ImageSha256), ByteLength: int64Value(row.ImageFileSize),
				Width: feedrender.ImageWidth, Height: feedrender.ImageHeight,
			}
		}
	}
	return item
}

type cursorPayload struct {
	WatchedAt   string `json:"watchedAt"`
	ComponentID string `json:"componentId"`
	Locale      string `json:"locale"`
	Query       string `json:"query"`
	Category    string `json:"category"`
}

type decodedCursor struct {
	WatchedAt   pgtype.Timestamptz
	ComponentID pgtype.UUID
	Locale      string
	Query       string
	Category    string
}

type feedCursorPayload struct {
	WindowStart string `json:"windowStart"`
	OccurredAt  string `json:"occurredAt"`
	EventID     string `json:"eventId"`
}

type decodedFeedCursor struct {
	WindowStart time.Time
	OccurredAt  pgtype.Timestamptz
	EventID     pgtype.UUID
}

func decodeFeedCursor(raw string) (decodedFeedCursor, error) {
	if strings.TrimSpace(raw) == "" {
		return decodedFeedCursor{}, nil
	}
	data, err := base64.RawURLEncoding.DecodeString(raw)
	if err != nil {
		return decodedFeedCursor{}, err
	}
	var payload feedCursorPayload
	if err := json.Unmarshal(data, &payload); err != nil {
		return decodedFeedCursor{}, err
	}
	windowStart, err := time.Parse(time.RFC3339Nano, payload.WindowStart)
	if err != nil {
		return decodedFeedCursor{}, err
	}
	occurredAt, err := time.Parse(time.RFC3339Nano, payload.OccurredAt)
	if err != nil {
		return decodedFeedCursor{}, err
	}
	eventID, err := uuidutil.Parse(payload.EventID)
	if err != nil {
		return decodedFeedCursor{}, err
	}
	return decodedFeedCursor{
		WindowStart: windowStart.UTC(), OccurredAt: timestamp(occurredAt.UTC()), EventID: eventID,
	}, nil
}

func resolveFeedWindowStart(raw string, cursor decodedFeedCursor, now time.Time) (time.Time, error) {
	if cursor.OccurredAt.Valid {
		if strings.TrimSpace(raw) == "" {
			return cursor.WindowStart, nil
		}
		provided, err := time.Parse(time.RFC3339Nano, raw)
		if err != nil || !provided.UTC().Equal(cursor.WindowStart) {
			return time.Time{}, errors.New("feed cursor window mismatch")
		}
		return cursor.WindowStart, nil
	}
	if strings.TrimSpace(raw) == "" {
		return now.Add(-defaultFeedWindow), nil
	}
	provided, err := time.Parse(time.RFC3339Nano, raw)
	if err != nil {
		return time.Time{}, err
	}
	return provided.UTC(), nil
}

func encodeFeedCursor(windowStart, occurredAt time.Time, eventID pgtype.UUID) (string, error) {
	payload, err := json.Marshal(feedCursorPayload{
		WindowStart: windowStart.UTC().Format(time.RFC3339Nano),
		OccurredAt:  occurredAt.UTC().Format(time.RFC3339Nano), EventID: uuidutil.String(eventID),
	})
	if err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(payload), nil
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
		Locale: payload.Locale, Query: payload.Query, Category: payload.Category,
	}, nil
}

func encodeCursor(watchedAt time.Time, componentID pgtype.UUID, locale, query, category string) (string, error) {
	payload, err := json.Marshal(cursorPayload{
		WatchedAt: watchedAt.UTC().Format(time.RFC3339Nano), ComponentID: uuidutil.String(componentID),
		Locale: locale, Query: query, Category: category,
	})
	if err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(payload), nil
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

func watchLogicalSize(width, depth, height pgtype.Numeric) *FeedLogicalSize {
	if !width.Valid || !depth.Valid || !height.Valid {
		return nil
	}
	w, wErr := width.Float64Value()
	d, dErr := depth.Float64Value()
	h, hErr := height.Float64Value()
	if wErr != nil || dErr != nil || hErr != nil || !w.Valid || !d.Valid || !h.Valid {
		return nil
	}
	return &FeedLogicalSize{WidthStud: w.Float64, DepthStud: d.Float64, HeightPlate: h.Float64}
}

func validJSON(value []byte) json.RawMessage {
	if !json.Valid(value) {
		return json.RawMessage(`{}`)
	}
	return json.RawMessage(value)
}

func selectedText(value string, present bool) *string {
	if !present {
		return nil
	}
	return &value
}

func nonNilStrings(values []string) []string {
	if values == nil {
		return []string{}
	}
	return values
}

func stringValue(value *string) string {
	if value == nil {
		return ""
	}
	return *value
}

func int64Value(value *int64) int64 {
	if value == nil {
		return 0
	}
	return *value
}

func timestamp(value time.Time) pgtype.Timestamptz {
	return pgtype.Timestamptz{Time: value, Valid: true}
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
