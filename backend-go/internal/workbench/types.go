package workbench

import (
	"encoding/json"
	"time"
)

const (
	RelationDetectionType       = "component.relations.detect"
	ValidationType              = "component.validate"
	PreviewMaterializeType      = "component.preview.materialize"
	PartPreviewMaterializeType  = "component.part_preview.materialize"
	RelationDetectionVersion    = "component-relation-detector-v1"
	ValidatorVersion            = "component-repo-validator-v1"
	PreviewGeneratorVersion     = "component-preview-structural-glb-v1"
	PartPreviewGeneratorVersion = "part-preview-ldraw-glb-v1"
)

type AcceptedTask struct {
	TaskID string `json:"taskId"`
	Status string `json:"status"`
}

type PartLibraryVersion struct {
	ID         string    `json:"id"`
	SourceName string    `json:"sourceName"`
	SourceHash string    `json:"sourceHash"`
	Status     string    `json:"status"`
	CreatedAt  time.Time `json:"createdAt"`
}

type PartPreview struct {
	PartLibraryVersionID string            `json:"partLibraryVersionId"`
	LDrawPartNum         string            `json:"ldrawPartNum"`
	Name                 string            `json:"name"`
	ContentLocale        string            `json:"contentLocale"`
	TranslationStatus    string            `json:"translationStatus"`
	Status               string            `json:"status"`
	GeneratorVersion     *string           `json:"generatorVersion"`
	TaskID               *string           `json:"taskId"`
	Geometry             *PartGeometry     `json:"geometry"`
	Model                *PartPreviewModel `json:"model"`
	Failure              *Failure          `json:"failure"`
}

type PartGeometry struct {
	BBox               PartBoundingBox `json:"bbox"`
	LogicalWidthStud   float64         `json:"logicalWidthStud"`
	LogicalDepthStud   float64         `json:"logicalDepthStud"`
	LogicalHeightPlate float64         `json:"logicalHeightPlate"`
	VertexCount        int32           `json:"vertexCount"`
	FaceCount          int32           `json:"faceCount"`
}

type PartBoundingBox struct {
	MinX float64 `json:"minX"`
	MinY float64 `json:"minY"`
	MinZ float64 `json:"minZ"`
	MaxX float64 `json:"maxX"`
	MaxY float64 `json:"maxY"`
	MaxZ float64 `json:"maxZ"`
}

type PartPreviewModel struct {
	ArtifactID string `json:"artifactId"`
	Format     string `json:"format"`
	URL        string `json:"url"`
	SHA256     string `json:"sha256"`
	ByteLength int64  `json:"byteLength"`
}

type PartPreviewMaterializeInput struct {
	Locale   string `json:"locale"`
	Timezone string `json:"timezone"`
}

type RelationCandidate struct {
	ID                   string          `json:"id"`
	ComponentCandidateID string          `json:"componentCandidateId"`
	PartLibraryVersionID string          `json:"partLibraryVersionId"`
	EndpointA            json.RawMessage `json:"endpointA"`
	EndpointB            json.RawMessage `json:"endpointB"`
	ConnectionType       string          `json:"connectionType"`
	JointType            string          `json:"jointType"`
	PositionResidual     float64         `json:"positionResidual"`
	RotationResidual     float64         `json:"rotationResidual"`
	VerifiedByTolerance  bool            `json:"verifiedByTolerance"`
	Confidence           float64         `json:"confidence"`
	Status               string          `json:"status"`
	DetectionMethod      string          `json:"detectionMethod"`
	Metadata             json.RawMessage `json:"metadata"`
	CreatedAt            time.Time       `json:"createdAt"`
	UpdatedAt            time.Time       `json:"updatedAt"`
}

type AssemblyRelation struct {
	ID                   string          `json:"id"`
	ComponentCandidateID string          `json:"componentCandidateId"`
	RelationCandidateID  string          `json:"relationCandidateId"`
	EndpointA            json.RawMessage `json:"endpointA"`
	EndpointB            json.RawMessage `json:"endpointB"`
	ConnectionType       string          `json:"connectionType"`
	JointType            string          `json:"jointType"`
	Placement            json.RawMessage `json:"placement"`
	ConfirmedBy          string          `json:"confirmedBy"`
	ConfirmedAt          time.Time       `json:"confirmedAt"`
}

type Connector struct {
	ID                  string          `json:"id"`
	WorldConnectorID    string          `json:"worldConnectorId"`
	PartInstanceID      string          `json:"partInstanceId"`
	PartRef             string          `json:"partRef"`
	ConnectorType       *string         `json:"connectorType"`
	ConnectorKind       *string         `json:"connectorKind"`
	ConnectorGender     *string         `json:"connectorGender"`
	State               string          `json:"state"`
	Position            []float64       `json:"position"`
	Axis                []float64       `json:"axis"`
	Matrix              []float64       `json:"matrix"`
	AccessAxis          []float64       `json:"accessAxis"`
	ExternalInterfaceID *string         `json:"externalInterfaceId"`
	Capacity            int32           `json:"capacity"`
	OccupiedSlots       int32           `json:"occupiedSlots"`
	AvailableCapacity   int32           `json:"availableCapacity"`
	Eligibility         json.RawMessage `json:"eligibility"`
}

type Interface struct {
	ID                   string          `json:"id"`
	ComponentCandidateID string          `json:"componentCandidateId"`
	WorldConnectorID     string          `json:"worldConnectorId"`
	Name                 string          `json:"name"`
	Exposure             string          `json:"exposure"`
	DefaultBehavior      string          `json:"defaultBehavior"`
	SourceConnector      json.RawMessage `json:"sourceConnector"`
	MechanicalRoles      json.RawMessage `json:"mechanicalRoles"`
	BusinessRoles        json.RawMessage `json:"businessRoles"`
	Requirements         json.RawMessage `json:"requirements"`
	ReviewStatus         string          `json:"reviewStatus"`
	CreatedAt            time.Time       `json:"createdAt"`
	UpdatedAt            time.Time       `json:"updatedAt"`
}

type Preview struct {
	VersionID        string   `json:"versionId"`
	Status           string   `json:"status"`
	GeneratorVersion *string  `json:"generatorVersion"`
	ArtifactID       *string  `json:"artifactId"`
	SHA256           *string  `json:"sha256"`
	FileSize         *int64   `json:"fileSize"`
	URL              *string  `json:"url"`
	Failure          *Failure `json:"failure"`
}

type Failure struct {
	Code   string          `json:"code"`
	Params json.RawMessage `json:"params"`
}

type ValidationReport struct {
	ID                   string          `json:"id"`
	ComponentCandidateID *string         `json:"componentCandidateId"`
	ComponentVersionID   *string         `json:"componentVersionId"`
	ValidationLevel      string          `json:"validationLevel"`
	Passed               bool            `json:"passed"`
	Checks               json.RawMessage `json:"checks"`
	Issues               json.RawMessage `json:"issues"`
	ValidatorVersion     string          `json:"validatorVersion"`
	CreatedAt            time.Time       `json:"createdAt"`
}

type VersionParts struct {
	VersionID            string     `json:"versionId"`
	PartLibraryVersionID *string    `json:"partLibraryVersionId"`
	PartCount            int        `json:"partCount"`
	Items                []PartItem `json:"items"`
}

type PartItem struct {
	LDrawPartNum      string  `json:"ldrawPartNum"`
	Quantity          int     `json:"quantity"`
	Name              *string `json:"name"`
	ContentLocale     *string `json:"contentLocale"`
	TranslationStatus string  `json:"translationStatus"`
}
