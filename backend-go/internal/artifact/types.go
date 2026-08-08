package artifact

import (
	"encoding/json"
	"time"
)

type FileSpec struct {
	Filename    string `json:"filename"`
	ContentType string `json:"contentType"`
	FileSize    int64  `json:"fileSize"`
	SHA256      string `json:"sha256"`
}

type CreateUploadSessionInput struct {
	SourceFile        FileSpec  `json:"sourceFile"`
	ExchangeFile      *FileSpec `json:"exchangeFile"`
	TargetComponentID *string   `json:"targetComponentId"`
	BaseVersionID     *string   `json:"baseVersionId"`
	ContentLocale     string    `json:"contentLocale"`
	Timezone          string    `json:"timezone"`
}

type UploadTarget struct {
	Role             string `json:"role"`
	ArtifactID       string `json:"artifactId"`
	ArtifactType     string `json:"artifactType"`
	OriginalFilename string `json:"originalFilename"`
	Bucket           string `json:"bucket"`
	ObjectPath       string `json:"objectPath"`
	ContentType      string `json:"contentType"`
	FileSize         int64  `json:"fileSize"`
	ExpectedSHA256   string `json:"expectedSha256"`
	UploadSessionID  string `json:"uploadSessionId"`
}

type UploadSession struct {
	ID          string          `json:"id"`
	OwnerID     string          `json:"ownerId"`
	Status      string          `json:"status"`
	Bucket      string          `json:"bucket"`
	Uploads     []UploadTarget  `json:"uploads"`
	CreatedBy   string          `json:"createdBy"`
	CreatedAt   time.Time       `json:"createdAt"`
	ExpiresAt   time.Time       `json:"expiresAt"`
	CompletedAt *time.Time      `json:"completedAt"`
	Failure     *Failure        `json:"failure"`
	Metadata    json.RawMessage `json:"metadata"`
}

type Failure struct {
	Code   string          `json:"code"`
	Params json.RawMessage `json:"params"`
}

type Artifact struct {
	ID                 string          `json:"id"`
	OwnerID            string          `json:"ownerId"`
	ArtifactType       string          `json:"artifactType"`
	SourceKind         string          `json:"sourceKind"`
	OriginalFilename   string          `json:"originalFilename"`
	SHA256             string          `json:"sha256"`
	FileSize           int64           `json:"fileSize"`
	MimeType           string          `json:"mimeType"`
	Immutable          bool            `json:"immutable"`
	VerificationStatus string          `json:"verificationStatus"`
	VerifiedAt         *time.Time      `json:"verifiedAt"`
	UploadedBy         string          `json:"uploadedBy"`
	UploadedAt         time.Time       `json:"uploadedAt"`
	Metadata           json.RawMessage `json:"metadata"`
}

type UploadCompletion struct {
	UploadSessionID string     `json:"uploadSessionId"`
	Status          string     `json:"status"`
	Artifacts       []Artifact `json:"artifacts"`
}

type Download struct {
	ArtifactID string    `json:"artifactId"`
	URL        string    `json:"url"`
	ExpiresAt  time.Time `json:"expiresAt"`
}
