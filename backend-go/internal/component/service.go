package component

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"net/http"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/componentactivity"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/componentdiff"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/feedrender"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/observability"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/storage"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	defaultPageSize                = 20
	maxPageSize                    = 100
	maxGroupDepth                  = 5
	maxSearchConditions            = 8
	watchEndReasonComponentDeleted = "component_deleted"
)

var componentSizeQueryPattern = regexp.MustCompile(`^\s*(\d+(?:\.\d+)?|\.\d+)\s*[xX×]\s*(\d+(?:\.\d+)?|\.\d+)(?:\s*[xX×]\s*(\d+(?:\.\d+)?|\.\d+))?\s*$`)

type componentSizeFilter struct {
	DimensionCount int32   `json:"dimension_count"`
	A              float64 `json:"size_a"`
	B              float64 `json:"size_b"`
	C              float64 `json:"size_c"`
}

type Service struct {
	pool            *pgxpool.Pool
	q               *db.Queries
	metrics         *observability.Registry
	feedImageStore  storage.Store
	feedImageURLTTL time.Duration
}

type publicFeedCursorPayload struct {
	AvailableAt string `json:"availableAt"`
	EventID     string `json:"eventId"`
	Query       string `json:"query"`
}

type decodedPublicFeedCursor struct {
	AvailableAt pgtype.Timestamptz
	EventID     pgtype.UUID
	Query       string
}

func NewService(pool *pgxpool.Pool) *Service {
	return &Service{pool: pool, q: db.New(pool)}
}

// WithMetrics 为发布事务接入进程级运维指标；未配置时业务行为保持不变。
func (s *Service) WithMetrics(metrics *observability.Registry) *Service {
	s.metrics = metrics
	return s
}

// WithFeedImages 为 SQL 已授权的 Feed 图片批量签发短期 URL；签名失败时单卡降级，不隐藏发布事件。
func (s *Service) WithFeedImages(store storage.Store, ttl time.Duration) *Service {
	s.feedImageStore = store
	s.feedImageURLTTL = ttl
	return s
}

func (s *Service) CreateComponent(ctx context.Context, actor pgtype.UUID, input CreateComponentInput) (Component, error) {
	if strings.TrimSpace(input.Name) == "" || len(input.Name) > 255 {
		return Component{}, validationError("name")
	}
	locale, ok := NormalizeLocale(input.ContentLocale)
	if !ok {
		return Component{}, validationError("contentLocale")
	}
	if len(input.Tags) > 50 {
		return Component{}, validationError("tags")
	}
	return withTx(ctx, s.pool, func(q *db.Queries) (Component, error) {
		id, err := uuidutil.New()
		if err != nil {
			return Component{}, err
		}
		_, err = q.CreateComponent(ctx, db.CreateComponentParams{
			ID: id, OwnerID: actor, ContentLocale: locale, Name: input.Name,
			Description: input.Description, Tags: nonNilStrings(input.Tags),
			Category: cleanOptional(input.Category), CreatedBy: actor,
		})
		if err != nil {
			return Component{}, mapDatabaseError(err, "request.conflict")
		}
		row, err := q.GetVisibleComponent(ctx, db.GetVisibleComponentParams{
			Locale: locale, ActorID: actor, ComponentID: id,
		})
		return componentFromVisible(row), err
	})
}

func (s *Service) GetComponent(ctx context.Context, actor pgtype.UUID, componentID, localeInput string) (Component, error) {
	id, err := resourceID(componentID, "componentId")
	if err != nil {
		return Component{}, err
	}
	locale := displayLocale(localeInput)
	row, err := s.q.GetVisibleComponent(ctx, db.GetVisibleComponentParams{
		Locale: locale, ActorID: actor, ComponentID: id,
	})
	if errors.Is(err, pgx.ErrNoRows) {
		return Component{}, notFound("component_repo.component_not_found", "componentId", componentID)
	}
	if err != nil {
		return Component{}, err
	}
	return componentFromVisible(row), nil
}

// ListComponents 返回 actor 自有和公开可见目录；候选使用双降序 keyset，页面固定后才做展示 enrichment。
// 目录不返回 exact total，避免每一页附加 O(N) Count，也从根源消除两次 READ COMMITTED 快照不一致。
func (s *Service) ListComponents(ctx context.Context, actor pgtype.UUID, request ComponentListRequest) (ComponentPage, error) {
	limit := request.Limit
	if limit == 0 {
		limit = defaultPageSize
	}
	if limit < 1 || limit > maxPageSize {
		return ComponentPage{}, validationError("limit")
	}
	locale := displayLocale(request.Locale)
	query := strings.TrimSpace(request.Query)
	category := strings.TrimSpace(request.Category)
	status := strings.TrimSpace(request.Status)
	if len(query) > 200 || len(category) > 128 {
		return ComponentPage{}, validationError("query")
	}
	if status != "" && status != "draft" && status != "active" {
		return ComponentPage{}, validationError("status")
	}
	cursor, err := decodeComponentListCursor(request.Cursor)
	if err != nil {
		return ComponentPage{}, validationError("cursor")
	}
	if cursor.UpdatedAt.Valid && (cursor.Locale != locale || cursor.Query != query ||
		cursor.Category != category || cursor.Status != status) {
		return ComponentPage{}, validationError("cursor")
	}
	// 完整 UUID 使用等值路径，既保持机器标识符的精确语义，也避免把它送入模糊字符串扫描。
	searchQuery := query
	var searchComponentID pgtype.UUID
	hasSearchComponentID := false
	if query != "" {
		if parsedID, parseErr := uuidutil.Parse(query); parseErr == nil {
			searchComponentID = parsedID
			hasSearchComponentID = true
			searchQuery = ""
		}
	}
	rows, err := s.q.ListVisibleComponents(ctx, db.ListVisibleComponentsParams{
		Locale: locale, ActorID: actor, StatusFilter: status,
		CategoryFilter: category, SearchQuery: searchQuery,
		HasSearchComponentID: hasSearchComponentID, SearchComponentID: searchComponentID,
		CursorUpdatedAt: cursor.UpdatedAt, CursorComponentID: cursor.ComponentID,
		PageSize: int32(limit + 1),
	})
	if err != nil {
		return ComponentPage{}, err
	}
	hasMore := len(rows) > limit
	if hasMore {
		rows = rows[:limit]
	}
	items := make([]Component, 0, len(rows))
	for _, row := range rows {
		items = append(items, componentFromList(row))
	}
	var next *string
	if hasMore && len(rows) > 0 {
		last := rows[len(rows)-1]
		encoded, encodeErr := encodeComponentListCursor(
			last.UpdatedAt.Time, last.ID, locale, query, category, status,
		)
		if encodeErr != nil {
			return ComponentPage{}, encodeErr
		}
		next = &encoded
	}
	return ComponentPage{Items: items, NextCursor: next}, nil
}

// ListPublicFeed 按不可变发布事件返回公共广场。Watch 只作为当前 actor 的展示投影，不能改变候选集合。
func (s *Service) ListPublicFeed(ctx context.Context, actor pgtype.UUID, request PublicFeedRequest) (PublicFeedPage, error) {
	limit := request.Limit
	if limit == 0 {
		limit = defaultPageSize
	}
	if limit < 1 || limit > maxPageSize {
		return PublicFeedPage{}, validationError("limit")
	}
	query := strings.TrimSpace(request.Query)
	if len(query) > 200 {
		return PublicFeedPage{}, validationError("query")
	}
	cursor, err := decodePublicFeedCursor(request.Cursor)
	if err != nil || (cursor.AvailableAt.Valid && cursor.Query != query) {
		return PublicFeedPage{}, validationError("cursor")
	}
	rows, err := s.q.ListComponentPublicFeed(ctx, db.ListComponentPublicFeedParams{
		ActorID: actor, SearchQuery: query, CursorAvailableAt: cursor.AvailableAt,
		CursorEventID: cursor.EventID, PageSize: int32(limit + 1),
	})
	if err != nil {
		return PublicFeedPage{}, err
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
	items := make([]PublicFeedItem, 0, len(rows))
	for _, row := range rows {
		items = append(items, publicFeedItemFromDB(row, imageURLs))
	}
	var next *string
	if hasMore && len(rows) > 0 {
		last := rows[len(rows)-1]
		encoded, encodeErr := encodePublicFeedCursor(last.AvailableAt.Time, last.EventID, query)
		if encodeErr != nil {
			return PublicFeedPage{}, encodeErr
		}
		next = &encoded
	}
	return PublicFeedPage{Items: items, NextCursor: next}, nil
}

func decodePublicFeedCursor(raw string) (decodedPublicFeedCursor, error) {
	if strings.TrimSpace(raw) == "" {
		return decodedPublicFeedCursor{}, nil
	}
	data, err := base64.RawURLEncoding.DecodeString(raw)
	if err != nil {
		return decodedPublicFeedCursor{}, err
	}
	var payload publicFeedCursorPayload
	if err := json.Unmarshal(data, &payload); err != nil {
		return decodedPublicFeedCursor{}, err
	}
	when, err := time.Parse(time.RFC3339Nano, payload.AvailableAt)
	if err != nil {
		return decodedPublicFeedCursor{}, err
	}
	eventID, err := uuidutil.Parse(payload.EventID)
	if err != nil {
		return decodedPublicFeedCursor{}, err
	}
	return decodedPublicFeedCursor{
		AvailableAt: pgtype.Timestamptz{Time: when.UTC(), Valid: true}, EventID: eventID, Query: payload.Query,
	}, nil
}

func encodePublicFeedCursor(availableAt time.Time, eventID pgtype.UUID, query string) (string, error) {
	payload, err := json.Marshal(publicFeedCursorPayload{
		AvailableAt: availableAt.UTC().Format(time.RFC3339Nano), EventID: uuidutil.String(eventID), Query: query,
	})
	if err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(payload), nil
}

// ListStars 返回 actor 当前仍公开可见的个人收藏；归档/删除提交后立即隐藏，持久任务随后删除关系。
func (s *Service) ListStars(ctx context.Context, actor pgtype.UUID, request StarListRequest) (StarPage, error) {
	request.PageRequest = normalizePage(request.PageRequest)
	if len(request.Query) > 200 || len(request.Category) > 128 {
		return StarPage{}, validationError("query")
	}
	if request.Sort != "" && request.Sort != "starred_at_desc" {
		return StarPage{}, validationError("sort")
	}
	searchQuery := strings.TrimSpace(request.Query)
	sizeFilter := componentSizeFilter{}
	if parsed, ok := parseComponentSizeQuery(searchQuery); ok {
		// 完整尺寸表达式只参与 Box 匹配，避免同时把“2x4x3”误当名称关键字。
		sizeFilter = parsed
		searchQuery = ""
	}
	params := db.ListStarredComponentsParams{
		Locale: displayLocale(request.Locale), ActorID: actor,
		CategoryFilter: strings.TrimSpace(request.Category), SearchQuery: searchQuery,
		SizeDimensionCount: sizeFilter.DimensionCount, SizeA: sizeFilter.A, SizeB: sizeFilter.B, SizeC: sizeFilter.C,
		PageOffset: int32((request.Page - 1) * request.PageSize), PageSize: int32(request.PageSize),
	}
	counts, err := s.q.CountStarredComponents(ctx, db.CountStarredComponentsParams{
		Locale: params.Locale, ActorID: actor,
		CategoryFilter: params.CategoryFilter, SearchQuery: params.SearchQuery,
		SizeDimensionCount: params.SizeDimensionCount, SizeA: params.SizeA, SizeB: params.SizeB, SizeC: params.SizeC,
	})
	if err != nil {
		return StarPage{}, err
	}
	rows, err := s.q.ListStarredComponents(ctx, params)
	if err != nil {
		return StarPage{}, err
	}
	items := make([]StarredComponent, 0, len(rows))
	for _, row := range rows {
		items = append(items, starredComponentFromDB(row))
	}
	totalPages := 0
	if counts.Total > 0 {
		totalPages = int((counts.Total + int64(request.PageSize) - 1) / int64(request.PageSize))
	}
	return StarPage{
		Items: items, Page: request.Page, PageSize: request.PageSize,
		Total: counts.Total, TotalPages: totalPages, RelationshipTotal: counts.RelationshipTotal,
	}, nil
}

func (s *Service) UpdateComponent(ctx context.Context, actor pgtype.UUID, componentID string, input UpdateComponentInput) (Component, error) {
	id, err := resourceID(componentID, "componentId")
	if err != nil {
		return Component{}, err
	}
	if input.Name == nil && !input.Description.Set && input.Tags == nil && !input.Category.Set && input.ContentLocale == nil {
		return Component{}, validationError("body")
	}
	name := ""
	if input.Name != nil {
		name = *input.Name
		if strings.TrimSpace(name) == "" || len(name) > 255 {
			return Component{}, validationError("name")
		}
	}
	locale := ""
	if input.ContentLocale != nil {
		var ok bool
		locale, ok = NormalizeLocale(*input.ContentLocale)
		if !ok {
			return Component{}, validationError("contentLocale")
		}
	}
	if input.Tags != nil && len(*input.Tags) > 50 {
		return Component{}, validationError("tags")
	}
	return withTx(ctx, s.pool, func(q *db.Queries) (Component, error) {
		_, err := q.UpdateOwnedComponent(ctx, db.UpdateOwnedComponentParams{
			SetName: input.Name != nil, Name: name,
			SetDescription: input.Description.Set, Description: input.Description.Value,
			SetTags: input.Tags != nil, Tags: nonNilStringPointer(input.Tags),
			SetCategory: input.Category.Set, Category: cleanOptional(input.Category.Value),
			SetContentLocale: input.ContentLocale != nil, ContentLocale: locale,
			ComponentID: id, ActorID: actor,
		})
		if errors.Is(err, pgx.ErrNoRows) {
			return Component{}, notFound("component_repo.component_not_found", "componentId", componentID)
		}
		if err != nil {
			return Component{}, mapDatabaseError(err, "request.conflict")
		}
		row, err := q.GetVisibleComponent(ctx, db.GetVisibleComponentParams{
			Locale: displayLocale(locale), ActorID: actor, ComponentID: id,
		})
		return componentFromVisible(row), err
	})
}

func (s *Service) DeleteComponent(ctx context.Context, actor pgtype.UUID, componentID string) error {
	id, err := resourceID(componentID, "componentId")
	if err != nil {
		return err
	}
	_, err = withTx(ctx, s.pool, func(q *db.Queries) (struct{}, error) {
		// 生命周期独占锁先于状态写入取得：已在途的 Star/Watch 先完成，删除提交后新的关系创建
		// 重新执行资格检查并失败；同事务持久化的清理任务因此覆盖完整且不会继续增长的候选集合。
		if lockErr := q.AcquireExclusiveComponentActivityLock(ctx, componentactivity.LockKey(id)); lockErr != nil {
			return struct{}{}, lockErr
		}
		_, err := q.SoftDeleteOwnedComponent(ctx, db.SoftDeleteOwnedComponentParams{ActorID: actor, ComponentID: id})
		if errors.Is(err, pgx.ErrNoRows) {
			return struct{}{}, notFound("component_repo.component_not_found", "componentId", componentID)
		}
		if err != nil {
			return struct{}{}, err
		}
		boundary, err := q.CreateComponentRelationshipEndBoundary(ctx)
		if err != nil {
			return struct{}{}, err
		}
		payload, err := json.Marshal(relationshipCleanupPayload{
			ComponentID: componentID,
			EndedSeq:    boundary.EndedSeq,
			EndedAt:     boundary.EndedAt.Time.UTC(),
			EndedReason: watchEndReasonComponentDeleted,
		})
		if err != nil {
			return struct{}{}, err
		}
		// 百万关系的同步清理会把 DELETE Handler 扩大成长事务；任务与软删除同事务创建，列表立即因
		// Component 不可见而移除条目，Worker 再以冻结边界分批物理收敛 Star/Watch 关系。
		_, _, err = task.EnqueueWithQueries(ctx, q, task.EnqueueInput{
			OwnerID: actor, TaskType: task.RelationshipCleanupType, Payload: payload,
			Locale: "en-US", Timezone: "UTC", CreatedBy: actor,
			IdempotencyKey: componentID, MaxAttempts: 10,
		})
		return struct{}{}, err
	})
	return err
}

func (s *Service) CreateVersion(ctx context.Context, actor pgtype.UUID, componentID string, input CreateVersionInput) (ComponentVersion, error) {
	componentUUID, err := resourceID(componentID, "componentId")
	if err != nil {
		return ComponentVersion{}, err
	}
	params, err := versionCreateParams(actor, componentUUID, input)
	if err != nil {
		return ComponentVersion{}, err
	}
	return withTx(ctx, s.pool, func(q *db.Queries) (ComponentVersion, error) {
		if _, err := q.LockOwnedComponent(ctx, db.LockOwnedComponentParams{ComponentID: componentUUID, ActorID: actor}); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return ComponentVersion{}, notFound("component_repo.component_not_found", "componentId", componentID)
			}
			return ComponentVersion{}, err
		}
		source, err := q.GetOwnedVersionCandidateSource(ctx, db.GetOwnedVersionCandidateSourceParams{
			CandidateID: params.ComponentCandidateID,
			ActorID:     actor,
			ComponentID: componentUUID,
		})
		if errors.Is(err, pgx.ErrNoRows) {
			return ComponentVersion{}, apierror.New("component_repo.version_source_not_found_failed", http.StatusNotFound, nil)
		}
		if err != nil {
			return ComponentVersion{}, err
		}
		params.SourceArtifactID = source.SourceArtifactID
		params.ExchangeArtifactID = source.ExchangeArtifactID
		params.SceneSnapshotID = source.SceneSnapshotID
		params.ParserVersion = source.ParserVersion
		params.PartLibraryVersionID = source.PartLibraryVersionID
		params.InterfaceSignature = source.InterfaceSignature
		params.StructureHash = source.StructureHash
		params.GeometryHash = source.GeometryHash
		row, err := q.CreateComponentVersion(ctx, params)
		if err != nil {
			return ComponentVersion{}, mapDatabaseError(err, "component_repo.version_conflict")
		}
		return versionFromDB(row), nil
	})
}

func (s *Service) GetVersion(ctx context.Context, actor pgtype.UUID, versionID string) (ComponentVersion, error) {
	id, err := resourceID(versionID, "versionId")
	if err != nil {
		return ComponentVersion{}, err
	}
	row, err := s.q.GetVisibleComponentVersion(ctx, db.GetVisibleComponentVersionParams{VersionID: id, ActorID: actor})
	if errors.Is(err, pgx.ErrNoRows) {
		return ComponentVersion{}, notFound("component_repo.version_not_found", "versionId", versionID)
	}
	if err != nil {
		return ComponentVersion{}, err
	}
	return versionFromDB(row), nil
}

// GetVersionDiff 计算 owner 当前版本相对其 Import.base_version_id 的结构差异。
// 该方法不写数据库、不读取 GLB，也不会按时间猜测父版本；首个版本与空树比较。
func (s *Service) GetVersionDiff(ctx context.Context, actor pgtype.UUID, versionID string) (VersionDiff, error) {
	id, err := resourceID(versionID, "versionId")
	if err != nil {
		return VersionDiff{}, err
	}
	head, err := s.q.GetOwnedVersionDiffHead(ctx, db.GetOwnedVersionDiffHeadParams{ActorID: actor, VersionID: id})
	if errors.Is(err, pgx.ErrNoRows) {
		return VersionDiff{}, notFound("component_repo.version_not_found", "versionId", versionID)
	}
	if err != nil {
		return VersionDiff{}, err
	}

	response := VersionDiff{
		VersionID:       uuidutil.String(head.ID),
		ComparisonBasis: "empty",
		StructureHash:   head.StructureHash,
		GeometryHash:    head.GeometryHash,
	}
	if !head.BaseVersionID.Valid {
		result, compareErr := componentdiff.CompareFromEmptyJSON(head.Document, componentdiff.Options{})
		if compareErr != nil {
			return VersionDiff{}, mapVersionDiffError(compareErr)
		}
		response.Result = result
		return response, nil
	}

	base, err := s.q.GetOwnedVersionDiffBase(ctx, db.GetOwnedVersionDiffBaseParams{
		ActorID: actor, VersionID: head.BaseVersionID, ComponentID: head.ComponentID,
	})
	if err != nil {
		// 外键存在但跨 Component、被软删除或快照缺失都属于持久化 lineage 不变量损坏，不对外泄露细节。
		return VersionDiff{}, err
	}
	baseVersionID := uuidutil.String(base.ID)
	response.BaseVersionID = &baseVersionID
	response.ComparisonBasis = "import_base_version"
	response.BaseStructureHash = &base.StructureHash
	response.BaseGeometryHash = &base.GeometryHash
	result, err := componentdiff.CompareJSON(base.Document, head.Document, componentdiff.Options{})
	if err != nil {
		return VersionDiff{}, mapVersionDiffError(err)
	}
	response.Result = result
	return response, nil
}

func mapVersionDiffError(err error) error {
	if errors.Is(err, componentdiff.ErrTooLarge) {
		return validationError("versionDiff")
	}
	return err
}

func (s *Service) ListVersions(ctx context.Context, actor pgtype.UUID, componentID string, page PageRequest) (VersionPage, error) {
	id, err := resourceID(componentID, "componentId")
	if err != nil {
		return VersionPage{}, err
	}
	page = normalizePage(page)
	visible, err := s.q.ComponentIsVisible(ctx, db.ComponentIsVisibleParams{ComponentID: id, ActorID: actor})
	if err != nil {
		return VersionPage{}, err
	}
	if !visible {
		return VersionPage{}, notFound("component_repo.component_not_found", "componentId", componentID)
	}
	rows, err := s.q.ListVisibleComponentVersions(ctx, db.ListVisibleComponentVersionsParams{
		ComponentID: id, ActorID: actor, PageOffset: int32((page.Page - 1) * page.PageSize), PageSize: int32(page.PageSize),
	})
	if err != nil {
		return VersionPage{}, err
	}
	items := make([]ComponentVersion, 0, len(rows))
	for _, row := range rows {
		items = append(items, versionFromDB(row))
	}
	return VersionPage{Items: items, Page: page.Page, PageSize: page.PageSize}, nil
}

// PublishVersion 直接发布 owner 的 Draft，并在同一事务中追加唯一的版本发布领域事件。
// 发布不枚举 watcher；订阅 Feed 在读取时按 actor 当前 active Watch 关联该不可变事件。
func (s *Service) PublishVersion(ctx context.Context, actor pgtype.UUID, versionID string) (ComponentVersion, error) {
	id, err := resourceID(versionID, "versionId")
	if err != nil {
		return ComponentVersion{}, err
	}
	eventAttempted := false
	published, publishErr := withTx(ctx, s.pool, func(q *db.Queries) (ComponentVersion, error) {
		locked, err := q.LockOwnedComponentVersion(ctx, db.LockOwnedComponentVersionParams{VersionID: id, ActorID: actor})
		if errors.Is(err, pgx.ErrNoRows) {
			return ComponentVersion{}, notFound("component_repo.version_not_found", "versionId", versionID)
		}
		if err != nil {
			return ComponentVersion{}, err
		}
		if locked.Status != "draft" {
			return ComponentVersion{}, apierror.New("request.conflict", http.StatusConflict, nil)
		}
		if err := q.AcquireExclusiveComponentActivityLock(ctx, componentactivity.LockKey(locked.ComponentID)); err != nil {
			return ComponentVersion{}, err
		}
		if err := q.DeprecateOtherPublishedVersions(ctx, db.DeprecateOtherPublishedVersionsParams{ComponentID: locked.ComponentID, VersionID: id}); err != nil {
			return ComponentVersion{}, err
		}
		if _, err := q.PublishComponentVersion(ctx, id); err != nil {
			return ComponentVersion{}, err
		}
		if err := q.SetComponentCurrentVersion(ctx, db.SetComponentCurrentVersionParams{VersionID: id, ComponentID: locked.ComponentID, ActorID: actor}); err != nil {
			return ComponentVersion{}, err
		}
		eventID, err := uuidutil.New()
		if err != nil {
			return ComponentVersion{}, err
		}
		eventAttempted = true
		if _, err := q.CreateComponentVersionPublishedEvent(ctx, db.CreateComponentVersionPublishedEventParams{
			ID: eventID, ComponentID: locked.ComponentID, ComponentVersionID: id, ActorID: actor,
		}); err != nil {
			return ComponentVersion{}, mapDatabaseError(err, "request.conflict")
		}
		// 发布只提交领域事实与持久任务，不等待图片计算；pending entry 在任务成功或重试终结前不会进入 Feed。
		if err := feedrender.ScheduleWithQueries(
			ctx, q, eventID, locked.ComponentID, id, actor, locked.ContentLocale,
			locked.PreviewTaskID, locked.PreviewTaskStatus, locked.PreviewIdentity,
		); err != nil {
			return ComponentVersion{}, err
		}
		row, err := q.GetVisibleComponentVersion(ctx, db.GetVisibleComponentVersionParams{VersionID: id, ActorID: actor})
		return versionFromDB(row), err
	})
	if publishErr == nil {
		s.metrics.RecordComponentDomainEvent(observability.ComponentVersionPublishedEvent, observability.DomainEventCommitted)
	} else if eventAttempted {
		s.metrics.RecordComponentDomainEvent(observability.ComponentVersionPublishedEvent, observability.DomainEventFailed)
	}
	return published, publishErr
}

func (s *Service) TransitionVersion(ctx context.Context, actor pgtype.UUID, versionID, target string) (ComponentVersion, error) {
	if target != "deprecated" && target != "archived" {
		return ComponentVersion{}, validationError("targetStatus")
	}
	id, err := resourceID(versionID, "versionId")
	if err != nil {
		return ComponentVersion{}, err
	}
	return withTx(ctx, s.pool, func(q *db.Queries) (ComponentVersion, error) {
		if _, err := q.TransitionOwnedComponentVersion(ctx, db.TransitionOwnedComponentVersionParams{TargetStatus: target, VersionID: id, ActorID: actor}); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return ComponentVersion{}, apierror.New("request.conflict", http.StatusConflict, nil)
			}
			return ComponentVersion{}, err
		}
		row, err := q.GetVisibleComponentVersion(ctx, db.GetVisibleComponentVersionParams{VersionID: id, ActorID: actor})
		return versionFromDB(row), err
	})
}

func (s *Service) DeleteVersion(ctx context.Context, actor pgtype.UUID, versionID string) error {
	id, err := resourceID(versionID, "versionId")
	if err != nil {
		return err
	}
	_, err = withTx(ctx, s.pool, func(q *db.Queries) (struct{}, error) {
		_, err := q.SoftDeleteOwnedDraftVersion(ctx, db.SoftDeleteOwnedDraftVersionParams{ActorID: actor, VersionID: id})
		if errors.Is(err, pgx.ErrNoRows) {
			return struct{}{}, notFound("component_repo.version_not_found", "versionId", versionID)
		}
		return struct{}{}, err
	})
	return err
}

func (s *Service) UpdateVersion(ctx context.Context, actor pgtype.UUID, versionID string, input UpdateVersionInput) (ComponentVersion, error) {
	id, err := resourceID(versionID, "versionId")
	if err != nil {
		return ComponentVersion{}, err
	}
	if input.Version == nil && input.Revision == nil && !input.ReleaseNote.Set && !input.ReleaseNoteLocale.Set {
		return ComponentVersion{}, validationError("body")
	}
	versionLabel := ""
	if input.Version != nil {
		versionLabel = strings.TrimSpace(*input.Version)
		if versionLabel == "" || len(versionLabel) > 64 {
			return ComponentVersion{}, validationError("version")
		}
	}
	if input.Revision != nil && *input.Revision < 1 {
		return ComponentVersion{}, validationError("revision")
	}
	if input.ReleaseNote.Set != input.ReleaseNoteLocale.Set {
		return ComponentVersion{}, validationError("releaseNoteLocale")
	}
	var releaseNote, releaseNoteLocale *string
	if input.ReleaseNote.Set {
		releaseNote = input.ReleaseNote.Value
		releaseNoteLocale = input.ReleaseNoteLocale.Value
		if (releaseNote == nil) != (releaseNoteLocale == nil) {
			return ComponentVersion{}, validationError("releaseNoteLocale")
		}
		if releaseNoteLocale != nil {
			normalized, ok := NormalizeLocale(*releaseNoteLocale)
			if !ok {
				return ComponentVersion{}, validationError("releaseNoteLocale")
			}
			releaseNoteLocale = &normalized
		}
	}
	row, err := s.q.UpdateOwnedDraftComponentVersion(ctx, db.UpdateOwnedDraftComponentVersionParams{
		SetVersionLabel: input.Version != nil, VersionLabel: versionLabel,
		SetRevision: input.Revision != nil, Revision: int32Value(input.Revision),
		SetReleaseNote: input.ReleaseNote.Set, ReleaseNote: releaseNote, ReleaseNoteLocale: releaseNoteLocale,
		VersionID: id, ActorID: actor,
	})
	if errors.Is(err, pgx.ErrNoRows) {
		return ComponentVersion{}, notFound("component_repo.version_not_found", "versionId", versionID)
	}
	if err != nil {
		return ComponentVersion{}, mapDatabaseError(err, "component_repo.version_conflict")
	}
	return versionFromDB(row), nil
}

func (s *Service) BootstrapGroups(ctx context.Context, actor pgtype.UUID) error {
	_, err := withTx(ctx, s.pool, func(q *db.Queries) (struct{}, error) {
		_, err := ensureRoot(ctx, q, actor)
		return struct{}{}, err
	})
	return err
}

func (s *Service) ListGroups(ctx context.Context, actor pgtype.UUID) ([]Group, error) {
	rows, err := s.q.ListOwnedComponentGroups(ctx, actor)
	if err != nil {
		return nil, err
	}
	groups := make([]Group, 0, len(rows))
	for _, row := range rows {
		groups = append(groups, groupFromList(row))
	}
	return groups, nil
}

func (s *Service) ListComponentGroupIDs(ctx context.Context, actor pgtype.UUID, componentID string) ([]string, error) {
	id, err := resourceID(componentID, "componentId")
	if err != nil {
		return nil, err
	}
	visible, err := s.q.ComponentIsVisible(ctx, db.ComponentIsVisibleParams{ComponentID: id, ActorID: actor})
	if err != nil {
		return nil, err
	}
	if !visible {
		return nil, notFound("component_repo.component_not_found", "componentId", componentID)
	}
	rows, err := s.q.ListOwnedComponentGroupIDsForComponent(ctx, db.ListOwnedComponentGroupIDsForComponentParams{
		OwnerID: actor, ComponentID: id,
	})
	if err != nil {
		return nil, err
	}
	ids := make([]string, 0, len(rows))
	for _, row := range rows {
		ids = append(ids, uuidutil.String(row))
	}
	return ids, nil
}

// SearchGroupComponents 在同一 owner/group 可见性边界内执行复合查询；每个文字或尺寸条件都必须满足。
// 条件在进入 SQL 前完成裁剪、去重和尺寸解析；尺寸条件编码为内部 JSON 数组，避免动态拼接 SQL。
func (s *Service) SearchGroupComponents(ctx context.Context, actor pgtype.UUID, groupID string, input ComponentGroupSearchRequest) (ComponentGroupSearchPage, error) {
	id, err := resourceID(groupID, "groupId")
	if err != nil {
		return ComponentGroupSearchPage{}, err
	}
	if _, err := s.q.GetOwnedComponentGroup(ctx, db.GetOwnedComponentGroupParams{GroupID: id, OwnerID: actor}); errors.Is(err, pgx.ErrNoRows) {
		return ComponentGroupSearchPage{}, notFound("component_repo.group_not_found", "groupId", groupID)
	} else if err != nil {
		return ComponentGroupSearchPage{}, err
	}
	if len(input.Queries) > maxSearchConditions {
		return ComponentGroupSearchPage{}, validationError("query")
	}
	if len(input.Statuses) > 16 {
		return ComponentGroupSearchPage{}, validationError("statuses")
	}
	statuses := make([]string, 0, len(input.Statuses))
	seenStatuses := make(map[string]struct{}, len(input.Statuses))
	for _, status := range input.Statuses {
		// Component 列表只公开草稿与已发布状态；archived 是软删除实现细节，Import/Task 状态不得混入。
		if status != "draft" && status != "active" {
			return ComponentGroupSearchPage{}, validationError("statuses")
		}
		if _, exists := seenStatuses[status]; exists {
			continue
		}
		seenStatuses[status] = struct{}{}
		statuses = append(statuses, status)
	}
	page := normalizePage(input.PageRequest)
	locale := displayLocale(input.Locale)
	textFilters := make([]string, 0, len(input.Queries))
	sizeFilters := make([]componentSizeFilter, 0, len(input.Queries))
	seenQueries := make(map[string]struct{}, len(input.Queries))
	for _, rawQuery := range input.Queries {
		query := strings.TrimSpace(rawQuery)
		if query == "" {
			continue
		}
		if len(query) > 200 {
			return ComponentGroupSearchPage{}, validationError("query")
		}
		normalizedQuery := strings.ToLower(query)
		if _, exists := seenQueries[normalizedQuery]; exists {
			continue
		}
		seenQueries[normalizedQuery] = struct{}{}
		if sizeFilter, ok := parseComponentSizeQuery(query); ok {
			sizeFilters = append(sizeFilters, sizeFilter)
			continue
		}
		textFilters = append(textFilters, query)
	}
	sizeFiltersJSON, err := json.Marshal(sizeFilters)
	if err != nil {
		return ComponentGroupSearchPage{}, err
	}
	rows, err := s.q.SearchComponentGroupComponents(ctx, db.SearchComponentGroupComponentsParams{
		Locale: locale, OwnerID: actor, GroupID: id, StatusFilters: statuses, TextFilters: textFilters,
		SizeFilters: sizeFiltersJSON,
		PageOffset:  int32((page.Page - 1) * page.PageSize), PageSize: int32(page.PageSize),
	})
	if err != nil {
		return ComponentGroupSearchPage{}, err
	}
	items := make([]Component, 0, len(rows))
	for _, row := range rows {
		items = append(items, componentFromGroupSearch(row))
	}
	counts, err := s.q.CountComponentGroupStatuses(ctx, db.CountComponentGroupStatusesParams{
		Locale: locale, GroupID: id, OwnerID: actor, TextFilters: textFilters,
		SizeFilters: sizeFiltersJSON,
	})
	if err != nil {
		return ComponentGroupSearchPage{}, err
	}
	statusCounts := make(map[string]int64, len(counts))
	for _, count := range counts {
		statusCounts[count.Status] = count.ComponentCount
	}
	var total int64
	if len(statuses) == 0 {
		for _, count := range statusCounts {
			total += count
		}
	} else {
		for _, status := range statuses {
			total += statusCounts[status]
		}
	}
	totalPages := 0
	if total > 0 {
		totalPages = int((total + int64(page.PageSize) - 1) / int64(page.PageSize))
	}
	return ComponentGroupSearchPage{Items: items, Total: total, Page: page.Page, PageSize: page.PageSize, TotalPages: totalPages, StatusCounts: statusCounts}, nil
}

// parseComponentSizeQuery 只把完整的二维或三维表达式识别为尺寸搜索，避免普通名称中的数字被误判。
// 尺寸先升序归一化：三值逐维匹配；两值由 SQL 枚举 ab/ac/bc，保持与 Box 轴方向无关。
func parseComponentSizeQuery(query string) (componentSizeFilter, bool) {
	matches := componentSizeQueryPattern.FindStringSubmatch(query)
	if matches == nil {
		return componentSizeFilter{}, false
	}
	values := make([]float64, 0, 3)
	for _, raw := range matches[1:] {
		if raw == "" {
			continue
		}
		value, err := strconv.ParseFloat(raw, 64)
		if err != nil {
			return componentSizeFilter{}, false
		}
		values = append(values, value)
	}
	if len(values) != 2 && len(values) != 3 {
		return componentSizeFilter{}, false
	}
	sort.Float64s(values)
	filter := componentSizeFilter{DimensionCount: int32(len(values)), A: values[0], B: values[1]}
	if len(values) == 3 {
		filter.C = values[2]
	}
	return filter, true
}

func (s *Service) CreateGroup(ctx context.Context, actor pgtype.UUID, input CreateGroupInput) (Group, error) {
	name, locale, err := validateGroupContent(input.Name, input.ContentLocale)
	if err != nil {
		return Group{}, err
	}
	return withTx(ctx, s.pool, func(q *db.Queries) (Group, error) {
		parentID, err := optionalParent(ctx, q, actor, input.ParentGroupID)
		if err != nil {
			return Group{}, err
		}
		depth, err := q.ComponentGroupDepth(ctx, db.ComponentGroupDepthParams{GroupID: parentID, OwnerID: actor})
		if err != nil {
			return Group{}, err
		}
		if depth+1 > maxGroupDepth {
			return Group{}, apierror.New("component_repo.group_depth_exceeded", http.StatusConflict, map[string]any{"maximumDepth": maxGroupDepth})
		}
		id, err := uuidutil.New()
		if err != nil {
			return Group{}, err
		}
		row, err := q.CreateComponentGroup(ctx, db.CreateComponentGroupParams{
			ID: id, OwnerID: actor, ParentGroupID: parentID, Name: &name,
			NormalizedName: pointer(normalizeGroupName(name)), ContentLocale: &locale, SortOrder: input.SortOrder,
		})
		if err != nil {
			return Group{}, mapDatabaseError(err, "component_repo.group_name_duplicate")
		}
		return groupFromDB(row, depth+1), nil
	})
}

func (s *Service) UpdateGroup(ctx context.Context, actor pgtype.UUID, groupID string, input UpdateGroupInput) (Group, error) {
	id, err := resourceID(groupID, "groupId")
	if err != nil {
		return Group{}, err
	}
	if input.Name == nil && input.ContentLocale == nil && input.SortOrder == nil {
		return Group{}, validationError("body")
	}
	name := ""
	if input.Name != nil {
		name = *input.Name
		if strings.TrimSpace(name) == "" || len(name) > 100 {
			return Group{}, validationError("name")
		}
	}
	locale := ""
	if input.ContentLocale != nil {
		var ok bool
		locale, ok = NormalizeLocale(*input.ContentLocale)
		if !ok {
			return Group{}, validationError("contentLocale")
		}
	}
	return withTx(ctx, s.pool, func(q *db.Queries) (Group, error) {
		row, err := q.UpdateOwnedComponentGroup(ctx, db.UpdateOwnedComponentGroupParams{
			SetName: input.Name != nil, Name: name, NormalizedName: normalizeGroupName(name),
			SetContentLocale: input.ContentLocale != nil, ContentLocale: locale,
			SetSortOrder: input.SortOrder != nil, SortOrder: int32Value(input.SortOrder),
			GroupID: id, OwnerID: actor,
		})
		if errors.Is(err, pgx.ErrNoRows) {
			return Group{}, notFound("component_repo.group_not_found", "groupId", groupID)
		}
		if err != nil {
			return Group{}, mapDatabaseError(err, "component_repo.group_name_duplicate")
		}
		depth, err := q.ComponentGroupDepth(ctx, db.ComponentGroupDepthParams{GroupID: id, OwnerID: actor})
		return groupFromDB(row, depth), err
	})
}

func (s *Service) MoveGroup(ctx context.Context, actor pgtype.UUID, groupID string, input MoveGroupInput) (Group, error) {
	id, err := resourceID(groupID, "groupId")
	if err != nil {
		return Group{}, err
	}
	parentID, err := resourceID(input.ParentGroupID, "parentGroupId")
	if err != nil {
		return Group{}, err
	}
	return withTx(ctx, s.pool, func(q *db.Queries) (Group, error) {
		group, err := q.GetOwnedComponentGroup(ctx, db.GetOwnedComponentGroupParams{GroupID: id, OwnerID: actor})
		if errors.Is(err, pgx.ErrNoRows) || group.GroupType != "custom" {
			return Group{}, notFound("component_repo.group_not_found", "groupId", groupID)
		}
		if _, err := q.GetOwnedComponentGroup(ctx, db.GetOwnedComponentGroupParams{GroupID: parentID, OwnerID: actor}); err != nil {
			return Group{}, notFound("component_repo.group_not_found", "groupId", input.ParentGroupID)
		}
		descendants, err := q.ListComponentGroupDescendantIDs(ctx, db.ListComponentGroupDescendantIDsParams{GroupID: id, OwnerID: actor})
		if err != nil {
			return Group{}, err
		}
		for _, descendant := range descendants {
			if uuidutil.Equal(descendant, parentID) {
				return Group{}, apierror.New("component_repo.group_cycle", http.StatusConflict, nil)
			}
		}
		parentDepth, err := q.ComponentGroupDepth(ctx, db.ComponentGroupDepthParams{GroupID: parentID, OwnerID: actor})
		if err != nil {
			return Group{}, err
		}
		subtreeDepth, err := q.ComponentGroupSubtreeDepth(ctx, db.ComponentGroupSubtreeDepthParams{GroupID: id, OwnerID: actor})
		if err != nil {
			return Group{}, err
		}
		if parentDepth+1+subtreeDepth > maxGroupDepth {
			return Group{}, apierror.New("component_repo.group_depth_exceeded", http.StatusConflict, map[string]any{"maximumDepth": maxGroupDepth})
		}
		row, err := q.MoveOwnedComponentGroup(ctx, db.MoveOwnedComponentGroupParams{
			ParentGroupID: parentID, SortOrder: input.SortOrder, GroupID: id, OwnerID: actor,
		})
		if err != nil {
			return Group{}, mapDatabaseError(err, "component_repo.group_name_duplicate")
		}
		return groupFromDB(row, parentDepth+1), nil
	})
}

func (s *Service) DeleteGroup(ctx context.Context, actor pgtype.UUID, groupID string) error {
	id, err := resourceID(groupID, "groupId")
	if err != nil {
		return err
	}
	_, err = withTx(ctx, s.pool, func(q *db.Queries) (struct{}, error) {
		_, err := q.DeleteOwnedComponentGroup(ctx, db.DeleteOwnedComponentGroupParams{GroupID: id, OwnerID: actor})
		if errors.Is(err, pgx.ErrNoRows) {
			return struct{}{}, notFound("component_repo.group_not_found", "groupId", groupID)
		}
		return struct{}{}, err
	})
	return err
}

func (s *Service) AddGroupMember(ctx context.Context, actor pgtype.UUID, groupID, componentID string) error {
	groupUUID, err := resourceID(groupID, "groupId")
	if err != nil {
		return err
	}
	componentUUID, err := resourceID(componentID, "componentId")
	if err != nil {
		return err
	}
	_, err = withTx(ctx, s.pool, func(q *db.Queries) (struct{}, error) {
		group, err := q.GetOwnedComponentGroup(ctx, db.GetOwnedComponentGroupParams{GroupID: groupUUID, OwnerID: actor})
		if errors.Is(err, pgx.ErrNoRows) || group.GroupType != "custom" {
			return struct{}{}, notFound("component_repo.group_not_found", "groupId", groupID)
		}
		visible, err := q.ComponentIsVisible(ctx, db.ComponentIsVisibleParams{ComponentID: componentUUID, ActorID: actor})
		if err != nil {
			return struct{}{}, err
		}
		if !visible {
			return struct{}{}, notFound("component_repo.component_not_found", "componentId", componentID)
		}
		_, err = q.AddComponentGroupMembership(ctx, db.AddComponentGroupMembershipParams{
			OwnerID: actor, GroupID: groupUUID, ComponentID: componentUUID, AddedBy: actor,
		})
		if errors.Is(err, pgx.ErrNoRows) {
			err = nil
		}
		return struct{}{}, err
	})
	return err
}

func (s *Service) RemoveGroupMember(ctx context.Context, actor pgtype.UUID, groupID, componentID string) error {
	groupUUID, err := resourceID(groupID, "groupId")
	if err != nil {
		return err
	}
	componentUUID, err := resourceID(componentID, "componentId")
	if err != nil {
		return err
	}
	_, err = withTx(ctx, s.pool, func(q *db.Queries) (struct{}, error) {
		_, err := q.RemoveComponentGroupMembership(ctx, db.RemoveComponentGroupMembershipParams{OwnerID: actor, GroupID: groupUUID, ComponentID: componentUUID})
		if errors.Is(err, pgx.ErrNoRows) {
			err = nil
		}
		return struct{}{}, err
	})
	return err
}

func (s *Service) ListGroupMembers(ctx context.Context, actor pgtype.UUID, groupID, localeInput string, page PageRequest) (GroupMemberPage, error) {
	groupUUID, err := resourceID(groupID, "groupId")
	if err != nil {
		return GroupMemberPage{}, err
	}
	if _, err := s.q.GetOwnedComponentGroup(ctx, db.GetOwnedComponentGroupParams{GroupID: groupUUID, OwnerID: actor}); errors.Is(err, pgx.ErrNoRows) {
		return GroupMemberPage{}, notFound("component_repo.group_not_found", "groupId", groupID)
	} else if err != nil {
		return GroupMemberPage{}, err
	}
	page = normalizePage(page)
	rows, err := s.q.ListComponentGroupMembers(ctx, db.ListComponentGroupMembersParams{
		Locale: displayLocale(localeInput), OwnerID: actor, GroupID: groupUUID,
		PageOffset: int32((page.Page - 1) * page.PageSize), PageSize: int32(page.PageSize),
	})
	if err != nil {
		return GroupMemberPage{}, err
	}
	items := make([]GroupMember, 0, len(rows))
	for _, row := range rows {
		items = append(items, groupMemberFromDB(row))
	}
	return GroupMemberPage{Items: items, Page: page.Page, PageSize: page.PageSize}, nil
}

// Star 幂等收藏一个公开非本人 Component。资格检查只读取目标状态和既有关系，收藏不会授予额外权限。
func (s *Service) Star(ctx context.Context, actor pgtype.UUID, componentID string) (Star, error) {
	id, err := resourceID(componentID, "componentId")
	if err != nil {
		return Star{}, err
	}
	return withTx(ctx, s.pool, func(q *db.Queries) (Star, error) {
		// Star 创建参与 Component activity 共享锁，使归档/删除的独占清理边界可以等待已在途收藏，
		// 并阻止资格检查之后、生命周期清理之后又提交一条新的 Star 关系。
		if err := q.AcquireSharedComponentActivityLock(ctx, componentactivity.LockKey(id)); err != nil {
			return Star{}, err
		}
		target, err := q.GetComponentStarTarget(ctx, db.GetComponentStarTargetParams{ActorID: actor, ComponentID: id})
		if errors.Is(err, pgx.ErrNoRows) {
			return Star{}, notFound("component_repo.component_not_found", "componentId", componentID)
		}
		if err != nil {
			return Star{}, err
		}
		if uuidutil.Equal(target.OwnerID, actor) {
			return Star{}, apierror.New("component_repo.star_own_component_forbidden", http.StatusConflict, nil)
		}
		// 已收藏是 PUT 的幂等成功路径：返回首次时间，不重复写库，也不让后续计数规模进入资格检查。
		if target.StarredAt.Valid {
			return Star{ComponentID: componentID, StarredAt: target.StarredAt.Time}, nil
		}
		if target.Status != "active" || !target.PublicVersionAvailable {
			return Star{}, apierror.New("component_repo.star_component_unavailable", http.StatusConflict, nil)
		}
		row, err := q.CreateComponentStar(ctx, db.CreateComponentStarParams{ActorID: actor, ComponentID: id})
		if err != nil {
			return Star{}, err
		}
		return Star{ComponentID: uuidutil.String(row.ComponentID), StarredAt: row.StarredAt.Time}, nil
	})
}

// Unstar 幂等删除 actor 的收藏；即使 Component 后续不可见，actor 仍能清理自己的关系。
func (s *Service) Unstar(ctx context.Context, actor pgtype.UUID, componentID string) error {
	id, err := resourceID(componentID, "componentId")
	if err != nil {
		return err
	}
	_, err = withTx(ctx, s.pool, func(q *db.Queries) (struct{}, error) {
		_, err := q.DeleteComponentStar(ctx, db.DeleteComponentStarParams{ActorID: actor, ComponentID: id})
		if errors.Is(err, pgx.ErrNoRows) {
			err = nil
		}
		return struct{}{}, err
	})
	return err
}

func NormalizeLocale(input string) (string, bool) {
	normalized := strings.TrimSpace(strings.ReplaceAll(input, "_", "-"))
	lower := strings.ToLower(normalized)
	switch {
	case lower == "zh" || lower == "zh-cn" || strings.HasPrefix(lower, "zh-hans-"):
		return "zh-CN", true
	case lower == "en" || lower == "en-us" || strings.HasPrefix(lower, "en-"):
		return "en-US", true
	default:
		return "", false
	}
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
			if retryableTransaction(runErr) {
				continue
			}
			return zero, runErr
		}
		if err = tx.Commit(ctx); err == nil {
			return value, nil
		}
		if !retryableTransaction(err) {
			return zero, err
		}
	}
	return zero, apierror.New("request.conflict", http.StatusConflict, nil)
}

func retryableTransaction(err error) bool {
	var pgError *pgconn.PgError
	return errors.As(err, &pgError) && (pgError.Code == "40001" || pgError.Code == "40P01")
}

func resourceID(value, field string) (pgtype.UUID, error) {
	id, err := uuidutil.Parse(value)
	if err != nil {
		return pgtype.UUID{}, validationError(field)
	}
	return id, nil
}

func versionCreateParams(actor, componentID pgtype.UUID, input CreateVersionInput) (db.CreateComponentVersionParams, error) {
	id, err := uuidutil.New()
	if err != nil {
		return db.CreateComponentVersionParams{}, err
	}
	candidate, err := resourceID(input.ComponentCandidateID, "componentCandidateId")
	if err != nil {
		return db.CreateComponentVersionParams{}, err
	}
	if strings.TrimSpace(input.Version) == "" || input.Revision < 1 {
		return db.CreateComponentVersionParams{}, validationError("version")
	}
	if (input.ReleaseNote == nil) != (input.ReleaseNoteLocale == nil) {
		return db.CreateComponentVersionParams{}, validationError("releaseNoteLocale")
	}
	if input.ReleaseNoteLocale != nil {
		normalized, ok := NormalizeLocale(*input.ReleaseNoteLocale)
		if !ok {
			return db.CreateComponentVersionParams{}, validationError("releaseNoteLocale")
		}
		input.ReleaseNoteLocale = &normalized
	}
	metadata := input.Metadata
	if len(metadata) == 0 {
		metadata = json.RawMessage(`{}`)
	}
	if !json.Valid(metadata) {
		return db.CreateComponentVersionParams{}, validationError("metadata")
	}
	return db.CreateComponentVersionParams{
		ID: id, ComponentID: componentID, ComponentCandidateID: candidate,
		VersionLabel: strings.TrimSpace(input.Version), Revision: input.Revision,
		ReleaseNote: input.ReleaseNote, ReleaseNoteLocale: input.ReleaseNoteLocale,
		Metadata: metadata, CreatedBy: actor,
	}, nil
}

func optionalParent(ctx context.Context, q *db.Queries, actor pgtype.UUID, value *string) (pgtype.UUID, error) {
	if value == nil {
		root, err := ensureRoot(ctx, q, actor)
		return root.ID, err
	}
	id, err := resourceID(*value, "parentGroupId")
	if err != nil {
		return pgtype.UUID{}, err
	}
	if _, err := q.GetOwnedComponentGroup(ctx, db.GetOwnedComponentGroupParams{GroupID: id, OwnerID: actor}); errors.Is(err, pgx.ErrNoRows) {
		return pgtype.UUID{}, notFound("component_repo.group_not_found", "groupId", *value)
	} else if err != nil {
		return pgtype.UUID{}, err
	}
	return id, nil
}

func ensureRoot(ctx context.Context, q *db.Queries, actor pgtype.UUID) (db.ComponentRepoComponentGroup, error) {
	id, err := uuidutil.New()
	if err != nil {
		return db.ComponentRepoComponentGroup{}, err
	}
	return q.EnsureComponentRootGroup(ctx, db.EnsureComponentRootGroupParams{ID: id, OwnerID: actor})
}

func validateGroupContent(nameInput, localeInput string) (string, string, error) {
	name := nameInput
	if strings.TrimSpace(name) == "" || len(name) > 100 {
		return "", "", validationError("name")
	}
	locale, ok := NormalizeLocale(localeInput)
	if !ok {
		return "", "", validationError("contentLocale")
	}
	return name, locale, nil
}

func normalizeGroupName(name string) string {
	return strings.ToLower(strings.Join(strings.Fields(name), " "))
}

func displayLocale(input string) string {
	locale, ok := NormalizeLocale(input)
	if !ok {
		return "zh-CN"
	}
	return locale
}

func normalizePage(page PageRequest) PageRequest {
	if page.Page < 1 {
		page.Page = 1
	}
	if page.PageSize < 1 {
		page.PageSize = defaultPageSize
	}
	if page.PageSize > maxPageSize {
		page.PageSize = maxPageSize
	}
	if page.Page > 1_000_000 {
		page.Page = 1_000_000
	}
	return page
}

func mapDatabaseError(err error, conflictCode string) error {
	var pgError *pgconn.PgError
	if !errors.As(err, &pgError) {
		return err
	}
	switch pgError.Code {
	case "23505":
		return apierror.New(conflictCode, http.StatusConflict, nil)
	case "23503":
		return apierror.New("component_repo.version_source_not_found_failed", http.StatusUnprocessableEntity, nil)
	case "23514", "23502":
		return apierror.New("request.validation_failed", http.StatusUnprocessableEntity, nil)
	default:
		return err
	}
}

func validationError(field string) *apierror.Error {
	return apierror.New("request.validation_failed", http.StatusUnprocessableEntity, map[string]any{"field": field})
}

func notFound(code, parameter, value string) *apierror.Error {
	return apierror.New(code, http.StatusNotFound, map[string]any{parameter: value})
}

func cleanOptional(value *string) *string {
	if value == nil {
		return nil
	}
	cleaned := strings.TrimSpace(*value)
	return &cleaned
}

func nonNilStrings(values []string) []string {
	if values == nil {
		return []string{}
	}
	return values
}

func nonNilStringPointer(values *[]string) []string {
	if values == nil || *values == nil {
		return []string{}
	}
	return *values
}

func int32Value(value *int32) int32 {
	if value == nil {
		return 0
	}
	return *value
}

func pointer[T any](value T) *T { return &value }
