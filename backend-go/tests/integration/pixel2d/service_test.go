//go:build integration

package pixel2d_test

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
	. "github.com/ctbzbricks/brickbuilder/backend-go/internal/pixel2d"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/storage"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
	"io"
	"os"
	"sync"
	"testing"
	"time"
)

// testStore 模拟独立对象存储；跨 Service/Worker 重建仍保留内容，支持故障注入。
type testStore struct {
	sync.Mutex
	objects map[string][]byte
	fail    bool
}

type testPixelService struct {
	*Service
	pool *pgxpool.Pool
	q    *db.Queries
}

func newTestPixelService(pool *pgxpool.Pool, store storage.Store, cfg config.StorageConfig) *testPixelService {
	return &testPixelService{Service: NewService(pool, store, cfg), pool: pool, q: db.New(pool)}
}

func (s *testStore) Provider() string { return "test" }
func (s *testStore) Bucket() string   { return "test" }
func (s *testStore) Put(_ context.Context, key, _ string, r io.Reader, _ int64) error {
	s.Lock()
	defer s.Unlock()
	if s.fail {
		return storage.ErrUnavailable
	}
	b, e := io.ReadAll(r)
	s.objects[key] = b
	return e
}
func (s *testStore) Open(_ context.Context, key string) (io.ReadCloser, error) {
	s.Lock()
	defer s.Unlock()
	b, ok := s.objects[key]
	if !ok {
		return nil, storage.ErrNotFound
	}
	return io.NopCloser(bytes.NewReader(b)), nil
}
func (s *testStore) Head(ctx context.Context, key string) (storage.ObjectMetadata, error) {
	r, e := s.Open(ctx, key)
	if e != nil {
		return storage.ObjectMetadata{}, e
	}
	defer r.Close()
	b, e := io.ReadAll(r)
	return storage.ObjectMetadata{Size: int64(len(b))}, e
}
func (s *testStore) HeadForUser(c context.Context, k, _ string) (storage.ObjectMetadata, error) {
	return s.Head(c, k)
}
func (s *testStore) Delete(_ context.Context, k string) error {
	s.Lock()
	defer s.Unlock()
	delete(s.objects, k)
	return nil
}
func (s *testStore) SignDownload(_ context.Context, k string, _ time.Duration) (string, error) {
	return "https://objects.test/" + k, nil
}
func (s *testStore) SignDownloadForUser(c context.Context, k string, d time.Duration, _ string) (string, error) {
	return s.SignDownload(c, k, d)
}
func (s *testStore) SignDownloads(c context.Context, keys []string, d time.Duration) (map[string]string, error) {
	m := map[string]string{}
	for _, k := range keys {
		m[k], _ = s.SignDownload(c, k, d)
	}
	return m, nil
}
func testPool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	url := os.Getenv("TEST_DATABASE_URL")
	if url == "" {
		t.Skip("TEST_DATABASE_URL required")
	}
	pool, e := pgxpool.New(context.Background(), url)
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(pool.Close)
	return pool
}
func newActor(t *testing.T) pgtype.UUID {
	t.Helper()
	v, e := uuidutil.New()
	if e != nil {
		t.Fatal(e)
	}
	return v
}
func runTask(t *testing.T, s *testPixelService, kind string) task.ClaimedTask {
	t.Helper()
	ctx := context.Background()
	queue := task.NewService(s.pool)
	c, ok, e := queue.Claim(ctx, "pixel-test", []string{kind}, time.Minute)
	if e != nil || !ok {
		t.Fatalf("claim %t %v", ok, e)
	}
	r, e := s.Handle(ctx, c)
	if e != nil {
		t.Fatal(e)
	}
	if e = queue.Complete(ctx, "pixel-test", c, r); e != nil {
		t.Fatal(e)
	}
	return c
}

// TestGoOnlyPixelWorkflow 验证无 Python 的源上传、任务、并发编辑、冻结设计、跨 actor 拒绝与导出恢复。
func TestGoOnlyPixelWorkflow(t *testing.T) {
	ctx := context.Background()
	pool := testPool(t)
	store := &testStore{objects: map[string][]byte{}}
	cfg := config.StorageConfig{KeyPrefix: "test"}
	s := newTestPixelService(pool, store, cfg)
	a, b := newActor(t), newActor(t)
	_, m, _ := fixture(t)
	if _, e := ImportCatalog(ctx, pool, mustJSON(m)); e != nil {
		t.Fatal(e)
	}
	source, e := os.ReadFile("../../../internal/pixel2d/testdata/photo_illustration-blocks.png")
	if e != nil {
		t.Fatal(e)
	}
	settings := Settings{Algorithm: "photo_illustration", GridWidth: 4, GridHeight: 4, ColorCount: 4}
	settings.Crop.Width = 12
	settings.Crop.Height = 12
	settings.Preprocessing.Brightness = 1
	settings.Preprocessing.Contrast = 1
	settings.Preprocessing.Saturation = 1
	settings.Preprocessing.Sharpness = 1
	accepted, e := s.Create(ctx, a, "原样 Name", "source.png", "image/png", source, settings, "zh-CN", "Asia/Shanghai")
	if e != nil {
		t.Fatal(e)
	}
	if _, e = s.Get(ctx, b, accepted.ModelID); e == nil {
		t.Fatal("cross actor read")
	}
	// 重建 API/Worker 对象后 claim PostgreSQL 中的任务；不使用内存 job 状态。
	s = newTestPixelService(pool, store, cfg)
	runTask(t, s, GenerateType)
	pid, _ := id(accepted.ModelID)
	projectRow, e := s.q.GetPixelProject(ctx, db.GetPixelProjectParams{ID: pid, OwnerID: a})
	if e != nil {
		t.Fatal(e)
	}
	sourceBlob, e := s.q.GetPixelBlob(ctx, db.GetPixelBlobParams{ID: projectRow.SourceBlobID, OwnerID: a})
	if e != nil {
		t.Fatal(e)
	}
	if _, e = store.Open(ctx, sourceBlob.ObjectKey); !errors.Is(e, storage.ErrNotFound) {
		t.Fatal("successful pixel task retained temporary source")
	}
	value, e := s.Get(ctx, a, accepted.ModelID)
	if e != nil {
		t.Fatal(e)
	}
	p := value.(Project)
	if p.Name != "原样 Name" || p.PreviewImage == "" {
		t.Fatal(p)
	}
	job, e := s.CreateDesign(ctx, a, p.ModelID, "en-US", "UTC")
	if e != nil {
		t.Fatal(e)
	}
	jobID := job.(map[string]any)["jobId"].(string)
	same, e := s.CreateDesign(ctx, a, p.ModelID, "en-US", "UTC")
	if e != nil || same.(map[string]any)["jobId"] != jobID {
		t.Fatal("logical job not reused", e)
	}
	p.Pixels[0].RGB = "#0000FF"
	next, e := s.Edit(ctx, a, p.ModelID, p.RevisionID, p.Pixels, "zh-CN", "Asia/Shanghai")
	if e != nil {
		t.Fatal(e)
	}
	if _, e = s.Edit(ctx, a, p.ModelID, p.RevisionID, p.Pixels, "zh-CN", "Asia/Shanghai"); e == nil {
		t.Fatal("stale edit accepted")
	}
	runTask(t, s, EditType)
	value, e = s.Get(ctx, a, p.ModelID)
	if e != nil {
		t.Fatal(e)
	}
	updated := value.(Project)
	if updated.RevisionID != next.RevisionID || updated.PreviewImage == p.PreviewImage {
		t.Fatal("edit did not refresh preview")
	}
	// 设计仍读取排队时的旧修订，而不是随后编辑后的当前项目。
	runTask(t, s, DesignType)
	result, e := s.Job(ctx, a, jobID)
	if e != nil {
		t.Fatal(e)
	}
	finished := result.(map[string]any)
	if finished["status"] != "complete" || finished["locale"] != "en-US" {
		t.Fatal(finished)
	}
	progress := finished["progress"].(map[string]any)
	if progress["params"].(map[string]any)["percent"] != 100 {
		t.Fatal("progress interpolation missing")
	}
	if finished["result"].(*Design).Placements[0].ColorRGB != "#FF0000" {
		t.Fatal("design used mutable project")
	}
	for _, base := range []bool{false, true} {
		for _, kind := range []string{"ldraw", "plan"} {
			content, name, e := s.Download(ctx, a, jobID, kind, base)
			if e != nil || len(content) == 0 || name == "" {
				t.Fatal("download", e)
			}
			if _, _, e = s.Download(ctx, b, jobID, kind, base); e == nil {
				t.Fatal("cross actor download")
			}
		}
	}
	// Worker 重复执行已物化 revision 不覆盖文件或不可变行。
	rid, _ := id(p.RevisionID)
	rev, e := s.q.GetPixelRevision(ctx, db.GetPixelRevisionParams{ID: rid, OwnerID: a})
	if e != nil {
		t.Fatal(e)
	}
	if _, e = s.pool.Exec(ctx, "UPDATE pixel_2d.revisions SET settings='{}' WHERE id=$1", rid); e == nil {
		t.Fatal("immutable revision changed")
	}
	if !rev.DocumentBlobID.Valid {
		t.Fatal("missing document")
	}
	store.fail = true
	if _, e = s.Create(ctx, a, "fail", "other.png", "image/png", []byte("bad"), settings, "en-US", "UTC"); e == nil {
		t.Fatal("storage failure ignored")
	}
	store.fail = false
	list, e := s.List(ctx, a, 1, 12)
	if e != nil {
		t.Fatal(e)
	}
	if list.(map[string]any)["total"] != int64(1) {
		t.Fatal("failed source created project", list)
	}
}

// TestIdenticalTemporaryInputsAreIndependent 防止相同照片的并发任务共享对象后被先完成任务误删。
func TestIdenticalTemporaryInputsAreIndependent(t *testing.T) {
	ctx := context.Background()
	pool := testPool(t)
	store := &testStore{objects: map[string][]byte{}}
	s := newTestPixelService(pool, store, config.StorageConfig{KeyPrefix: "test"})
	actor := newActor(t)
	source, err := os.ReadFile("../../../internal/pixel2d/testdata/photo_illustration-blocks.png")
	if err != nil {
		t.Fatal(err)
	}
	settings := Settings{Algorithm: "photo_illustration", GridWidth: 4, GridHeight: 4, ColorCount: 4}
	settings.Crop.Width, settings.Crop.Height = 12, 12
	settings.Preprocessing.Brightness, settings.Preprocessing.Contrast = 1, 1
	settings.Preprocessing.Saturation, settings.Preprocessing.Sharpness = 1, 1
	first, err := s.Create(ctx, actor, "first", "same.png", "image/png", source, settings, "en-US", "UTC")
	if err != nil {
		t.Fatal(err)
	}
	second, err := s.Create(ctx, actor, "second", "same.png", "image/png", source, settings, "en-US", "UTC")
	if err != nil {
		t.Fatal(err)
	}
	runTask(t, s, GenerateType)
	runTask(t, s, GenerateType)
	if _, err = s.Get(ctx, actor, first.ModelID); err != nil {
		t.Fatal(err)
	}
	if _, err = s.Get(ctx, actor, second.ModelID); err != nil {
		t.Fatal(err)
	}
}

func fixture(t *testing.T) (Project, Metadata, Design) {
	t.Helper()
	data, err := os.ReadFile("../../../internal/pixel2d/testdata/design.json")
	if err != nil {
		t.Fatal(err)
	}
	var value struct {
		Project  Project
		Metadata Metadata
		Expected Design
	}
	if err := json.Unmarshal(data, &value); err != nil {
		t.Fatal(err)
	}
	return value.Project, value.Metadata, value.Expected
}

func mustJSON(value any) []byte {
	data, err := json.Marshal(value)
	if err != nil {
		panic(err)
	}
	return data
}

func id(value string) (pgtype.UUID, error) {
	return uuidutil.Parse(value)
}
