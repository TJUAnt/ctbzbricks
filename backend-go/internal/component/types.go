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

type ComponentListRequest struct {
	PageRequest
	Locale   string
	Query    string
	Category string
	Status   string
}

// ComponentPage 返回 actor 可见目录的稳定分页和总数；总数复用相同授权与过滤条件。
type ComponentPage struct {
	Items      []Component `json:"items"`
	Page       int         `json:"page"`
	PageSize   int         `json:"pageSize"`
	Total      int64       `json:"total"`
	TotalPages int         `json:"totalPages"`
}

// StarListRequest 描述当前 actor 的收藏列表查询；完整尺寸表达式复用分组搜索规范。
type StarListRequest struct {
	PageRequest
	Locale   string
	Query    string
	Category string
	Sort     string
}

// StarPage 返回稳定分页的个人收藏；RelationshipTotal 仅用于区分“从未收藏”和“关系存在但目标不可见”。
type StarPage struct {
	Items             []StarredComponent `json:"items"`
	Page              int                `json:"page"`
	PageSize          int                `json:"pageSize"`
	Total             int64              `json:"total"`
	TotalPages        int                `json:"totalPages"`
	RelationshipTotal int64              `json:"relationshipTotal"`
}

// Component 是面向当前 actor 的展示投影；Star 字段只描述收藏关系与聚合计数，不授予权限。
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
	TranslationMissing bool            `json:"translationMissing"`
	CreatedAt          time.Time       `json:"createdAt"`
	UpdatedAt          time.Time       `json:"updatedAt"`
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
	Locale   string
	Queries  []string
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
