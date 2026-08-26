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
	PartPreviewPrebuildType     = "component.part_preview.prebuild"
	RelationDetectionVersion    = "component-relation-detector-v3"
	ValidatorVersion            = "component-repo-validator-v2"
	PreviewGeneratorVersion     = "component-preview-studio-ldraw-glb-v4"
	PartPreviewGeneratorVersion = "part-preview-ldraw-meshopt-glb-v2"
)

type AcceptedTask struct {
	TaskID string `json:"taskId"`
	Status string `json:"status"`
}

type PartLibraryVersion struct {
	ID             string    `json:"id"`
	SourceName     string    `json:"sourceName"`
	SourceHash     string    `json:"sourceHash"`
	Status         string    `json:"status"`
	PreviewReady   bool      `json:"previewReady"`
	RelationReady  bool      `json:"relationReady"`
	ConnectorCount int32     `json:"connectorCount"`
	ColliderCount  int32     `json:"colliderCount"`
	CreatedAt      time.Time `json:"createdAt"`
}

// PartSearchRequest 是零件搜索的有界输入；query 同时承载名称/编号关键词和二维或三维精确尺寸片段。
type PartSearchRequest struct {
	Query    string `json:"query"`
	Page     int    `json:"page"`
	PageSize int    `json:"pageSize"`
}

// PartSearchPage 固定返回本次查询使用的 Part Library Version，避免 active library 切换后链接指向错误快照。
type PartSearchPage struct {
	PartLibraryVersionID string           `json:"partLibraryVersionId"`
	Items                []PartSearchItem `json:"items"`
	Total                int64            `json:"total"`
	Returned             int              `json:"returned"`
	Page                 int              `json:"page"`
	PageSize             int              `json:"pageSize"`
	TotalPages           int              `json:"totalPages"`
}

// PartSearchItem 是 active Studio Part Library 的源内容搜索投影；previewModel 只引用已物化的当前 GLB。
type PartSearchItem struct {
	LDrawPartNum                string                  `json:"ldrawPartNum"`
	Name                        string                  `json:"name"`
	ContentLocale               string                  `json:"contentLocale"`
	TranslationStatus           string                  `json:"translationStatus"`
	GeometryStatus              string                  `json:"geometryStatus"`
	LogicalSize                 *PartSearchLogicalSize  `json:"logicalSize"`
	LogicalSizeDerivationStatus string                  `json:"logicalSizeDerivationStatus"`
	ImageURL                    *string                 `json:"imageUrl"`
	PreviewModel                *PartSearchPreviewModel `json:"previewModel"`
}

// PartSearchPreviewModel 为列表缩略图提供短期下载定位；Storage key 和内部 provider 信息不得暴露。
type PartSearchPreviewModel struct {
	ArtifactID  string `json:"artifactId"`
	Format      string `json:"format"`
	Compression string `json:"compression"`
	URL         string `json:"url"`
	SHA256      string `json:"sha256"`
	ByteLength  int64  `json:"byteLength"`
}

// PartSearchLogicalSize 使用既有 Part Library 派生单位：平面为 stud，高度为 plate。
type PartSearchLogicalSize struct {
	WidthStud   float64 `json:"widthStud"`
	DepthStud   float64 `json:"depthStud"`
	HeightPlate float64 `json:"heightPlate"`
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
	BBox                        PartBoundingBox `json:"bbox"`
	LogicalWidthStud            *float64        `json:"logicalWidthStud"`
	LogicalDepthStud            *float64        `json:"logicalDepthStud"`
	LogicalHeightPlate          *float64        `json:"logicalHeightPlate"`
	LogicalSizeDerivationStatus string          `json:"logicalSizeDerivationStatus"`
	VertexCount                 int32           `json:"vertexCount"`
	FaceCount                   int32           `json:"faceCount"`
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

// VersionParts 是 ComponentVersion BOM 接口的稳定响应结构；编号和数量属于不可翻译的机器数据。
type VersionParts struct {
	VersionID            string     `json:"versionId"`
	PartLibraryVersionID *string    `json:"partLibraryVersionId"`
	PartCount            int        `json:"partCount"`
	Items                []PartItem `json:"items"`
}

// PartItem 表示一种 Part 的汇总数量、预览几何状态及 locale-aware 官方名称投影。
type PartItem struct {
	LDrawPartNum      string  `json:"ldrawPartNum"`
	Quantity          int     `json:"quantity"`
	Name              *string `json:"name"`
	ContentLocale     *string `json:"contentLocale"`
	TranslationStatus string  `json:"translationStatus"`
	GeometryStatus    string  `json:"geometryStatus"`
}
