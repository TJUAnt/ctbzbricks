package ingestion

import (
	"testing"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/jackc/pgx/v5/pgtype"
)

func TestImportProcessingStatus(t *testing.T) {
	value := func(text string) *string { return &text }
	validID := pgtype.UUID{Valid: true}
	tests := []struct {
		name string
		row  db.GetOwnedImportRow
		want string
	}{
		{name: "解析排队", row: db.GetOwnedImportRow{Status: "queued"}, want: "processing"},
		{name: "BOM 已完成但 GLB 排队", row: db.GetOwnedImportRow{
			Status: "succeeded", CandidateID: validID, DraftVersionID: validID,
			SceneSnapshotID: validID, PreviewTaskID: validID, PreviewStatus: "pending",
			PreviewTaskStatus: value("queued"),
		}, want: "processing"},
		{name: "GLB 与 BOM 均就绪", row: db.GetOwnedImportRow{
			Status: "succeeded", CandidateID: validID, DraftVersionID: validID,
			SceneSnapshotID: validID, PreviewTaskID: validID, PreviewArtifactID: validID,
			PreviewStatus: "ready", PreviewTaskStatus: value("succeeded"),
			PreviewArtifactVerificationStatus: value("verified"),
		}, want: "ready"},
		{name: "解析失败", row: db.GetOwnedImportRow{Status: "failed"}, want: "failed"},
		{name: "预览任务失败", row: db.GetOwnedImportRow{
			Status: "succeeded", PreviewStatus: "pending", PreviewTaskStatus: value("failed"),
		}, want: "failed"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if got := importProcessingStatus(test.row); got != test.want {
				t.Fatalf("importProcessingStatus() = %q, want %q", got, test.want)
			}
		})
	}
}
