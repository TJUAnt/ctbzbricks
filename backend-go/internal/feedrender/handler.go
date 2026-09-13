package feedrender

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"strings"
	"time"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/ldrawmaterial"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/storage"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Handler 在 Go Worker 内把已验证 GLB 转成 Feed PNG；对象写入与数据库登记使用幂等 Artifact 身份。
type Handler struct {
	pool      *pgxpool.Pool
	q         *db.Queries
	store     storage.Store
	keyPrefix string
	renderer  ImageRenderer
}

// NewHandler 创建只使用 Go 光栅 fallback 的 Feed 图片任务入口，主要供测试和无外部渲染器的降级环境使用。
func NewHandler(pool *pgxpool.Pool, store storage.Store, keyPrefix string) *Handler {
	return newHandler(pool, store, keyPrefix, NewImageRenderer("", 0))
}

// NewPathTracingHandler 创建 Cycles 优先的 Feed 图片任务入口。
// Go 仍负责任务、超时、输出校验和持久化；外部渲染器失败时在同一 Attempt 内回退到确定性光栅器。
func NewPathTracingHandler(pool *pgxpool.Pool, store storage.Store, keyPrefix, blenderPath string, timeout time.Duration) *Handler {
	return newHandler(pool, store, keyPrefix, NewImageRenderer(blenderPath, timeout))
}

func newHandler(pool *pgxpool.Pool, store storage.Store, keyPrefix string, renderer ImageRenderer) *Handler {
	return &Handler{pool: pool, q: db.New(pool), store: store, keyPrefix: keyPrefix, renderer: renderer}
}

// Handle 验证任务与事件绑定后读取 GLB、执行确定性 3:2 渲染并登记派生 Artifact。
// 输入损坏属于永久失败；对象存储和数据库瞬态错误交给通用任务租约继续有限重试。
func (h *Handler) Handle(ctx context.Context, claimed task.ClaimedTask) (task.Result, error) {
	var payload Payload
	decoder := json.NewDecoder(bytes.NewReader(claimed.Payload))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&payload); err != nil || payload.RenderProfile != RenderProfile || payload.RendererVersion != RendererVersion {
		return task.Result{}, renderFailure(payload.ComponentVersionID, false)
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return task.Result{}, renderFailure(payload.ComponentVersionID, false)
	}
	eventID, err := uuidutil.Parse(payload.EventID)
	if err != nil {
		return task.Result{}, renderFailure(payload.ComponentVersionID, false)
	}
	versionID, err := uuidutil.Parse(payload.ComponentVersionID)
	if err != nil {
		return task.Result{}, renderFailure(payload.ComponentVersionID, false)
	}
	input, err := h.q.GetComponentFeedRenderInput(ctx, db.GetComponentFeedRenderInputParams{
		OwnerID: claimed.OwnerID, TaskID: claimed.ID,
	})
	if errors.Is(err, pgx.ErrNoRows) {
		return task.Result{}, renderFailure(payload.ComponentVersionID, false)
	}
	if err != nil {
		return task.Result{}, err
	}
	if !uuidutil.Equal(input.EventID, eventID) || !uuidutil.Equal(input.ComponentVersionID, versionID) {
		return task.Result{}, renderFailure(payload.ComponentVersionID, false)
	}
	if input.PreviewFileSize < 1 || input.PreviewFileSize > MaxGLBBytes {
		return task.Result{}, renderFailure(payload.ComponentVersionID, false)
	}
	reader, err := h.store.Open(ctx, input.PreviewStorageKey)
	if err != nil {
		return task.Result{}, renderFailure(payload.ComponentVersionID, !errors.Is(err, storage.ErrNotFound))
	}
	source, readErr := io.ReadAll(io.LimitReader(reader, MaxGLBBytes+1))
	closeErr := reader.Close()
	if readErr != nil || closeErr != nil || len(source) > MaxGLBBytes {
		return task.Result{}, renderFailure(payload.ComponentVersionID, true)
	}
	sourceHash := sha256.Sum256(source)
	if hex.EncodeToString(sourceHash[:]) != input.PreviewSha256 {
		return task.Result{}, renderFailure(payload.ComponentVersionID, false)
	}
	renderer := h.renderer
	if renderer == nil {
		renderer = NewImageRenderer("", 0)
	}
	rendered, err := renderer.Render(ctx, source)
	if err != nil {
		if ctx.Err() != nil {
			return task.Result{}, ctx.Err()
		}
		return task.Result{}, renderFailure(payload.ComponentVersionID, false)
	}
	pngBytes := rendered.PNG
	imageHash := sha256.Sum256(pngBytes)
	imageHashText := hex.EncodeToString(imageHash[:])
	// Cycles/fallback 的实际输出 hash 属于派生资产身份，避免重试时不同引擎或硬件结果覆盖同一 immutable key。
	artifactID := feedArtifactID(payload.ComponentVersionID, input.PreviewSha256, imageHashText)
	artifactText := uuidutil.String(artifactID)
	ownerText := uuidutil.String(claimed.OwnerID)
	key := strings.Join(nonEmpty([]string{
		ownerText, h.keyPrefix, "feed-renders", payload.ComponentVersionID,
		RendererVersion, artifactText + ".png",
	}), "/")
	if err := h.store.Put(ctx, key, "image/png", bytes.NewReader(pngBytes), int64(len(pngBytes))); err != nil {
		return task.Result{}, renderFailure(payload.ComponentVersionID, true)
	}
	metadataValue := map[string]any{
		"derivedBy": TaskType, "rendererVersion": RendererVersion, "renderProfile": RenderProfile,
		"materialProfileVersion": ldrawmaterial.ProfileVersion,
		"componentVersionId":     payload.ComponentVersionID, "sourceSha256": input.PreviewSha256,
		"width": ImageWidth, "height": ImageHeight,
		"targetWidthRatio": rendered.TargetWidthRatio, "targetHeightRatio": rendered.TargetHeightRatio,
		"renderEngine": rendered.Engine, "rasterFallback": rendered.Fallback,
	}
	if rendered.FallbackCode != "" {
		metadataValue["fallbackCode"] = rendered.FallbackCode
	}
	metadata, _ := json.Marshal(metadataValue)
	if err := h.persistArtifact(ctx, db.UpsertComponentFeedImageArtifactParams{
		ID: artifactID, OwnerID: claimed.OwnerID, OriginalFilename: payload.ComponentVersionID + ".png",
		StorageProvider: h.store.Provider(), StorageBucket: h.store.Bucket(), StorageKey: key,
		Sha256: imageHashText, FileSize: int64(len(pngBytes)),
		UploadedBy: claimed.OwnerID, Metadata: metadata, DerivedFromArtifactID: input.PreviewArtifactID,
	}); err != nil {
		return task.Result{}, err
	}
	result, _ := json.Marshal(map[string]any{
		"eventId": payload.EventID, "componentVersionId": payload.ComponentVersionID,
		"artifactId": artifactText, "rendererVersion": RendererVersion,
		"renderProfile": RenderProfile, "width": ImageWidth, "height": ImageHeight,
		"renderEngine": rendered.Engine, "rasterFallback": rendered.Fallback,
	})
	return task.Result{Payload: result, ArtifactID: artifactID}, nil
}

// feedArtifactID 把来源、固定渲染协议和最终字节共同绑定到不可变 Artifact 身份。
func feedArtifactID(versionID, sourceHash, imageHash string) pgtype.UUID {
	return deterministicUUID(strings.Join([]string{
		versionID, sourceHash, RenderProfile, RendererVersion, imageHash,
	}, "\x00"))
}

func (h *Handler) persistArtifact(ctx context.Context, params db.UpsertComponentFeedImageArtifactParams) error {
	tx, err := h.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return err
	}
	if _, err := db.New(tx).UpsertComponentFeedImageArtifact(ctx, params); err != nil {
		_ = tx.Rollback(ctx)
		return err
	}
	return tx.Commit(ctx)
}

func renderFailure(versionID string, retryable bool) *task.Failure {
	params := map[string]any{}
	if versionID != "" {
		params["versionId"] = versionID
	}
	return &task.Failure{Code: "component_repo.feed_render_unavailable", Params: params, Retryable: retryable}
}

func deterministicUUID(value string) pgtype.UUID {
	sum := sha256.Sum256([]byte(value))
	var data [16]byte
	copy(data[:], sum[:16])
	data[6] = (data[6] & 0x0f) | 0x50
	data[8] = (data[8] & 0x3f) | 0x80
	return pgtype.UUID{Bytes: data, Valid: true}
}

func nonEmpty(values []string) []string {
	result := values[:0]
	for _, value := range values {
		if value != "" {
			result = append(result, value)
		}
	}
	return result
}

var _ task.Handler = (*Handler)(nil)
