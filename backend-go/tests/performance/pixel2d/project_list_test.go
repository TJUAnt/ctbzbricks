//go:build integration

package pixel2d_test

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"testing"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/config"
	. "github.com/ctbzbricks/brickbuilder/backend-go/internal/pixel2d"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/storage"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

// TestPixelProjectPlans 评估 10 万高占比 actor 的首/深页及空/选择性 actor，保留真实执行计划。
func TestPixelProjectPlans(t *testing.T) {
	if os.Getenv("RUN_PIXEL_PLAN_TEST") != "1" {
		t.Skip("RUN_PIXEL_PLAN_TEST=1 required")
	}
	ctx := context.Background()
	pool := testPool(t)
	a, b, blob := newActor(t), newActor(t), newActor(t)
	_, err := pool.Exec(ctx, `INSERT INTO pixel_2d.blobs(id,owner_id,object_key,bucket,kind,sha256,byte_size,content_type,status) VALUES($1,$2,$3,'test','source',repeat('a',64),1,'image/png','ready')`, blob, a, "perf/"+uuidutil.String(blob))
	if err != nil {
		t.Fatal(err)
	}
	_, err = pool.Exec(ctx, `INSERT INTO pixel_2d.projects(id,owner_id,name,content_locale,source_name,source_blob_id,grid_width,grid_height,color_count,created_at) SELECT md5($1::text || i::text)::uuid,$2,'project','en-US','source.png',$3,4,4,4,'2026-01-01'::timestamptz + i * interval '1 second' FROM generate_series(1,100000) i`, uuidutil.String(a), a, blob)
	if err != nil {
		t.Fatal(err)
	}
	// 每个项目都有修订；大表下验证页内 enrich 仍按主键探测，避免空修订样本低估成本。
	_, err = pool.Exec(ctx, `INSERT INTO pixel_2d.revisions(id,project_id,owner_id,input_blob_id,task_id,settings)
 SELECT md5(p.id::text || 'revision')::uuid,p.id,p.owner_id,p.source_blob_id,
 (SELECT id FROM component_repo.tasks LIMIT 1),'{}'::jsonb FROM pixel_2d.projects p WHERE p.owner_id=$1`, a)
	if err != nil {
		t.Fatal(err)
	}
	_, err = pool.Exec(ctx, `UPDATE pixel_2d.projects SET current_revision_id=md5(id::text || 'revision')::uuid WHERE owner_id=$1`, a)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = pool.Exec(ctx, "VACUUM ANALYZE pixel_2d.revisions"); err != nil {
		t.Fatal(err)
	}
	if _, err = pool.Exec(ctx, "VACUUM ANALYZE pixel_2d.projects"); err != nil {
		t.Fatal(err)
	}
	var version string
	if err := pool.QueryRow(ctx, "SELECT version()").Scan(&version); err != nil {
		t.Fatal(err)
	}
	t.Log(version)
	raw, err := os.ReadFile("../../../db/queries/pixel_2d.sql")
	if err != nil {
		t.Fatal(err)
	}
	query := strings.Split(string(raw), "-- name: ListPixelProjects :one")[1]
	query = strings.ReplaceAll(query, "sqlc.arg(owner_id)", "$1")
	query = strings.ReplaceAll(query, "sqlc.arg(page_size)", "$2")
	query = strings.ReplaceAll(query, "sqlc.arg(page_offset)", "$3")
	for _, scenario := range []struct {
		name   string
		actor  pgtype.UUID
		offset int
	}{{"high-match-first", a, 0}, {"high-match-middle", a, 49992}, {"high-match-deep", a, 99996}, {"empty-actor", b, 0}} {
		rows, err := pool.Query(ctx, "EXPLAIN (ANALYZE, BUFFERS, SETTINGS) "+query, scenario.actor, 12, scenario.offset)
		if err != nil {
			t.Fatal(err)
		}
		t.Log(scenario.name)
		for rows.Next() {
			var line string
			if err := rows.Scan(&line); err != nil {
				t.Fatal(err)
			}
			t.Log(line)
		}
		if err := rows.Err(); err != nil {
			t.Fatal(err)
		}
		rows.Close()
	}
	// actor-owned one-row scope 有相同过滤结构，不读取高占比 actor 数据。
	var owner pgtype.UUID
	// 选择性 actor 只在已有其他所有者样本时补采计划；当前基准数据允许该分支为空。
	_ = pool.QueryRow(ctx, "SELECT owner_id FROM pixel_2d.projects WHERE owner_id<>$1 LIMIT 1", a).Scan(&owner)
	if owner.Valid {
		rows, err := pool.Query(ctx, "EXPLAIN (ANALYZE, BUFFERS, SETTINGS) "+query, owner, 12, 0)
		if err != nil {
			t.Fatal(err)
		}
		t.Log("selective-actor")
		for rows.Next() {
			var line string
			if err := rows.Scan(&line); err != nil {
				t.Fatal(err)
			}
			t.Log(line)
		}
		rows.Close()
	}
	service := NewService(pool, storage.New(config.StorageConfig{}), config.StorageConfig{})
	list, err := service.List(ctx, a, 1, 12)
	if err != nil {
		t.Fatal(err)
	}
	data, _ := json.Marshal(list)
	if !bytes.Contains(data, []byte(`"total":100000`)) {
		t.Fatal(fmt.Sprint(list))
	}
}

func testPool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	databaseURL := os.Getenv("TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("TEST_DATABASE_URL required")
	}
	pool, err := pgxpool.New(context.Background(), databaseURL)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	return pool
}

func newActor(t *testing.T) pgtype.UUID {
	t.Helper()
	id, err := uuidutil.New()
	if err != nil {
		t.Fatal(err)
	}
	return id
}
