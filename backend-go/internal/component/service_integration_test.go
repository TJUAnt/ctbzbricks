//go:build integration

package component

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"strings"
	"sync"
	"testing"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/componentactivity"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/componentwatch"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/observability"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/scene"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
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

	metrics := observability.NewRegistry()
	service := NewService(pool).WithMetrics(metrics)
	actorA := mustUUID(t, "20000000-0000-0000-0000-000000000001")
	actorB := mustUUID(t, "20000000-0000-0000-0000-000000000002")

	created, err := service.CreateComponent(ctx, actorA, CreateComponentInput{
		Name: "  用户组件  ", Description: pointer(" 保留原文 "), Tags: []string{"标签"}, ContentLocale: "zh",
	})
	if err != nil {
		t.Fatalf("create component: %v", err)
	}
	if created.Name != "  用户组件  " || created.Description == nil || *created.Description != " 保留原文 " || created.ContentLocale != "zh-CN" || created.OwnerID == nil || *created.OwnerID != uuidutil.String(actorA) || !created.OwnedByActor {
		t.Fatalf("unexpected created component: %+v", created)
	}
	if _, err := service.GetComponent(ctx, actorB, created.ID, "en-US"); errorCode(err) != "component_repo.component_not_found" {
		t.Fatalf("cross-user draft read code = %q, error = %v", errorCode(err), err)
	}
	newName := "越权修改"
	if _, err := service.UpdateComponent(ctx, actorB, created.ID, UpdateComponentInput{Name: &newName}); errorCode(err) != "component_repo.component_not_found" {
		t.Fatalf("cross-user update code = %q, error = %v", errorCode(err), err)
	}
	emptyList, err := service.ListComponents(ctx, actorA, ComponentListRequest{PageRequest: PageRequest{Page: 1, PageSize: 10}, Locale: "zh-CN"})
	if err != nil || len(emptyList.Items) != 0 {
		t.Fatalf("component without versions must be hidden from list: %+v, %v", emptyList, err)
	}

	seedVersionDependencies(t, pool, actorA, actorB, created.ID)
	_, err = service.CreateVersion(ctx, actorA, created.ID, CreateVersionInput{
		ComponentCandidateID: "20000000-0000-0000-0000-000000000023",
		Version:              "forbidden",
		Revision:             1,
	})
	if errorCode(err) != "component_repo.version_source_not_found_failed" {
		t.Fatalf("foreign candidate code = %q, error = %v", errorCode(err), err)
	}
	_, err = service.CreateVersion(ctx, actorA, created.ID, CreateVersionInput{
		ComponentCandidateID: "20000000-0000-0000-0000-000000000033",
		Version:              "unverified",
		Revision:             1,
	})
	if errorCode(err) != "component_repo.version_source_not_found_failed" {
		t.Fatalf("unverified candidate code = %q, error = %v", errorCode(err), err)
	}
	version, err := service.CreateVersion(ctx, actorA, created.ID, CreateVersionInput{
		ComponentCandidateID: "20000000-0000-0000-0000-000000000013",
		Version:              "1.0.0",
		Revision:             1,
	})
	if err != nil {
		t.Fatalf("create draft version: %v", err)
	}
	if version.ComponentCandidateID == nil || *version.ComponentCandidateID != "20000000-0000-0000-0000-000000000013" ||
		version.SourceArtifactID != "20000000-0000-0000-0000-000000000010" ||
		version.SceneSnapshotID != "20000000-0000-0000-0000-000000000012" ||
		version.ParserVersion != "g3-fixture" || version.InterfaceSignature != strings.Repeat("1", 64) ||
		version.StructureHash != strings.Repeat("2", 64) || version.GeometryHash != strings.Repeat("3", 64) {
		t.Fatalf("version source was not derived from candidate: %+v", version)
	}
	releaseNote := "保留用户原文"
	releaseLocale := "zh"
	updatedVersion, err := service.UpdateVersion(ctx, actorA, version.ID, UpdateVersionInput{
		Version: pointer("1.0.1"), ReleaseNote: OptionalString{Set: true, Value: &releaseNote},
		ReleaseNoteLocale: OptionalString{Set: true, Value: &releaseLocale},
	})
	if err != nil || updatedVersion.Version != "1.0.1" || updatedVersion.ReleaseNote == nil ||
		*updatedVersion.ReleaseNote != releaseNote || updatedVersion.ReleaseNoteLocale == nil || *updatedVersion.ReleaseNoteLocale != "zh-CN" {
		t.Fatalf("update draft version: %+v, %v", updatedVersion, err)
	}
	if _, err := pool.Exec(ctx, `
		UPDATE component_repo.component_versions
		SET preview_bbox_min=ARRAY[0,0,0]::float8[],
		    preview_bbox_max=ARRAY[40,24,20]::float8[],
		    logical_width_stud=2, logical_depth_stud=1,
		    logical_height_plate=3, preview_bounds_complete=true
		WHERE id=$1`, mustUUID(t, version.ID)); err != nil {
		t.Fatalf("seed draft preview bounds: %v", err)
	}
	draftList, err := service.ListComponents(ctx, actorA, ComponentListRequest{PageRequest: PageRequest{Page: 1, PageSize: 10}, Locale: "zh-CN"})
	if err != nil || len(draftList.Items) != 1 || draftList.Items[0].LogicalSize == nil ||
		draftList.Items[0].LogicalSize.WidthStud != 2 || draftList.Items[0].LogicalSize.DepthStud != 1 ||
		draftList.Items[0].LogicalSize.HeightPlate != 3 {
		t.Fatalf("latest draft logical size projection: %+v, %v", draftList, err)
	}
	_, err = pool.Exec(ctx, `
		INSERT INTO component_repo.component_versions
			(id, component_id, component_candidate_id, version_label, source_artifact_id,
			 scene_snapshot_id, parser_version, interface_signature, structure_hash,
			 geometry_hash, created_by)
		VALUES
			('20000000-0000-0000-0000-000000000040', $1,
			 '20000000-0000-0000-0000-000000000013', 'invalid-lineage',
			 '20000000-0000-0000-0000-000000000030',
			 '20000000-0000-0000-0000-000000000012', 'g3-fixture', repeat('1', 64),
			 repeat('2', 64), repeat('3', 64), $2)`, created.ID, actorA)
	if databaseCode(err) != "23514" {
		t.Fatalf("database accepted mismatched version lineage: %v", err)
	}
	if _, err := service.GetVersion(ctx, actorB, version.ID); errorCode(err) != "component_repo.version_not_found" {
		t.Fatalf("cross-user draft version read code = %q", errorCode(err))
	}
	if _, err := service.Star(ctx, actorB, created.ID); errorCode(err) != "component_repo.component_not_found" {
		t.Fatalf("draft-only component star code = %q, error = %v", errorCode(err), err)
	}
	testPublishedEventRollback(t, service.pool, actorA, mustUUID(t, created.ID), mustUUID(t, version.ID))
	type publishResult struct {
		version ComponentVersion
		err     error
	}
	publishResults := make(chan publishResult, 2)
	publishStart := make(chan struct{})
	for range 2 {
		go func() {
			<-publishStart
			published, publishErr := service.PublishVersion(ctx, actorA, version.ID)
			publishResults <- publishResult{version: published, err: publishErr}
		}()
	}
	close(publishStart)
	var published ComponentVersion
	publishSuccesses, publishConflicts := 0, 0
	for range 2 {
		result := <-publishResults
		switch {
		case result.err == nil:
			publishSuccesses++
			published = result.version
		case errorCode(result.err) == "request.conflict":
			publishConflicts++
		default:
			t.Fatalf("concurrent publish error: %v", result.err)
		}
	}
	if publishSuccesses != 1 || publishConflicts != 1 || published.Status != "published" || published.PublishedAt == nil {
		t.Fatalf("concurrent publish results: successes=%d conflicts=%d version=%+v", publishSuccesses, publishConflicts, published)
	}
	if committed, _ := metrics.ComponentDomainEventCounts(); committed != 1 {
		t.Fatalf("committed domain event metric = %d, want 1", committed)
	}
	var projectedSizeA, projectedSizeB, projectedSizeC float64
	if err := pool.QueryRow(ctx, `
		SELECT current_logical_size_a, current_logical_size_b, current_logical_size_c
		FROM component_repo.components WHERE id=$1`, mustUUID(t, created.ID)).Scan(
		&projectedSizeA, &projectedSizeB, &projectedSizeC,
	); err != nil || projectedSizeA != 1 || projectedSizeB != 2 || projectedSizeC != 3 {
		t.Fatalf("published Component normalized size projection = %v/%v/%v, error=%v",
			projectedSizeA, projectedSizeB, projectedSizeC, err)
	}
	var eventType string
	var eventComponentID, eventVersionID, eventActorID pgtype.UUID
	var eventSeq int64
	var eventPayload []byte
	if err := pool.QueryRow(ctx, `
		SELECT event_type, component_id, component_version_id, actor_id, event_seq, payload
		FROM component_repo.component_domain_events
		WHERE component_version_id = $1`, mustUUID(t, version.ID)).Scan(
		&eventType, &eventComponentID, &eventVersionID, &eventActorID, &eventSeq, &eventPayload,
	); err != nil {
		t.Fatalf("read version published event: %v", err)
	}
	if eventType != "component.version.published.v1" || !uuidutil.Equal(eventComponentID, mustUUID(t, created.ID)) ||
		!uuidutil.Equal(eventVersionID, mustUUID(t, version.ID)) || !uuidutil.Equal(eventActorID, actorA) ||
		eventSeq <= 0 || string(eventPayload) != "{}" {
		t.Fatalf("unexpected version published event: type=%q component=%s version=%s actor=%s seq=%d payload=%s",
			eventType, uuidutil.String(eventComponentID), uuidutil.String(eventVersionID), uuidutil.String(eventActorID), eventSeq, eventPayload)
	}
	if _, err := service.PublishVersion(ctx, actorA, version.ID); errorCode(err) != "request.conflict" {
		t.Fatalf("repeated publish code = %q, error = %v", errorCode(err), err)
	}
	if committed, _ := metrics.ComponentDomainEventCounts(); committed != 1 {
		t.Fatalf("repeated publish changed committed metric to %d", committed)
	}
	var eventCount int64
	if err := pool.QueryRow(ctx, `
		SELECT count(*) FROM component_repo.component_domain_events
		WHERE component_version_id = $1`, mustUUID(t, version.ID)).Scan(&eventCount); err != nil || eventCount != 1 {
		t.Fatalf("repeated publish event count = %d, error = %v", eventCount, err)
	}
	visible, err := service.GetComponent(ctx, actorB, created.ID, "en-US")
	if err != nil || visible.Status != "active" || visible.CurrentVersionID == nil || *visible.CurrentVersionID != version.ID || visible.OwnedByActor {
		t.Fatalf("published component visibility: %+v, %v", visible, err)
	}
	if _, err := service.GetVersion(ctx, actorB, version.ID); err != nil {
		t.Fatalf("published version should be visible: %v", err)
	}

	// Diff 的父版本必须来自新 Import 的 base_version_id；即使已发布版本公开，Diff 仍只允许 owner 读取。
	rootDiff, err := service.GetVersionDiff(ctx, actorA, version.ID)
	if err != nil || rootDiff.ComparisonBasis != "empty" || rootDiff.BaseVersionID != nil || rootDiff.Summary.AddedInstances != 1 {
		t.Fatalf("root version diff: %+v, %v", rootDiff, err)
	}
	if _, err := pool.Exec(ctx, `UPDATE component_repo.artifacts SET verification_status='verified', verified_at=now() WHERE id='20000000-0000-0000-0000-000000000030'`); err != nil {
		t.Fatalf("verify head diff artifact: %v", err)
	}
	if _, err := pool.Exec(ctx, `UPDATE component_repo.upload_sessions SET base_version_id=$1 WHERE id='20000000-0000-0000-0000-000000000034'`, mustUUID(t, version.ID)); err != nil {
		t.Fatalf("seed head upload lineage: %v", err)
	}
	if _, err := pool.Exec(ctx, `UPDATE component_repo.imports SET base_version_id=$1 WHERE id='20000000-0000-0000-0000-000000000031'`, mustUUID(t, version.ID)); err != nil {
		t.Fatalf("seed head diff lineage: %v", err)
	}
	headVersion, err := service.CreateVersion(ctx, actorA, created.ID, CreateVersionInput{
		ComponentCandidateID: "20000000-0000-0000-0000-000000000033",
		Version:              "2.0.0",
		Revision:             1,
	})
	if err != nil {
		t.Fatalf("create head diff version: %v", err)
	}
	diff, err := service.GetVersionDiff(ctx, actorA, headVersion.ID)
	if err != nil || diff.BaseVersionID == nil || *diff.BaseVersionID != version.ID || diff.ComparisonBasis != "import_base_version" ||
		diff.Summary.ColorChangedInstances != 1 || diff.Summary.AddedInstances != 1 || diff.Summary.BeforeInstances != 1 || diff.Summary.AfterInstances != 2 {
		t.Fatalf("lineage version diff: %+v, %v", diff, err)
	}
	if _, err := service.GetVersionDiff(ctx, actorB, headVersion.ID); errorCode(err) != "component_repo.version_not_found" {
		t.Fatalf("cross-user version diff code = %q, error = %v", errorCode(err), err)
	}

	testOfficialTranslationSelection(t, service, pool, actorA)
	testGroupsMembershipsAndStars(t, service, actorA, actorB, created.ID, headVersion.ID)
	testStablePagination(t, service, actorA)

	// Component DELETE 是软删除生命周期终点：Star 直接移除，active Watch 使用一个共同边界关闭并保留历史。
	actorC := mustUUID(t, "20000000-0000-0000-0000-000000000003")
	watchService := componentwatch.NewService(pool)
	for _, watcher := range []pgtype.UUID{actorB, actorC} {
		if _, err := service.Star(ctx, watcher, created.ID); err != nil {
			t.Fatalf("seed lifecycle Star for %s: %v", uuidutil.String(watcher), err)
		}
		if _, err := watchService.Watch(ctx, watcher, created.ID, componentwatch.ReleasesOnlyLevel); err != nil {
			t.Fatalf("seed lifecycle Watch for %s: %v", uuidutil.String(watcher), err)
		}
	}

	if err := service.DeleteComponent(ctx, actorA, created.ID); err != nil {
		t.Fatalf("owner should be able to delete published component: %v", err)
	}
	// 关系物理清理由同事务创建的持久任务完成；在 Worker 执行前，两个列表已因 Component 不可见而移除条目。
	pendingStars, err := service.ListStars(ctx, actorB, StarListRequest{
		PageRequest: PageRequest{Page: 1, PageSize: 10}, Locale: "en-US",
	})
	if err != nil || len(pendingStars.Items) != 0 {
		t.Fatalf("deleted Component remained visible while cleanup pending: %+v, %v", pendingStars, err)
	}
	pendingWatches, err := watchService.List(ctx, actorC, componentwatch.ListRequest{Locale: "en-US", Limit: 20})
	if err != nil || len(pendingWatches.Items) != 0 {
		t.Fatalf("deleted Component remained in Watch list while cleanup pending: %+v, %v", pendingWatches, err)
	}
	var cleanupTaskID pgtype.UUID
	var cleanupPayload []byte
	if err := pool.QueryRow(ctx, `
		SELECT id, payload
		FROM component_repo.tasks
		WHERE task_type=$1 AND owner_id=$2`, task.RelationshipCleanupType, actorA).Scan(
		&cleanupTaskID, &cleanupPayload,
	); err != nil {
		t.Fatalf("read relationship cleanup task: %v", err)
	}
	cleanupResult, err := NewRelationshipCleanupTaskHandler(pool).Handle(ctx, task.ClaimedTask{
		ID: cleanupTaskID, OwnerID: actorA, TaskType: task.RelationshipCleanupType, Payload: cleanupPayload,
	})
	if err != nil || len(cleanupResult.Payload) == 0 {
		t.Fatalf("run relationship cleanup task: result=%s error=%v", cleanupResult.Payload, err)
	}
	// Worker lease 超时后可能重放同一任务；第二次执行必须是成功的空操作，且不能改写 Watch 历史边界。
	repeatedCleanup, err := NewRelationshipCleanupTaskHandler(pool).Handle(ctx, task.ClaimedTask{
		ID: cleanupTaskID, OwnerID: actorA, TaskType: task.RelationshipCleanupType, Payload: cleanupPayload,
	})
	if err != nil || string(repeatedCleanup.Payload) != `{"closedWatches":0,"componentId":"`+created.ID+`","deletedStars":0}` {
		t.Fatalf("repeat relationship cleanup task: result=%s error=%v", repeatedCleanup.Payload, err)
	}
	var remainingStars, activeWatches, lifecycleClosed, lifecycleBoundaries int64
	var lifecycleStart, lifecycleEnd int64
	if err := pool.QueryRow(ctx, `
		SELECT
			(SELECT count(*) FROM component_repo.component_stars star WHERE star.component_id=$1),
			count(*) FILTER (WHERE watch.ended_seq IS NULL),
			count(*) FILTER (WHERE watch.ended_reason='component_deleted'),
			count(DISTINCT watch.ended_seq) FILTER (WHERE watch.ended_reason='component_deleted'),
			max(watch.started_seq) FILTER (WHERE watch.ended_reason='component_deleted'),
			min(watch.ended_seq) FILTER (WHERE watch.ended_reason='component_deleted')
		FROM component_repo.component_watch_periods watch
		WHERE watch.component_id=$1`, mustUUID(t, created.ID)).Scan(
		&remainingStars, &activeWatches, &lifecycleClosed, &lifecycleBoundaries, &lifecycleStart, &lifecycleEnd,
	); err != nil {
		t.Fatalf("read deleted Component relationships: %v", err)
	}
	if remainingStars != 0 || activeWatches != 0 || lifecycleClosed != 2 || lifecycleBoundaries != 1 || lifecycleEnd <= lifecycleStart {
		t.Fatalf("deleted Component relationship cleanup: stars=%d active=%d closed=%d boundaries=%d start=%d end=%d",
			remainingStars, activeWatches, lifecycleClosed, lifecycleBoundaries, lifecycleStart, lifecycleEnd)
	}
	deletedStars, err := service.ListStars(ctx, actorB, StarListRequest{
		PageRequest: PageRequest{Page: 1, PageSize: 10}, Locale: "en-US",
	})
	if err != nil || deletedStars.RelationshipTotal != 0 || len(deletedStars.Items) != 0 {
		t.Fatalf("deleted Component remained in Star list: %+v, %v", deletedStars, err)
	}
	deletedWatches, err := watchService.List(ctx, actorC, componentwatch.ListRequest{Locale: "en-US", Limit: 20})
	if err != nil || len(deletedWatches.Items) != 0 {
		t.Fatalf("deleted Component remained in Watch list: %+v, %v", deletedWatches, err)
	}
	if _, err := service.GetComponent(ctx, actorA, created.ID, "zh-CN"); errorCode(err) != "component_repo.component_not_found" {
		t.Fatalf("deleted component owner read code = %q, error = %v", errorCode(err), err)
	}
	if _, err := service.GetComponent(ctx, actorB, created.ID, "en-US"); errorCode(err) != "component_repo.component_not_found" {
		t.Fatalf("deleted component public read code = %q, error = %v", errorCode(err), err)
	}
	if _, err := service.Star(ctx, actorB, created.ID); errorCode(err) != "component_repo.component_not_found" {
		t.Fatalf("deleted component star code = %q, error = %v", errorCode(err), err)
	}
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

func testGroupsMembershipsAndStars(t *testing.T, service *Service, actorA, actorB pgtype.UUID, componentID, publishVersionID string) {
	t.Helper()
	ctx := context.Background()
	groups, err := service.ListGroups(ctx, actorA)
	if err != nil || len(groups) != 0 {
		t.Fatalf("initial group list must be read-only and empty: %+v, %v", groups, err)
	}
	if err := service.BootstrapGroups(ctx, actorA); err != nil {
		t.Fatalf("bootstrap root group: %v", err)
	}
	groups, err = service.ListGroups(ctx, actorA)
	if err != nil || len(groups) != 1 || groups[0].GroupType != "root" || groups[0].DirectComponentCount < 1 {
		t.Fatalf("explicitly bootstrapped root: %+v, %v", groups, err)
	}
	first, err := service.CreateGroup(ctx, actorA, CreateGroupInput{
		Name: "Level 1", ContentLocale: "en-US", SortOrder: 1,
	})
	if err != nil {
		t.Fatalf("create first group: %v", err)
	}
	groups, err = service.ListGroups(ctx, actorA)
	if err != nil || len(groups) != 2 || groups[0].GroupType != "root" || groups[0].Name != nil {
		t.Fatalf("root group after mutation: %+v, %v", groups, err)
	}
	rootID := groups[0].ID
	parentID := first.ID
	firstID := first.ID
	for depth := 2; depth <= maxGroupDepth; depth++ {
		group, err := service.CreateGroup(ctx, actorA, CreateGroupInput{
			ParentGroupID: &parentID, Name: "Level " + string(rune('0'+depth)), ContentLocale: "en-US", SortOrder: int32(depth),
		})
		if err != nil {
			t.Fatalf("create group depth %d: %v", depth, err)
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
	if _, err := service.CreateGroup(ctx, actorB, CreateGroupInput{
		Name: "Other user group", ContentLocale: "en-US",
	}); err != nil {
		t.Fatalf("create actor B group: %v", err)
	}
	otherGroups, err := service.ListGroups(ctx, actorB)
	if err != nil || len(otherGroups) < 1 {
		t.Fatalf("actor B groups: %+v, %v", otherGroups, err)
	}
	if _, err := service.MoveGroup(ctx, actorB, firstID, MoveGroupInput{ParentGroupID: otherGroups[0].ID}); errorCode(err) != "component_repo.group_not_found" {
		t.Fatalf("cross-user group move code = %q", errorCode(err))
	}

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
	groupIDs, err := service.ListComponentGroupIDs(ctx, actorA, componentID)
	if err != nil || len(groupIDs) != 1 || groupIDs[0] != firstID {
		t.Fatalf("component group ids: %+v, %v", groupIDs, err)
	}
	search, err := service.SearchGroupComponents(ctx, actorA, firstID, ComponentGroupSearchRequest{
		PageRequest: PageRequest{Page: 1, PageSize: 10}, Locale: "zh-CN", Queries: []string{"用户"}, Statuses: []string{"active"},
	})
	if err != nil || search.Total != 1 || len(search.Items) != 1 || search.Items[0].ID != componentID || search.StatusCounts["active"] != 1 {
		t.Fatalf("group component search: %+v, %v", search, err)
	}
	for _, sizeQuery := range []string{"1x2x3", "1x2", "1x3", "2x3"} {
		sizeSearch, err := service.SearchGroupComponents(ctx, actorA, firstID, ComponentGroupSearchRequest{
			PageRequest: PageRequest{Page: 1, PageSize: 10}, Locale: "zh-CN", Queries: []string{sizeQuery}, Statuses: []string{"active"},
		})
		if err != nil || sizeSearch.Total != 1 || len(sizeSearch.Items) != 1 || sizeSearch.Items[0].ID != componentID || sizeSearch.StatusCounts["active"] != 1 {
			t.Fatalf("size search %q: %+v, %v", sizeQuery, sizeSearch, err)
		}
	}
	// 开区间必须排除恰好相差 1 的边界：组件最小维度为 1，查询 0 的上边界也是 1。
	boundarySearch, err := service.SearchGroupComponents(ctx, actorA, firstID, ComponentGroupSearchRequest{
		PageRequest: PageRequest{Page: 1, PageSize: 10}, Locale: "zh-CN", Queries: []string{"0x2x3"}, Statuses: []string{"active"},
	})
	if err != nil || boundarySearch.Total != 0 || len(boundarySearch.Items) != 0 || boundarySearch.StatusCounts["active"] != 0 {
		t.Fatalf("open interval boundary search: %+v, %v", boundarySearch, err)
	}
	compoundSearch, err := service.SearchGroupComponents(ctx, actorA, firstID, ComponentGroupSearchRequest{
		PageRequest: PageRequest{Page: 1, PageSize: 10}, Locale: "zh-CN",
		Queries: []string{"用户", "1x3", "2x3"}, Statuses: []string{"active"},
	})
	if err != nil || compoundSearch.Total != 1 || len(compoundSearch.Items) != 1 || compoundSearch.Items[0].ID != componentID {
		t.Fatalf("compound text and size search: %+v, %v", compoundSearch, err)
	}
	compoundMiss, err := service.SearchGroupComponents(ctx, actorA, firstID, ComponentGroupSearchRequest{
		PageRequest: PageRequest{Page: 1, PageSize: 10}, Locale: "zh-CN",
		Queries: []string{"用户", "0x2x3"}, Statuses: []string{"active"},
	})
	if err != nil || compoundMiss.Total != 0 || len(compoundMiss.Items) != 0 {
		t.Fatalf("compound search must require every condition: %+v, %v", compoundMiss, err)
	}
	members, err := service.ListGroupMembers(ctx, actorA, firstID, "zh-CN", PageRequest{})
	if err != nil || len(members.Items) != 1 || members.Items[0].ID != componentID {
		t.Fatalf("group members: %+v, %v", members, err)
	}
	if _, err := service.Star(ctx, actorA, componentID); errorCode(err) != "component_repo.star_own_component_forbidden" {
		t.Fatalf("own star code = %q", errorCode(err))
	}
	starResults := make(chan Star, 2)
	starErrors := make(chan error, 2)
	var starWait sync.WaitGroup
	for i := 0; i < 2; i++ {
		starWait.Add(1)
		go func() {
			defer starWait.Done()
			star, err := service.Star(ctx, actorB, componentID)
			starResults <- star
			starErrors <- err
		}()
	}
	starWait.Wait()
	close(starResults)
	close(starErrors)
	starsCreated := make([]Star, 0, 2)
	for star := range starResults {
		starsCreated = append(starsCreated, star)
	}
	for err := range starErrors {
		if err != nil {
			t.Fatalf("concurrent star active component: %v", err)
		}
	}
	if len(starsCreated) != 2 || starsCreated[0].ComponentID != componentID || starsCreated[0].StarredAt.IsZero() ||
		!starsCreated[0].StarredAt.Equal(starsCreated[1].StarredAt) {
		t.Fatalf("concurrent star must converge on one timestamp: %+v", starsCreated)
	}
	star := starsCreated[0]
	repeatedStar, err := service.Star(ctx, actorB, componentID)
	if err != nil || !repeatedStar.StarredAt.Equal(star.StarredAt) {
		t.Fatalf("repeated star must preserve original timestamp: %+v, %v", repeatedStar, err)
	}
	starredComponent, err := service.GetComponent(ctx, actorB, componentID, "en-US")
	if err != nil || !starredComponent.StarredByActor || starredComponent.StarCount != 1 {
		t.Fatalf("starred component projection: %+v, %v", starredComponent, err)
	}
	watchMetrics := observability.NewRegistry()
	watchService := componentwatch.NewService(service.pool).WithMetrics(watchMetrics)
	testComponentActivityLockProtocol(t, service.pool, mustUUID(t, componentID))
	if _, err := watchService.Watch(ctx, actorA, componentID, componentwatch.ReleasesOnlyLevel); errorCode(err) != "component_repo.watch_own_component_forbidden" {
		t.Fatalf("own watch code = %q, error = %v", errorCode(err), err)
	}
	watch, err := watchService.Watch(ctx, actorB, componentID, componentwatch.ReleasesOnlyLevel)
	if err != nil || !watch.Watching || watch.WatchedAt.IsZero() {
		t.Fatalf("watch active component: %+v, %v", watch, err)
	}
	repeatedWatch, err := watchService.Watch(ctx, actorB, componentID, componentwatch.ReleasesOnlyLevel)
	if err != nil || !repeatedWatch.WatchedAt.Equal(watch.WatchedAt) {
		t.Fatalf("repeated watch must preserve original timestamp: %+v, %v", repeatedWatch, err)
	}
	var firstPeriodID, firstStartedSeq int64
	if err := service.pool.QueryRow(ctx, `
		SELECT id, started_seq
		FROM component_repo.component_watch_periods
		WHERE actor_id=$1 AND component_id=$2 AND ended_seq IS NULL`, actorB, mustUUID(t, componentID)).Scan(
		&firstPeriodID, &firstStartedSeq,
	); err != nil {
		t.Fatalf("read first active watch period: %v", err)
	}
	if _, err := watchService.Watch(ctx, actorB, componentID, "all_public_activity"); errorCode(err) != "component_repo.watch_level_unsupported" {
		t.Fatalf("unsupported watch level code = %q, error = %v", errorCode(err), err)
	}
	// 保持本用例后续 Star 尺寸筛选的既有 current-version fixture，只改变发布边界本身。
	if _, err := service.pool.Exec(ctx, `
		UPDATE component_repo.component_versions
		SET preview_bbox_min=ARRAY[0,0,0]::float8[], preview_bbox_max=ARRAY[40,24,20]::float8[],
		    logical_width_stud=2, logical_depth_stud=1, logical_height_plate=3,
		    preview_bounds_complete=true
		WHERE id=$1`, mustUUID(t, publishVersionID)); err != nil {
		t.Fatalf("seed watched publish logical size: %v", err)
	}
	if published, err := service.PublishVersion(ctx, actorA, publishVersionID); err != nil || published.Status != "published" {
		t.Fatalf("publish watched Component version: %+v, %v", published, err)
	}
	var watchedEventSeq int64
	if err := service.pool.QueryRow(ctx, `
		SELECT event_seq
		FROM component_repo.component_domain_events
		WHERE component_version_id=$1`, mustUUID(t, publishVersionID)).Scan(&watchedEventSeq); err != nil || watchedEventSeq <= firstStartedSeq {
		t.Fatalf("watched publish boundary: watchStart=%d event=%d error=%v", firstStartedSeq, watchedEventSeq, err)
	}
	if committed, _ := service.metrics.ComponentDomainEventCounts(); committed != 2 {
		t.Fatalf("watched publish committed metric = %d, want 2", committed)
	}
	watchedComponent, err := service.GetComponent(ctx, actorB, componentID, "en-US")
	if err != nil || watchedComponent.Watch == nil || !watchedComponent.Watch.Watching ||
		watchedComponent.Watch.Level == nil || *watchedComponent.Watch.Level != componentwatch.ReleasesOnlyLevel {
		t.Fatalf("component watch projection: %+v, %v", watchedComponent.Watch, err)
	}
	watches, err := watchService.List(ctx, actorB, componentwatch.ListRequest{Locale: "en-US", Limit: 20})
	if err != nil || len(watches.Items) != 1 || watches.Items[0].ComponentID != componentID || watches.NextCursor != nil {
		t.Fatalf("watch list: %+v, %v", watches, err)
	}
	if err := watchService.Unwatch(ctx, actorB, componentID); err != nil {
		t.Fatalf("unwatch: %v", err)
	}
	var firstEndedSeq int64
	var firstUnwatchedAt pgtype.Timestamptz
	var firstEndedReason string
	if err := service.pool.QueryRow(ctx, `
		SELECT ended_seq, unwatched_at, ended_reason
		FROM component_repo.component_watch_periods
		WHERE id=$1`, firstPeriodID).Scan(&firstEndedSeq, &firstUnwatchedAt, &firstEndedReason); err != nil {
		t.Fatalf("read closed watch period: %v", err)
	}
	if firstEndedSeq <= watchedEventSeq || !firstUnwatchedAt.Valid || firstEndedReason != "user_unwatched" {
		t.Fatalf("invalid closed watch period: start=%d event=%d end=%d unwatched=%+v reason=%q",
			firstStartedSeq, watchedEventSeq, firstEndedSeq, firstUnwatchedAt, firstEndedReason)
	}
	if err := watchService.Unwatch(ctx, actorB, componentID); err != nil {
		t.Fatalf("idempotent unwatch: %v", err)
	}
	var repeatedEndedSeq int64
	var repeatedUnwatchedAt pgtype.Timestamptz
	if err := service.pool.QueryRow(ctx, `
		SELECT ended_seq, unwatched_at
		FROM component_repo.component_watch_periods
		WHERE id=$1`, firstPeriodID).Scan(&repeatedEndedSeq, &repeatedUnwatchedAt); err != nil ||
		repeatedEndedSeq != firstEndedSeq || !repeatedUnwatchedAt.Time.Equal(firstUnwatchedAt.Time) {
		t.Fatalf("repeated unwatch changed closed period: end=%d at=%+v error=%v", repeatedEndedSeq, repeatedUnwatchedAt, err)
	}
	unwatchedComponent, err := service.GetComponent(ctx, actorB, componentID, "en-US")
	if err != nil || unwatchedComponent.Watch == nil || unwatchedComponent.Watch.Watching ||
		unwatchedComponent.Watch.Level != nil || unwatchedComponent.Watch.WatchedAt != nil {
		t.Fatalf("unwatched component projection: %+v, %v", unwatchedComponent.Watch, err)
	}
	emptyWatches, err := watchService.List(ctx, actorB, componentwatch.ListRequest{Locale: "en-US", Limit: 20})
	if err != nil || len(emptyWatches.Items) != 0 {
		t.Fatalf("unwatched list: %+v, %v", emptyWatches, err)
	}
	// 两个并发 Rewatch 必须共同创建并返回一个新 active period，不能覆盖旧周期或追加两个 active 行。
	rewatchResults := make(chan componentwatch.Watch, 2)
	rewatchErrors := make(chan error, 2)
	var rewatchWait sync.WaitGroup
	for range 2 {
		rewatchWait.Add(1)
		go func() {
			defer rewatchWait.Done()
			result, watchErr := watchService.Watch(ctx, actorB, componentID, componentwatch.ReleasesOnlyLevel)
			rewatchResults <- result
			rewatchErrors <- watchErr
		}()
	}
	rewatchWait.Wait()
	close(rewatchResults)
	close(rewatchErrors)
	for watchErr := range rewatchErrors {
		if watchErr != nil {
			t.Fatalf("concurrent rewatch inactive relation: %v", watchErr)
		}
	}
	var rewatchTimestamp pgtype.Timestamptz
	for result := range rewatchResults {
		if !result.Watching || result.WatchedAt.IsZero() {
			t.Fatalf("invalid concurrent rewatch result: %+v", result)
		}
		if rewatchTimestamp.Valid && !rewatchTimestamp.Time.Equal(result.WatchedAt) {
			t.Fatalf("concurrent rewatch returned different periods: %s != %s", rewatchTimestamp.Time, result.WatchedAt)
		}
		rewatchTimestamp = pgtype.Timestamptz{Time: result.WatchedAt, Valid: true}
	}
	var periodCount, activePeriodCount int
	var secondStartedSeq int64
	if err := service.pool.QueryRow(ctx, `
		SELECT count(*)::int,
		       count(*) FILTER (WHERE ended_seq IS NULL)::int,
		       max(started_seq) FILTER (WHERE ended_seq IS NULL)
		FROM component_repo.component_watch_periods
		WHERE actor_id=$1 AND component_id=$2`, actorB, mustUUID(t, componentID)).Scan(
		&periodCount, &activePeriodCount, &secondStartedSeq,
	); err != nil || periodCount != 2 || activePeriodCount != 1 || secondStartedSeq <= firstEndedSeq {
		t.Fatalf("rewatch periods: total=%d active=%d secondStart=%d firstEnd=%d error=%v",
			periodCount, activePeriodCount, secondStartedSeq, firstEndedSeq, err)
	}
	watchSucceeded, watchFailed, unwatchSucceeded, unwatchFailed := watchMetrics.ComponentWatchMutationCounts()
	if watchSucceeded != 4 || watchFailed != 2 || unwatchSucceeded != 2 || unwatchFailed != 0 {
		t.Fatalf("watch mutation metrics = %d %d %d %d", watchSucceeded, watchFailed, unwatchSucceeded, unwatchFailed)
	}
	testWatchKeysetPagination(t, service, actorA, actorB)
	stars, err := service.ListStars(ctx, actorB, StarListRequest{
		PageRequest: PageRequest{Page: 1, PageSize: 10}, Locale: "en-US",
	})
	if err != nil || stars.Total != 1 || stars.RelationshipTotal != 1 || len(stars.Items) != 1 || stars.Items[0].ID != componentID || stars.Items[0].StarredAt.IsZero() {
		t.Fatalf("star list: %+v, %v", stars, err)
	}
	sizeStars, err := service.ListStars(ctx, actorB, StarListRequest{
		PageRequest: PageRequest{Page: 1, PageSize: 10}, Locale: "en-US", Query: "1x2x3", Sort: "starred_at_desc",
	})
	if err != nil || sizeStars.Total != 1 || len(sizeStars.Items) != 1 || sizeStars.Items[0].ID != componentID {
		t.Fatalf("star logical size filter: %+v, %v", sizeStars, err)
	}
	if _, err := service.ListStars(ctx, actorB, StarListRequest{Sort: "name_asc"}); errorCode(err) != "request.validation_failed" {
		t.Fatalf("invalid star sort code = %q, error = %v", errorCode(err), err)
	}
	if err := service.BootstrapGroups(ctx, actorB); err != nil {
		t.Fatalf("bootstrap actor B root group: %v", err)
	}
	actorBGroups, err := service.ListGroups(ctx, actorB)
	if err != nil || len(actorBGroups) == 0 {
		t.Fatalf("actor B groups after star: %+v, %v", actorBGroups, err)
	}
	actorBRoot, err := service.SearchGroupComponents(ctx, actorB, actorBGroups[0].ID, ComponentGroupSearchRequest{
		PageRequest: PageRequest{Page: 1, PageSize: 10}, Locale: "en-US", Statuses: []string{"active"},
	})
	if err != nil || actorBRoot.Total != 0 || len(actorBRoot.Items) != 0 {
		t.Fatalf("starred component must not enter owned-only root: %+v, %v", actorBRoot, err)
	}
	actorBGroup, err := service.CreateGroup(ctx, actorB, CreateGroupInput{
		ParentGroupID: &actorBGroups[0].ID, Name: "Saved", ContentLocale: "en-US",
	})
	if err != nil {
		t.Fatalf("create actor B custom group: %v", err)
	}
	if err := service.AddGroupMember(ctx, actorB, actorBGroup.ID, componentID); err != nil {
		t.Fatalf("add starred component to custom group: %v", err)
	}
	if err := service.Unstar(ctx, actorB, componentID); err != nil {
		t.Fatalf("unstar: %v", err)
	}
	if err := service.Unstar(ctx, actorB, componentID); err != nil {
		t.Fatalf("idempotent unstar: %v", err)
	}
	unstarredComponent, err := service.GetComponent(ctx, actorB, componentID, "en-US")
	if err != nil || unstarredComponent.StarredByActor || unstarredComponent.StarCount != 0 {
		t.Fatalf("unstarred component projection: %+v, %v", unstarredComponent, err)
	}
	actorBCustom, err := service.SearchGroupComponents(ctx, actorB, actorBGroup.ID, ComponentGroupSearchRequest{
		PageRequest: PageRequest{Page: 1, PageSize: 10}, Locale: "en-US", Statuses: []string{"active"},
	})
	if err != nil || actorBCustom.Total != 1 || len(actorBCustom.Items) != 1 || actorBCustom.Items[0].ID != componentID {
		t.Fatalf("unstar must preserve custom group membership: %+v, %v", actorBCustom, err)
	}
	actorBRoot, err = service.SearchGroupComponents(ctx, actorB, actorBGroups[0].ID, ComponentGroupSearchRequest{
		PageRequest: PageRequest{Page: 1, PageSize: 10}, Locale: "en-US", Statuses: []string{"active"},
	})
	if err != nil || actorBRoot.Total != 0 || len(actorBRoot.Items) != 0 {
		t.Fatalf("unstarred component removed from personal root: %+v, %v", actorBRoot, err)
	}
}

func testComponentActivityLockProtocol(t *testing.T, pool *pgxpool.Pool, componentID pgtype.UUID) {
	t.Helper()
	ctx := context.Background()
	sharedTx, err := pool.Begin(ctx)
	if err != nil {
		t.Fatalf("begin shared activity lock transaction: %v", err)
	}
	defer sharedTx.Rollback(ctx)
	lockKey := componentactivity.LockKey(componentID)
	if err := db.New(sharedTx).AcquireSharedComponentActivityLock(ctx, lockKey); err != nil {
		t.Fatalf("acquire shared Component activity lock: %v", err)
	}
	exclusiveTx, err := pool.Begin(ctx)
	if err != nil {
		t.Fatalf("begin exclusive activity lock transaction: %v", err)
	}
	defer exclusiveTx.Rollback(ctx)
	var acquired bool
	if err := exclusiveTx.QueryRow(ctx, `SELECT pg_try_advisory_xact_lock($1)`, lockKey).Scan(&acquired); err != nil {
		t.Fatalf("try exclusive Component activity lock: %v", err)
	}
	if acquired {
		t.Fatal("exclusive Publish boundary bypassed active shared Watch lock")
	}
	if err := sharedTx.Rollback(ctx); err != nil {
		t.Fatalf("release shared Component activity lock: %v", err)
	}
	if err := exclusiveTx.QueryRow(ctx, `SELECT pg_try_advisory_xact_lock($1)`, lockKey).Scan(&acquired); err != nil {
		t.Fatalf("retry exclusive Component activity lock: %v", err)
	}
	if !acquired {
		t.Fatal("exclusive Publish boundary remained blocked after shared Watch transaction ended")
	}
}

func testPublishedEventRollback(t *testing.T, pool *pgxpool.Pool, actor, componentID, versionID pgtype.UUID) {
	t.Helper()
	ctx := context.Background()
	tx, err := pool.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.Serializable})
	if err != nil {
		t.Fatalf("begin publish rollback transaction: %v", err)
	}
	q := db.New(tx)
	locked, err := q.LockOwnedComponentVersion(ctx, db.LockOwnedComponentVersionParams{VersionID: versionID, ActorID: actor})
	if err != nil {
		t.Fatalf("lock rollback fixture version: %v", err)
	}
	if err := q.AcquireExclusiveComponentActivityLock(ctx, componentactivity.LockKey(locked.ComponentID)); err != nil {
		t.Fatalf("lock rollback fixture activity: %v", err)
	}
	if err := q.DeprecateOtherPublishedVersions(ctx, db.DeprecateOtherPublishedVersionsParams{ComponentID: componentID, VersionID: versionID}); err != nil {
		t.Fatalf("deprecate rollback fixture versions: %v", err)
	}
	if _, err := q.PublishComponentVersion(ctx, versionID); err != nil {
		t.Fatalf("publish rollback fixture version: %v", err)
	}
	if err := q.SetComponentCurrentVersion(ctx, db.SetComponentCurrentVersionParams{VersionID: versionID, ComponentID: componentID, ActorID: actor}); err != nil {
		t.Fatalf("set rollback fixture current version: %v", err)
	}
	if _, err := q.CreateComponentVersionPublishedEvent(ctx, db.CreateComponentVersionPublishedEventParams{
		ID: mustUUID(t, "20000000-0000-0000-0000-000000000041"), ComponentID: componentID,
		ComponentVersionID: versionID, ActorID: actor,
	}); err != nil {
		t.Fatalf("insert rollback fixture event: %v", err)
	}
	if err := tx.Rollback(ctx); err != nil {
		t.Fatalf("rollback publish transaction: %v", err)
	}
	var status string
	var currentVersionID pgtype.UUID
	var eventCount int64
	if err := pool.QueryRow(ctx, `
		SELECT version.status, component.current_version_id,
		       (SELECT count(*) FROM component_repo.component_domain_events event
		        WHERE event.component_version_id = version.id)
		FROM component_repo.component_versions version
		JOIN component_repo.components component ON component.id = version.component_id
		WHERE version.id = $1`, versionID).Scan(&status, &currentVersionID, &eventCount); err != nil {
		t.Fatalf("read rolled-back publish state: %v", err)
	}
	if status != "draft" || currentVersionID.Valid || eventCount != 0 {
		t.Fatalf("rolled-back publish leaked state: status=%q current=%s events=%d", status, uuidutil.String(currentVersionID), eventCount)
	}
}

func testWatchKeysetPagination(t *testing.T, service *Service, creator, actor pgtype.UUID) {
	t.Helper()
	ctx := context.Background()
	// official fixture 不需要复制 user Component 的 Import/Candidate 所有权链；这里只验证关系分页不变量。
	_, err := service.pool.Exec(ctx, `
		INSERT INTO component_repo.components
			(id, content_kind, content_locale, name, category, status, created_by)
		VALUES
			('21000000-0000-0000-0000-000000000001', 'official', 'en-US', 'Watch page one', 'building', 'active', $1),
			('21000000-0000-0000-0000-000000000002', 'official', 'en-US', 'Watch page two', 'vehicle', 'active', $1)`, creator)
	if err != nil {
		t.Fatalf("seed watch pagination components: %v", err)
	}
	_, err = service.pool.Exec(ctx, `
		INSERT INTO component_repo.component_versions
			(id, component_id, version_label, revision, status, source_artifact_id, scene_snapshot_id,
			 parser_version, interface_signature, structure_hash, geometry_hash, preview_status, created_by, published_at)
		SELECT fixture.version_id, fixture.component_id, '1.0.0', 1, 'published',
		       source.source_artifact_id, source.scene_snapshot_id, source.parser_version,
		       source.interface_signature, source.structure_hash, source.geometry_hash,
		       'pending', $1, now()
		FROM (VALUES
			('21000000-0000-0000-0000-000000000011'::uuid, '21000000-0000-0000-0000-000000000001'::uuid),
			('21000000-0000-0000-0000-000000000012'::uuid, '21000000-0000-0000-0000-000000000002'::uuid)
		) AS fixture(version_id, component_id)
		CROSS JOIN LATERAL (
			SELECT source_artifact_id, scene_snapshot_id, parser_version,
			       interface_signature, structure_hash, geometry_hash
			FROM component_repo.component_versions
			WHERE status = 'published'
			LIMIT 1
		) source`, creator)
	if err != nil {
		t.Fatalf("seed watch pagination versions: %v", err)
	}
	_, err = service.pool.Exec(ctx, `
		INSERT INTO component_repo.component_translations
			(component_id, locale, name, translation_status, reviewed_by, reviewed_at)
		VALUES
			('21000000-0000-0000-0000-000000000002', 'zh-CN', '订阅分页车辆', 'reviewed', $1, now())`, creator)
	if err != nil {
		t.Fatalf("seed watch pagination translation: %v", err)
	}
	_, err = service.pool.Exec(ctx, `
		UPDATE component_repo.components component
		SET current_version_id = fixture.version_id
		FROM (VALUES
			('21000000-0000-0000-0000-000000000001'::uuid, '21000000-0000-0000-0000-000000000011'::uuid),
			('21000000-0000-0000-0000-000000000002'::uuid, '21000000-0000-0000-0000-000000000012'::uuid)
		) AS fixture(component_id, version_id)
		WHERE component.id = fixture.component_id`)
	if err != nil {
		t.Fatalf("link watch pagination current versions: %v", err)
	}
	watchService := componentwatch.NewService(service.pool)
	for _, componentID := range []string{
		"21000000-0000-0000-0000-000000000001",
		"21000000-0000-0000-0000-000000000002",
	} {
		if _, err := watchService.Watch(ctx, actor, componentID, componentwatch.ReleasesOnlyLevel); err != nil {
			t.Fatalf("watch pagination fixture %s: %v", componentID, err)
		}
	}
	// 相同 watched_at 强制游标必须使用 component_id 唯一 tiebreaker，不能只依赖时间。
	if _, err := service.pool.Exec(ctx, `
		UPDATE component_repo.component_watch_periods
		SET watched_at = '2026-08-31 12:00:00+00'
		WHERE actor_id = $1 AND ended_seq IS NULL`, actor); err != nil {
		t.Fatalf("align watch timestamps: %v", err)
	}
	first, err := watchService.List(ctx, actor, componentwatch.ListRequest{Locale: "en-US", Limit: 2})
	if err != nil || len(first.Items) != 2 || first.NextCursor == nil {
		t.Fatalf("first watch cursor page: %+v, %v", first, err)
	}
	second, err := watchService.List(ctx, actor, componentwatch.ListRequest{Locale: "en-US", Limit: 2, Cursor: *first.NextCursor})
	if err != nil || len(second.Items) != 1 || second.NextCursor != nil {
		t.Fatalf("second watch cursor page: %+v, %v", second, err)
	}
	seen := map[string]bool{}
	for _, item := range append(first.Items, second.Items...) {
		if seen[item.ComponentID] {
			t.Fatalf("watch cursor returned duplicate component %s", item.ComponentID)
		}
		seen[item.ComponentID] = true
	}
	if len(seen) != 3 {
		t.Fatalf("watch cursor components = %v", seen)
	}
	filtered, err := watchService.List(ctx, actor, componentwatch.ListRequest{
		Locale: "en-US", Limit: 20, Query: "page one", Category: "building",
	})
	if err != nil || len(filtered.Items) != 1 || filtered.Items[0].ComponentID != "21000000-0000-0000-0000-000000000001" {
		t.Fatalf("filtered watch list: %+v, %v", filtered, err)
	}
	translated, err := watchService.List(ctx, actor, componentwatch.ListRequest{
		Locale: "zh-CN", Limit: 20, Query: "分页车辆", Category: "vehicle",
	})
	if err != nil || len(translated.Items) != 1 || translated.Items[0].Name != "订阅分页车辆" {
		t.Fatalf("translated watch search: %+v, %v", translated, err)
	}
}

func testStablePagination(t *testing.T, service *Service, actor pgtype.UUID) {
	t.Helper()
	ctx := context.Background()
	seedListableOfficialComponents(t, service.pool, actor)
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

func seedListableOfficialComponents(t *testing.T, pool *pgxpool.Pool, actor pgtype.UUID) {
	t.Helper()
	ctx := context.Background()
	_, err := pool.Exec(ctx, `
		WITH inserted_components AS (
			INSERT INTO component_repo.components
			(id, content_kind, content_locale, name, status, created_by, updated_at)
			VALUES
				('20000000-0000-0000-0000-000000000050', 'official', 'en-US', 'Page A', 'active', $1, now() - interval '3 minutes'),
				('20000000-0000-0000-0000-000000000060', 'official', 'en-US', 'Page B', 'active', $1, now() - interval '2 minutes'),
				('20000000-0000-0000-0000-000000000070', 'official', 'en-US', 'Page C', 'active', $1, now() - interval '1 minute')
			RETURNING id
		), inserted_versions AS (
			INSERT INTO component_repo.component_versions
			(id, component_id, version_label, status, source_artifact_id, scene_snapshot_id,
			 parser_version, interface_signature, structure_hash, geometry_hash, created_by, created_at)
			VALUES
				('20000000-0000-0000-0000-000000000051', '20000000-0000-0000-0000-000000000050',
				 '1.0.0', 'published', '20000000-0000-0000-0000-000000000010',
				 '20000000-0000-0000-0000-000000000012', 'g3-fixture', repeat('1', 64),
				 repeat('2', 64), repeat('3', 64), $1, now() - interval '3 minutes'),
				('20000000-0000-0000-0000-000000000061', '20000000-0000-0000-0000-000000000060',
				 '1.0.0', 'published', '20000000-0000-0000-0000-000000000010',
				 '20000000-0000-0000-0000-000000000012', 'g3-fixture', repeat('1', 64),
				 repeat('2', 64), repeat('3', 64), $1, now() - interval '2 minutes'),
				('20000000-0000-0000-0000-000000000071', '20000000-0000-0000-0000-000000000070',
				 '1.0.0', 'published', '20000000-0000-0000-0000-000000000010',
				 '20000000-0000-0000-0000-000000000012', 'g3-fixture', repeat('1', 64),
				 repeat('2', 64), repeat('3', 64), $1, now() - interval '1 minute')
			RETURNING id, component_id
		)
		UPDATE component_repo.components c
		SET current_version_id = v.id
		FROM inserted_versions v
		WHERE v.component_id = c.id
		  AND c.id IN (
		      '20000000-0000-0000-0000-000000000050',
		      '20000000-0000-0000-0000-000000000060',
		      '20000000-0000-0000-0000-000000000070'
		  )`, actor)
	if err != nil {
		t.Fatalf("seed pagination components with versions: %v", err)
	}
}

func seedVersionDependencies(t *testing.T, pool *pgxpool.Pool, actorA, actorB pgtype.UUID, componentID string) {
	t.Helper()
	ctx := context.Background()
	baseDocument := diffSceneDocument([]scene.RootInstance{{InstanceID: "base-root", TargetModelID: "assembly", Transform: scene.IdentityTransform()}}, "4")
	headDocument := diffSceneDocument([]scene.RootInstance{
		{InstanceID: "head-left", TargetModelID: "assembly", Transform: scene.IdentityTransform()},
		{InstanceID: "head-right", TargetModelID: "assembly", Transform: translatedSceneTransform(20)},
	}, "14")
	_, err := pool.Exec(ctx, `
		INSERT INTO component_repo.artifacts
			(id, owner_id, artifact_type, source_kind, original_filename, storage_provider,
			 storage_bucket, storage_key, sha256, file_size, mime_type, immutable,
			 verification_status, verified_at, uploaded_by)
		VALUES
			('20000000-0000-0000-0000-000000000010', $1, 'ldraw', 'source', 'fixture.ldr',
			 'test', 'test', 'g3/fixture.ldr', repeat('0', 64), 1, 'text/plain', true,
			 'verified', now(), $1),
			('20000000-0000-0000-0000-000000000020', $2, 'ldraw', 'source', 'foreign.ldr',
			 'test', 'test', 'g3/foreign.ldr', repeat('4', 64), 1, 'text/plain', true,
			 'verified', now(), $2),
			('20000000-0000-0000-0000-000000000030', $1, 'ldraw', 'source', 'pending.ldr',
			 'test', 'test', 'g3/pending.ldr', repeat('5', 64), 1, 'text/plain', true,
			 'pending', NULL, $1)`, actorA, actorB)
	if err != nil {
		t.Fatalf("seed source artifacts: %v", err)
	}
	_, err = pool.Exec(ctx, `
		INSERT INTO component_repo.upload_sessions
			(id, owner_id, status, target_component_id, locale, timezone, created_by, expires_at, completed_at)
		VALUES
			('20000000-0000-0000-0000-000000000014', $1, 'completed', $3, 'zh-CN', 'Asia/Shanghai', $1, now() + interval '1 hour', now()),
			('20000000-0000-0000-0000-000000000024', $2, 'completed', $3, 'en-US', 'UTC', $2, now() + interval '1 hour', now()),
			('20000000-0000-0000-0000-000000000034', $1, 'completed', $3, 'en-US', 'UTC', $1, now() + interval '1 hour', now())`, actorA, actorB, componentID)
	if err != nil {
		t.Fatalf("seed import upload sessions: %v", err)
	}
	_, err = pool.Exec(ctx, `
		INSERT INTO component_repo.tasks
			(id, owner_id, task_type, payload, locale, timezone, created_by)
		VALUES
			('20000000-0000-0000-0000-000000000016', $1, 'component.artifact.verify',
			 '{"artifactId":"20000000-0000-0000-0000-000000000010"}', 'zh-CN', 'Asia/Shanghai', $1),
			('20000000-0000-0000-0000-000000000015', $1, 'component.import.parse',
			 '{"importId":"20000000-0000-0000-0000-000000000011","parserVersion":"g3-fixture","snapshotSchema":"1"}', 'zh-CN', 'Asia/Shanghai', $1),
			('20000000-0000-0000-0000-000000000026', $2, 'component.artifact.verify',
			 '{"artifactId":"20000000-0000-0000-0000-000000000020"}', 'en-US', 'UTC', $2),
			('20000000-0000-0000-0000-000000000025', $2, 'component.import.parse',
			 '{"importId":"20000000-0000-0000-0000-000000000021","parserVersion":"g3-foreign","snapshotSchema":"1"}', 'en-US', 'UTC', $2),
			('20000000-0000-0000-0000-000000000036', $1, 'component.artifact.verify',
			 '{"artifactId":"20000000-0000-0000-0000-000000000030"}', 'en-US', 'UTC', $1),
			('20000000-0000-0000-0000-000000000035', $1, 'component.import.parse',
			 '{"importId":"20000000-0000-0000-0000-000000000031","parserVersion":"g3-pending","snapshotSchema":"1"}', 'en-US', 'UTC', $1)`, actorA, actorB)
	if err != nil {
		t.Fatalf("seed import parse tasks: %v", err)
	}
	_, err = pool.Exec(ctx, `
		INSERT INTO component_repo.task_dependencies (task_id, prerequisite_task_id, owner_id)
		VALUES
			('20000000-0000-0000-0000-000000000015', '20000000-0000-0000-0000-000000000016', $1),
			('20000000-0000-0000-0000-000000000025', '20000000-0000-0000-0000-000000000026', $2),
			('20000000-0000-0000-0000-000000000035', '20000000-0000-0000-0000-000000000036', $1)`, actorA, actorB)
	if err != nil {
		t.Fatalf("seed task dependencies: %v", err)
	}
	_, err = pool.Exec(ctx, `
		INSERT INTO component_repo.imports
			(id, owner_id, source_artifact_id, target_component_id, status, parser_version,
			 locale, timezone, created_by, upload_session_id, parse_task_id)
		VALUES
			('20000000-0000-0000-0000-000000000011', $1,
			 '20000000-0000-0000-0000-000000000010', $3, 'succeeded', 'g3-fixture',
			 'zh-CN', 'Asia/Shanghai', $1,
			 '20000000-0000-0000-0000-000000000014', '20000000-0000-0000-0000-000000000015'),
			('20000000-0000-0000-0000-000000000021', $2,
			 '20000000-0000-0000-0000-000000000020', $3, 'succeeded', 'g3-foreign',
			 'en-US', 'UTC', $2,
			 '20000000-0000-0000-0000-000000000024', '20000000-0000-0000-0000-000000000025'),
			('20000000-0000-0000-0000-000000000031', $1,
			 '20000000-0000-0000-0000-000000000030', $3, 'succeeded', 'g3-pending',
			 'en-US', 'UTC', $1,
			 '20000000-0000-0000-0000-000000000034', '20000000-0000-0000-0000-000000000035')`, actorA, actorB, componentID)
	if err != nil {
		t.Fatalf("seed imports: %v", err)
	}
	_, err = pool.Exec(ctx, `
		INSERT INTO component_repo.scene_snapshots
			(id, import_id, schema_version, parser_version, document, bom, parse_issues)
		VALUES
			('20000000-0000-0000-0000-000000000012',
			 '20000000-0000-0000-0000-000000000011', '1', 'g3-fixture', $1::jsonb, '{"3001.dat":1}', '[]'),
			('20000000-0000-0000-0000-000000000022',
			 '20000000-0000-0000-0000-000000000021', '1', 'g3-foreign', $1::jsonb, '{"3001.dat":1}', '[]'),
			('20000000-0000-0000-0000-000000000032',
			 '20000000-0000-0000-0000-000000000031', '1', 'g3-pending', $2::jsonb, '{"3001.dat":2}', '[]')`, baseDocument, headDocument)
	if err != nil {
		t.Fatalf("seed scene snapshots: %v", err)
	}
	_, err = pool.Exec(ctx, `
		INSERT INTO component_repo.candidates
			(id, owner_id, import_id, scene_snapshot_id, summary,
			 interface_signature, structure_hash, geometry_hash)
		VALUES
			('20000000-0000-0000-0000-000000000013', $1,
			 '20000000-0000-0000-0000-000000000011',
			 '20000000-0000-0000-0000-000000000012', '{}', repeat('1', 64), repeat('2', 64), repeat('3', 64)),
			('20000000-0000-0000-0000-000000000023', $2,
			 '20000000-0000-0000-0000-000000000021',
			 '20000000-0000-0000-0000-000000000022', '{}', repeat('1', 64), repeat('2', 64), repeat('3', 64)),
			('20000000-0000-0000-0000-000000000033', $1,
			 '20000000-0000-0000-0000-000000000031',
			 '20000000-0000-0000-0000-000000000032', '{}', repeat('1', 64), repeat('2', 64), repeat('3', 64))`, actorA, actorB)
	if err != nil {
		t.Fatalf("seed candidates: %v", err)
	}
}

func diffSceneDocument(roots []scene.RootInstance, colorCode string) json.RawMessage {
	document := scene.Document{
		RootInstances: roots,
		Models: []scene.Model{{ModelID: "assembly", References: []scene.Reference{{
			InstanceID: "leaf", ReferenceName: "3001.dat", ReferenceKind: "part",
			ColorCode: colorCode, Transform: scene.IdentityTransform(),
		}}}},
	}
	encoded, _ := json.Marshal(document)
	return encoded
}

func translatedSceneTransform(x float64) scene.Transform {
	transform := scene.IdentityTransform()
	transform.Position.X = x
	return transform
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

func databaseCode(err error) string {
	var databaseError *pgconn.PgError
	if errors.As(err, &databaseError) {
		return databaseError.Code
	}
	return ""
}
