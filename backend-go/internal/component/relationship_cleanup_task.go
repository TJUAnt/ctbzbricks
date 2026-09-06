package component

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"time"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

const relationshipCleanupBatchSize int32 = 5000

type relationshipCleanupPayload struct {
	ComponentID string    `json:"componentId"`
	EndedSeq    int64     `json:"endedSeq"`
	EndedAt     time.Time `json:"endedAt"`
	EndedReason string    `json:"endedReason"`
}

// RelationshipCleanupTaskHandler 在 Component 已退出公开生命周期后分批收敛 Star/Watch 关系。
// 删除事务冻结统一 Watch 结束边界并原子创建任务；Handler 只做可重试的短事务批次，不生成通知或 Feed。
type RelationshipCleanupTaskHandler struct {
	pool *pgxpool.Pool
}

// NewRelationshipCleanupTaskHandler 创建 Component 关系清理 Worker 入口。
func NewRelationshipCleanupTaskHandler(pool *pgxpool.Pool) *RelationshipCleanupTaskHandler {
	return &RelationshipCleanupTaskHandler{pool: pool}
}

// Handle 校验内部任务快照并持续执行固定批次，直到 Watch 与 Star 都没有剩余关系。
// 每个批次独立提交，Worker lease 丢失或进程退出后可从尚未清理的关系继续，不会重写已关闭 Watch 历史。
func (h *RelationshipCleanupTaskHandler) Handle(ctx context.Context, claimed task.ClaimedTask) (task.Result, error) {
	var payload relationshipCleanupPayload
	if err := decodeRelationshipCleanupPayload(claimed.Payload, &payload); err != nil ||
		payload.EndedSeq <= 0 || payload.EndedAt.IsZero() ||
		(payload.EndedReason != "component_archived" && payload.EndedReason != "component_deleted") {
		return task.Result{}, &task.Failure{Code: "common.internal_error", Params: map[string]any{}, Retryable: false}
	}
	componentID, err := uuidutil.Parse(payload.ComponentID)
	if err != nil {
		return task.Result{}, &task.Failure{Code: "common.internal_error", Params: map[string]any{}, Retryable: false}
	}

	var closedWatches, deletedStars int64
	// 全零 UUID 是有序扫描的闭区间起点；关系行被处理后会退出对应索引，所以后续批次使用
	// “>= 上批最大 actor”既不会遗漏合法的全零 actor，也不会重复写已处理关系。
	watchCursor := pgtype.UUID{Valid: true}
	starCursor := pgtype.UUID{Valid: true}
	for {
		batch, batchErr := h.cleanupBatch(ctx, componentID, payload, watchCursor, starCursor)
		if batchErr != nil {
			return task.Result{}, batchErr
		}
		closedWatches += batch.closedWatches
		deletedStars += batch.deletedStars
		if batch.watchCursor.Valid {
			watchCursor = batch.watchCursor
		}
		if batch.starCursor.Valid {
			starCursor = batch.starCursor
		}
		if batch.closedWatches == 0 && batch.deletedStars == 0 {
			break
		}
	}
	result, err := json.Marshal(map[string]any{
		"componentId":   payload.ComponentID,
		"closedWatches": closedWatches,
		"deletedStars":  deletedStars,
	})
	if err != nil {
		return task.Result{}, err
	}
	return task.Result{Payload: result}, nil
}

type relationshipCleanupBatch struct {
	closedWatches int64
	deletedStars  int64
	watchCursor   pgtype.UUID
	starCursor    pgtype.UUID
}

func (h *RelationshipCleanupTaskHandler) cleanupBatch(
	ctx context.Context,
	componentID pgtype.UUID,
	payload relationshipCleanupPayload,
	watchCursor pgtype.UUID,
	starCursor pgtype.UUID,
) (relationshipCleanupBatch, error) {
	tx, err := h.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return relationshipCleanupBatch{}, err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	q := db.New(tx)
	closed, err := q.CloseActiveComponentWatchesForLifecycleBatch(ctx, db.CloseActiveComponentWatchesForLifecycleBatchParams{
		EndedSeq: payload.EndedSeq,
		EndedAt: pgtype.Timestamptz{
			Time:  payload.EndedAt.UTC(),
			Valid: true,
		},
		EndedReason:  payload.EndedReason,
		ComponentID:  componentID,
		AfterActorID: watchCursor,
		BatchSize:    relationshipCleanupBatchSize,
	})
	if err != nil {
		return relationshipCleanupBatch{}, err
	}
	deleted, err := q.DeleteComponentStarsForLifecycleBatch(ctx, db.DeleteComponentStarsForLifecycleBatchParams{
		ComponentID:  componentID,
		AfterActorID: starCursor,
		BatchSize:    relationshipCleanupBatchSize,
	})
	if err != nil {
		return relationshipCleanupBatch{}, err
	}
	if err := tx.Commit(ctx); err != nil {
		return relationshipCleanupBatch{}, err
	}
	return relationshipCleanupBatch{
		closedWatches: int64(len(closed)),
		deletedStars:  int64(len(deleted)),
		watchCursor:   maxRelationshipActor(closed),
		starCursor:    maxRelationshipActor(deleted),
	}, nil
}

func maxRelationshipActor(actors []pgtype.UUID) pgtype.UUID {
	var maximum pgtype.UUID
	for _, actor := range actors {
		if actor.Valid && (!maximum.Valid || bytes.Compare(actor.Bytes[:], maximum.Bytes[:]) > 0) {
			maximum = actor
		}
	}
	return maximum
}

func decodeRelationshipCleanupPayload(raw json.RawMessage, destination *relationshipCleanupPayload) error {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		return err
	}
	if err := decoder.Decode(&struct{}{}); err == nil {
		return errors.New("relationship cleanup payload contains trailing JSON")
	} else if err != io.EOF {
		return err
	}
	return nil
}
