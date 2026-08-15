//go:build integration

package workbench

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	db "github.com/ctbzbricks/brickbuilder/backend-go/db/generated"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/component"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/storage"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

func TestG7WorkbenchContract(t *testing.T) {
	databaseURL := os.Getenv("TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("TEST_DATABASE_URL is required")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	seedWorkbench(t, ctx, pool)
	owner := testUUID(t, "77000000-0000-0000-0000-000000000002")
	other := testUUID(t, "77000000-0000-0000-0000-000000000099")
	store := newWorkbenchStore()
	service := NewService(pool, store, time.Minute)

	accepted, err := service.DetectRelations(ctx, owner, fixtureCandidateID)
	if err != nil || accepted.Status != task.StatusQueued {
		t.Fatalf("detect task = %+v error=%v", accepted, err)
	}
	if _, err := service.DetectRelations(ctx, other, fixtureCandidateID); publicCode(err) != "component_repo.candidate_id_not_found" {
		t.Fatalf("cross-owner detect = %v", err)
	}
	duplicateDetection, err := service.DetectRelations(ctx, owner, fixtureCandidateID)
	if err != nil || duplicateDetection.TaskID != accepted.TaskID {
		t.Fatalf("active relation execution was not reused: %+v error=%v", duplicateDetection, err)
	}
	queue := task.NewService(pool)
	claimedDetection, ok, err := queue.Claim(ctx, "g7-relations", []string{RelationDetectionType}, time.Minute)
	if err != nil || !ok || uuidutil.String(claimedDetection.ID) != accepted.TaskID {
		t.Fatalf("claim relation detection: %+v found=%v error=%v", claimedDetection, ok, err)
	}
	if err := queue.FinishFailure(ctx, "g7-relations", claimedDetection, &task.Failure{
		Code: "component_repo.relation_detect_failed", Params: map[string]any{}, Retryable: false,
	}, time.Second); err != nil {
		t.Fatalf("fail relation detection: %v", err)
	}
	rerunDetection, err := service.DetectRelations(ctx, owner, fixtureCandidateID)
	if err != nil || rerunDetection.TaskID == accepted.TaskID {
		t.Fatalf("failed relation execution was not replaced: %+v error=%v", rerunDetection, err)
	}
	firstDetection, err := queue.GetOwned(ctx, owner, uuidutil.String(claimedDetection.ID))
	if err != nil {
		t.Fatal(err)
	}
	secondDetection, err := queue.GetOwned(ctx, owner, rerunDetection.TaskID)
	if err != nil || firstDetection.TaskJobID != secondDetection.TaskJobID || secondDetection.ExecutionNumber != 2 {
		t.Fatalf("relation executions do not share a logical job: first=%+v second=%+v error=%v", firstDetection, secondDetection, err)
	}
	if _, err := queue.Cancel(ctx, owner, rerunDetection.TaskID); err != nil {
		t.Fatalf("cancel relation rerun fixture: %v", err)
	}

	var before, after []byte
	if err := pool.QueryRow(ctx, `SELECT document FROM component_repo.scene_snapshots WHERE id=$1`, fixtureSnapshotID).Scan(&before); err != nil {
		t.Fatal(err)
	}
	confirmed, err := service.ConfirmRelation(ctx, owner, fixtureCandidateID, fixtureRelationOneID)
	if err != nil || confirmed.RelationCandidateID != fixtureRelationOneID {
		t.Fatalf("confirm = %+v error=%v", confirmed, err)
	}
	if err := pool.QueryRow(ctx, `SELECT document FROM component_repo.scene_snapshots WHERE id=$1`, fixtureSnapshotID).Scan(&after); err != nil || !bytes.Equal(before, after) {
		t.Fatalf("relation confirmation changed immutable snapshot transform")
	}
	if _, err := service.ConfirmRelation(ctx, owner, fixtureCandidateID, fixtureRelationTwoID); publicCode(err) != "component_repo.connector_capacity_exceeded" {
		t.Fatalf("capacity error = %v", err)
	}
	if _, err := pool.Exec(ctx, `INSERT INTO component_repo.relation_candidates (id,component_candidate_id,owner_id,part_library_version_id,endpoint_a,endpoint_b,connection_type,joint_type,position_residual,rotation_residual,verified_by_tolerance,confidence,detection_method) VALUES ('77000000-0000-0000-0000-000000000049',$1,$2,$3,'{"worldConnectorId":"c"}','{"worldConnectorId":"a"}','duplicate','fixed',0,0,true,1,'automatic')`, testUUID(t, fixtureCandidateID), owner, testUUID(t, fixturePartLibraryID)); databaseCode(err) != "23505" {
		t.Fatalf("reversed endpoint pair accepted: %v", err)
	}

	connectors, err := service.ListConnectors(ctx, owner, fixtureCandidateID)
	if err != nil || len(connectors) != 3 {
		t.Fatalf("connectors = %+v error=%v", connectors, err)
	}
	interfaces, err := service.ListInterfaces(ctx, owner, fixtureCandidateID)
	if err != nil || len(interfaces) != 1 || interfaces[0].WorldConnectorID != "c" {
		t.Fatalf("free interfaces = %+v error=%v", interfaces, err)
	}
	componentService := component.NewService(pool)
	if _, err := componentService.PublishVersion(ctx, owner, fixtureVersionID); publicCode(err) != "component_repo.publish_validation_failed" {
		t.Fatalf("publish without validation was not blocked: %v", err)
	}
	validationInput, err := db.New(pool).GetValidationTaskInput(ctx, db.GetValidationTaskInputParams{
		CandidateID: testUUID(t, fixtureCandidateID), OwnerID: owner, VersionID: testUUID(t, fixtureVersionID),
	})
	if err != nil || validationInput.UnresolvedPartCount != 0 || validationInput.InvalidRelationCount != 0 ||
		validationInput.InvalidInterfaceCount != 0 || validationInput.ValidExternalInterfaceCount != 1 {
		t.Fatalf("validation domain facts = %+v error=%v", validationInput, err)
	}

	validation, err := service.Validate(ctx, owner, fixtureCandidateID)
	if err != nil {
		t.Fatalf("enqueue validation: %v", err)
	}
	duplicateValidation, err := service.Validate(ctx, owner, fixtureCandidateID)
	if err != nil || duplicateValidation.TaskID != validation.TaskID {
		t.Fatalf("active validation execution was not reused: %+v error=%v", duplicateValidation, err)
	}
	claimedValidation, ok, err := queue.Claim(ctx, "g7-validation", []string{ValidationType}, time.Minute)
	if err != nil || !ok || uuidutil.String(claimedValidation.ID) != validation.TaskID {
		t.Fatalf("claim validation: %+v %v", claimedValidation, err)
	}
	validationResult, err := NewValidationTaskHandler(pool).Handle(ctx, claimedValidation)
	if err != nil {
		t.Fatalf("validate handler: %v", err)
	}
	if err := queue.Complete(ctx, "g7-validation", claimedValidation, validationResult); err != nil {
		t.Fatalf("complete validation: %v", err)
	}
	reusedValidation, err := service.Validate(ctx, owner, fixtureCandidateID)
	if err != nil || reusedValidation.TaskID != validation.TaskID || reusedValidation.Status != task.StatusSucceeded {
		t.Fatalf("successful validation execution was not reused: %+v error=%v", reusedValidation, err)
	}
	published, err := componentService.PublishVersion(ctx, owner, fixtureVersionID)
	if err != nil || published.Status != "published" {
		t.Fatalf("publish after validation = %+v error=%v", published, err)
	}

	parts, err := service.GetVersionParts(ctx, owner, fixtureVersionID, "zh-CN")
	if err != nil || len(parts.Items) != 3 || parts.Items[0].TranslationStatus != "reviewed" {
		t.Fatalf("localized BOM = %+v error=%v", parts, err)
	}

	initialPreview, err := service.GetPreview(ctx, owner, "owner-jwt", fixtureVersionID)
	if err != nil || initialPreview.Status != "pending" || store.putCount != 0 {
		t.Fatalf("GET generated preview: %+v error=%v writes=%d", initialPreview, err, store.putCount)
	}
	previewTask, err := service.MaterializePreview(ctx, owner, "owner-jwt", fixtureVersionID)
	if err != nil {
		t.Fatalf("enqueue preview: %v", err)
	}
	claimedPreview, ok, err := queue.Claim(ctx, "g7-preview", []string{PreviewMaterializeType}, time.Minute)
	if err != nil || !ok || uuidutil.String(claimedPreview.ID) != previewTask.TaskID {
		t.Fatalf("claim preview: %+v %v", claimedPreview, err)
	}
	previewResult, err := NewPreviewTaskHandler(pool, store, "component-repo").Handle(ctx, claimedPreview)
	if err != nil {
		t.Fatalf("preview handler: %v", err)
	}
	recoveredResult, err := NewPreviewTaskHandler(pool, store, "component-repo").Handle(ctx, claimedPreview)
	if err != nil || uuidutil.String(recoveredResult.ArtifactID) != uuidutil.String(previewResult.ArtifactID) || store.putCount != 1 {
		t.Fatalf("preview crash recovery duplicated output: result=%+v error=%v writes=%d", recoveredResult, err, store.putCount)
	}
	if err := queue.Complete(ctx, "g7-preview", claimedPreview, previewResult); err != nil {
		t.Fatalf("complete preview: %v", err)
	}
	ready, err := service.GetPreview(ctx, other, "other-jwt", fixtureVersionID)
	if err != nil || ready.Status != "ready" || ready.URL == nil || ready.ArtifactID == nil {
		t.Fatalf("public signed preview = %+v error=%v", ready, err)
	}
	artifactID := *ready.ArtifactID
	store.removeOnlyObject()
	rebuild, err := service.MaterializePreview(ctx, owner, "owner-jwt", fixtureVersionID)
	if err != nil || rebuild.TaskID == previewTask.TaskID {
		t.Fatalf("cache rebuild task = %+v error=%v", rebuild, err)
	}
	firstPreview, err := queue.GetOwned(ctx, owner, previewTask.TaskID)
	if err != nil {
		t.Fatal(err)
	}
	secondPreview, err := queue.GetOwned(ctx, owner, rebuild.TaskID)
	if err != nil || firstPreview.TaskJobID != secondPreview.TaskJobID || secondPreview.ExecutionNumber != 2 {
		t.Fatalf("preview rebuild does not share a logical job: first=%+v second=%+v error=%v", firstPreview, secondPreview, err)
	}
	claimedRebuild, ok, _ := queue.Claim(ctx, "g7-preview", []string{PreviewMaterializeType}, time.Minute)
	if !ok {
		t.Fatal("rebuild not claimable")
	}
	rebuildResult, err := NewPreviewTaskHandler(pool, store, "component-repo").Handle(ctx, claimedRebuild)
	if err != nil {
		t.Fatalf("rebuild handler: %v", err)
	}
	if err := queue.Complete(ctx, "g7-preview", claimedRebuild, rebuildResult); err != nil {
		t.Fatal(err)
	}
	rebuilt, _ := service.GetPreview(ctx, owner, "owner-jwt", fixtureVersionID)
	if rebuilt.ArtifactID == nil || *rebuilt.ArtifactID != artifactID || store.putCount != 2 {
		t.Fatalf("idempotent rebuild = %+v writes=%d", rebuilt, store.putCount)
	}

	ldrawRoot := t.TempDir()
	partsRoot := filepath.Join(ldrawRoot, "parts")
	if err := os.MkdirAll(partsRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	partSource := []byte("3 16 0 0 0 20 0 0 0 10 0\n")
	if err := os.WriteFile(filepath.Join(partsRoot, "3001.dat"), partSource, 0o644); err != nil {
		t.Fatal(err)
	}
	partHash := sha256.Sum256(partSource)
	if _, err := pool.Exec(ctx, `
		INSERT INTO component_repo.part_geometries (
			part_library_version_id, ldraw_part_num, source_relative_path, source_file_hash,
			bbox_min, bbox_max, logical_width_stud, logical_depth_stud, logical_height_plate,
			vertex_count, face_count
		) VALUES ($1, '3001.dat', 'parts/3001.dat', $2,
			ARRAY[0,0,0]::float8[], ARRAY[20,10,0]::float8[], 2, 4, 3, 3, 1)`,
		testUUID(t, fixturePartLibraryID), hex.EncodeToString(partHash[:])); err != nil {
		t.Fatal(err)
	}
	activeLibrary, err := service.GetActivePartLibraryVersion(ctx)
	if err != nil || activeLibrary.ID != fixturePartLibraryID {
		t.Fatalf("active Part library = %+v error=%v", activeLibrary, err)
	}
	initialPart, err := service.GetPartPreview(ctx, fixturePartLibraryID, "3001.dat", "zh-CN")
	if err != nil || initialPart.Status != "pending" || initialPart.TranslationStatus != "reviewed" || initialPart.Model != nil {
		t.Fatalf("initial Part preview = %+v error=%v", initialPart, err)
	}
	partTask, err := service.MaterializePartPreview(ctx, owner, fixturePartLibraryID, "3001.dat", PartPreviewMaterializeInput{Locale: "zh-CN", Timezone: "Asia/Shanghai"})
	if err != nil {
		t.Fatalf("enqueue Part preview: %v", err)
	}
	claimedPart, ok, err := queue.Claim(ctx, "g8-part-preview", []string{PartPreviewMaterializeType}, time.Minute)
	if err != nil || !ok || uuidutil.String(claimedPart.ID) != partTask.TaskID {
		t.Fatalf("claim Part preview: %+v found=%v error=%v", claimedPart, ok, err)
	}
	partHandler, err := NewPartPreviewTaskHandler(pool, store, "component-repo", ldrawRoot)
	if err != nil {
		t.Fatal(err)
	}
	partResult, err := partHandler.Handle(ctx, claimedPart)
	if err != nil {
		t.Fatalf("materialize Part preview: %v", err)
	}
	if err := queue.Complete(ctx, "g8-part-preview", claimedPart, partResult); err != nil {
		t.Fatal(err)
	}
	readyPart, err := service.GetPartPreview(ctx, fixturePartLibraryID, "3001.dat", "zh-CN")
	if err != nil || readyPart.Status != "ready" || readyPart.Model == nil || readyPart.Model.Format != "glb" {
		t.Fatalf("ready Part preview = %+v error=%v", readyPart, err)
	}
}

const (
	fixtureCandidateID   = "77000000-0000-0000-0000-000000000009"
	fixtureSnapshotID    = "77000000-0000-0000-0000-000000000008"
	fixtureVersionID     = "77000000-0000-0000-0000-000000000010"
	fixturePartLibraryID = "77000000-0000-0000-0000-000000000020"
	fixtureRelationOneID = "77000000-0000-0000-0000-000000000040"
	fixtureRelationTwoID = "77000000-0000-0000-0000-000000000041"
)

func seedWorkbench(t *testing.T, ctx context.Context, pool *pgxpool.Pool) {
	t.Helper()
	_, err := pool.Exec(ctx, `
		TRUNCATE component_repo.components, component_repo.upload_sessions, component_repo.artifacts,
		         component_repo.part_library_versions, component_repo.tasks, component_repo.outbox_events
		RESTART IDENTITY CASCADE;
		INSERT INTO component_repo.components (id,owner_id,content_kind,content_locale,name,created_by)
		VALUES ('77000000-0000-0000-0000-000000000001','77000000-0000-0000-0000-000000000002','user','zh-CN','结构件','77000000-0000-0000-0000-000000000002');
		INSERT INTO component_repo.part_library_versions (id,source_name,source_hash,connector_count,status,created_by)
		VALUES ('77000000-0000-0000-0000-000000000020','fixture',repeat('a',64),3,'active','77000000-0000-0000-0000-000000000002');
		INSERT INTO component_repo.parts (part_library_version_id,ldraw_part_num,source_name,content_locale) VALUES
		('77000000-0000-0000-0000-000000000020','3001.dat','Brick 2 x 4','en-US'),
		('77000000-0000-0000-0000-000000000020','3002.dat','Brick 2 x 3','en-US'),
		('77000000-0000-0000-0000-000000000020','3003.dat','Brick 2 x 2','en-US');
		INSERT INTO component_repo.part_translations (part_library_version_id,ldraw_part_num,locale,name,translation_status,reviewed_by,reviewed_at)
		VALUES ('77000000-0000-0000-0000-000000000020','3001.dat','zh-CN','2×4 砖','reviewed','77000000-0000-0000-0000-000000000002',now());
		INSERT INTO component_repo.part_connector_definitions (part_library_version_id,source_connector_id,ldraw_part_num,connector_kind,normalized_connector_type,connector_gender,position,orientation,direction)
		VALUES
		('77000000-0000-0000-0000-000000000020',1,'3001.dat','stud','stud','M',ARRAY[0,0,0]::float8[],ARRAY[1,0,0,0,1,0,0,0,1]::float8[],ARRAY[0,1,0]::float8[]),
		('77000000-0000-0000-0000-000000000020',2,'3002.dat','tube','anti_stud','F',ARRAY[0,0,0]::float8[],ARRAY[1,0,0,0,1,0,0,0,1]::float8[],ARRAY[0,-1,0]::float8[]),
		('77000000-0000-0000-0000-000000000020',3,'3003.dat','tube','anti_stud','F',ARRAY[0,0,0]::float8[],ARRAY[1,0,0,0,1,0,0,0,1]::float8[],ARRAY[0,-1,0]::float8[]);
		INSERT INTO component_repo.upload_sessions (id,owner_id,status,target_component_id,locale,timezone,created_by,expires_at,completed_at)
		VALUES ('77000000-0000-0000-0000-000000000003','77000000-0000-0000-0000-000000000002','completed','77000000-0000-0000-0000-000000000001','zh-CN','Asia/Shanghai','77000000-0000-0000-0000-000000000002',now()+interval '1 hour',now());
		INSERT INTO component_repo.artifacts (id,owner_id,artifact_type,source_kind,original_filename,storage_provider,storage_bucket,storage_key,sha256,file_size,mime_type,verification_status,verified_at,uploaded_by)
		VALUES ('77000000-0000-0000-0000-000000000004','77000000-0000-0000-0000-000000000002','ldraw_ldr','source','fixture.ldr','test','test','fixture.ldr',repeat('0',64),1,'text/plain','verified',now(),'77000000-0000-0000-0000-000000000002');
		INSERT INTO component_repo.tasks (id,owner_id,task_type,payload,locale,timezone,created_by) VALUES
		('77000000-0000-0000-0000-000000000005','77000000-0000-0000-0000-000000000002','component.artifact.verify','{"artifactId":"77000000-0000-0000-0000-000000000004"}','zh-CN','Asia/Shanghai','77000000-0000-0000-0000-000000000002'),
		('77000000-0000-0000-0000-000000000006','77000000-0000-0000-0000-000000000002','component.import.parse','{"importId":"77000000-0000-0000-0000-000000000007","parserVersion":"fixture-parser","snapshotSchema":"fixture-schema"}','zh-CN','Asia/Shanghai','77000000-0000-0000-0000-000000000002');
		INSERT INTO component_repo.task_dependencies (task_id,prerequisite_task_id,owner_id) VALUES ('77000000-0000-0000-0000-000000000006','77000000-0000-0000-0000-000000000005','77000000-0000-0000-0000-000000000002');
		INSERT INTO component_repo.imports (id,owner_id,source_artifact_id,target_component_id,status,parser_version,part_library_version_id,locale,timezone,created_by,upload_session_id,parse_task_id)
		VALUES ('77000000-0000-0000-0000-000000000007','77000000-0000-0000-0000-000000000002','77000000-0000-0000-0000-000000000004','77000000-0000-0000-0000-000000000001','succeeded','fixture-parser','77000000-0000-0000-0000-000000000020','zh-CN','Asia/Shanghai','77000000-0000-0000-0000-000000000002','77000000-0000-0000-0000-000000000003','77000000-0000-0000-0000-000000000006');
		INSERT INTO component_repo.scene_snapshots (id,import_id,schema_version,parser_version,root_model_id,document,bom,parse_issues)
		VALUES ('77000000-0000-0000-0000-000000000008','77000000-0000-0000-0000-000000000007','fixture-schema','fixture-parser','root',
		'{"rootModelId":"root","models":[{"modelId":"root","references":[{"instanceId":"p1","referenceName":"3001.dat","referenceKind":"part","targetModelId":null,"transform":{"position":{"x":0,"y":0,"z":0},"matrix":[1,0,0,0,1,0,0,0,1]}},{"instanceId":"p2","referenceName":"3002.dat","referenceKind":"part","targetModelId":null,"transform":{"position":{"x":0,"y":0,"z":0},"matrix":[1,0,0,0,1,0,0,0,1]}},{"instanceId":"p3","referenceName":"3003.dat","referenceKind":"part","targetModelId":null,"transform":{"position":{"x":20,"y":0,"z":0},"matrix":[1,0,0,0,1,0,0,0,1]}}]}]}',
		'{"3001.dat":1,"3002.dat":1,"3003.dat":1}','[]');
		INSERT INTO component_repo.candidates (id,owner_id,import_id,scene_snapshot_id,summary,interface_signature,structure_hash,geometry_hash)
		VALUES ('77000000-0000-0000-0000-000000000009','77000000-0000-0000-0000-000000000002','77000000-0000-0000-0000-000000000007','77000000-0000-0000-0000-000000000008','{"partInstanceCount":3}',repeat('1',64),repeat('2',64),repeat('3',64));
		INSERT INTO component_repo.component_versions (id,component_id,component_candidate_id,version_label,source_artifact_id,scene_snapshot_id,parser_version,part_library_version_id,interface_signature,structure_hash,geometry_hash,created_by)
		VALUES ('77000000-0000-0000-0000-000000000010','77000000-0000-0000-0000-000000000001','77000000-0000-0000-0000-000000000009','0.1.0','77000000-0000-0000-0000-000000000004','77000000-0000-0000-0000-000000000008','fixture-parser','77000000-0000-0000-0000-000000000020',repeat('1',64),repeat('2',64),repeat('3',64),'77000000-0000-0000-0000-000000000002');
		INSERT INTO component_repo.connector_analyses (component_candidate_id,owner_id,part_library_version_id,recognition_method,recognition_version)
		VALUES ('77000000-0000-0000-0000-000000000009','77000000-0000-0000-0000-000000000002','77000000-0000-0000-0000-000000000020','automatic','fixture-v1');
		INSERT INTO component_repo.connector_analysis_items (id,component_candidate_id,owner_id,part_connector_definition_id,world_connector_id,part_instance_id,part_ref,state,position,axis,matrix,access_axis,eligibility_unoccupied,eligibility_supported_type,eligibility_outward_facing,eligibility_clearance_data_available,eligibility_clearance_available,outward_score,capacity) VALUES
		('77000000-0000-0000-0000-000000000030','77000000-0000-0000-0000-000000000009','77000000-0000-0000-0000-000000000002',1,'a','p1','3001.dat','external',ARRAY[0,0,0]::float8[],ARRAY[0,1,0]::float8[],ARRAY[1,0,0,0,1,0,0,0,1]::float8[],ARRAY[0,1,0]::float8[],true,true,true,true,true,1,1),
		('77000000-0000-0000-0000-000000000031','77000000-0000-0000-0000-000000000009','77000000-0000-0000-0000-000000000002',2,'b','p2','3002.dat','external',ARRAY[0,0,0]::float8[],ARRAY[0,-1,0]::float8[],ARRAY[1,0,0,0,1,0,0,0,1]::float8[],ARRAY[0,-1,0]::float8[],true,true,true,true,true,1,1),
		('77000000-0000-0000-0000-000000000032','77000000-0000-0000-0000-000000000009','77000000-0000-0000-0000-000000000002',3,'c','p3','3003.dat','external',ARRAY[20,0,0]::float8[],ARRAY[0,-1,0]::float8[],ARRAY[1,0,0,0,1,0,0,0,1]::float8[],ARRAY[0,-1,0]::float8[],true,true,true,true,true,1,1);
		INSERT INTO component_repo.interfaces (id,component_candidate_id,owner_id,world_connector_id,name,exposure,default_behavior,source_connector,mechanical_roles,business_roles,requirements,created_by) VALUES
		('77000000-0000-0000-0000-000000000033','77000000-0000-0000-0000-000000000009','77000000-0000-0000-0000-000000000002','a','auto:a','external','fixed','{"worldConnectorId":"a","connectorType":"stud","connectorGender":"M"}','[]','[]','{}','77000000-0000-0000-0000-000000000002'),
		('77000000-0000-0000-0000-000000000034','77000000-0000-0000-0000-000000000009','77000000-0000-0000-0000-000000000002','b','auto:b','external','fixed','{"worldConnectorId":"b","connectorType":"anti_stud","connectorGender":"F"}','[]','[]','{}','77000000-0000-0000-0000-000000000002'),
		('77000000-0000-0000-0000-000000000035','77000000-0000-0000-0000-000000000009','77000000-0000-0000-0000-000000000002','c','auto:c','external','fixed','{"worldConnectorId":"c","connectorType":"anti_stud","connectorGender":"F"}','[]','[]','{}','77000000-0000-0000-0000-000000000002');
		UPDATE component_repo.connector_analysis_items
		SET external_interface_id = CASE world_connector_id
			WHEN 'a' THEN '77000000-0000-0000-0000-000000000033'::uuid
			WHEN 'b' THEN '77000000-0000-0000-0000-000000000034'::uuid
			WHEN 'c' THEN '77000000-0000-0000-0000-000000000035'::uuid
		END
		WHERE component_candidate_id = '77000000-0000-0000-0000-000000000009';
		INSERT INTO component_repo.relation_candidates (id,component_candidate_id,owner_id,part_library_version_id,endpoint_a,endpoint_b,connection_type,joint_type,position_residual,rotation_residual,verified_by_tolerance,confidence,detection_method) VALUES
		('77000000-0000-0000-0000-000000000040','77000000-0000-0000-0000-000000000009','77000000-0000-0000-0000-000000000002','77000000-0000-0000-0000-000000000020','{"worldConnectorId":"a"}','{"worldConnectorId":"b"}','stud_tube','fixed',0,0,true,1,'automatic'),
		('77000000-0000-0000-0000-000000000041','77000000-0000-0000-0000-000000000009','77000000-0000-0000-0000-000000000002','77000000-0000-0000-0000-000000000020','{"worldConnectorId":"a"}','{"worldConnectorId":"c"}','stud_tube','fixed',0,0,true,1,'automatic');`)
	if err != nil {
		t.Fatalf("seed G7 fixture: %v", err)
	}
}

type workbenchStore struct {
	mu       sync.Mutex
	objects  map[string][]byte
	putCount int
}

func newWorkbenchStore() *workbenchStore { return &workbenchStore{objects: map[string][]byte{}} }
func (*workbenchStore) Provider() string { return "test" }
func (*workbenchStore) Bucket() string   { return "test" }
func (s *workbenchStore) Head(_ context.Context, key string) (storage.ObjectMetadata, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	value, ok := s.objects[key]
	if !ok {
		return storage.ObjectMetadata{}, storage.ErrNotFound
	}
	return storage.ObjectMetadata{Size: int64(len(value)), ContentType: "model/gltf-binary"}, nil
}
func (s *workbenchStore) HeadForUser(ctx context.Context, key, _ string) (storage.ObjectMetadata, error) {
	return s.Head(ctx, key)
}
func (s *workbenchStore) Open(_ context.Context, key string) (io.ReadCloser, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	value, ok := s.objects[key]
	if !ok {
		return nil, storage.ErrNotFound
	}
	return io.NopCloser(bytes.NewReader(value)), nil
}
func (s *workbenchStore) Put(_ context.Context, key, _ string, body io.Reader, _ int64) error {
	value, err := io.ReadAll(body)
	if err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.objects[key] = value
	s.putCount++
	return nil
}
func (s *workbenchStore) Delete(_ context.Context, key string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.objects, key)
	return nil
}
func (s *workbenchStore) SignDownload(_ context.Context, key string, _ time.Duration) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.objects[key]; !ok {
		return "", storage.ErrNotFound
	}
	return "https://storage.test/" + key, nil
}
func (s *workbenchStore) SignDownloadForUser(ctx context.Context, key string, ttl time.Duration, _ string) (string, error) {
	return s.SignDownload(ctx, key, ttl)
}
func (s *workbenchStore) removeOnlyObject() {
	s.mu.Lock()
	defer s.mu.Unlock()
	for key := range s.objects {
		delete(s.objects, key)
	}
}

func testUUID(t *testing.T, value string) pgtype.UUID {
	t.Helper()
	id, err := uuidutil.Parse(value)
	if err != nil {
		t.Fatal(err)
	}
	return id
}
func publicCode(err error) string {
	var value *apierror.Error
	if errors.As(err, &value) {
		return value.Code
	}
	return ""
}
func databaseCode(err error) string {
	if err == nil {
		return ""
	}
	if strings.Contains(err.Error(), "SQLSTATE 23505") {
		return "23505"
	}
	return ""
}
