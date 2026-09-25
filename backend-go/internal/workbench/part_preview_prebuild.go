package workbench

import (
	"context"
	"encoding/json"
	"errors"
	"sort"
	"sync"
	"sync/atomic"
	"time"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type partPreviewPrebuildPayload struct {
	PartLibraryVersionID string `json:"partLibraryVersionId"`
	GeneratorVersion     string `json:"generatorVersion"`
	SourceHash           string `json:"sourceHash"`
}

// PartPreviewPrebuildTaskHandler 在一个持久任务中顺序预生成目标 Part Library 的缺失或过期模型。
// 每个 Part 单独落库，因此 Worker 中断后重试只会继续处理尚未完成的条目。
type PartPreviewPrebuildTaskHandler struct {
	part *PartPreviewTaskHandler
}

// NewPartPreviewPrebuildTaskHandler 复用单 Part 物化器，确保按需预览和批量预生成输出完全一致。
func NewPartPreviewPrebuildTaskHandler(part *PartPreviewTaskHandler) *PartPreviewPrebuildTaskHandler {
	return &PartPreviewPrebuildTaskHandler{part: part}
}

// Handle 处理全库预生成；单个坏零件会记录稳定失败码并继续，不阻断其他可用模型写入 Storage。
func (h *PartPreviewPrebuildTaskHandler) Handle(ctx context.Context, claimed task.ClaimedTask) (task.Result, error) {
	var payload partPreviewPrebuildPayload
	if err := strictTaskPayload(claimed.Payload, &payload); err != nil || payload.GeneratorVersion != PartPreviewGeneratorVersion {
		return task.Result{}, &task.Failure{Code: "component_repo.part_preview_prebuild_invalid", Retryable: false}
	}
	libraryID, err := uuidutil.Parse(payload.PartLibraryVersionID)
	if err != nil {
		return task.Result{}, partPreviewPrebuildFailure("library_invalid", false)
	}
	library, err := h.part.q.GetPartPreviewPrebuildLibrary(ctx, libraryID)
	if errors.Is(err, pgx.ErrNoRows) || (err == nil && library.SourceHash != payload.SourceHash) {
		return task.Result{}, partPreviewPrebuildFailure("library_stale", false)
	}
	if err != nil {
		return task.Result{}, partPreviewPrebuildFailure("library_read", true)
	}
	for {
		prepared, prepareErr := h.part.q.PreparePartPreviewPrebuildCandidateBatch(ctx, db.PreparePartPreviewPrebuildCandidateBatchParams{
			TaskID: claimed.ID, PartLibraryVersionID: libraryID,
			GeneratorVersion: stringPointer(payload.GeneratorVersion), BatchSize: 500,
		})
		if prepareErr != nil {
			return task.Result{}, partPreviewPrebuildFailure("candidate_prepare", true)
		}
		if prepared == 0 {
			break
		}
	}
	var ready atomic.Int64
	var failed atomic.Int64
	const concurrency = 8
	const batchSize = 500
	process := func(workerCtx context.Context, candidate db.ListPreparedPartPreviewPrebuildCandidatesRow) error {
		partPayload := partPreviewPayload{
			PartLibraryVersionID: payload.PartLibraryVersionID, LDrawPartNum: candidate.LdrawPartNum,
			GeneratorVersion: payload.GeneratorVersion, Generation: candidate.Generation,
			InputHash: hashStrings(payload.SourceHash, candidate.SourceFileHash, payload.GeneratorVersion),
		}
		var partFailure *task.Failure
		for attempt := 0; attempt < 3; attempt++ {
			_, materializeErr := h.part.materializePrepared(
				workerCtx, claimed, partPayload, libraryID, candidate.LdrawPartNum,
				candidate.SourceRelativePath, candidate.SourceFileHash, false,
			)
			if materializeErr == nil {
				ready.Add(1)
				return nil
			}
			if !errors.As(materializeErr, &partFailure) {
				return materializeErr
			}
			if !partFailure.Retryable || attempt == 2 {
				break
			}
			// 只在同一 durable task 内重试确定为 retryable 的压缩/Storage 短暂故障。
			timer := time.NewTimer(time.Duration(attempt+1) * time.Second)
			select {
			case <-workerCtx.Done():
				timer.Stop()
				return workerCtx.Err()
			case <-timer.C:
			}
		}
		failed.Add(1)
		failureParams := mustJSON(partFailure.Params)
		if _, markErr := h.part.q.MarkPartPreviewPrebuildFailed(workerCtx, db.MarkPartPreviewPrebuildFailedParams{
			FailureCode: stringPointer(partFailure.Code), FailureParams: failureParams,
			PartLibraryVersionID: libraryID, LdrawPartNum: candidate.LdrawPartNum,
			TaskID: claimed.ID, Generation: candidate.Generation,
		}); markErr != nil {
			return markErr
		}
		return nil
	}
	matched := 0
	for {
		candidates, listErr := h.part.q.ListPreparedPartPreviewPrebuildCandidates(ctx, db.ListPreparedPartPreviewPrebuildCandidatesParams{
			TaskID: claimed.ID, PartLibraryVersionID: libraryID,
			GeneratorVersion: stringPointer(payload.GeneratorVersion), BatchSize: batchSize,
		})
		if listErr != nil {
			return task.Result{}, partPreviewPrebuildFailure("candidate_list", true)
		}
		if len(candidates) == 0 {
			break
		}
		// 每批仍先生成轻量 Part；固定 500 行避免远程 pooler 的大结果阻塞首条完成与 heartbeat。
		sort.Slice(candidates, func(left, right int) bool {
			if candidates[left].FaceCount == candidates[right].FaceCount {
				return candidates[left].LdrawPartNum < candidates[right].LdrawPartNum
			}
			return candidates[left].FaceCount < candidates[right].FaceCount
		})
		workerCtx, cancel := context.WithCancel(ctx)
		jobs := make(chan db.ListPreparedPartPreviewPrebuildCandidatesRow)
		var firstError error
		var errorOnce sync.Once
		var workers sync.WaitGroup
		for index := 0; index < concurrency; index++ {
			workers.Add(1)
			go func() {
				defer workers.Done()
				for candidate := range jobs {
					if err := process(workerCtx, candidate); err != nil {
						errorOnce.Do(func() {
							firstError = err
							cancel()
						})
						return
					}
				}
			}()
		}
	sendLoop:
		for _, candidate := range candidates {
			select {
			case <-workerCtx.Done():
				break sendLoop
			case jobs <- candidate:
			}
		}
		close(jobs)
		workers.Wait()
		cancel()
		if firstError != nil {
			return task.Result{}, firstError
		}
		if err := ctx.Err(); err != nil {
			return task.Result{}, err
		}
		matched += len(candidates)
	}
	return task.Result{Payload: mustJSON(map[string]any{
		"partLibraryVersionId": payload.PartLibraryVersionID, "generatorVersion": payload.GeneratorVersion,
		"matched": matched, "ready": ready.Load(), "failed": failed.Load(),
	})}, nil
}

func partPreviewPrebuildFailure(stage string, retryable bool) *task.Failure {
	return &task.Failure{
		Code:   "component_repo.part_preview_prebuild_unavailable",
		Params: map[string]any{"stage": stage}, Retryable: retryable,
	}
}

// PartPreviewPrebuildSchedule 是维护命令的可审计结果；Matched 只统计当前缺失或生成器过期的条目。
type PartPreviewPrebuildSchedule struct {
	PartLibraryVersionID string
	GeneratorVersion     string
	Matched              int64
	TaskID               string
	TaskStatus           string
}

// SchedulePartPreviewPrebuild 创建单个持久全库任务；显式版本可指向 building 快照以先备妥预览再激活。
// 未指定版本仍只使用 active；dryRun 只读取规模，不修改任务或预览状态。
func SchedulePartPreviewPrebuild(ctx context.Context, pool *pgxpool.Pool, partLibraryVersionID string, dryRun, force bool) (PartPreviewPrebuildSchedule, error) {
	q := db.New(pool)
	var library db.GetPartPreviewPrebuildLibraryRow
	var err error
	if partLibraryVersionID == "" {
		active, activeErr := q.GetActivePartPreviewPrebuildLibrary(ctx)
		if activeErr != nil {
			return PartPreviewPrebuildSchedule{}, activeErr
		}
		library = db.GetPartPreviewPrebuildLibraryRow(active)
	} else {
		libraryID, parseErr := uuidutil.Parse(partLibraryVersionID)
		if parseErr != nil {
			return PartPreviewPrebuildSchedule{}, parseErr
		}
		library, err = q.GetPartPreviewPrebuildLibrary(ctx, libraryID)
		if err != nil {
			return PartPreviewPrebuildSchedule{}, err
		}
	}
	result := PartPreviewPrebuildSchedule{
		PartLibraryVersionID: uuidutil.String(library.ID), GeneratorVersion: PartPreviewGeneratorVersion,
	}
	result.Matched, err = q.CountPartPreviewPrebuildCandidates(ctx, db.CountPartPreviewPrebuildCandidatesParams{
		PartLibraryVersionID: library.ID, GeneratorVersion: stringPointer(PartPreviewGeneratorVersion),
	})
	if err != nil || dryRun || result.Matched == 0 {
		return result, err
	}
	payload := mustJSON(partPreviewPrebuildPayload{
		PartLibraryVersionID: result.PartLibraryVersionID, GeneratorVersion: PartPreviewGeneratorVersion,
		SourceHash: library.SourceHash,
	})
	scheduled, err := txValue(ctx, pool, func(txq *db.Queries) (task.ScheduleResult, error) {
		return task.ScheduleWithQueries(ctx, txq, task.ScheduleInput{
			OwnerID: library.CreatedBy, TaskType: PartPreviewPrebuildType,
			LogicalKey: result.PartLibraryVersionID, InputHash: hashStrings(library.SourceHash, PartPreviewGeneratorVersion),
			Payload: json.RawMessage(payload), Locale: "en-US", Timezone: "UTC", CreatedBy: library.CreatedBy,
			MaxAttempts: 3, AvailableAt: time.Now().UTC(), ForceNew: force,
		})
	})
	if err != nil {
		return PartPreviewPrebuildSchedule{}, err
	}
	result.TaskID = uuidutil.String(scheduled.Task.ID)
	result.TaskStatus = scheduled.Task.Status
	return result, nil
}
