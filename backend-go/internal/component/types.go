package component

import (
	"encoding/json"
	"time"
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

type ComponentPage struct {
	Items    []Component `json:"items"`
	Page     int         `json:"page"`
	PageSize int         `json:"pageSize"`
}

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
	Subscribed         bool            `json:"subscribed"`
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
	Query    string
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

type Subscription struct {
	ComponentID  string    `json:"componentId"`
	SubscribedAt time.Time `json:"subscribedAt"`
}
