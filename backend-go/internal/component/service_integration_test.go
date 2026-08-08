//go:build integration

package component

import (
	"context"
	"errors"
	"os"
	"strings"
	"sync"
	"testing"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

func TestG3ComponentCatalogContract(t *testing.T) {
	databaseURL := os.Getenv("TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatalf("connect PostgreSQL: %v", err)
	}
	defer pool.Close()
	resetComponentRepo(t, pool)

	service := NewService(pool)
	actorA := mustUUID(t, "20000000-0000-0000-0000-000000000001")
	actorB := mustUUID(t, "20000000-0000-0000-0000-000000000002")

	created, err := service.CreateComponent(ctx, actorA, CreateComponentInput{
		Name: "  用户组件  ", Description: pointer(" 保留原文 "), Tags: []string{"标签"}, ContentLocale: "zh",
	})
	if err != nil {
		t.Fatalf("create component: %v", err)
	}
	if created.Name != "  用户组件  " || created.Description == nil || *created.Description != " 保留原文 " || created.ContentLocale != "zh-CN" || created.OwnerID == nil || *created.OwnerID != uuidutil.String(actorA) {
		t.Fatalf("unexpected created component: %+v", created)
	}
	if _, err := service.GetComponent(ctx, actorB, created.ID, "en-US"); errorCode(err) != "component_repo.component_not_found" {
		t.Fatalf("cross-user draft read code = %q, error = %v", errorCode(err), err)
	}
	newName := "越权修改"
	if _, err := service.UpdateComponent(ctx, actorB, created.ID, UpdateComponentInput{Name: &newName}); errorCode(err) != "component_repo.component_not_found" {
		t.Fatalf("cross-user update code = %q, error = %v", errorCode(err), err)
	}

	seedVersionDependencies(t, pool, actorA)
	_, err = pool.Exec(ctx, `
		INSERT INTO component_repo.artifacts
			(id, owner_id, artifact_type, source_kind, original_filename, storage_provider,
			 storage_bucket, storage_key, sha256, file_size, mime_type, uploaded_by)
		VALUES
			('20000000-0000-0000-0000-000000000013', $1, 'ldraw', 'source', 'foreign.ldr',
			 'test', 'test', 'g3/foreign.ldr', repeat('4', 64), 1, 'text/plain', $1)`, actorB)
	if err != nil {
		t.Fatalf("seed foreign artifact: %v", err)
	}
	_, err = service.CreateVersion(ctx, actorA, created.ID, CreateVersionInput{
		Version: "forbidden", Revision: 1,
		SourceArtifactID: "20000000-0000-0000-0000-000000000013",
		SceneSnapshotID:  "20000000-0000-0000-0000-000000000012", ParserVersion: "g3-fixture",
		InterfaceSignature: strings.Repeat("1", 64), StructureHash: strings.Repeat("2", 64), GeometryHash: strings.Repeat("3", 64),
	})
	if errorCode(err) != "component_repo.version_source_not_found_failed" {
		t.Fatalf("foreign version input code = %q, error = %v", errorCode(err), err)
	}
	version, err := service.CreateVersion(ctx, actorA, created.ID, CreateVersionInput{
		Version: "1.0.0", Revision: 1,
		SourceArtifactID: "20000000-0000-0000-0000-000000000010",
		SceneSnapshotID:  "20000000-0000-0000-0000-000000000012",
		ParserVersion:    "g3-fixture", InterfaceSignature: strings.Repeat("1", 64),
		StructureHash: strings.Repeat("2", 64), GeometryHash: strings.Repeat("3", 64),
	})
	if err != nil {
		t.Fatalf("create draft version: %v", err)
	}
	if _, err := service.GetVersion(ctx, actorB, version.ID); errorCode(err) != "component_repo.version_not_found" {
		t.Fatalf("cross-user draft version read code = %q", errorCode(err))
	}
	published, err := service.PublishVersion(ctx, actorA, version.ID)
	if err != nil || published.Status != "published" || published.PublishedAt == nil {
		t.Fatalf("publish version: %+v, %v", published, err)
	}
	visible, err := service.GetComponent(ctx, actorB, created.ID, "en-US")
	if err != nil || visible.Status != "active" || visible.CurrentVersionID == nil || *visible.CurrentVersionID != version.ID {
		t.Fatalf("published component visibility: %+v, %v", visible, err)
	}
	if _, err := service.GetVersion(ctx, actorB, version.ID); err != nil {
		t.Fatalf("published version should be visible: %v", err)
	}

	testOfficialTranslationSelection(t, service, pool, actorA)
	testGroupsMembershipsAndSubscriptions(t, service, actorA, actorB, created.ID)
	testStablePagination(t, service, actorA)
}

func testOfficialTranslationSelection(t *testing.T, service *Service, pool *pgxpool.Pool, reviewer pgtype.UUID) {
	t.Helper()
	ctx := context.Background()
	_, err := pool.Exec(ctx, `
		INSERT INTO component_repo.components
			(id, content_kind, content_locale, name, status, created_by)
		VALUES
			('20000000-0000-0000-0000-000000000020', 'official', 'en-US', 'Official source', 'active', $1)`, reviewer)
	if err != nil {
		t.Fatalf("seed official component: %v", err)
	}
	_, err = pool.Exec(ctx, `
		INSERT INTO component_repo.component_translations
			(component_id, locale, name, translation_status)
		VALUES
			('20000000-0000-0000-0000-000000000020', 'zh-CN', '未审核名称', 'draft')`)
	if err != nil {
		t.Fatalf("seed official translation: %v", err)
	}
	fallback, err := service.GetComponent(ctx, reviewer, "20000000-0000-0000-0000-000000000020", "zh-CN")
	if err != nil || fallback.Name != "Official source" || fallback.ContentLocale != "en-US" || !fallback.TranslationMissing {
		t.Fatalf("draft translation must not be selected: %+v, %v", fallback, err)
	}
	_, err = pool.Exec(ctx, `
		UPDATE component_repo.component_translations
		SET name = '已审核名称', translation_status = 'reviewed', reviewed_by = $1, reviewed_at = now()
		WHERE component_id = '20000000-0000-0000-0000-000000000020' AND locale = 'zh-CN'`, reviewer)
	if err != nil {
		t.Fatalf("review translation: %v", err)
	}
	reviewed, err := service.GetComponent(ctx, reviewer, "20000000-0000-0000-0000-000000000020", "zh-CN")
	if err != nil || reviewed.Name != "已审核名称" || reviewed.ContentLocale != "zh-CN" || reviewed.TranslationMissing {
		t.Fatalf("reviewed translation selection: %+v, %v", reviewed, err)
	}
}

func testGroupsMembershipsAndSubscriptions(t *testing.T, service *Service, actorA, actorB pgtype.UUID, componentID string) {
	t.Helper()
	ctx := context.Background()
	groups, err := service.ListGroups(ctx, actorA)
	if err != nil || len(groups) != 1 || groups[0].GroupType != "root" || groups[0].Name != nil {
		t.Fatalf("root group: %+v, %v", groups, err)
	}
	parentID := groups[0].ID
	var firstID string
	for depth := 1; depth <= maxGroupDepth; depth++ {
		group, err := service.CreateGroup(ctx, actorA, CreateGroupInput{
			ParentGroupID: &parentID, Name: "Level " + string(rune('0'+depth)), ContentLocale: "en-US", SortOrder: int32(depth),
		})
		if err != nil {
			t.Fatalf("create group depth %d: %v", depth, err)
		}
		if depth == 1 {
			firstID = group.ID
		}
		parentID = group.ID
	}
	if _, err := service.CreateGroup(ctx, actorA, CreateGroupInput{
		ParentGroupID: &parentID, Name: "Too deep", ContentLocale: "en-US",
	}); errorCode(err) != "component_repo.group_depth_exceeded" {
		t.Fatalf("depth error code = %q, error = %v", errorCode(err), err)
	}
	if _, err := service.MoveGroup(ctx, actorA, firstID, MoveGroupInput{ParentGroupID: parentID}); errorCode(err) != "component_repo.group_cycle" {
		t.Fatalf("cycle error code = %q, error = %v", errorCode(err), err)
	}
	otherRoot, err := service.ListGroups(ctx, actorB)
	if err != nil {
		t.Fatalf("actor B root: %v", err)
	}
	if _, err := service.MoveGroup(ctx, actorB, firstID, MoveGroupInput{ParentGroupID: otherRoot[0].ID}); errorCode(err) != "component_repo.group_not_found" {
		t.Fatalf("cross-user group move code = %q", errorCode(err))
	}

	rootID := groups[0].ID
	concurrent := make(chan error, 2)
	var wait sync.WaitGroup
	for i := 0; i < 2; i++ {
		wait.Add(1)
		go func() {
			defer wait.Done()
			_, err := service.CreateGroup(ctx, actorA, CreateGroupInput{
				ParentGroupID: &rootID, Name: "Same Name", ContentLocale: "en-US",
			})
			concurrent <- err
		}()
	}
	wait.Wait()
	close(concurrent)
	successes, conflicts := 0, 0
	for err := range concurrent {
		if err == nil {
			successes++
		} else if errorCode(err) == "component_repo.group_name_duplicate" {
			conflicts++
		}
	}
	if successes != 1 || conflicts != 1 {
		t.Fatalf("concurrent sibling uniqueness successes/conflicts = %d/%d", successes, conflicts)
	}

	if err := service.AddGroupMember(ctx, actorA, firstID, componentID); err != nil {
		t.Fatalf("add group member: %v", err)
	}
	members, err := service.ListGroupMembers(ctx, actorA, firstID, "zh-CN", PageRequest{})
	if err != nil || len(members.Items) != 1 || members.Items[0].ID != componentID {
		t.Fatalf("group members: %+v, %v", members, err)
	}
	if _, err := service.Subscribe(ctx, actorA, componentID); errorCode(err) != "component_repo.subscription_own_component_forbidden" {
		t.Fatalf("own subscription code = %q", errorCode(err))
	}
	subscription, err := service.Subscribe(ctx, actorB, componentID)
	if err != nil || subscription.ComponentID != componentID {
		t.Fatalf("subscribe to active component: %+v, %v", subscription, err)
	}
	if err := service.Unsubscribe(ctx, actorB, componentID); err != nil {
		t.Fatalf("unsubscribe: %v", err)
	}
}

func testStablePagination(t *testing.T, service *Service, actor pgtype.UUID) {
	t.Helper()
	ctx := context.Background()
	for _, name := range []string{"Page A", "Page B", "Page C"} {
		if _, err := service.CreateComponent(ctx, actor, CreateComponentInput{Name: name, ContentLocale: "en-US"}); err != nil {
			t.Fatalf("create pagination fixture: %v", err)
		}
	}
	first, err := service.ListComponents(ctx, actor, ComponentListRequest{PageRequest: PageRequest{Page: 1, PageSize: 2}, Locale: "en-US"})
	if err != nil {
		t.Fatalf("list first page: %v", err)
	}
	second, err := service.ListComponents(ctx, actor, ComponentListRequest{PageRequest: PageRequest{Page: 2, PageSize: 2}, Locale: "en-US"})
	if err != nil {
		t.Fatalf("list second page: %v", err)
	}
	if len(first.Items) != 2 || len(second.Items) != 2 || first.Items[0].ID == second.Items[0].ID || first.Items[1].ID == second.Items[0].ID {
		t.Fatalf("unstable pagination: first=%+v second=%+v", first.Items, second.Items)
	}
}

func seedVersionDependencies(t *testing.T, pool *pgxpool.Pool, actor pgtype.UUID) {
	t.Helper()
	ctx := context.Background()
	_, err := pool.Exec(ctx, `
		INSERT INTO component_repo.artifacts
			(id, owner_id, artifact_type, source_kind, original_filename, storage_provider,
			 storage_bucket, storage_key, sha256, file_size, mime_type, uploaded_by)
		VALUES
			('20000000-0000-0000-0000-000000000010', $1, 'ldraw', 'source', 'fixture.ldr',
			 'test', 'test', 'g3/fixture.ldr', repeat('0', 64), 1, 'text/plain', $1)`, actor)
	if err != nil {
		t.Fatalf("seed source artifact: %v", err)
	}
	_, err = pool.Exec(ctx, `
		INSERT INTO component_repo.imports
			(id, owner_id, source_artifact_id, locale, timezone, created_by)
		VALUES
			('20000000-0000-0000-0000-000000000011', $1,
			 '20000000-0000-0000-0000-000000000010', 'zh-CN', 'Asia/Shanghai', $1)`, actor)
	if err != nil {
		t.Fatalf("seed import: %v", err)
	}
	_, err = pool.Exec(ctx, `
		INSERT INTO component_repo.scene_snapshots
			(id, import_id, schema_version, parser_version, document, bom, parse_issues)
		VALUES
			('20000000-0000-0000-0000-000000000012',
			 '20000000-0000-0000-0000-000000000011', '1', 'g3-fixture', '{}', '[]', '[]')`)
	if err != nil {
		t.Fatalf("seed version dependencies: %v", err)
	}
}

func resetComponentRepo(t *testing.T, pool *pgxpool.Pool) {
	t.Helper()
	_, err := pool.Exec(context.Background(), `
		TRUNCATE component_repo.components, component_repo.artifacts,
		         component_repo.upload_sessions, component_repo.imports,
		         component_repo.part_library_versions, component_repo.component_groups,
		         component_repo.tasks, component_repo.outbox_events
		RESTART IDENTITY CASCADE`)
	if err != nil {
		t.Fatalf("reset component_repo fixtures: %v", err)
	}
}

func mustUUID(t *testing.T, value string) pgtype.UUID {
	t.Helper()
	id, err := uuidutil.Parse(value)
	if err != nil {
		t.Fatalf("parse fixture UUID: %v", err)
	}
	return id
}

func errorCode(err error) string {
	var publicError *apierror.Error
	if errors.As(err, &publicError) {
		return publicError.Code
	}
	return ""
}
