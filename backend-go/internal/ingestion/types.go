package ingestion

import (
	"encoding/json"
	"time"
)

type Failure struct {
	Code   string          `json:"code"`
	Params json.RawMessage `json:"params"`
}

type Import struct {
	ID                   string          `json:"id"`
	SourceArtifactID     string          `json:"sourceArtifactId"`
	ExchangeArtifactID   *string         `json:"exchangeArtifactId"`
	TargetComponentID    *string         `json:"targetComponentId"`
	BaseVersionID        *string         `json:"baseVersionId"`
	Status               string          `json:"status"`
	ParserVersion        string          `json:"parserVersion"`
	PartLibraryVersionID *string         `json:"partLibraryVersionId"`
	TaskID               string          `json:"taskId"`
	CandidateID          *string         `json:"candidateId"`
	DraftVersionID       *string         `json:"draftVersionId"`
	ProcessingStatus     string          `json:"processingStatus"`
	PreviewTaskID        *string         `json:"previewTaskId"`
	Locale               string          `json:"locale"`
	Timezone             string          `json:"timezone"`
	Failure              *Failure        `json:"failure"`
	Metadata             json.RawMessage `json:"metadata"`
	CreatedAt            time.Time       `json:"createdAt"`
	StartedAt            *time.Time      `json:"startedAt"`
	CompletedAt          *time.Time      `json:"completedAt"`
}

// ImportListRequest 描述当前用户的导入历史筛选；ComponentID 只用于组件详情中的关联历史，不改变 owner 边界。
type ImportListRequest struct {
	Page             int
	PageSize         int
	ProcessingStatus string
	Query            string
	ComponentID      string
}

// ImportRecord 是导入历史的只读投影，不暴露对象存储位置和 Worker 内部 payload。
type ImportRecord struct {
	ID                   string     `json:"id"`
	SourceArtifactID     string     `json:"sourceArtifactId"`
	OriginalFilename     string     `json:"originalFilename"`
	FileSize             int64      `json:"fileSize"`
	MimeType             string     `json:"mimeType"`
	ImportKind           string     `json:"importKind"`
	TargetComponentID    *string    `json:"targetComponentId"`
	ComponentID          *string    `json:"componentId"`
	BaseVersionID        *string    `json:"baseVersionId"`
	Status               string     `json:"status"`
	ProcessingStatus     string     `json:"processingStatus"`
	ParserVersion        string     `json:"parserVersion"`
	PartLibraryVersionID *string    `json:"partLibraryVersionId"`
	TaskID               string     `json:"taskId"`
	CandidateID          *string    `json:"candidateId"`
	DraftVersionID       *string    `json:"draftVersionId"`
	PreviewTaskID        *string    `json:"previewTaskId"`
	Failure              *Failure   `json:"failure"`
	CreatedAt            time.Time  `json:"createdAt"`
	StartedAt            *time.Time `json:"startedAt"`
	CompletedAt          *time.Time `json:"completedAt"`
}

// ImportPage 返回分页导入记录和未受当前状态筛选影响的状态计数。
type ImportPage struct {
	Items        []ImportRecord   `json:"items"`
	Total        int64            `json:"total"`
	Page         int              `json:"page"`
	PageSize     int              `json:"pageSize"`
	TotalPages   int              `json:"totalPages"`
	StatusCounts map[string]int64 `json:"statusCounts"`
}

type SceneSnapshot struct {
	ID            string          `json:"id"`
	SchemaVersion string          `json:"schemaVersion"`
	ParserVersion string          `json:"parserVersion"`
	RootModelID   *string         `json:"rootModelId"`
	Document      json.RawMessage `json:"document"`
	BOM           json.RawMessage `json:"bom"`
	ParseIssues   json.RawMessage `json:"parseIssues"`
	CreatedAt     time.Time       `json:"createdAt"`
}

type Candidate struct {
	ID                 string          `json:"id"`
	ImportID           string          `json:"importId"`
	Status             string          `json:"status"`
	Summary            json.RawMessage `json:"summary"`
	ReviewDecisions    json.RawMessage `json:"reviewDecisions"`
	InterfaceSignature string          `json:"interfaceSignature"`
	StructureHash      string          `json:"structureHash"`
	GeometryHash       string          `json:"geometryHash"`
	ComponentID        *string         `json:"componentId"`
	DraftVersionID     *string         `json:"draftVersionId"`
	SceneSnapshot      SceneSnapshot   `json:"sceneSnapshot"`
	CreatedAt          time.Time       `json:"createdAt"`
	UpdatedAt          time.Time       `json:"updatedAt"`
}
