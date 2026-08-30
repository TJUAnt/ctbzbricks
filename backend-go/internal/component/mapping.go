package component

import (
	"encoding/json"
	"time"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5/pgtype"
)

func componentFromVisible(row db.GetVisibleComponentRow) Component {
	return Component{
		ID: uuidutil.String(row.ID), OwnerID: uuidutil.NullableString(row.OwnerID),
		ContentKind: row.ContentKind, ContentLocale: row.SelectedContentLocale,
		Name: row.SelectedName, Description: optionalSelected(row.SelectedDescription, row.HasDescription),
		Tags: nonNilStrings(row.SelectedTags), Category: row.Category, Status: row.Status,
		CurrentVersionID: uuidutil.NullableString(row.CurrentVersionID), Metadata: validJSON(row.Metadata),
		LogicalSize:  logicalSize(row.LogicalWidthStud, row.LogicalDepthStud, row.LogicalHeightPlate),
		OwnedByActor: row.OwnedByActor, StarredByActor: row.StarredByActor, StarCount: row.StarCount,
		TranslationMissing: row.TranslationMissing,
		CreatedAt:          row.CreatedAt.Time, UpdatedAt: row.UpdatedAt.Time,
	}
}

func componentFromList(row db.ListVisibleComponentsRow) Component {
	return Component{
		ID: uuidutil.String(row.ID), OwnerID: uuidutil.NullableString(row.OwnerID),
		ContentKind: row.ContentKind, ContentLocale: row.SelectedContentLocale,
		Name: row.SelectedName, Description: optionalSelected(row.SelectedDescription, row.HasDescription),
		Tags: nonNilStrings(row.SelectedTags), Category: row.Category, Status: row.Status,
		CurrentVersionID: uuidutil.NullableString(row.CurrentVersionID), Metadata: validJSON(row.Metadata),
		LogicalSize:  logicalSize(row.LogicalWidthStud, row.LogicalDepthStud, row.LogicalHeightPlate),
		OwnedByActor: row.OwnedByActor, StarredByActor: row.StarredByActor, StarCount: row.StarCount,
		TranslationMissing: row.TranslationMissing,
		CreatedAt:          row.CreatedAt.Time, UpdatedAt: row.UpdatedAt.Time,
	}
}

func versionFromDB(row db.ComponentRepoComponentVersion) ComponentVersion {
	return ComponentVersion{
		ID: uuidutil.String(row.ID), ComponentID: uuidutil.String(row.ComponentID),
		ComponentCandidateID: uuidutil.NullableString(row.ComponentCandidateID),
		Version:              row.VersionLabel, Revision: row.Revision, Status: row.Status,
		SourceArtifactID:   uuidutil.String(row.SourceArtifactID),
		ExchangeArtifactID: uuidutil.NullableString(row.ExchangeArtifactID),
		SceneSnapshotID:    uuidutil.String(row.SceneSnapshotID), ParserVersion: row.ParserVersion,
		PartLibraryVersionID: uuidutil.NullableString(row.PartLibraryVersionID),
		ValidationReportID:   uuidutil.NullableString(row.ValidationReportID),
		InterfaceSignature:   row.InterfaceSignature, StructureHash: row.StructureHash,
		GeometryHash: row.GeometryHash, PreviewArtifactID: uuidutil.NullableString(row.PreviewArtifactID),
		PreviewStatus: row.PreviewStatus, PreviewGeneratorVersion: row.PreviewGeneratorVersion,
		PreviewFailureCode: row.PreviewFailureCode, PreviewFailureParams: validJSON(row.PreviewFailureParams), ReleaseNote: row.ReleaseNote,
		ReleaseNoteLocale: row.ReleaseNoteLocale, Metadata: validJSON(row.Metadata),
		CreatedAt: row.CreatedAt.Time, PublishedAt: nullableTime(row.PublishedAt),
	}
}

func groupFromList(row db.ListOwnedComponentGroupsRow) Group {
	return Group{
		ID: uuidutil.String(row.ID), OwnerID: uuidutil.String(row.OwnerID),
		ParentGroupID: uuidutil.NullableString(row.ParentGroupID), GroupType: row.GroupType,
		Name: row.Name, ContentLocale: row.ContentLocale, SortOrder: row.SortOrder,
		Depth: row.Depth, DirectComponentCount: row.DirectComponentCount,
		CreatedAt: row.CreatedAt.Time, UpdatedAt: row.UpdatedAt.Time,
	}
}

func groupFromDB(row db.ComponentRepoComponentGroup, depth int32) Group {
	return Group{
		ID: uuidutil.String(row.ID), OwnerID: uuidutil.String(row.OwnerID),
		ParentGroupID: uuidutil.NullableString(row.ParentGroupID), GroupType: row.GroupType,
		Name: row.Name, ContentLocale: row.ContentLocale, SortOrder: row.SortOrder,
		Depth: depth, CreatedAt: row.CreatedAt.Time, UpdatedAt: row.UpdatedAt.Time,
	}
}

func groupMemberFromDB(row db.ListComponentGroupMembersRow) GroupMember {
	return GroupMember{
		Component: Component{
			ID: uuidutil.String(row.ID), OwnerID: uuidutil.NullableString(row.OwnerID),
			ContentKind: row.ContentKind, ContentLocale: row.SelectedContentLocale,
			Name: row.SelectedName, Description: optionalSelected(row.SelectedDescription, row.HasDescription),
			Tags: nonNilStrings(row.SelectedTags), Category: row.Category, Status: row.Status,
			CurrentVersionID: uuidutil.NullableString(row.CurrentVersionID), Metadata: validJSON(row.Metadata),
			LogicalSize:  logicalSize(row.LogicalWidthStud, row.LogicalDepthStud, row.LogicalHeightPlate),
			OwnedByActor: row.OwnedByActor, StarredByActor: row.StarredByActor, StarCount: row.StarCount,
			TranslationMissing: row.TranslationMissing,
			CreatedAt:          row.CreatedAt.Time, UpdatedAt: row.UpdatedAt.Time,
		},
		AddedAt: row.AddedAt.Time,
	}
}

func componentFromGroupSearch(row db.SearchComponentGroupComponentsRow) Component {
	return Component{
		ID: uuidutil.String(row.ID), OwnerID: uuidutil.NullableString(row.OwnerID),
		ContentKind: row.ContentKind, ContentLocale: row.SelectedContentLocale,
		Name: row.SelectedName, Description: optionalSelected(row.SelectedDescription, row.HasDescription),
		Tags: nonNilStrings(row.SelectedTags), Category: row.Category, Status: row.Status,
		CurrentVersionID: uuidutil.NullableString(row.CurrentVersionID),
		LogicalSize:      logicalSize(row.LogicalWidthStud, row.LogicalDepthStud, row.LogicalHeightPlate),
		Metadata:         validJSON(row.Metadata), OwnedByActor: row.OwnedByActor,
		StarredByActor: row.StarredByActor, StarCount: row.StarCount,
		TranslationMissing: row.TranslationMissing, CreatedAt: row.CreatedAt.Time,
		UpdatedAt: row.UpdatedAt.Time,
	}
}

func starredComponentFromDB(row db.ListStarredComponentsRow) StarredComponent {
	return StarredComponent{
		Component: Component{
			ID: uuidutil.String(row.ID), OwnerID: uuidutil.NullableString(row.OwnerID),
			ContentKind: row.ContentKind, ContentLocale: row.SelectedContentLocale,
			Name: row.SelectedName, Description: optionalSelected(row.SelectedDescription, row.HasDescription),
			Tags: nonNilStrings(row.SelectedTags), Category: row.Category, Status: row.Status,
			CurrentVersionID: uuidutil.NullableString(row.CurrentVersionID),
			LogicalSize:      logicalSize(row.LogicalWidthStud, row.LogicalDepthStud, row.LogicalHeightPlate),
			Metadata:         validJSON(row.Metadata), OwnedByActor: row.OwnedByActor,
			StarredByActor: row.StarredByActor, StarCount: row.StarCount,
			TranslationMissing: row.TranslationMissing, CreatedAt: row.CreatedAt.Time,
			UpdatedAt: row.UpdatedAt.Time,
		},
		StarredAt: row.StarredAt.Time,
	}
}

func logicalSize(width, depth, height pgtype.Numeric) *LogicalSize {
	if !width.Valid || !depth.Valid || !height.Valid {
		return nil
	}
	w, wErr := width.Float64Value()
	d, dErr := depth.Float64Value()
	h, hErr := height.Float64Value()
	if wErr != nil || dErr != nil || hErr != nil || !w.Valid || !d.Valid || !h.Valid {
		return nil
	}
	return &LogicalSize{WidthStud: w.Float64, DepthStud: d.Float64, HeightPlate: h.Float64}
}

func validJSON(value []byte) json.RawMessage {
	if !json.Valid(value) {
		return json.RawMessage(`{}`)
	}
	return json.RawMessage(value)
}

func nullableTime(value pgtype.Timestamptz) *time.Time {
	if !value.Valid {
		return nil
	}
	result := value.Time
	return &result
}

func optionalSelected(value string, present bool) *string {
	if !present {
		return nil
	}
	return &value
}
