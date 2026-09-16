package componentwatch

import (
	"encoding/json"
	"time"
)

// ReleasesOnlyLevel 是 WATCH-1 唯一允许的稳定订阅级别机器值。
const ReleasesOnlyLevel = "releases_only"

// Watch 表示 actor 对一个公开非本人 Component 的更新订阅有效区间。
// Level 是稳定机器值；展示文案必须由前端 typed semantic key 提供。
type Watch struct {
	ComponentID string    `json:"componentId"`
	Watching    bool      `json:"watching"`
	Level       string    `json:"level"`
	WatchedAt   time.Time `json:"watchedAt"`
}

// WatchInput 是 Watch PUT 的严格输入；Feed 在读取时使用当前 locale，不在偏好关系中冻结最终展示上下文。
type WatchInput struct {
	Level string `json:"level"`
}

// WatchListItem 是“我的订阅”的只读投影，不公开 watcher 数量或其他 actor 身份。
type WatchListItem struct {
	ComponentID        string     `json:"componentId"`
	ContentKind        string     `json:"contentKind"`
	ContentLocale      string     `json:"contentLocale"`
	Name               string     `json:"name"`
	Category           *string    `json:"category"`
	CurrentVersionID   *string    `json:"currentVersionId"`
	VersionLabel       *string    `json:"version"`
	Revision           *int32     `json:"revision"`
	PublishedAt        *time.Time `json:"publishedAt"`
	Level              string     `json:"level"`
	WatchedAt          time.Time  `json:"watchedAt"`
	TranslationMissing bool       `json:"translationMissing"`
}

// WatchPage 使用不透明 keyset cursor；不执行与产品价值无关的 exact COUNT。
type WatchPage struct {
	Items      []WatchListItem `json:"items"`
	NextCursor *string         `json:"nextCursor"`
}

// ListRequest 描述 actor-scoped Watch 列表；Cursor 只能由同一筛选条件的上一页响应返回。
type ListRequest struct {
	Locale   string
	Limit    int
	Cursor   string
	Query    string
	Category string
}

// FeedItem 是读取时由当前 active Watch 与不可变发布事件关联得到的动态条目。
// 它与公共 Feed 共用卡片投影，但成员资格、时间窗口和 cursor 仍由 Watch 服务独立控制。
type FeedItem struct {
	EventID            string        `json:"eventId"`
	EventType          string        `json:"eventType"`
	OccurredAt         time.Time     `json:"occurredAt"`
	ComponentVersionID string        `json:"componentVersionId"`
	VersionLabel       string        `json:"version"`
	Revision           int32         `json:"revision"`
	PublishedAt        *time.Time    `json:"publishedAt"`
	ReleaseNote        *string       `json:"releaseNote"`
	ReleaseNoteLocale  *string       `json:"releaseNoteLocale"`
	Publisher          FeedPublisher `json:"publisher"`
	Render             FeedRender    `json:"render"`
	Component          FeedComponent `json:"component"`
}

// FeedPublisher 是事件发布人的稳定身份投影；公开资料未建模时只返回用户 ID。
type FeedPublisher struct {
	ID string `json:"id"`
}

// FeedImage 是 Worker 生成并通过当前请求签发的 3:2 派生图片。
type FeedImage struct {
	ArtifactID string `json:"artifactId"`
	URL        string `json:"url"`
	Format     string `json:"format"`
	SHA256     string `json:"sha256"`
	ByteLength int64  `json:"byteLength"`
	Width      int    `json:"width"`
	Height     int    `json:"height"`
}

// FeedRender 表达个人 Feed 的终态图片准入；fallback 仍代表可展示的发布事件。
type FeedRender struct {
	Status      string     `json:"status"`
	AvailableAt time.Time  `json:"availableAt"`
	Image       *FeedImage `json:"image"`
}

// FeedComponent 是事件卡片需要的当前 Component 展示投影，字段与公共 Feed 的 Component 契约一致。
type FeedComponent struct {
	ID                 string           `json:"id"`
	OwnerID            *string          `json:"ownerId"`
	ContentKind        string           `json:"contentKind"`
	ContentLocale      string           `json:"contentLocale"`
	Name               string           `json:"name"`
	Description        *string          `json:"description"`
	Tags               []string         `json:"tags"`
	Category           *string          `json:"category"`
	Status             string           `json:"status"`
	CurrentVersionID   *string          `json:"currentVersionId"`
	LogicalSize        *FeedLogicalSize `json:"logicalSize"`
	Metadata           json.RawMessage  `json:"metadata"`
	OwnedByActor       bool             `json:"ownedByActor"`
	StarredByActor     bool             `json:"starredByActor"`
	StarCount          int64            `json:"starCount"`
	Watch              *FeedWatchState  `json:"watch,omitempty"`
	TranslationMissing bool             `json:"translationMissing"`
	CreatedAt          time.Time        `json:"createdAt"`
	UpdatedAt          time.Time        `json:"updatedAt"`
}

// FeedLogicalSize 是卡片共享的当前逻辑尺寸投影。
type FeedLogicalSize struct {
	WidthStud   float64 `json:"widthStud"`
	DepthStud   float64 `json:"depthStud"`
	HeightPlate float64 `json:"heightPlate"`
}

// FeedWatchState 明确该卡片来自当前 active Watch，供详情交互保持一致。
type FeedWatchState struct {
	Watching  bool       `json:"watching"`
	Level     *string    `json:"level"`
	WatchedAt *time.Time `json:"watchedAt"`
}

// FeedPage 返回冻结的查询窗口与 keyset cursor；它不返回 exact count，也不物化收件人或已读状态。
type FeedPage struct {
	Items       []FeedItem `json:"items"`
	NextCursor  *string    `json:"nextCursor"`
	WindowStart time.Time  `json:"windowStart"`
}

// FeedRequest 描述当前 actor 的动态订阅 Feed。Since 为空时采用默认回溯窗口；cursor 会冻结首次窗口起点。
type FeedRequest struct {
	Locale string
	Limit  int
	Cursor string
	Since  string
}
