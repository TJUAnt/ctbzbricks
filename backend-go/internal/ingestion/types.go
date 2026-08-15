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
	Locale               string          `json:"locale"`
	Timezone             string          `json:"timezone"`
	Failure              *Failure        `json:"failure"`
	Metadata             json.RawMessage `json:"metadata"`
	CreatedAt            time.Time       `json:"createdAt"`
	StartedAt            *time.Time      `json:"startedAt"`
	CompletedAt          *time.Time      `json:"completedAt"`
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
