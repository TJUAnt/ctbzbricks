package component

import (
	"encoding/json"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/componentdiff"
)

type PageRequest struct {
	Page     int
	PageSize int
}

// ComponentListRequest 描述 Component 目录 keyset 请求；Cursor 是服务端签发的不透明边界。
type ComponentListRequest struct {
	Limit    int
	Cursor   string
	Locale   string
	Query    string
	Category string
	Status   string
}

// ComponentSearchFilters 是 Component 列表共用的结构化筛选；所有非空字段按 AND 组合。
// 名称与机器 ID 保持独立语义，宽/深允许平面旋转，高度始终使用 plate 轴。
type ComponentSearchFilters struct {
	Name        string
	ComponentID string
	WidthStud   *float64
	DepthStud   *float64
	HeightPlate *float64
}

// PublicFeedRequest 描述组件库广场查询；Cursor 只能继续相同结构化筛选下的发布事件流。
type PublicFeedRequest struct {
	Limit  int
	Cursor string
	ComponentSearchFilters
}

// PublicFeedPublisher 是发布事件中已验证的发布人身份投影；公开资料尚未建模时只返回稳定用户 ID。
type PublicFeedPublisher struct {
	ID string `json:"id"`
}

// PublicFeedImage 是 Worker 生成的不可变 3:2 派生图定位；内部 storage key 不进入公共响应。
type PublicFeedImage struct {
	ArtifactID string `json:"artifactId"`
	URL        string `json:"url"`
	Format     string `json:"format"`
	SHA256     string `json:"sha256"`
	ByteLength int64  `json:"byteLength"`
	Width      int    `json:"width"`
	Height     int    `json:"height"`
}

// PublicFeedRender 表达 Feed 准入终态。fallback 仍是已发布事件，但没有高质量图片。
type PublicFeedRender struct {
	Status      string           `json:"status"`
	AvailableAt time.Time        `json:"availableAt"`
	Image       *PublicFeedImage `json:"image"`
}

// PublicFeedItem 保留发布事件身份，并嵌入当前可见的用户 Component 展示投影。
// 发布版本字段描述事件发生时发布的不可变版本，Component 字段则反映当前公开状态。
type PublicFeedItem struct {
	EventID            string              `json:"eventId"`
	OccurredAt         time.Time           `json:"occurredAt"`
	ComponentVersionID string              `json:"componentVersionId"`
	Version            string              `json:"version"`
	Revision           int32               `json:"revision"`
	PublishedAt        *time.Time          `json:"publishedAt"`
	ReleaseNote        *string             `json:"releaseNote"`
	ReleaseNoteLocale  *string             `json:"releaseNoteLocale"`
	Publisher          PublicFeedPublisher `json:"publisher"`
	Render             PublicFeedRender    `json:"render"`
	Component          Component           `json:"component"`
}

// PublicFeedPage 使用不透明 keyset cursor 继续全局事件流，不执行 exact COUNT。
type PublicFeedPage struct {
	Items      []PublicFeedItem `json:"items"`
	NextCursor *string          `json:"nextCursor"`
}

// ComponentPage 返回已固定顺序的一页目录与可选续页游标，不计算全量精确总数。
type ComponentPage struct {
	Items      []Component `json:"items"`
	NextCursor *string     `json:"nextCursor"`
}

// StarListRequest 描述当前 actor 的收藏列表查询；结构化字段与分组、公共 Feed 使用同一 AND 语义。
type StarListRequest struct {
	PageRequest
	Locale string
	ComponentSearchFilters
	Category string
	Sort     string
}

// StarPage 返回稳定分页的可见个人收藏；删除清理中的内部残留关系不进入公共契约。
type StarPage struct {
	Items      []StarredComponent `json:"items"`
	Page       int                `json:"page"`
	PageSize   int                `json:"pageSize"`
	Total      int64              `json:"total"`
	TotalPages int                `json:"totalPages"`
}

// Component 是面向当前 actor 的展示投影；Star 与 Watch 都不授予资源权限。
type Component struct {
	ID                 string          `json:"id"`
	OwnerID            *string         `json:"ownerId"`
	ContentKind        string          `json:"contentKind"`
	ContentLocale      string          `json:"contentLocale"`
	Name               string          `json:"name"`
	Description        *string         `json:"description"`
	Tags               []string        `json:"tags"`
	Category           *string         `json:"category"`
	Status             string          `json:"status"`
	CurrentVersionID   *string         `json:"currentVersionId"`
	LogicalSize        *LogicalSize    `json:"logicalSize"`
	Metadata           json.RawMessage `json:"metadata"`
	OwnedByActor       bool            `json:"ownedByActor"`
	StarredByActor     bool            `json:"starredByActor"`
	StarCount          int64           `json:"starCount"`
	Watch              *WatchState     `json:"watch,omitempty"`
	TranslationMissing bool            `json:"translationMissing"`
	CreatedAt          time.Time       `json:"createdAt"`
	UpdatedAt          time.Time       `json:"updatedAt"`
}

// WatchState 是当前 actor 的 Component 更新订阅投影；Level 是稳定机器值，不在 API 层翻译。
type WatchState struct {
	Watching  bool       `json:"watching"`
	Level     *string    `json:"level"`
	WatchedAt *time.Time `json:"watchedAt"`
}

type LogicalSize struct {
	WidthStud   float64 `json:"widthStud"`
	DepthStud   float64 `json:"depthStud"`
	HeightPlate float64 `json:"heightPlate"`
}

type CreateComponentInput struct {
	Name          string   `json:"name"`
	Description   *string  `json:"description"`
	Tags          []string `json:"tags"`
	Category      *string  `json:"category"`
	ContentLocale string   `json:"contentLocale"`
}

type UpdateComponentInput struct {
	Name          *string        `json:"name"`
	Description   OptionalString `json:"description"`
	Tags          *[]string      `json:"tags"`
	Category      OptionalString `json:"category"`
	ContentLocale *string        `json:"contentLocale"`
}

type OptionalString struct {
	Set   bool
	Value *string
}

func (value *OptionalString) UnmarshalJSON(data []byte) error {
	value.Set = true
	if string(data) == "null" {
		value.Value = nil
		return nil
	}
	var decoded string
	if err := json.Unmarshal(data, &decoded); err != nil {
		return err
	}
	value.Value = &decoded
	return nil
}

type VersionPage struct {
	Items    []ComponentVersion `json:"items"`
	Page     int                `json:"page"`
	PageSize int                `json:"pageSize"`
}

type ComponentVersion struct {
	ID                      string          `json:"id"`
	ComponentID             string          `json:"componentId"`
	ComponentCandidateID    *string         `json:"componentCandidateId"`
	Version                 string          `json:"version"`
	Revision                int32           `json:"revision"`
	Status                  string          `json:"status"`
	SourceArtifactID        string          `json:"sourceArtifactId"`
	ExchangeArtifactID      *string         `json:"exchangeArtifactId"`
	SceneSnapshotID         string          `json:"sceneSnapshotId"`
	ParserVersion           string          `json:"parserVersion"`
	PartLibraryVersionID    *string         `json:"partLibraryVersionId"`
	ValidationReportID      *string         `json:"validationReportId"`
	InterfaceSignature      string          `json:"interfaceSignature"`
	StructureHash           string          `json:"structureHash"`
	GeometryHash            string          `json:"geometryHash"`
	PreviewArtifactID       *string         `json:"previewArtifactId"`
	PreviewStatus           string          `json:"previewStatus"`
	PreviewGeneratorVersion *string         `json:"previewGeneratorVersion"`
	PreviewFailureCode      *string         `json:"previewFailureCode"`
	PreviewFailureParams    json.RawMessage `json:"previewFailureParams"`
	ReleaseNote             *string         `json:"releaseNote"`
	ReleaseNoteLocale       *string         `json:"releaseNoteLocale"`
	Metadata                json.RawMessage `json:"metadata"`
	CreatedAt               time.Time       `json:"createdAt"`
	PublishedAt             *time.Time      `json:"publishedAt"`
}

// VersionDiff 是当前版本相对导入基准版本的只读结构差异。
// ComparisonBasis 只使用 import_base_version 或 empty；版本标识、hash 与差异字段均为稳定机器数据。
type VersionDiff struct {
	VersionID         string  `json:"versionId"`
	BaseVersionID     *string `json:"baseVersionId"`
	ComparisonBasis   string  `json:"comparisonBasis"`
	StructureHash     string  `json:"structureHash"`
	GeometryHash      string  `json:"geometryHash"`
	BaseStructureHash *string `json:"baseStructureHash"`
	BaseGeometryHash  *string `json:"baseGeometryHash"`
	componentdiff.Result
}

type CreateVersionInput struct {
	ComponentCandidateID string          `json:"componentCandidateId"`
	Version              string          `json:"version"`
	Revision             int32           `json:"revision"`
	ReleaseNote          *string         `json:"releaseNote"`
	ReleaseNoteLocale    *string         `json:"releaseNoteLocale"`
	Metadata             json.RawMessage `json:"metadata"`
}

type UpdateVersionInput struct {
	Version           *string        `json:"version"`
	Revision          *int32         `json:"revision"`
	ReleaseNote       OptionalString `json:"releaseNote"`
	ReleaseNoteLocale OptionalString `json:"releaseNoteLocale"`
}

type Group struct {
	ID                   string    `json:"id"`
	OwnerID              string    `json:"ownerId"`
	ParentGroupID        *string   `json:"parentGroupId"`
	GroupType            string    `json:"groupType"`
	Name                 *string   `json:"name"`
	ContentLocale        *string   `json:"contentLocale"`
	SortOrder            int32     `json:"sortOrder"`
	Depth                int32     `json:"depth"`
	DirectComponentCount int64     `json:"directComponentCount"`
	CreatedAt            time.Time `json:"createdAt"`
	UpdatedAt            time.Time `json:"updatedAt"`
}

type ComponentGroupSearchRequest struct {
	PageRequest
	Locale string
	ComponentSearchFilters
	Statuses []string
}

type ComponentGroupSearchPage struct {
	Items        []Component      `json:"items"`
	Total        int64            `json:"total"`
	Page         int              `json:"page"`
	PageSize     int              `json:"pageSize"`
	TotalPages   int              `json:"totalPages"`
	StatusCounts map[string]int64 `json:"statusCounts"`
}

type CreateGroupInput struct {
	ParentGroupID *string `json:"parentGroupId"`
	Name          string  `json:"name"`
	ContentLocale string  `json:"contentLocale"`
	SortOrder     int32   `json:"sortOrder"`
}

type UpdateGroupInput struct {
	Name          *string `json:"name"`
	ContentLocale *string `json:"contentLocale"`
	SortOrder     *int32  `json:"sortOrder"`
}

type MoveGroupInput struct {
	ParentGroupID string `json:"parentGroupId"`
	SortOrder     int32  `json:"sortOrder"`
}

type GroupMemberPage struct {
	Items    []GroupMember `json:"items"`
	Page     int           `json:"page"`
	PageSize int           `json:"pageSize"`
}

type GroupMember struct {
	Component
	AddedAt time.Time `json:"addedAt"`
}

type MembershipInput struct {
	ComponentID string `json:"componentId"`
}

// Star 是 actor 对公开非本人 Component 的轻量收藏关系，不包含通知或授权语义。
type Star struct {
	ComponentID string    `json:"componentId"`
	StarredAt   time.Time `json:"starredAt"`
}

// StarredComponent 在 Component 投影之外保留个人收藏时间，用于稳定倒序分页。
type StarredComponent struct {
	Component
	StarredAt time.Time `json:"starredAt"`
}
