package pixel2d

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/component"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/storage"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
	"io"
	"log/slog"
	"strings"
	"time"
)

// Service 编排 actor 授权、对象存储和短事务，不在 HTTP 链路执行图片/拼接计算。
type Service struct {
	pool  *pgxpool.Pool
	q     *db.Queries
	store storage.Store
	cfg   config.StorageConfig
}

func NewService(pool *pgxpool.Pool, store storage.Store, cfg config.StorageConfig) *Service {
	return &Service{pool, db.New(pool), store, cfg}
}

// Accepted 表示写请求已持久化，客户端可通过 taskId 或项目列表恢复进度。
type Accepted struct {
	ModelID    string `json:"modelId"`
	RevisionID string `json:"revisionId"`
	TaskID     string `json:"taskId"`
	Status     string `json:"status"`
}
type workInput struct {
	ProjectID     string        `json:"projectId"`
	RevisionID    string        `json:"revisionId"`
	Algorithm     string        `json:"algorithmVersion"`
	Metadata      Metadata      `json:"metadata,omitempty"`
	CatalogHash   string        `json:"catalogHash,omitempty"`
	ExportContext ExportContext `json:"exportContext"`
}
type workResult struct {
	ProjectID  string            `json:"projectId"`
	RevisionID string            `json:"revisionId"`
	Document   string            `json:"documentBlobId"`
	Exports    map[string]string `json:"exports,omitempty"`
}

func id(s string) (pgtype.UUID, error) {
	v, e := uuidutil.Parse(s)
	if e != nil {
		return v, invalid("id")
	}
	return v, nil
}
func taskContext(locale, zone string) (ExportContext, error) {
	l, ok := component.NormalizeLocale(locale)
	if !ok {
		return ExportContext{}, invalid("locale")
	}
	if zone == "" || len(zone) > 128 {
		return ExportContext{}, invalid("timezone")
	}
	if _, e := time.LoadLocation(zone); e != nil {
		return ExportContext{}, invalid("timezone")
	}
	return ExportContext{l, zone, ExportVersion}, nil
}
func notFound(err error) error {
	if errors.Is(err, pgx.ErrNoRows) {
		return apierror.New("request.not_found", 404, nil)
	}
	return err
}

// putBlob 先保存 owner-scoped 预留记录，再写对象。临时任务输入使用独立 UUID，避免两个相同图片任务
// 共享对象后被其中一个清理；派生产物继续按内容寻址，重试复用相同哈希且不会覆盖其他 owner。
// 失败记录保留以便审计/补偿；未 ready 对象不会被领域引用或公开下载。
func (s *Service) putBlob(ctx context.Context, actor pgtype.UUID, kind, mime string, data []byte) (pgtype.UUID, error) {
	hash := fmt.Sprintf("%x", sha256.Sum256(data))
	temporary := kind == "source" || kind == "input"
	var blobID pgtype.UUID
	if temporary {
		var err error
		blobID, err = uuidutil.New()
		if err != nil {
			return blobID, err
		}
	} else {
		sum := sha256.Sum256([]byte(uuidutil.String(actor) + ":" + kind + ":" + hash))
		var raw [16]byte
		copy(raw[:], sum[:16])
		raw[6] = (raw[6] & 15) | 80
		raw[8] = (raw[8] & 63) | 128
		blobID = pgtype.UUID{Bytes: raw, Valid: true}
	}
	key := strings.Trim(s.cfg.KeyPrefix, "/") + "/pixel-2d/" + uuidutil.String(actor) + "/" + kind + "/"
	if temporary {
		key += uuidutil.String(blobID) + "/"
	}
	key += hash
	err := s.q.ReservePixelBlob(ctx, db.ReservePixelBlobParams{ID: blobID, OwnerID: actor, ObjectKey: key, Bucket: s.store.Bucket(), Kind: kind, Sha256: hash, ByteSize: int64(len(data)), ContentType: mime})
	if err != nil {
		return blobID, err
	}
	row, err := s.q.GetPixelBlob(ctx, db.GetPixelBlobParams{ID: blobID, OwnerID: actor})
	if err != nil {
		return blobID, err
	}
	if row.Status == "ready" {
		return blobID, nil
	}
	if err = s.store.Put(ctx, key, mime, bytes.NewReader(data), int64(len(data))); err != nil {
		return blobID, err
	}
	return blobID, s.q.ReadyPixelBlob(ctx, db.ReadyPixelBlobParams{ID: blobID, OwnerID: actor})
}
func (s *Service) readBlob(ctx context.Context, actor, blobID pgtype.UUID) ([]byte, error) {
	row, err := s.q.GetPixelBlob(ctx, db.GetPixelBlobParams{ID: blobID, OwnerID: actor})
	if err != nil {
		return nil, notFound(err)
	}
	if row.Status != "ready" || row.ByteSize > 32*1024*1024 {
		return nil, domain("pixel_art.generation_failed")
	}
	r, err := s.store.Open(ctx, row.ObjectKey)
	if err != nil {
		return nil, err
	}
	defer r.Close()
	data, err := io.ReadAll(io.LimitReader(r, row.ByteSize+1))
	if err != nil {
		return nil, err
	}
	if int64(len(data)) != row.ByteSize || fmt.Sprintf("%x", sha256.Sum256(data)) != row.Sha256 {
		return nil, domain("pixel_art.generation_failed")
	}
	return data, nil
}
func (s *Service) blobURL(ctx context.Context, actor, blobID pgtype.UUID) (string, error) {
	row, e := s.q.GetPixelBlob(ctx, db.GetPixelBlobParams{ID: blobID, OwnerID: actor})
	if e != nil {
		return "", e
	}
	if row.Status != "ready" {
		return "", domain("pixel_art.generation_failed")
	}
	return s.store.SignDownload(ctx, row.ObjectKey, 15*time.Minute)
}

// Create 将上传源保存到对象存储，项目/初始修订/持久任务在同一事务中提交。
func (s *Service) Create(ctx context.Context, actor pgtype.UUID, name, source, mime string, data []byte, settings Settings, locale, zone string) (Accepted, error) {
	if err := ValidateSettings(settings); err != nil {
		return Accepted{}, err
	}
	context, e := taskContext(locale, zone)
	if e != nil {
		return Accepted{}, e
	}
	if strings.TrimSpace(name) == "" || len(name) > 512 || len(source) > 512 {
		return Accepted{}, invalid("name")
	}
	if len(data) == 0 || len(data) > 20*1024*1024 {
		return Accepted{}, invalid("image")
	}
	if mime != "image/png" && mime != "image/jpeg" && mime != "image/webp" {
		return Accepted{}, domain("pixel_art.unsupported_image_type")
	}
	blob, e := s.putBlob(ctx, actor, "source", mime, data)
	if e != nil {
		return Accepted{}, e
	}
	projectID, e := uuidutil.New()
	if e != nil {
		return Accepted{}, e
	}
	revision, e := uuidutil.New()
	if e != nil {
		return Accepted{}, e
	}
	tx, e := s.pool.Begin(ctx)
	if e != nil {
		return Accepted{}, e
	}
	defer tx.Rollback(ctx)
	q := s.q.WithTx(tx)
	if e = q.CreatePixelProject(ctx, db.CreatePixelProjectParams{ID: projectID, OwnerID: actor, Name: name, SourceName: source, ContentLocale: context.Locale, SourceBlobID: blob, GridWidth: int32(settings.GridWidth), GridHeight: int32(settings.GridHeight), ColorCount: int32(settings.ColorCount)}); e != nil {
		return Accepted{}, e
	}
	a, e := s.scheduleRevision(ctx, q, actor, projectID, revision, pgtype.UUID{}, blob, settings, GenerateType, context)
	if e != nil {
		return Accepted{}, e
	}
	if e = tx.Commit(ctx); e != nil {
		return Accepted{}, e
	}
	return a, nil
}
func (s *Service) scheduleRevision(ctx context.Context, q *db.Queries, actor, projectID, revision, parent, blob pgtype.UUID, settings Settings, kind string, c ExportContext) (Accepted, error) {
	input := workInput{ProjectID: uuidutil.String(projectID), RevisionID: uuidutil.String(revision), Algorithm: AlgorithmVersion, ExportContext: c}
	payload := mustJSON(input)
	hash := fmt.Sprintf("%x", sha256.Sum256(payload))
	job, e := task.ScheduleWithQueries(ctx, q, task.ScheduleInput{OwnerID: actor, CreatedBy: actor, TaskType: kind, LogicalKey: uuidutil.String(revision), InputHash: hash, Payload: payload, Locale: c.Locale, Timezone: c.Timezone, MaxAttempts: 3})
	if e != nil {
		return Accepted{}, e
	}
	if e = q.CreatePixelRevision(ctx, db.CreatePixelRevisionParams{ID: revision, ProjectID: projectID, OwnerID: actor, ParentRevisionID: parent, InputBlobID: blob, TaskID: job.Task.ID, Settings: mustJSON(settings)}); e != nil {
		return Accepted{}, e
	}
	n, e := q.AdvancePixelProject(ctx, db.AdvancePixelProjectParams{RevisionID: revision, ProjectID: projectID, OwnerID: actor, ParentRevisionID: parent})
	if e != nil {
		return Accepted{}, e
	}
	if n != 1 {
		return Accepted{}, apierror.New("request.validation_failed", 409, map[string]any{"field": "revisionId"})
	}
	return Accepted{input.ProjectID, input.RevisionID, uuidutil.String(job.Task.ID), job.Task.Status}, nil
}

// Edit 以 revisionId CAS 防止两个浏览器互相覆盖；像素正文进入不可变输入对象，预览由 Worker 重建。
func (s *Service) Edit(ctx context.Context, actor pgtype.UUID, projectID, revisionID string, pixels []Pixel, locale, zone string) (Accepted, error) {
	pid, e := id(projectID)
	if e != nil {
		return Accepted{}, e
	}
	parent, e := id(revisionID)
	if e != nil {
		return Accepted{}, e
	}
	c, e := taskContext(locale, zone)
	if e != nil {
		return Accepted{}, e
	}
	if len(pixels) == 0 || len(pixels) > 16384 {
		return Accepted{}, invalid("pixels")
	}
	p, e := s.q.GetPixelProject(ctx, db.GetPixelProjectParams{ID: pid, OwnerID: actor})
	if e != nil {
		return Accepted{}, notFound(e)
	}
	if !uuidutil.Equal(p.CurrentRevisionID, parent) {
		return Accepted{}, apierror.New("request.validation_failed", 409, map[string]any{"field": "revisionId"})
	}
	rev, e := s.q.GetPixelRevision(ctx, db.GetPixelRevisionParams{ID: parent, OwnerID: actor})
	if e != nil {
		return Accepted{}, notFound(e)
	}
	if !rev.DocumentBlobID.Valid {
		return Accepted{}, domain("lego_design.design_not_ready")
	}
	// HTTP 仅做有界结构校验，完整像素和 PNG 校验在 Worker；不在事务中写对象正文。
	blob, e := s.putBlob(ctx, actor, "input", "application/json", mustJSON(pixels))
	if e != nil {
		return Accepted{}, e
	}
	var settings Settings
	if e = json.Unmarshal(rev.Settings, &settings); e != nil {
		return Accepted{}, e
	}
	next, e := uuidutil.New()
	if e != nil {
		return Accepted{}, e
	}
	tx, e := s.pool.Begin(ctx)
	if e != nil {
		return Accepted{}, e
	}
	defer tx.Rollback(ctx)
	q := s.q.WithTx(tx)
	if _, e = q.LockPixelProject(ctx, db.LockPixelProjectParams{ID: pid, OwnerID: actor}); e != nil {
		return Accepted{}, e
	}
	a, e := s.scheduleRevision(ctx, q, actor, pid, next, parent, blob, settings, EditType, c)
	if e != nil {
		return Accepted{}, e
	}
	if e = tx.Commit(ctx); e != nil {
		return Accepted{}, e
	}
	return a, nil
}

// Get 返回当前不可变修订。未完成时返回可恢复的 taskId，失败不会伪装成旧成功预览。
func (s *Service) Get(ctx context.Context, actor pgtype.UUID, projectID string) (any, error) {
	pid, e := id(projectID)
	if e != nil {
		return nil, e
	}
	p, e := s.q.GetPixelProject(ctx, db.GetPixelProjectParams{ID: pid, OwnerID: actor})
	if e != nil {
		return nil, notFound(e)
	}
	r, e := s.q.GetPixelRevision(ctx, db.GetPixelRevisionParams{ID: p.CurrentRevisionID, OwnerID: actor})
	if e != nil {
		return nil, e
	}
	t, e := task.NewService(s.pool).GetOwned(ctx, actor, uuidutil.String(r.TaskID))
	if e != nil {
		return nil, e
	}
	if t.Status != task.StatusSucceeded {
		return map[string]any{"modelId": projectID, "revisionId": uuidutil.String(r.ID), "taskId": t.ID, "status": t.Status, "error": t.Error}, nil
	}
	data, e := s.readBlob(ctx, actor, r.DocumentBlobID)
	if e != nil {
		return nil, e
	}
	var result Project
	if e = json.Unmarshal(data, &result); e != nil {
		return nil, e
	}
	result.PreviewImage, e = s.blobURL(ctx, actor, r.PreviewBlobID)
	return result, e
}

// List 在同一 SQL 快照内获取页码与精确总数，只为选中页的预览签名。
func (s *Service) List(ctx context.Context, actor pgtype.UUID, page, size int) (any, error) {
	if page < 1 || size < 1 || size > 48 || int64(page-1)*int64(size) > mathMaxOffset {
		return nil, invalid("page")
	}
	row, e := s.q.ListPixelProjects(ctx, db.ListPixelProjectsParams{OwnerID: actor, PageSize: int32(size), PageOffset: int32((page - 1) * size)})
	if e != nil {
		return nil, e
	}
	var selected []struct {
		ID            string    `json:"id"`
		Name          string    `json:"name"`
		ContentLocale string    `json:"content_locale"`
		Source        string    `json:"source_name"`
		Width         int       `json:"grid_width"`
		Height        int       `json:"grid_height"`
		Colors        int       `json:"color_count"`
		Created       time.Time `json:"created_at"`
		Revision      string    `json:"current_revision_id"`
		TaskID        string    `json:"task_id"`
		Preview       *string   `json:"preview_blob_id"`
		Status        string    `json:"task_status"`
	}
	raw := row.Items
	if e = json.Unmarshal(raw, &selected); e != nil {
		return nil, e
	}
	items := []any{}
	for _, p := range selected {
		preview := ""
		if p.Preview != nil && p.Status == task.StatusSucceeded {
			bid, e := id(*p.Preview)
			if e != nil {
				return nil, e
			}
			preview, e = s.blobURL(ctx, actor, bid)
			if e != nil {
				return nil, e
			}
		}
		items = append(items, map[string]any{"modelId": p.ID, "name": p.Name, "contentLocale": p.ContentLocale, "source": p.Source, "gridWidth": p.Width, "gridHeight": p.Height, "colorCount": p.Colors, "createdAt": p.Created, "revisionId": p.Revision, "taskId": p.TaskID, "status": p.Status, "previewImage": preview})
	}
	return map[string]any{"page": page, "pageSize": size, "total": row.Total, "items": items}, nil
}

const mathMaxOffset = int64(2147483647)

// Metadata 只读取显式导入的冻结目录，不在请求中解析 Part Library 或生成几何。
func (s *Service) Metadata(ctx context.Context) (Metadata, error) {
	row, e := s.q.GetPixelCatalog(ctx)
	if e != nil {
		return Metadata{}, notFound(e)
	}
	var m Metadata
	e = json.Unmarshal(row.Document, &m)
	return m, e
}

// CreateDesign 在短事务中确认项目修订与冻结目录，逻辑任务哈希包括版本及导出上下文。
func (s *Service) CreateDesign(ctx context.Context, actor pgtype.UUID, projectID, locale, zone string) (any, error) {
	pid, e := id(projectID)
	if e != nil {
		return nil, e
	}
	c, e := taskContext(locale, zone)
	if e != nil {
		return nil, e
	}
	tx, e := s.pool.Begin(ctx)
	if e != nil {
		return nil, e
	}
	defer tx.Rollback(ctx)
	q := s.q.WithTx(tx)
	p, e := q.LockPixelProject(ctx, db.LockPixelProjectParams{ID: pid, OwnerID: actor})
	if e != nil {
		return nil, notFound(e)
	}
	r, e := q.GetPixelRevision(ctx, db.GetPixelRevisionParams{ID: p.CurrentRevisionID, OwnerID: actor})
	if e != nil {
		return nil, e
	}
	if !r.DocumentBlobID.Valid {
		return nil, domain("lego_design.design_not_ready")
	}
	// 派生文件先于任务完成写入；不能把崩溃窗口内的物化状态视为任务成功。
	origin, e := q.GetOwnedTask(ctx, db.GetOwnedTaskParams{TaskID: r.TaskID, ActorID: actor})
	if e != nil {
		return nil, e
	}
	if origin.Status != task.StatusSucceeded {
		return nil, domain("lego_design.design_not_ready")
	}
	catalog, e := q.GetPixelCatalog(ctx)
	if e != nil {
		return nil, notFound(e)
	}
	var m Metadata
	if e = json.Unmarshal(catalog.Document, &m); e != nil {
		return nil, e
	}
	input := workInput{projectID, uuidutil.String(r.ID), AlgorithmVersion, m, catalog.Hash, c}
	payload := mustJSON(input)
	hash := fmt.Sprintf("%x", sha256.Sum256(payload))
	job, e := task.ScheduleWithQueries(ctx, q, task.ScheduleInput{OwnerID: actor, CreatedBy: actor, TaskType: DesignType, LogicalKey: projectID, InputHash: hash, Payload: payload, Locale: c.Locale, Timezone: c.Timezone, MaxAttempts: 3})
	if e != nil {
		return nil, e
	}
	if e = tx.Commit(ctx); e != nil {
		return nil, e
	}
	return s.Job(ctx, actor, uuidutil.String(job.Task.ID))
}

// Job 将共享任务投影为现有设计页面契约；succeeded 映射 complete，数据库状态不翻译。
func (s *Service) Job(ctx context.Context, actor pgtype.UUID, jobID string) (any, error) {
	tid, e := id(jobID)
	if e != nil {
		return nil, e
	}
	row, e := s.q.GetOwnedTask(ctx, db.GetOwnedTaskParams{TaskID: tid, ActorID: actor})
	if e != nil {
		return nil, notFound(e)
	}
	if row.TaskType != DesignType {
		return nil, apierror.New("request.not_found", 404, nil)
	}
	var input workInput
	if e = json.Unmarshal(row.Payload, &input); e != nil {
		return nil, e
	}
	t, e := task.NewService(s.pool).GetOwned(ctx, actor, jobID)
	if e != nil {
		return nil, e
	}
	status := t.Status
	var result *Design
	if status == task.StatusSucceeded {
		status = "complete"
		var wr workResult
		if e = json.Unmarshal(t.Result, &wr); e != nil {
			return nil, e
		}
		bid, e := id(wr.Document)
		if e != nil {
			return nil, e
		}
		data, e := s.readBlob(ctx, actor, bid)
		if e != nil {
			return nil, e
		}
		result = &Design{}
		if e = json.Unmarshal(data, result); e != nil {
			return nil, e
		}
	}
	code := "lego_design.progress.queued"
	percent := 0
	if status == "running" {
		code = "lego_design.progress.processing"
		percent = 20
	}
	if status == "complete" {
		code = "lego_design.progress.completed"
		percent = 100
	}
	if status == "failed" || status == "cancelled" {
		code = "lego_design.progress.failed"
		percent = 100
		status = "failed"
	}
	return map[string]any{"jobId": jobID, "status": status, "projectId": input.ProjectID, "result": result, "error": t.Error, "progress": map[string]any{"percent": percent, "code": code, "params": map[string]any{"percent": percent}}, "locale": input.ExportContext.Locale, "timezone": input.ExportContext.Timezone, "catalogVersion": input.ExportContext.CatalogVersion}, nil
}

// Download 只读取任务已冻结、验证并落库的导出对象；下载不触发生成。
func (s *Service) Download(ctx context.Context, actor pgtype.UUID, jobID, kind string, base bool) ([]byte, string, error) {
	tid, e := id(jobID)
	if e != nil {
		return nil, "", e
	}
	row, e := s.q.GetOwnedTask(ctx, db.GetOwnedTaskParams{TaskID: tid, ActorID: actor})
	if e != nil {
		return nil, "", notFound(e)
	}
	if row.TaskType != DesignType || row.Status != task.StatusSucceeded {
		return nil, "", domain("lego_design.design_not_ready")
	}
	var wr workResult
	var input workInput
	if e = json.Unmarshal(row.Result, &wr); e != nil {
		return nil, "", e
	}
	if e = json.Unmarshal(row.Payload, &input); e != nil {
		return nil, "", e
	}
	bid, e := id(wr.Exports[fmt.Sprintf("%s:%t", kind, base)])
	if e != nil {
		return nil, "", e
	}
	data, e := s.readBlob(ctx, actor, bid)
	if e != nil {
		return nil, "", e
	}
	catalog, e := exportCatalog(input.ExportContext)
	if e != nil {
		return nil, "", e
	}
	key := "legoLdraw"
	if kind == "plan" {
		key = "legoPlan"
	}
	return data, exportText(catalog, "filenames."+key, map[string]any{"jobId": jobID}), nil
}

// Handle 是三类持久任务的共同入口。产物以内容寻址幂等写入，旧 attempt 只能完成自己的修订。
func (s *Service) Handle(ctx context.Context, claimed task.ClaimedTask) (task.Result, error) {
	r, e := s.execute(ctx, claimed)
	if e == nil {
		return r, nil
	}
	var public *apierror.Error
	if errors.As(e, &public) {
		return task.Result{}, &task.Failure{Code: public.Code, Params: public.Params, Retryable: false}
	}
	if errors.Is(e, context.Canceled) {
		return task.Result{}, e
	}
	code := "pixel_art.generation_failed"
	if claimed.TaskType == DesignType {
		code = "lego_design.generation_failed"
	}
	return task.Result{}, &task.Failure{Code: code, Retryable: true}
}

// execute 按持久任务读取冻结输入；阶段计时只记录机器 ID 和耗时，不记录图片、路径或用户内容。
func (s *Service) execute(ctx context.Context, c task.ClaimedTask) (task.Result, error) {
	var input workInput
	if e := json.Unmarshal(c.Payload, &input); e != nil {
		return task.Result{}, invalid("payload")
	}
	if input.Algorithm != AlgorithmVersion {
		return task.Result{}, invalid("algorithmVersion")
	}
	rid, e := id(input.RevisionID)
	if e != nil {
		return task.Result{}, e
	}
	rev, e := s.q.GetPixelRevision(ctx, db.GetPixelRevisionParams{ID: rid, OwnerID: c.OwnerID})
	if e != nil {
		return task.Result{}, notFound(e)
	}
	if uuidutil.String(rev.ProjectID) != input.ProjectID {
		return task.Result{}, invalid("projectId")
	}
	if c.TaskType == DesignType {
		return s.executeDesign(ctx, c, input, rev)
	}
	if c.TaskType != GenerateType && c.TaskType != EditType {
		return task.Result{}, invalid("taskType")
	}
	if !uuidutil.Equal(rev.TaskID, c.ID) {
		return task.Result{}, invalid("taskId")
	}
	if rev.DocumentBlobID.Valid {
		// 产物已完成但上次清理可能因网络失败中断；重试只清理临时输入，不重复像素计算。
		if e = s.deleteTemporaryInput(ctx, c.OwnerID, rev.InputBlobID); e != nil {
			return task.Result{}, e
		}
		return task.Result{Payload: mustJSON(workResult{ProjectID: input.ProjectID, RevisionID: input.RevisionID, Document: uuidutil.String(rev.DocumentBlobID)})}, nil
	}
	stageStarted := time.Now()
	data, e := s.readBlob(ctx, c.OwnerID, rev.InputBlobID)
	logPixelStage(c, "read_input", stageStarted, e)
	if e != nil {
		return task.Result{}, e
	}
	var settings Settings
	if e = json.Unmarshal(rev.Settings, &settings); e != nil {
		return task.Result{}, e
	}
	var p Project
	var preview []byte
	stageStarted = time.Now()
	if c.TaskType == GenerateType {
		p, preview, e = Quantize(ctx, data, settings)
	} else {
		p = Project{Schema: "pixel-art-v1", GridWidth: settings.GridWidth, GridHeight: settings.GridHeight, ColorCount: settings.ColorCount}
		e = json.Unmarshal(data, &p.Pixels)
		if e == nil {
			preview, e = normalizePixels(&p)
		}
	}
	if e != nil {
		return task.Result{}, e
	}
	logPixelStage(c, "compute_pixels", stageStarted, nil)
	stageStarted = time.Now()
	project, e := s.q.GetPixelProject(ctx, db.GetPixelProjectParams{ID: rev.ProjectID, OwnerID: c.OwnerID})
	if e != nil {
		return task.Result{}, e
	}
	p.ModelID = input.ProjectID
	p.RevisionID = input.RevisionID
	p.Name = project.Name
	p.ContentLocale = project.ContentLocale
	p.Source = project.SourceName
	p.CreatedAt = project.CreatedAt.Time
	document, e := s.putBlob(ctx, c.OwnerID, "project", "application/json", mustJSON(p))
	if e != nil {
		return task.Result{}, e
	}
	image, e := s.putBlob(ctx, c.OwnerID, "preview", "image/png", preview)
	if e != nil {
		return task.Result{}, e
	}
	_, e = s.q.CompletePixelRevision(ctx, db.CompletePixelRevisionParams{ID: rid, OwnerID: c.OwnerID, DocumentBlobID: document, PreviewBlobID: image})
	if e != nil {
		return task.Result{}, e
	}
	if e = s.deleteTemporaryInput(ctx, c.OwnerID, rev.InputBlobID); e != nil {
		return task.Result{}, e
	}
	logPixelStage(c, "persist_outputs", stageStarted, nil)
	return task.Result{Payload: mustJSON(workResult{ProjectID: p.ModelID, RevisionID: p.RevisionID, Document: uuidutil.String(document)})}, nil
}

// deleteTemporaryInput 在修订产物已完成后删除任务输入正文；数据库只保留哈希和审计定位。
// Supabase Delete 对不存在对象幂等，因此 Worker 在崩溃或网络失败后可以安全重试清理。
func (s *Service) deleteTemporaryInput(ctx context.Context, actor, blobID pgtype.UUID) error {
	row, err := s.q.GetPixelBlob(ctx, db.GetPixelBlobParams{ID: blobID, OwnerID: actor})
	if err != nil {
		return err
	}
	return s.store.Delete(ctx, row.ObjectKey)
}
func (s *Service) executeDesign(ctx context.Context, c task.ClaimedTask, input workInput, rev db.GetPixelRevisionRow) (task.Result, error) {
	data, e := s.readBlob(ctx, c.OwnerID, rev.DocumentBlobID)
	if e != nil {
		return task.Result{}, e
	}
	var p Project
	if e = json.Unmarshal(data, &p); e != nil {
		return task.Result{}, e
	}
	d, e := GenerateDesign(ctx, p, input.Metadata)
	if e != nil {
		return task.Result{}, e
	}
	document, e := s.putBlob(ctx, c.OwnerID, "design", "application/json", mustJSON(d))
	if e != nil {
		return task.Result{}, e
	}
	out := workResult{ProjectID: input.ProjectID, RevisionID: input.RevisionID, Document: uuidutil.String(document), Exports: map[string]string{}}
	for _, base := range []bool{false, true} {
		ldraw, plan, e := ExportDesign(ctx, d, input.Metadata, base, input.ExportContext)
		if e != nil {
			return task.Result{}, e
		}
		for _, f := range []struct {
			kind, mime string
			data       []byte
		}{{"ldraw", "text/plain; charset=utf-8", ldraw}, {"plan", "application/json", plan}} {
			bid, e := s.putBlob(ctx, c.OwnerID, f.kind, f.mime, f.data)
			if e != nil {
				return task.Result{}, e
			}
			out.Exports[fmt.Sprintf("%s:%t", f.kind, base)] = uuidutil.String(bid)
		}
	}
	return task.Result{Payload: mustJSON(out)}, nil
}

// logPixelStage 区分远程读取、纯计算与持久化耗时，避免将任务墙钟时间误判为算法 CPU 时间。
func logPixelStage(c task.ClaimedTask, stage string, started time.Time, err error) {
	slog.Info("pixel task stage completed", "taskId", uuidutil.String(c.ID), "taskType", c.TaskType, "stage", stage, "durationMs", float64(time.Since(started).Microseconds())/1000, "succeeded", err == nil)
}
