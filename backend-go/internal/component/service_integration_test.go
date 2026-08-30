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

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/scene"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
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

	service := NewService(pool)
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
	published, err := service.PublishVersion(ctx, actorA, version.ID)
	if err != nil || published.Status != "published" || published.PublishedAt == nil {
		t.Fatalf("publish version: %+v, %v", published, err)
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
	testGroupsMembershipsAndStars(t, service, actorA, actorB, created.ID)
	testStablePagination(t, service, actorA)

	if err := service.DeleteComponent(ctx, actorA, created.ID); err != nil {
		t.Fatalf("owner should be able to delete published component: %v", err)
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

func testGroupsMembershipsAndStars(t *testing.T, service *Service, actorA, actorB pgtype.UUID, componentID string) {
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
