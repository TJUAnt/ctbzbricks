package workbench

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"math"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/task"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/uuidutil"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

type RelationTaskHandler struct{ pool *pgxpool.Pool }

func NewRelationTaskHandler(pool *pgxpool.Pool) *RelationTaskHandler {
	return &RelationTaskHandler{pool: pool}
}

type relationPayload struct {
	CandidateID          string `json:"candidateId"`
	DetectionVersion     string `json:"detectionVersion"`
	PartLibraryVersionID string `json:"partLibraryVersionId"`
	InputHash            string `json:"inputHash"`
}

type relationTaskInput struct {
	candidateID, ownerID, taskID, libraryID, versionID      pgtype.UUID
	detectionVersion, structureHash, geometryHash           string
	schemaVersion, snapshotParserVersion, librarySourceHash string
	connectorSourceHash, connectorParserVersion             string
	document                                                json.RawMessage
}

type relationDefinition struct {
	id, sourceID                                 int64
	partRef, kind, normalizedType, group, gender string
	directionLabel, directionGroup               string
	position                                     [3]float64
	orientation                                  [9]float64
	direction                                    [3]float64
	radius, length                               *float64
	confidence                                   float64
}

type detectedConnector struct {
	definitionID                                                         int64
	analysisID, interfaceID                                              pgtype.UUID
	worldID, partInstanceID, partRef, connectorType, kind, gender, group string
	directionLabel, directionGroup                                       string
	position, axis                                                       [3]float64
	matrix                                                               [9]float64
	endpoint                                                             map[string]any
	clearanceData                                                        bool
}

type detectedRelation struct {
	id                                             pgtype.UUID
	endpointA, endpointB                           map[string]any
	connectionType, jointType                      string
	positionResidual, rotationResidual, confidence float64
	verified                                       bool
	metadata                                       map[string]any
}

type compatibilityRule struct {
	typeA, typeB, genderA, genderB, connectionType, jointType          string
	candidateDistance, candidateAngle, verifiedDistance, verifiedAngle float64
}

var relationCompatibility = []compatibilityRule{
	{"technic_pin", "technic_pin_hole", "M", "F", "pin_hole", "revolute", 0.8, 4, 0.4, 2},
	{"axle", "axle_hole", "M", "F", "axle_hole", "fixed", 0.6, 3, 0.3, 1.5},
	{"stud", "anti_stud", "M", "F", "stud_tube", "fixed", 1, 5, 0.5, 2},
}

func (h *RelationTaskHandler) Handle(ctx context.Context, claimed task.ClaimedTask) (task.Result, error) {
	var payload relationPayload
	if err := strictTaskPayload(claimed.Payload, &payload); err != nil || payload.DetectionVersion != RelationDetectionVersion {
		return task.Result{}, relationFailure(payload.CandidateID)
	}
	candidateID, err := uuidutil.Parse(payload.CandidateID)
	if err != nil {
		return task.Result{}, relationFailure(payload.CandidateID)
	}
	libraryID, err := uuidutil.Parse(payload.PartLibraryVersionID)
	if err != nil {
		return task.Result{}, relationFailure(payload.CandidateID)
	}
	input, definitions, colliderParts, err := h.load(ctx, claimed, candidateID)
	if errors.Is(err, pgx.ErrNoRows) {
		return task.Result{}, relationFailure(payload.CandidateID)
	}
	if err != nil {
		return task.Result{}, err
	}
	if !uuidutil.Equal(input.libraryID, libraryID) || payload.InputHash != relationInputHash(
		input.structureHash, input.geometryHash, input.schemaVersion, input.snapshotParserVersion,
		uuidutil.String(input.libraryID), input.librarySourceHash, input.connectorSourceHash,
		input.connectorParserVersion, RelationDetectionVersion,
	) {
		return task.Result{}, relationFailure(payload.CandidateID)
	}
	connectors, relations, signature, err := detectComponentRelations(input.document, input.candidateID, input.libraryID, definitions, colliderParts)
	if err != nil {
		return task.Result{}, relationFailure(payload.CandidateID)
	}
	if err := h.commit(ctx, claimed, input, connectors, relations, signature); err != nil {
		return task.Result{}, err
	}
	return task.Result{Payload: mustJSON(map[string]any{
		"candidateId": payload.CandidateID, "relationCandidateCount": len(relations),
		"connectorCount": len(connectors), "interfaceCount": len(connectors),
		"detectionVersion": RelationDetectionVersion,
	})}, nil
}

func (h *RelationTaskHandler) load(ctx context.Context, claimed task.ClaimedTask, candidateID pgtype.UUID) (relationTaskInput, []relationDefinition, map[string]bool, error) {
	var input relationTaskInput
	input.candidateID, input.ownerID = candidateID, claimed.OwnerID
	err := h.pool.QueryRow(ctx, `
		SELECT candidate.relation_detection_task_id, candidate.relation_detection_version,
		       snapshot.document, candidate.structure_hash, candidate.geometry_hash,
		       snapshot.schema_version, snapshot.parser_version,
		       import_job.part_library_version_id, version.id,
		       library.source_hash, library.connector_source_hash, library.connector_parser_version
		FROM component_repo.candidates candidate
		JOIN component_repo.scene_snapshots snapshot ON snapshot.id = candidate.scene_snapshot_id
		JOIN component_repo.imports import_job ON import_job.id = candidate.import_id AND import_job.owner_id = candidate.owner_id
		JOIN component_repo.component_versions version ON version.component_candidate_id = candidate.id AND version.deleted_at IS NULL
		JOIN component_repo.part_library_versions library ON library.id = import_job.part_library_version_id
		WHERE candidate.id = $1 AND candidate.owner_id = $2
		  AND candidate.relation_detection_task_id = $3
		  AND candidate.relation_detection_version = $4
		  AND version.status = 'draft' AND library.relation_ready = true
	`, candidateID, claimed.OwnerID, claimed.ID, RelationDetectionVersion).Scan(
		&input.taskID, &input.detectionVersion, &input.document, &input.structureHash, &input.geometryHash,
		&input.schemaVersion, &input.snapshotParserVersion, &input.libraryID, &input.versionID,
		&input.librarySourceHash, &input.connectorSourceHash, &input.connectorParserVersion,
	)
	if err != nil {
		return input, nil, nil, err
	}
	rows, err := h.pool.Query(ctx, `
		SELECT id, source_connector_id, ldraw_part_num, connector_kind, COALESCE(normalized_connector_type, ''),
		       COALESCE(connector_group, ''), COALESCE(connector_gender, ''),
		       COALESCE(direction_label, ''), COALESCE(direction_group, ''),
		       position, orientation, COALESCE(direction, ARRAY[orientation[2], orientation[5], orientation[8]]::float8[]),
		       radius, length, confidence::double precision
		FROM component_repo.part_connector_definitions
		WHERE part_library_version_id = $1
		ORDER BY ldraw_part_num, id
	`, input.libraryID)
	if err != nil {
		return input, nil, nil, err
	}
	defer rows.Close()
	definitions := []relationDefinition{}
	for rows.Next() {
		var definition relationDefinition
		var position, orientation, direction []float64
		if err := rows.Scan(&definition.id, &definition.sourceID, &definition.partRef, &definition.kind, &definition.normalizedType,
			&definition.group, &definition.gender, &definition.directionLabel, &definition.directionGroup,
			&position, &orientation, &direction,
			&definition.radius, &definition.length, &definition.confidence); err != nil {
			return input, nil, nil, err
		}
		if len(position) != 3 || len(orientation) != 9 || len(direction) != 3 {
			return input, nil, nil, errors.New("invalid connector definition vectors")
		}
		copy(definition.position[:], position)
		copy(definition.orientation[:], orientation)
		copy(definition.direction[:], direction)
		definition.partRef = strings.ToLower(definition.partRef)
		definitions = append(definitions, definition)
	}
	if err := rows.Err(); err != nil {
		return input, nil, nil, err
	}
	colliderRows, err := h.pool.Query(ctx, `SELECT DISTINCT ldraw_part_num FROM component_repo.part_collider_definitions WHERE part_library_version_id = $1`, input.libraryID)
	if err != nil {
		return input, nil, nil, err
	}
	defer colliderRows.Close()
	colliderParts := map[string]bool{}
	for colliderRows.Next() {
		var part string
		if err := colliderRows.Scan(&part); err != nil {
			return input, nil, nil, err
		}
		colliderParts[strings.ToLower(part)] = true
	}
	return input, definitions, colliderParts, colliderRows.Err()
}

func detectComponentRelations(document json.RawMessage, candidateID, libraryID pgtype.UUID, definitions []relationDefinition, colliderParts map[string]bool) ([]detectedConnector, []detectedRelation, string, error) {
	parts, err := collectComponentWorldParts(document)
	if err != nil {
		return nil, nil, "", err
	}
	byPart := map[string][]relationDefinition{}
	for _, definition := range definitions {
		byPart[definition.partRef] = append(byPart[definition.partRef], definition)
	}
	connectors := []detectedConnector{}
	for _, part := range parts {
		worldRotation := [9]float64{part.matrix[0], part.matrix[4], part.matrix[8], part.matrix[1], part.matrix[5], part.matrix[9], part.matrix[2], part.matrix[6], part.matrix[10]}
		for _, definition := range byPart[part.partRef] {
			position := transformComponentPoint(part.matrix, definition.position)
			matrix := multiplyMatrix3(worldRotation, definition.orientation)
			axis := normalize3(multiplyVector3(worldRotation, definition.direction))
			worldID := part.instanceID + ":" + stringInt64(definition.sourceID)
			endpoint := map[string]any{
				"worldConnectorId": worldID, "partInstanceId": part.instanceID, "partRef": part.partRef,
				"connectorId": stringInt64(definition.id), "sourceConnectorId": stringInt64(definition.sourceID),
				"partLibraryVersionId": uuidutil.String(libraryID),
				"connectorType":        nullableEndpoint(definition.normalizedType), "connectorGender": nullableEndpoint(definition.gender),
				"connectorKind": definition.kind, "connectorGroup": nullableEndpoint(definition.group),
				"directionLabel": nullableEndpoint(definition.directionLabel), "directionGroup": nullableEndpoint(definition.directionGroup),
				"position": vectorObject(position), "axis": vectorObject(axis), "matrix": matrix[:],
				"metadata": map[string]any{"radius": definition.radius, "length": definition.length, "confidence": definition.confidence},
			}
			connectors = append(connectors, detectedConnector{
				definitionID: definition.id, analysisID: deterministicUUID("relation-connector:" + uuidutil.String(candidateID) + ":" + worldID),
				interfaceID: deterministicUUID("relation-interface:" + uuidutil.String(candidateID) + ":" + worldID + ":" + RelationDetectionVersion),
				worldID:     worldID, partInstanceID: part.instanceID, partRef: part.partRef,
				connectorType: definition.normalizedType, kind: definition.kind, gender: definition.gender, group: definition.group,
				directionLabel: definition.directionLabel, directionGroup: definition.directionGroup,
				position: position, axis: axis, matrix: matrix, endpoint: endpoint, clearanceData: colliderParts[part.partRef],
			})
		}
	}
	sort.Slice(connectors, func(i, j int) bool { return connectors[i].worldID < connectors[j].worldID })
	relations := []detectedRelation{}
	for left := 0; left < len(connectors); left++ {
		for right := left + 1; right < len(connectors); right++ {
			a, b := connectors[left], connectors[right]
			if a.partInstanceID == b.partInstanceID {
				continue
			}
			rule, ok := matchCompatibility(a, b)
			if !ok {
				continue
			}
			positionResidual := distance3(a.position, b.position)
			rotationResidual := axisAngle3(a.axis, b.axis)
			if positionResidual > rule.candidateDistance || rotationResidual > rule.candidateAngle {
				continue
			}
			id := deterministicUUID("relation-candidate:" + uuidutil.String(candidateID) + ":" + a.worldID + ":" + b.worldID)
			confidence := math.Round(math.Max(0, ((1-math.Min(1, positionResidual/rule.candidateDistance))+(1-math.Min(1, rotationResidual/rule.candidateAngle)))/2)*10000) / 10000
			relations = append(relations, detectedRelation{
				id: id, endpointA: a.endpoint, endpointB: b.endpoint,
				connectionType: rule.connectionType, jointType: rule.jointType,
				positionResidual: positionResidual, rotationResidual: rotationResidual,
				verified:   positionResidual <= rule.verifiedDistance && rotationResidual <= rule.verifiedAngle,
				confidence: confidence, metadata: map[string]any{"detectorVersion": RelationDetectionVersion},
			})
		}
	}
	signaturePayload := make([]map[string]any, 0, len(connectors))
	for _, connector := range connectors {
		signaturePayload = append(signaturePayload, map[string]any{"worldConnectorId": connector.worldID, "connectorType": nullableEndpoint(connector.connectorType), "connectorGender": nullableEndpoint(connector.gender)})
	}
	signatureBytes, _ := json.Marshal(signaturePayload)
	sum := sha256.Sum256(signatureBytes)
	return connectors, relations, hex.EncodeToString(sum[:]), nil
}

func (h *RelationTaskHandler) commit(ctx context.Context, claimed task.ClaimedTask, input relationTaskInput, connectors []detectedConnector, relations []detectedRelation, signature string) error {
	tx, err := h.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	var currentTask pgtype.UUID
	if err := tx.QueryRow(ctx, `SELECT relation_detection_task_id FROM component_repo.candidates WHERE id=$1 AND owner_id=$2 FOR UPDATE`, input.candidateID, claimed.OwnerID).Scan(&currentTask); err != nil {
		return err
	}
	if !uuidutil.Equal(currentTask, claimed.ID) {
		return errors.New("stale relation task")
	}
	var exists bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM component_repo.connector_analyses WHERE component_candidate_id=$1)`, input.candidateID).Scan(&exists); err != nil {
		return err
	}
	if exists {
		return tx.Commit(ctx)
	}
	now := time.Now().UTC()
	if _, err := tx.Exec(ctx, `INSERT INTO component_repo.connector_analyses (component_candidate_id,owner_id,part_library_version_id,recognition_method,recognition_version,calculated_at) VALUES ($1,$2,$3,'automatic',$4,$5)`, input.candidateID, claimed.OwnerID, input.libraryID, RelationDetectionVersion, now); err != nil {
		return err
	}
	for _, connector := range connectors {
		defaultBehavior := "fixed"
		if connector.connectorType == "technic_pin" || connector.connectorType == "technic_pin_hole" {
			defaultBehavior = "revolute"
		}
		if _, err := tx.Exec(ctx, `
			INSERT INTO component_repo.connector_analysis_items (
				id,component_candidate_id,owner_id,part_connector_definition_id,world_connector_id,
				part_instance_id,part_ref,connector_type,connector_kind,connector_gender,direction_label,direction_group,state,
				position,axis,matrix,access_axis,external_interface_id,
				eligibility_unoccupied,eligibility_supported_type,eligibility_outward_facing,
				eligibility_clearance_data_available,eligibility_clearance_available,outward_score,capacity
			) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'external',$13,$14,$15,$14,NULL,true,true,true,$16,$16,1,1)
		`, connector.analysisID, input.candidateID, claimed.OwnerID, connector.definitionID, connector.worldID,
			connector.partInstanceID, connector.partRef, nullableStringValue(connector.connectorType), connector.kind,
			nullableStringValue(connector.gender), nullableStringValue(connector.directionLabel), nullableStringValue(connector.directionGroup),
			connector.position[:], connector.axis[:], connector.matrix[:], connector.clearanceData); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `
			INSERT INTO component_repo.interfaces (
				id,component_candidate_id,owner_id,world_connector_id,name,exposure,default_behavior,
				source_connector,mechanical_roles,business_roles,requirements,review_status,created_by,created_at,updated_at
			) VALUES ($1,$2,$3,$4,$5,'external',$6,$7,'[]','[]','{}','pending',$3,$8,$8)
		`, connector.interfaceID, input.candidateID, claimed.OwnerID, connector.worldID, "auto:"+connector.worldID, defaultBehavior, connector.endpoint, now); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `UPDATE component_repo.connector_analysis_items SET external_interface_id=$1 WHERE id=$2`, connector.interfaceID, connector.analysisID); err != nil {
			return err
		}
	}
	for _, relation := range relations {
		if _, err := tx.Exec(ctx, `
			INSERT INTO component_repo.relation_candidates (
				id,component_candidate_id,owner_id,part_library_version_id,endpoint_a,endpoint_b,
				connection_type,joint_type,position_residual,rotation_residual,verified_by_tolerance,
				confidence,status,detection_method,metadata,created_at,updated_at
			) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'pending','automatic',$13,$14,$14)
		`, relation.id, input.candidateID, claimed.OwnerID, input.libraryID, relation.endpointA, relation.endpointB,
			relation.connectionType, relation.jointType, relation.positionResidual, relation.rotationResidual,
			relation.verified, relation.confidence, relation.metadata, now); err != nil {
			return err
		}
	}
	if _, err := tx.Exec(ctx, `UPDATE component_repo.candidates SET interface_signature=$1,review_decisions=review_decisions || $2::jsonb,updated_at=$3 WHERE id=$4`, signature, string(mustJSON(map[string]any{"relationDetectionCompleted": true, "partLibraryVersionId": uuidutil.String(input.libraryID), "relationDetectionVersion": RelationDetectionVersion})), now, input.candidateID); err != nil {
		return err
	}
	if _, err := tx.Exec(ctx, `UPDATE component_repo.component_versions SET interface_signature=$1,validation_report_id=NULL WHERE id=$2 AND status='draft'`, signature, input.versionID); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

func relationInputHash(values ...string) string { return hashStrings(values...) }
func relationFailure(candidateID string) *task.Failure {
	return &task.Failure{Code: "component_repo.relation_detect_failed", Params: map[string]any{"candidateId": candidateID}, Retryable: false}
}
func nullableStringValue(value string) any {
	if value == "" {
		return nil
	}
	return value
}
func nullableEndpoint(value string) any {
	if value == "" {
		return nil
	}
	return value
}
func stringInt64(value int64) string { return strconv.FormatInt(value, 10) }
func vectorObject(value [3]float64) map[string]float64 {
	return map[string]float64{"x": value[0], "y": value[1], "z": value[2]}
}
func transformComponentPoint(matrix [16]float64, point [3]float64) [3]float64 {
	return [3]float64{matrix[0]*point[0] + matrix[4]*point[1] + matrix[8]*point[2] + matrix[12], matrix[1]*point[0] + matrix[5]*point[1] + matrix[9]*point[2] + matrix[13], matrix[2]*point[0] + matrix[6]*point[1] + matrix[10]*point[2] + matrix[14]}
}
func multiplyMatrix3(a, b [9]float64) [9]float64 {
	var result [9]float64
	for r := 0; r < 3; r++ {
		for c := 0; c < 3; c++ {
			for k := 0; k < 3; k++ {
				result[r*3+c] += a[r*3+k] * b[k*3+c]
			}
		}
	}
	return result
}
func multiplyVector3(matrix [9]float64, vector [3]float64) [3]float64 {
	return [3]float64{matrix[0]*vector[0] + matrix[1]*vector[1] + matrix[2]*vector[2], matrix[3]*vector[0] + matrix[4]*vector[1] + matrix[5]*vector[2], matrix[6]*vector[0] + matrix[7]*vector[1] + matrix[8]*vector[2]}
}
func normalize3(value [3]float64) [3]float64 {
	length := math.Sqrt(value[0]*value[0] + value[1]*value[1] + value[2]*value[2])
	if length == 0 {
		return [3]float64{0, 1, 0}
	}
	return [3]float64{value[0] / length, value[1] / length, value[2] / length}
}
func distance3(a, b [3]float64) float64 {
	return math.Sqrt((a[0]-b[0])*(a[0]-b[0]) + (a[1]-b[1])*(a[1]-b[1]) + (a[2]-b[2])*(a[2]-b[2]))
}
func axisAngle3(a, b [3]float64) float64 {
	a = normalize3(a)
	b = normalize3(b)
	dot := math.Max(-1, math.Min(1, a[0]*b[0]+a[1]*b[1]+a[2]*b[2]))
	angle := math.Acos(dot) * 180 / math.Pi
	return math.Min(angle, 180-angle)
}
func matchCompatibility(a, b detectedConnector) (compatibilityRule, bool) {
	for _, rule := range relationCompatibility {
		if a.connectorType == rule.typeA && b.connectorType == rule.typeB && a.gender == rule.genderA && b.gender == rule.genderB {
			return rule, true
		}
		if b.connectorType == rule.typeA && a.connectorType == rule.typeB && b.gender == rule.genderA && a.gender == rule.genderB {
			return rule, true
		}
	}
	return compatibilityRule{}, false
}
