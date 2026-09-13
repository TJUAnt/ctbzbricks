package feedrender

import (
	"context"
	"crypto/sha256"
	"fmt"
	"strings"
	"time"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5/pgtype"
)

// ScheduleWithQueries 把发布事件、持久任务和 Feed pending 投影放入调用方的发布事务。
// previewTaskStatus 只有 queued/running 时才建立依赖；既有失败任务必须让 Feed 渲染自行进入 fallback。
func ScheduleWithQueries(
	ctx context.Context,
	q *db.Queries,
	eventID, componentID, versionID, ownerID pgtype.UUID,
	contentLocale string,
	previewTaskID pgtype.UUID,
	previewTaskStatus *string,
	previewIdentity string,
) error {
	payload := Payload{
		EventID: uuidutil.String(eventID), ComponentVersionID: uuidutil.String(versionID),
		RenderProfile: RenderProfile, RendererVersion: RendererVersion,
	}
	input := strings.Join([]string{payload.ComponentVersionID, RenderProfile, RendererVersion, previewIdentity}, "\x00")
	digest := sha256.Sum256([]byte(input))
	scheduled, err := task.ScheduleWithQueries(ctx, q, task.ScheduleInput{
		OwnerID: ownerID, TaskType: TaskType,
		LogicalKey: payload.ComponentVersionID + ":" + RenderProfile,
		InputHash:  fmt.Sprintf("%x", digest[:]), Payload: payloadJSON(payload),
		Locale: contentLocale, Timezone: "UTC", CreatedBy: ownerID,
		MaxAttempts: 3, AvailableAt: time.Now().UTC(),
	})
	if err != nil {
		return err
	}
	if _, err := q.CreateComponentFeedEntry(ctx, db.CreateComponentFeedEntryParams{
		EventID: eventID, ComponentID: componentID, ComponentVersionID: versionID, RenderTaskID: scheduled.Task.ID,
		RenderProfile: RenderProfile, RendererVersion: RendererVersion,
	}); err != nil {
		return err
	}
	if previewTaskID.Valid && previewTaskStatus != nil && (*previewTaskStatus == task.StatusQueued || *previewTaskStatus == task.StatusRunning) {
		return q.CreateTaskDependency(ctx, db.CreateTaskDependencyParams{
			TaskID: scheduled.Task.ID, PrerequisiteTaskID: previewTaskID, OwnerID: ownerID,
		})
	}
	return nil
}
