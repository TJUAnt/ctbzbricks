package componentwatch

import "time"

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
// Component 名称遵守用户原文/official reviewed translation 边界，ReleaseNote 始终保持作者原文。
type FeedItem struct {
	EventID            string     `json:"eventId"`
	EventType          string     `json:"eventType"`
	OccurredAt         time.Time  `json:"occurredAt"`
	ComponentID        string     `json:"componentId"`
	ContentKind        string     `json:"contentKind"`
	ContentLocale      string     `json:"contentLocale"`
	ComponentName      string     `json:"componentName"`
	Category           *string    `json:"category"`
	ComponentVersionID string     `json:"componentVersionId"`
	VersionLabel       string     `json:"version"`
	Revision           int32      `json:"revision"`
	PublishedAt        *time.Time `json:"publishedAt"`
	ReleaseNote        *string    `json:"releaseNote"`
	ReleaseNoteLocale  *string    `json:"releaseNoteLocale"`
	TranslationMissing bool       `json:"translationMissing"`
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
