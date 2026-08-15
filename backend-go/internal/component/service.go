package component

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	defaultPageSize = 20
	maxPageSize     = 100
	maxGroupDepth   = 5
)

type Service struct {
	pool *pgxpool.Pool
	q    *db.Queries
}

func NewService(pool *pgxpool.Pool) *Service {
	return &Service{pool: pool, q: db.New(pool)}
}

func (s *Service) CreateComponent(ctx context.Context, actor pgtype.UUID, input CreateComponentInput) (Component, error) {
	if strings.TrimSpace(input.Name) == "" || len(input.Name) > 255 {
		return Component{}, validationError("name")
	}
	locale, ok := NormalizeLocale(input.ContentLocale)
	if !ok {
		return Component{}, validationError("contentLocale")
	}
	if len(input.Tags) > 50 {
		return Component{}, validationError("tags")
	}
	return withTx(ctx, s.pool, func(q *db.Queries) (Component, error) {
		id, err := uuidutil.New()
		if err != nil {
			return Component{}, err
		}
		_, err = q.CreateComponent(ctx, db.CreateComponentParams{
			ID: id, OwnerID: actor, ContentLocale: locale, Name: input.Name,
			Description: input.Description, Tags: nonNilStrings(input.Tags),
			Category: cleanOptional(input.Category), CreatedBy: actor,
		})
		if err != nil {
			return Component{}, mapDatabaseError(err, "request.conflict")
		}
		row, err := q.GetVisibleComponent(ctx, db.GetVisibleComponentParams{
			Locale: locale, ActorID: actor, ComponentID: id,
		})
		return componentFromVisible(row), err
	})
}

func (s *Service) GetComponent(ctx context.Context, actor pgtype.UUID, componentID, localeInput string) (Component, error) {
	id, err := resourceID(componentID, "componentId")
	if err != nil {
		return Component{}, err
	}
	locale := displayLocale(localeInput)
	row, err := s.q.GetVisibleComponent(ctx, db.GetVisibleComponentParams{
		Locale: locale, ActorID: actor, ComponentID: id,
	})
	if errors.Is(err, pgx.ErrNoRows) {
		return Component{}, notFound("component_repo.component_not_found", "componentId", componentID)
	}
	if err != nil {
		return Component{}, err
	}
	return componentFromVisible(row), nil
}

func (s *Service) ListComponents(ctx context.Context, actor pgtype.UUID, request ComponentListRequest) (ComponentPage, error) {
	request.PageRequest = normalizePage(request.PageRequest)
	locale := displayLocale(request.Locale)
	if len(request.Query) > 200 || len(request.Category) > 128 {
		return ComponentPage{}, validationError("query")
	}
	if request.Status != "" && request.Status != "draft" && request.Status != "active" && request.Status != "archived" {
		return ComponentPage{}, validationError("status")
	}
	rows, err := s.q.ListVisibleComponents(ctx, db.ListVisibleComponentsParams{
		Locale: locale, ActorID: actor, StatusFilter: request.Status,
		CategoryFilter: strings.TrimSpace(request.Category), SearchQuery: strings.TrimSpace(request.Query),
		PageOffset: int32((request.Page - 1) * request.PageSize), PageSize: int32(request.PageSize),
	})
	if err != nil {
		return ComponentPage{}, err
	}
	items := make([]Component, 0, len(rows))
	for _, row := range rows {
		items = append(items, componentFromList(row))
	}
	return ComponentPage{Items: items, Page: request.Page, PageSize: request.PageSize}, nil
}

func (s *Service) UpdateComponent(ctx context.Context, actor pgtype.UUID, componentID string, input UpdateComponentInput) (Component, error) {
	id, err := resourceID(componentID, "componentId")
	if err != nil {
		return Component{}, err
	}
	if input.Name == nil && !input.Description.Set && input.Tags == nil && !input.Category.Set && input.ContentLocale == nil {
		return Component{}, validationError("body")
	}
	name := ""
	if input.Name != nil {
		name = *input.Name
		if strings.TrimSpace(name) == "" || len(name) > 255 {
			return Component{}, validationError("name")
		}
	}
	locale := ""
	if input.ContentLocale != nil {
		var ok bool
		locale, ok = NormalizeLocale(*input.ContentLocale)
		if !ok {
			return Component{}, validationError("contentLocale")
		}
	}
	if input.Tags != nil && len(*input.Tags) > 50 {
		return Component{}, validationError("tags")
	}
	return withTx(ctx, s.pool, func(q *db.Queries) (Component, error) {
		_, err := q.UpdateOwnedComponent(ctx, db.UpdateOwnedComponentParams{
			SetName: input.Name != nil, Name: name,
			SetDescription: input.Description.Set, Description: input.Description.Value,
			SetTags: input.Tags != nil, Tags: nonNilStringPointer(input.Tags),
			SetCategory: input.Category.Set, Category: cleanOptional(input.Category.Value),
			SetContentLocale: input.ContentLocale != nil, ContentLocale: locale,
			ComponentID: id, ActorID: actor,
		})
		if errors.Is(err, pgx.ErrNoRows) {
			return Component{}, notFound("component_repo.component_not_found", "componentId", componentID)
		}
		if err != nil {
			return Component{}, mapDatabaseError(err, "request.conflict")
		}
		row, err := q.GetVisibleComponent(ctx, db.GetVisibleComponentParams{
			Locale: displayLocale(locale), ActorID: actor, ComponentID: id,
		})
		return componentFromVisible(row), err
	})
}

func (s *Service) DeleteComponent(ctx context.Context, actor pgtype.UUID, componentID string) error {
	id, err := resourceID(componentID, "componentId")
	if err != nil {
		return err
	}
	_, err = withTx(ctx, s.pool, func(q *db.Queries) (struct{}, error) {
		_, err := q.SoftDeleteOwnedComponent(ctx, db.SoftDeleteOwnedComponentParams{ActorID: actor, ComponentID: id})
		if errors.Is(err, pgx.ErrNoRows) {
			return struct{}{}, notFound("component_repo.component_not_found", "componentId", componentID)
		}
		return struct{}{}, err
	})
	return err
}

func (s *Service) CreateVersion(ctx context.Context, actor pgtype.UUID, componentID string, input CreateVersionInput) (ComponentVersion, error) {
	componentUUID, err := resourceID(componentID, "componentId")
	if err != nil {
		return ComponentVersion{}, err
	}
	params, err := versionCreateParams(actor, componentUUID, input)
	if err != nil {
		return ComponentVersion{}, err
	}
	return withTx(ctx, s.pool, func(q *db.Queries) (ComponentVersion, error) {
		if _, err := q.LockOwnedComponent(ctx, db.LockOwnedComponentParams{ComponentID: componentUUID, ActorID: actor}); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return ComponentVersion{}, notFound("component_repo.component_not_found", "componentId", componentID)
			}
			return ComponentVersion{}, err
		}
		source, err := q.GetOwnedVersionCandidateSource(ctx, db.GetOwnedVersionCandidateSourceParams{
			CandidateID: params.ComponentCandidateID,
			ActorID:     actor,
			ComponentID: componentUUID,
		})
		if errors.Is(err, pgx.ErrNoRows) {
			return ComponentVersion{}, apierror.New("component_repo.version_source_not_found_failed", http.StatusNotFound, nil)
		}
		if err != nil {
			return ComponentVersion{}, err
		}
		params.SourceArtifactID = source.SourceArtifactID
		params.ExchangeArtifactID = source.ExchangeArtifactID
		params.SceneSnapshotID = source.SceneSnapshotID
		params.ParserVersion = source.ParserVersion
		params.PartLibraryVersionID = source.PartLibraryVersionID
		params.InterfaceSignature = source.InterfaceSignature
		params.StructureHash = source.StructureHash
		params.GeometryHash = source.GeometryHash
		row, err := q.CreateComponentVersion(ctx, params)
		if err != nil {
			return ComponentVersion{}, mapDatabaseError(err, "component_repo.version_conflict")
		}
		return versionFromDB(row), nil
	})
}

func (s *Service) GetVersion(ctx context.Context, actor pgtype.UUID, versionID string) (ComponentVersion, error) {
	id, err := resourceID(versionID, "versionId")
	if err != nil {
		return ComponentVersion{}, err
	}
	row, err := s.q.GetVisibleComponentVersion(ctx, db.GetVisibleComponentVersionParams{VersionID: id, ActorID: actor})
	if errors.Is(err, pgx.ErrNoRows) {
		return ComponentVersion{}, notFound("component_repo.version_not_found", "versionId", versionID)
	}
	if err != nil {
		return ComponentVersion{}, err
	}
	return versionFromDB(row), nil
}

func (s *Service) ListVersions(ctx context.Context, actor pgtype.UUID, componentID string, page PageRequest) (VersionPage, error) {
	id, err := resourceID(componentID, "componentId")
	if err != nil {
		return VersionPage{}, err
	}
	page = normalizePage(page)
	visible, err := s.q.ComponentIsVisible(ctx, db.ComponentIsVisibleParams{ComponentID: id, ActorID: actor})
	if err != nil {
		return VersionPage{}, err
	}
	if !visible {
		return VersionPage{}, notFound("component_repo.component_not_found", "componentId", componentID)
	}
	rows, err := s.q.ListVisibleComponentVersions(ctx, db.ListVisibleComponentVersionsParams{
		ComponentID: id, ActorID: actor, PageOffset: int32((page.Page - 1) * page.PageSize), PageSize: int32(page.PageSize),
	})
	if err != nil {
		return VersionPage{}, err
	}
	items := make([]ComponentVersion, 0, len(rows))
	for _, row := range rows {
		items = append(items, versionFromDB(row))
	}
	return VersionPage{Items: items, Page: page.Page, PageSize: page.PageSize}, nil
}

func (s *Service) PublishVersion(ctx context.Context, actor pgtype.UUID, versionID string) (ComponentVersion, error) {
	id, err := resourceID(versionID, "versionId")
	if err != nil {
		return ComponentVersion{}, err
	}
	return withTx(ctx, s.pool, func(q *db.Queries) (ComponentVersion, error) {
		locked, err := q.LockOwnedComponentVersion(ctx, db.LockOwnedComponentVersionParams{VersionID: id, ActorID: actor})
		if errors.Is(err, pgx.ErrNoRows) {
			return ComponentVersion{}, notFound("component_repo.version_not_found", "versionId", versionID)
		}
		if err != nil {
			return ComponentVersion{}, err
		}
		if locked.Status != "draft" {
			return ComponentVersion{}, apierror.New("request.conflict", http.StatusConflict, nil)
		}
		if err := q.DeprecateOtherPublishedVersions(ctx, db.DeprecateOtherPublishedVersionsParams{ComponentID: locked.ComponentID, VersionID: id}); err != nil {
			return ComponentVersion{}, err
		}
		if _, err := q.PublishComponentVersion(ctx, id); err != nil {
			var databaseError *pgconn.PgError
			if errors.As(err, &databaseError) && strings.Contains(databaseError.Message, "publish validation report") {
				return ComponentVersion{}, apierror.New("component_repo.publish_validation_failed", http.StatusConflict, map[string]any{"versionId": versionID})
			}
			return ComponentVersion{}, err
		}
		if err := q.SetComponentCurrentVersion(ctx, db.SetComponentCurrentVersionParams{VersionID: id, ComponentID: locked.ComponentID, ActorID: actor}); err != nil {
			return ComponentVersion{}, err
		}
		row, err := q.GetVisibleComponentVersion(ctx, db.GetVisibleComponentVersionParams{VersionID: id, ActorID: actor})
		return versionFromDB(row), err
	})
}

func (s *Service) TransitionVersion(ctx context.Context, actor pgtype.UUID, versionID, target string) (ComponentVersion, error) {
	if target != "deprecated" && target != "archived" {
		return ComponentVersion{}, validationError("targetStatus")
	}
	id, err := resourceID(versionID, "versionId")
	if err != nil {
		return ComponentVersion{}, err
	}
	return withTx(ctx, s.pool, func(q *db.Queries) (ComponentVersion, error) {
		if _, err := q.TransitionOwnedComponentVersion(ctx, db.TransitionOwnedComponentVersionParams{TargetStatus: target, VersionID: id, ActorID: actor}); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return ComponentVersion{}, apierror.New("request.conflict", http.StatusConflict, nil)
			}
			return ComponentVersion{}, err
		}
		row, err := q.GetVisibleComponentVersion(ctx, db.GetVisibleComponentVersionParams{VersionID: id, ActorID: actor})
		return versionFromDB(row), err
	})
}

func (s *Service) DeleteVersion(ctx context.Context, actor pgtype.UUID, versionID string) error {
	id, err := resourceID(versionID, "versionId")
	if err != nil {
		return err
	}
	_, err = withTx(ctx, s.pool, func(q *db.Queries) (struct{}, error) {
		_, err := q.SoftDeleteOwnedDraftVersion(ctx, db.SoftDeleteOwnedDraftVersionParams{ActorID: actor, VersionID: id})
		if errors.Is(err, pgx.ErrNoRows) {
			return struct{}{}, notFound("component_repo.version_not_found", "versionId", versionID)
		}
		return struct{}{}, err
	})
	return err
}

func (s *Service) UpdateVersion(ctx context.Context, actor pgtype.UUID, versionID string, input UpdateVersionInput) (ComponentVersion, error) {
	id, err := resourceID(versionID, "versionId")
	if err != nil {
		return ComponentVersion{}, err
	}
	if input.Version == nil && input.Revision == nil && !input.ReleaseNote.Set && !input.ReleaseNoteLocale.Set {
		return ComponentVersion{}, validationError("body")
	}
	versionLabel := ""
	if input.Version != nil {
		versionLabel = strings.TrimSpace(*input.Version)
		if versionLabel == "" || len(versionLabel) > 64 {
			return ComponentVersion{}, validationError("version")
		}
	}
	if input.Revision != nil && *input.Revision < 1 {
		return ComponentVersion{}, validationError("revision")
	}
	if input.ReleaseNote.Set != input.ReleaseNoteLocale.Set {
		return ComponentVersion{}, validationError("releaseNoteLocale")
	}
	var releaseNote, releaseNoteLocale *string
	if input.ReleaseNote.Set {
		releaseNote = input.ReleaseNote.Value
		releaseNoteLocale = input.ReleaseNoteLocale.Value
		if (releaseNote == nil) != (releaseNoteLocale == nil) {
			return ComponentVersion{}, validationError("releaseNoteLocale")
		}
		if releaseNoteLocale != nil {
			normalized, ok := NormalizeLocale(*releaseNoteLocale)
			if !ok {
				return ComponentVersion{}, validationError("releaseNoteLocale")
			}
			releaseNoteLocale = &normalized
		}
	}
	row, err := s.q.UpdateOwnedDraftComponentVersion(ctx, db.UpdateOwnedDraftComponentVersionParams{
		SetVersionLabel: input.Version != nil, VersionLabel: versionLabel,
		SetRevision: input.Revision != nil, Revision: int32Value(input.Revision),
		SetReleaseNote: input.ReleaseNote.Set, ReleaseNote: releaseNote, ReleaseNoteLocale: releaseNoteLocale,
		VersionID: id, ActorID: actor,
	})
	if errors.Is(err, pgx.ErrNoRows) {
		return ComponentVersion{}, notFound("component_repo.version_not_found", "versionId", versionID)
	}
	if err != nil {
		return ComponentVersion{}, mapDatabaseError(err, "component_repo.version_conflict")
	}
	return versionFromDB(row), nil
}

func (s *Service) BootstrapGroups(ctx context.Context, actor pgtype.UUID) error {
	_, err := withTx(ctx, s.pool, func(q *db.Queries) (struct{}, error) {
		_, err := ensureRoot(ctx, q, actor)
		return struct{}{}, err
	})
	return err
}

func (s *Service) ListGroups(ctx context.Context, actor pgtype.UUID) ([]Group, error) {
	rows, err := s.q.ListOwnedComponentGroups(ctx, actor)
	if err != nil {
		return nil, err
	}
	groups := make([]Group, 0, len(rows))
	for _, row := range rows {
		groups = append(groups, groupFromList(row))
	}
	return groups, nil
}

func (s *Service) ListComponentGroupIDs(ctx context.Context, actor pgtype.UUID, componentID string) ([]string, error) {
	id, err := resourceID(componentID, "componentId")
	if err != nil {
		return nil, err
	}
	visible, err := s.q.ComponentIsVisible(ctx, db.ComponentIsVisibleParams{ComponentID: id, ActorID: actor})
	if err != nil {
		return nil, err
	}
	if !visible {
		return nil, notFound("component_repo.component_not_found", "componentId", componentID)
	}
	rows, err := s.q.ListOwnedComponentGroupIDsForComponent(ctx, db.ListOwnedComponentGroupIDsForComponentParams{
		OwnerID: actor, ComponentID: id,
	})
	if err != nil {
		return nil, err
	}
	ids := make([]string, 0, len(rows))
	for _, row := range rows {
		ids = append(ids, uuidutil.String(row))
	}
	return ids, nil
}

func (s *Service) SearchGroupComponents(ctx context.Context, actor pgtype.UUID, groupID string, input ComponentGroupSearchRequest) (ComponentGroupSearchPage, error) {
	id, err := resourceID(groupID, "groupId")
	if err != nil {
		return ComponentGroupSearchPage{}, err
	}
	if _, err := s.q.GetOwnedComponentGroup(ctx, db.GetOwnedComponentGroupParams{GroupID: id, OwnerID: actor}); errors.Is(err, pgx.ErrNoRows) {
		return ComponentGroupSearchPage{}, notFound("component_repo.group_not_found", "groupId", groupID)
	} else if err != nil {
		return ComponentGroupSearchPage{}, err
	}
	query := strings.TrimSpace(input.Query)
	if len(query) > 200 {
		return ComponentGroupSearchPage{}, validationError("query")
	}
	if len(input.Statuses) > 16 {
		return ComponentGroupSearchPage{}, validationError("statuses")
	}
	statuses := make([]string, 0, len(input.Statuses))
	seenStatuses := make(map[string]struct{}, len(input.Statuses))
	for _, status := range input.Statuses {
		if status == "" || len(status) > 32 {
			return ComponentGroupSearchPage{}, validationError("statuses")
		}
		if _, exists := seenStatuses[status]; exists {
			continue
		}
		seenStatuses[status] = struct{}{}
		statuses = append(statuses, status)
	}
	page := normalizePage(input.PageRequest)
	locale := displayLocale(input.Locale)
	rows, err := s.q.SearchComponentGroupComponents(ctx, db.SearchComponentGroupComponentsParams{
		Locale: locale, OwnerID: actor, GroupID: id, StatusFilters: statuses, SearchQuery: query,
		PageOffset: int32((page.Page - 1) * page.PageSize), PageSize: int32(page.PageSize),
	})
	if err != nil {
		return ComponentGroupSearchPage{}, err
	}
	items := make([]Component, 0, len(rows))
	for _, row := range rows {
		items = append(items, componentFromGroupSearch(row))
	}
	counts, err := s.q.CountComponentGroupStatuses(ctx, db.CountComponentGroupStatusesParams{
		Locale: locale, GroupID: id, OwnerID: actor, SearchQuery: query,
	})
	if err != nil {
		return ComponentGroupSearchPage{}, err
	}
	statusCounts := make(map[string]int64, len(counts))
	for _, count := range counts {
		statusCounts[count.Status] = count.ComponentCount
	}
	var total int64
	if len(statuses) == 0 {
		for _, count := range statusCounts {
			total += count
		}
	} else {
		for _, status := range statuses {
			total += statusCounts[status]
		}
	}
	totalPages := 0
	if total > 0 {
		totalPages = int((total + int64(page.PageSize) - 1) / int64(page.PageSize))
	}
	return ComponentGroupSearchPage{Items: items, Total: total, Page: page.Page, PageSize: page.PageSize, TotalPages: totalPages, StatusCounts: statusCounts}, nil
}

func (s *Service) CreateGroup(ctx context.Context, actor pgtype.UUID, input CreateGroupInput) (Group, error) {
	name, locale, err := validateGroupContent(input.Name, input.ContentLocale)
	if err != nil {
		return Group{}, err
	}
	return withTx(ctx, s.pool, func(q *db.Queries) (Group, error) {
		parentID, err := optionalParent(ctx, q, actor, input.ParentGroupID)
		if err != nil {
			return Group{}, err
		}
		depth, err := q.ComponentGroupDepth(ctx, db.ComponentGroupDepthParams{GroupID: parentID, OwnerID: actor})
		if err != nil {
			return Group{}, err
		}
		if depth+1 > maxGroupDepth {
			return Group{}, apierror.New("component_repo.group_depth_exceeded", http.StatusConflict, map[string]any{"maximumDepth": maxGroupDepth})
		}
		id, err := uuidutil.New()
		if err != nil {
			return Group{}, err
		}
		row, err := q.CreateComponentGroup(ctx, db.CreateComponentGroupParams{
			ID: id, OwnerID: actor, ParentGroupID: parentID, Name: &name,
			NormalizedName: pointer(normalizeGroupName(name)), ContentLocale: &locale, SortOrder: input.SortOrder,
		})
		if err != nil {
			return Group{}, mapDatabaseError(err, "component_repo.group_name_duplicate")
		}
		return groupFromDB(row, depth+1), nil
	})
}

func (s *Service) UpdateGroup(ctx context.Context, actor pgtype.UUID, groupID string, input UpdateGroupInput) (Group, error) {
	id, err := resourceID(groupID, "groupId")
	if err != nil {
		return Group{}, err
	}
	if input.Name == nil && input.ContentLocale == nil && input.SortOrder == nil {
		return Group{}, validationError("body")
	}
	name := ""
	if input.Name != nil {
		name = *input.Name
		if strings.TrimSpace(name) == "" || len(name) > 100 {
			return Group{}, validationError("name")
		}
	}
	locale := ""
	if input.ContentLocale != nil {
		var ok bool
		locale, ok = NormalizeLocale(*input.ContentLocale)
		if !ok {
			return Group{}, validationError("contentLocale")
		}
	}
	return withTx(ctx, s.pool, func(q *db.Queries) (Group, error) {
		row, err := q.UpdateOwnedComponentGroup(ctx, db.UpdateOwnedComponentGroupParams{
			SetName: input.Name != nil, Name: name, NormalizedName: normalizeGroupName(name),
			SetContentLocale: input.ContentLocale != nil, ContentLocale: locale,
			SetSortOrder: input.SortOrder != nil, SortOrder: int32Value(input.SortOrder),
			GroupID: id, OwnerID: actor,
		})
		if errors.Is(err, pgx.ErrNoRows) {
			return Group{}, notFound("component_repo.group_not_found", "groupId", groupID)
		}
		if err != nil {
			return Group{}, mapDatabaseError(err, "component_repo.group_name_duplicate")
		}
		depth, err := q.ComponentGroupDepth(ctx, db.ComponentGroupDepthParams{GroupID: id, OwnerID: actor})
		return groupFromDB(row, depth), err
	})
}

func (s *Service) MoveGroup(ctx context.Context, actor pgtype.UUID, groupID string, input MoveGroupInput) (Group, error) {
	id, err := resourceID(groupID, "groupId")
	if err != nil {
		return Group{}, err
	}
	parentID, err := resourceID(input.ParentGroupID, "parentGroupId")
	if err != nil {
		return Group{}, err
	}
	return withTx(ctx, s.pool, func(q *db.Queries) (Group, error) {
		group, err := q.GetOwnedComponentGroup(ctx, db.GetOwnedComponentGroupParams{GroupID: id, OwnerID: actor})
		if errors.Is(err, pgx.ErrNoRows) || group.GroupType != "custom" {
			return Group{}, notFound("component_repo.group_not_found", "groupId", groupID)
		}
		if _, err := q.GetOwnedComponentGroup(ctx, db.GetOwnedComponentGroupParams{GroupID: parentID, OwnerID: actor}); err != nil {
			return Group{}, notFound("component_repo.group_not_found", "groupId", input.ParentGroupID)
		}
		descendants, err := q.ListComponentGroupDescendantIDs(ctx, db.ListComponentGroupDescendantIDsParams{GroupID: id, OwnerID: actor})
		if err != nil {
			return Group{}, err
		}
		for _, descendant := range descendants {
			if uuidutil.Equal(descendant, parentID) {
				return Group{}, apierror.New("component_repo.group_cycle", http.StatusConflict, nil)
			}
		}
		parentDepth, err := q.ComponentGroupDepth(ctx, db.ComponentGroupDepthParams{GroupID: parentID, OwnerID: actor})
		if err != nil {
			return Group{}, err
		}
		subtreeDepth, err := q.ComponentGroupSubtreeDepth(ctx, db.ComponentGroupSubtreeDepthParams{GroupID: id, OwnerID: actor})
		if err != nil {
			return Group{}, err
		}
		if parentDepth+1+subtreeDepth > maxGroupDepth {
			return Group{}, apierror.New("component_repo.group_depth_exceeded", http.StatusConflict, map[string]any{"maximumDepth": maxGroupDepth})
		}
		row, err := q.MoveOwnedComponentGroup(ctx, db.MoveOwnedComponentGroupParams{
			ParentGroupID: parentID, SortOrder: input.SortOrder, GroupID: id, OwnerID: actor,
		})
		if err != nil {
			return Group{}, mapDatabaseError(err, "component_repo.group_name_duplicate")
		}
		return groupFromDB(row, parentDepth+1), nil
	})
}

func (s *Service) DeleteGroup(ctx context.Context, actor pgtype.UUID, groupID string) error {
	id, err := resourceID(groupID, "groupId")
	if err != nil {
		return err
	}
	_, err = withTx(ctx, s.pool, func(q *db.Queries) (struct{}, error) {
		_, err := q.DeleteOwnedComponentGroup(ctx, db.DeleteOwnedComponentGroupParams{GroupID: id, OwnerID: actor})
		if errors.Is(err, pgx.ErrNoRows) {
			return struct{}{}, notFound("component_repo.group_not_found", "groupId", groupID)
		}
		return struct{}{}, err
	})
	return err
}

func (s *Service) AddGroupMember(ctx context.Context, actor pgtype.UUID, groupID, componentID string) error {
	groupUUID, err := resourceID(groupID, "groupId")
	if err != nil {
		return err
	}
	componentUUID, err := resourceID(componentID, "componentId")
	if err != nil {
		return err
	}
	_, err = withTx(ctx, s.pool, func(q *db.Queries) (struct{}, error) {
		group, err := q.GetOwnedComponentGroup(ctx, db.GetOwnedComponentGroupParams{GroupID: groupUUID, OwnerID: actor})
		if errors.Is(err, pgx.ErrNoRows) || group.GroupType != "custom" {
			return struct{}{}, notFound("component_repo.group_not_found", "groupId", groupID)
		}
		visible, err := q.ComponentIsVisible(ctx, db.ComponentIsVisibleParams{ComponentID: componentUUID, ActorID: actor})
		if err != nil {
			return struct{}{}, err
		}
		if !visible {
			return struct{}{}, notFound("component_repo.component_not_found", "componentId", componentID)
		}
		_, err = q.AddComponentGroupMembership(ctx, db.AddComponentGroupMembershipParams{
			OwnerID: actor, GroupID: groupUUID, ComponentID: componentUUID, AddedBy: actor,
		})
		if errors.Is(err, pgx.ErrNoRows) {
			err = nil
		}
		return struct{}{}, err
	})
	return err
}

func (s *Service) RemoveGroupMember(ctx context.Context, actor pgtype.UUID, groupID, componentID string) error {
	groupUUID, err := resourceID(groupID, "groupId")
	if err != nil {
		return err
	}
	componentUUID, err := resourceID(componentID, "componentId")
	if err != nil {
		return err
	}
	_, err = withTx(ctx, s.pool, func(q *db.Queries) (struct{}, error) {
		_, err := q.RemoveComponentGroupMembership(ctx, db.RemoveComponentGroupMembershipParams{OwnerID: actor, GroupID: groupUUID, ComponentID: componentUUID})
		if errors.Is(err, pgx.ErrNoRows) {
			err = nil
		}
		return struct{}{}, err
	})
	return err
}

func (s *Service) ListGroupMembers(ctx context.Context, actor pgtype.UUID, groupID, localeInput string, page PageRequest) (GroupMemberPage, error) {
	groupUUID, err := resourceID(groupID, "groupId")
	if err != nil {
		return GroupMemberPage{}, err
	}
	if _, err := s.q.GetOwnedComponentGroup(ctx, db.GetOwnedComponentGroupParams{GroupID: groupUUID, OwnerID: actor}); errors.Is(err, pgx.ErrNoRows) {
		return GroupMemberPage{}, notFound("component_repo.group_not_found", "groupId", groupID)
	} else if err != nil {
		return GroupMemberPage{}, err
	}
	page = normalizePage(page)
	rows, err := s.q.ListComponentGroupMembers(ctx, db.ListComponentGroupMembersParams{
		Locale: displayLocale(localeInput), OwnerID: actor, GroupID: groupUUID,
		PageOffset: int32((page.Page - 1) * page.PageSize), PageSize: int32(page.PageSize),
	})
	if err != nil {
		return GroupMemberPage{}, err
	}
	items := make([]GroupMember, 0, len(rows))
	for _, row := range rows {
		items = append(items, groupMemberFromDB(row))
	}
	return GroupMemberPage{Items: items, Page: page.Page, PageSize: page.PageSize}, nil
}

func (s *Service) Subscribe(ctx context.Context, actor pgtype.UUID, componentID string) (Subscription, error) {
	id, err := resourceID(componentID, "componentId")
	if err != nil {
		return Subscription{}, err
	}
	return withTx(ctx, s.pool, func(q *db.Queries) (Subscription, error) {
		componentRow, err := q.GetVisibleComponent(ctx, db.GetVisibleComponentParams{Locale: "zh-CN", ActorID: actor, ComponentID: id})
		if errors.Is(err, pgx.ErrNoRows) {
			return Subscription{}, notFound("component_repo.component_not_found", "componentId", componentID)
		}
		if err != nil {
			return Subscription{}, err
		}
		if uuidutil.Equal(componentRow.OwnerID, actor) {
			return Subscription{}, apierror.New("component_repo.subscription_own_component_forbidden", http.StatusConflict, nil)
		}
		row, err := q.CreateComponentSubscription(ctx, db.CreateComponentSubscriptionParams{OwnerID: actor, ComponentID: id})
		if err != nil {
			return Subscription{}, err
		}
		return Subscription{ComponentID: uuidutil.String(row.ComponentID), SubscribedAt: row.SubscribedAt.Time}, nil
	})
}

func (s *Service) Unsubscribe(ctx context.Context, actor pgtype.UUID, componentID string) error {
	id, err := resourceID(componentID, "componentId")
	if err != nil {
		return err
	}
	_, err = withTx(ctx, s.pool, func(q *db.Queries) (struct{}, error) {
		_, err := q.DeleteComponentSubscription(ctx, db.DeleteComponentSubscriptionParams{OwnerID: actor, ComponentID: id})
		if errors.Is(err, pgx.ErrNoRows) {
			err = nil
		}
		return struct{}{}, err
	})
	return err
}

func NormalizeLocale(input string) (string, bool) {
	normalized := strings.TrimSpace(strings.ReplaceAll(input, "_", "-"))
	lower := strings.ToLower(normalized)
	switch {
	case lower == "zh" || lower == "zh-cn" || strings.HasPrefix(lower, "zh-hans-"):
		return "zh-CN", true
	case lower == "en" || lower == "en-us" || strings.HasPrefix(lower, "en-"):
		return "en-US", true
	default:
		return "", false
	}
}

func withTx[T any](ctx context.Context, pool *pgxpool.Pool, fn func(*db.Queries) (T, error)) (T, error) {
	var zero T
	for attempt := 0; attempt < 3; attempt++ {
		tx, err := pool.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.Serializable})
		if err != nil {
			return zero, err
		}
		value, runErr := fn(db.New(tx))
		if runErr != nil {
			_ = tx.Rollback(ctx)
			if retryableTransaction(runErr) {
				continue
			}
			return zero, runErr
		}
		if err = tx.Commit(ctx); err == nil {
			return value, nil
		}
		if !retryableTransaction(err) {
			return zero, err
		}
	}
	return zero, apierror.New("request.conflict", http.StatusConflict, nil)
}

func retryableTransaction(err error) bool {
	var pgError *pgconn.PgError
	return errors.As(err, &pgError) && (pgError.Code == "40001" || pgError.Code == "40P01")
}

func resourceID(value, field string) (pgtype.UUID, error) {
	id, err := uuidutil.Parse(value)
	if err != nil {
		return pgtype.UUID{}, validationError(field)
	}
	return id, nil
}

func versionCreateParams(actor, componentID pgtype.UUID, input CreateVersionInput) (db.CreateComponentVersionParams, error) {
	id, err := uuidutil.New()
	if err != nil {
		return db.CreateComponentVersionParams{}, err
	}
	candidate, err := resourceID(input.ComponentCandidateID, "componentCandidateId")
	if err != nil {
		return db.CreateComponentVersionParams{}, err
	}
	if strings.TrimSpace(input.Version) == "" || input.Revision < 1 {
		return db.CreateComponentVersionParams{}, validationError("version")
	}
	if (input.ReleaseNote == nil) != (input.ReleaseNoteLocale == nil) {
		return db.CreateComponentVersionParams{}, validationError("releaseNoteLocale")
	}
	if input.ReleaseNoteLocale != nil {
		normalized, ok := NormalizeLocale(*input.ReleaseNoteLocale)
		if !ok {
			return db.CreateComponentVersionParams{}, validationError("releaseNoteLocale")
		}
		input.ReleaseNoteLocale = &normalized
	}
	metadata := input.Metadata
	if len(metadata) == 0 {
		metadata = json.RawMessage(`{}`)
	}
	if !json.Valid(metadata) {
		return db.CreateComponentVersionParams{}, validationError("metadata")
	}
	return db.CreateComponentVersionParams{
		ID: id, ComponentID: componentID, ComponentCandidateID: candidate,
		VersionLabel: strings.TrimSpace(input.Version), Revision: input.Revision,
		ReleaseNote: input.ReleaseNote, ReleaseNoteLocale: input.ReleaseNoteLocale,
		Metadata: metadata, CreatedBy: actor,
	}, nil
}

func optionalParent(ctx context.Context, q *db.Queries, actor pgtype.UUID, value *string) (pgtype.UUID, error) {
	if value == nil {
		root, err := ensureRoot(ctx, q, actor)
		return root.ID, err
	}
	id, err := resourceID(*value, "parentGroupId")
	if err != nil {
		return pgtype.UUID{}, err
	}
	if _, err := q.GetOwnedComponentGroup(ctx, db.GetOwnedComponentGroupParams{GroupID: id, OwnerID: actor}); errors.Is(err, pgx.ErrNoRows) {
		return pgtype.UUID{}, notFound("component_repo.group_not_found", "groupId", *value)
	} else if err != nil {
		return pgtype.UUID{}, err
	}
	return id, nil
}

func ensureRoot(ctx context.Context, q *db.Queries, actor pgtype.UUID) (db.ComponentRepoComponentGroup, error) {
	id, err := uuidutil.New()
	if err != nil {
		return db.ComponentRepoComponentGroup{}, err
	}
	return q.EnsureComponentRootGroup(ctx, db.EnsureComponentRootGroupParams{ID: id, OwnerID: actor})
}

func validateGroupContent(nameInput, localeInput string) (string, string, error) {
	name := nameInput
	if strings.TrimSpace(name) == "" || len(name) > 100 {
		return "", "", validationError("name")
	}
	locale, ok := NormalizeLocale(localeInput)
	if !ok {
		return "", "", validationError("contentLocale")
	}
	return name, locale, nil
}

func normalizeGroupName(name string) string {
	return strings.ToLower(strings.Join(strings.Fields(name), " "))
}

func displayLocale(input string) string {
	locale, ok := NormalizeLocale(input)
	if !ok {
		return "zh-CN"
	}
	return locale
}

func normalizePage(page PageRequest) PageRequest {
	if page.Page < 1 {
		page.Page = 1
	}
	if page.PageSize < 1 {
		page.PageSize = defaultPageSize
	}
	if page.PageSize > maxPageSize {
		page.PageSize = maxPageSize
	}
	if page.Page > 1_000_000 {
		page.Page = 1_000_000
	}
	return page
}

func mapDatabaseError(err error, conflictCode string) error {
	var pgError *pgconn.PgError
	if !errors.As(err, &pgError) {
		return err
	}
	switch pgError.Code {
	case "23505":
		return apierror.New(conflictCode, http.StatusConflict, nil)
	case "23503":
		return apierror.New("component_repo.version_source_not_found_failed", http.StatusUnprocessableEntity, nil)
	case "23514", "23502":
		return apierror.New("request.validation_failed", http.StatusUnprocessableEntity, nil)
	default:
		return err
	}
}

func validationError(field string) *apierror.Error {
	return apierror.New("request.validation_failed", http.StatusUnprocessableEntity, map[string]any{"field": field})
}

func notFound(code, parameter, value string) *apierror.Error {
	return apierror.New(code, http.StatusNotFound, map[string]any{parameter: value})
}

func cleanOptional(value *string) *string {
	if value == nil {
		return nil
	}
	cleaned := strings.TrimSpace(*value)
	return &cleaned
}

func nonNilStrings(values []string) []string {
	if values == nil {
		return []string{}
	}
	return values
}

func nonNilStringPointer(values *[]string) []string {
	if values == nil || *values == nil {
		return []string{}
	}
	return *values
}

func int32Value(value *int32) int32 {
	if value == nil {
		return 0
	}
	return *value
}

func pointer[T any](value T) *T { return &value }
