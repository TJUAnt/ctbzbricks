-- name: GetOwnedCandidateWorkbench :one
SELECT candidate.id, candidate.owner_id, candidate.status,
       candidate.interface_signature, candidate.structure_hash, candidate.geometry_hash,
       candidate.relation_detection_task_id, candidate.relation_detection_version,
       snapshot.schema_version, snapshot.parser_version AS snapshot_parser_version,
       import_job.part_library_version_id, part_library.source_hash AS part_library_source_hash,
       import_job.locale, import_job.timezone,
       version.id AS draft_version_id, version.status AS draft_version_status
FROM component_repo.candidates candidate
JOIN component_repo.imports import_job
  ON import_job.id = candidate.import_id
 AND import_job.owner_id = candidate.owner_id
JOIN component_repo.scene_snapshots snapshot ON snapshot.id = candidate.scene_snapshot_id
LEFT JOIN component_repo.part_library_versions part_library
  ON part_library.id = import_job.part_library_version_id
LEFT JOIN component_repo.component_versions version
  ON version.component_candidate_id = candidate.id
 AND version.deleted_at IS NULL
WHERE candidate.id = sqlc.arg(candidate_id)
  AND candidate.owner_id = sqlc.arg(actor_id);

-- name: SetCandidateRelationDetectionTask :exec
UPDATE component_repo.candidates
SET relation_detection_task_id = sqlc.arg(task_id),
    relation_detection_version = sqlc.arg(detection_version),
    updated_at = now()
WHERE id = sqlc.arg(candidate_id)
  AND owner_id = sqlc.arg(actor_id)
  AND status IN ('pending_review', 'accepted');

-- name: ListOwnedRelationCandidates :many
SELECT relation.id, relation.component_candidate_id, relation.part_library_version_id,
       relation.endpoint_a, relation.endpoint_b, relation.connection_type,
       relation.joint_type, relation.position_residual, relation.rotation_residual,
       relation.verified_by_tolerance, relation.confidence, relation.status,
       relation.detection_method, relation.metadata, relation.created_at, relation.updated_at
FROM component_repo.relation_candidates relation
WHERE relation.component_candidate_id = sqlc.arg(candidate_id)
  AND relation.owner_id = sqlc.arg(actor_id)
ORDER BY relation.created_at, relation.id;

-- name: LockOwnedRelationCandidate :one
SELECT relation.id, relation.component_candidate_id, relation.owner_id,
       relation.endpoint_a, relation.endpoint_b, relation.connection_type,
       relation.joint_type, relation.position_residual, relation.rotation_residual,
       relation.verified_by_tolerance, relation.status
FROM component_repo.relation_candidates relation
JOIN component_repo.candidates candidate ON candidate.id = relation.component_candidate_id
LEFT JOIN component_repo.component_versions version
  ON version.component_candidate_id = candidate.id
 AND version.deleted_at IS NULL
WHERE relation.id = sqlc.arg(relation_id)
  AND relation.component_candidate_id = sqlc.arg(candidate_id)
  AND relation.owner_id = sqlc.arg(actor_id)
  AND candidate.status IN ('pending_review', 'accepted')
  AND COALESCE(version.status, 'draft') = 'draft'
FOR UPDATE OF relation, candidate;

-- name: GetAssemblyRelationBySource :one
SELECT id, component_candidate_id, owner_id, relation_candidate_id,
       endpoint_a, endpoint_b, connection_type, joint_type, placement,
       confirmed_by, confirmed_at
FROM component_repo.assembly_relations
WHERE relation_candidate_id = sqlc.arg(relation_candidate_id);

-- name: CreateAssemblyRelation :one
INSERT INTO component_repo.assembly_relations (
    id, component_candidate_id, owner_id, relation_candidate_id,
    endpoint_a, endpoint_b, connection_type, joint_type, placement,
    confirmed_by
) VALUES (
    sqlc.arg(id), sqlc.arg(component_candidate_id), sqlc.arg(owner_id),
    sqlc.arg(relation_candidate_id), sqlc.arg(endpoint_a), sqlc.arg(endpoint_b),
    sqlc.arg(connection_type), sqlc.arg(joint_type), sqlc.arg(placement),
    sqlc.arg(confirmed_by)
)
RETURNING id, component_candidate_id, owner_id, relation_candidate_id,
          endpoint_a, endpoint_b, connection_type, joint_type, placement,
          confirmed_by, confirmed_at;

-- name: RejectOwnedRelationCandidate :one
UPDATE component_repo.relation_candidates relation
SET status = 'rejected', updated_at = now()
WHERE relation.id = sqlc.arg(relation_id)
  AND relation.component_candidate_id = sqlc.arg(candidate_id)
  AND relation.owner_id = sqlc.arg(actor_id)
  AND relation.status = 'pending'
  AND NOT EXISTS (
      SELECT 1 FROM component_repo.assembly_relations assembly
      WHERE assembly.relation_candidate_id = relation.id
  )
RETURNING relation.id, relation.component_candidate_id, relation.part_library_version_id,
          relation.endpoint_a, relation.endpoint_b, relation.connection_type,
          relation.joint_type, relation.position_residual, relation.rotation_residual,
          relation.verified_by_tolerance, relation.confidence, relation.status,
          relation.detection_method, relation.metadata, relation.created_at, relation.updated_at;

-- name: MarkConfirmedConnectorsInternal :exec
UPDATE component_repo.connector_analysis_items
SET state = 'internal', external_interface_id = NULL,
    eligibility_unoccupied = false
WHERE component_candidate_id = sqlc.arg(candidate_id)
  AND owner_id = sqlc.arg(actor_id)
  AND world_connector_id = ANY(sqlc.arg(world_connector_ids)::text[]);

-- name: DeleteConfirmedConnectorInterfaces :exec
DELETE FROM component_repo.interfaces
WHERE component_candidate_id = sqlc.arg(candidate_id)
  AND owner_id = sqlc.arg(actor_id)
  AND world_connector_id = ANY(sqlc.arg(world_connector_ids)::text[]);

-- name: ListOwnedCandidateInterfaces :many
SELECT interface_row.id, interface_row.component_candidate_id,
       interface_row.world_connector_id, interface_row.name,
       interface_row.exposure, interface_row.default_behavior,
       interface_row.source_connector, interface_row.mechanical_roles,
       interface_row.business_roles, interface_row.requirements,
       interface_row.review_status, interface_row.created_by,
       interface_row.created_at, interface_row.updated_at
FROM component_repo.interfaces interface_row
WHERE interface_row.component_candidate_id = sqlc.arg(candidate_id)
  AND interface_row.owner_id = sqlc.arg(actor_id)
ORDER BY interface_row.world_connector_id, interface_row.id;

-- name: ListOwnedCandidateConnectors :many
SELECT item.id, item.world_connector_id, item.part_instance_id, item.part_ref,
       item.connector_type, item.connector_kind, item.connector_gender,
       item.direction_label, item.direction_group, item.state,
       item.position, item.axis, item.matrix, item.access_axis,
       item.external_interface_id, item.eligibility_unoccupied,
       item.eligibility_supported_type, item.eligibility_outward_facing,
       item.eligibility_clearance_data_available, item.eligibility_clearance_available,
       item.outward_score, item.capacity,
       count(occupancy.assembly_relation_id)::integer AS occupied_slots
FROM component_repo.connector_analysis_items item
LEFT JOIN component_repo.assembly_relation_connector_occupancies occupancy
  ON occupancy.component_candidate_id = item.component_candidate_id
 AND occupancy.world_connector_id = item.world_connector_id
WHERE item.component_candidate_id = sqlc.arg(candidate_id)
  AND item.owner_id = sqlc.arg(actor_id)
GROUP BY item.id
ORDER BY item.world_connector_id, item.id;

-- name: UpdateCandidateAndDraftInterfaceSignature :exec
WITH updated_candidate AS (
    UPDATE component_repo.candidates candidate
    SET interface_signature = sqlc.arg(interface_signature), updated_at = now()
    WHERE candidate.id = sqlc.arg(candidate_id)
      AND candidate.owner_id = sqlc.arg(actor_id)
      AND candidate.status IN ('pending_review', 'accepted')
    RETURNING candidate.id
)
UPDATE component_repo.component_versions version
SET interface_signature = sqlc.arg(interface_signature), validation_report_id = NULL
FROM updated_candidate
WHERE version.component_candidate_id = updated_candidate.id
  AND version.status = 'draft'
  AND version.deleted_at IS NULL;

-- name: GetValidationTaskInput :one
SELECT candidate.id AS candidate_id, candidate.owner_id,
       candidate.interface_signature, candidate.structure_hash, candidate.geometry_hash,
       candidate.summary, snapshot.document, snapshot.bom, snapshot.parse_issues,
       import_job.source_artifact_id, source_artifact.artifact_type AS source_artifact_type,
       source_artifact.sha256 AS source_sha256,
       source_artifact.verification_status AS source_verification_status,
       import_job.exchange_artifact_id, exchange_artifact.verification_status AS exchange_verification_status,
       version.id AS version_id, version.status AS version_status,
       version.part_library_version_id = import_job.part_library_version_id AS part_library_consistent,
       part_library.source_hash AS part_library_source_hash,
       (SELECT count(*)::integer
        FROM jsonb_object_keys(snapshot.bom) requested(ldraw_part_num)
        LEFT JOIN component_repo.parts part
          ON part.part_library_version_id = version.part_library_version_id
         AND part.ldraw_part_num = lower(requested.ldraw_part_num)
        WHERE part.ldraw_part_num IS NULL) AS unresolved_part_count,
       (SELECT count(*)::integer FROM component_repo.interfaces interface_row
        WHERE interface_row.component_candidate_id = candidate.id
          AND interface_row.review_status <> 'rejected'
          AND EXISTS (
              SELECT 1
              FROM component_repo.connector_analysis_items item
              WHERE item.component_candidate_id = candidate.id
                AND item.world_connector_id = interface_row.world_connector_id
                AND item.state = 'external'
                AND item.external_interface_id = interface_row.id
                AND NOT EXISTS (
                    SELECT 1
                    FROM component_repo.assembly_relation_connector_occupancies occupancy
                    WHERE occupancy.component_candidate_id = item.component_candidate_id
                      AND occupancy.world_connector_id = item.world_connector_id
                )
          )) AS valid_external_interface_count,
       ((SELECT count(*)
         FROM component_repo.interfaces interface_row
         WHERE interface_row.component_candidate_id = candidate.id
           AND interface_row.review_status <> 'rejected'
           AND NOT EXISTS (
               SELECT 1
               FROM component_repo.connector_analysis_items item
               WHERE item.component_candidate_id = candidate.id
                 AND item.world_connector_id = interface_row.world_connector_id
                 AND item.state = 'external'
                 AND item.external_interface_id = interface_row.id
                 AND NOT EXISTS (
                     SELECT 1
                     FROM component_repo.assembly_relation_connector_occupancies occupancy
                     WHERE occupancy.component_candidate_id = item.component_candidate_id
                       AND occupancy.world_connector_id = item.world_connector_id
                 )
           )) +
        (SELECT count(*)
         FROM component_repo.connector_analysis_items item
         WHERE item.component_candidate_id = candidate.id
           AND item.state = 'external'
           AND NOT EXISTS (
               SELECT 1
               FROM component_repo.interfaces interface_row
               WHERE interface_row.component_candidate_id = candidate.id
                 AND interface_row.id = item.external_interface_id
                 AND interface_row.world_connector_id = item.world_connector_id
                 AND interface_row.review_status <> 'rejected'
           )))::integer AS invalid_interface_count,
       ((SELECT count(*)
         FROM component_repo.assembly_relations relation
         WHERE relation.component_candidate_id = candidate.id
           AND (
               NOT EXISTS (
                   SELECT 1 FROM component_repo.connector_analysis_items item
                   WHERE item.component_candidate_id = candidate.id
                     AND item.world_connector_id = relation.endpoint_a_world_connector_id
               )
               OR NOT EXISTS (
                   SELECT 1 FROM component_repo.connector_analysis_items item
                   WHERE item.component_candidate_id = candidate.id
                     AND item.world_connector_id = relation.endpoint_b_world_connector_id
               )
               OR NOT EXISTS (
                   SELECT 1 FROM component_repo.assembly_relation_connector_occupancies occupancy
                   WHERE occupancy.assembly_relation_id = relation.id
                     AND occupancy.world_connector_id = relation.endpoint_a_world_connector_id
               )
               OR NOT EXISTS (
                   SELECT 1 FROM component_repo.assembly_relation_connector_occupancies occupancy
                   WHERE occupancy.assembly_relation_id = relation.id
                     AND occupancy.world_connector_id = relation.endpoint_b_world_connector_id
               )
               OR (SELECT count(*)
                   FROM component_repo.assembly_relation_connector_occupancies occupancy
                   WHERE occupancy.assembly_relation_id = relation.id) <> 2
           )) +
        (SELECT count(*)
         FROM component_repo.connector_analysis_items item
         WHERE item.component_candidate_id = candidate.id
           AND (SELECT count(*)
                FROM component_repo.assembly_relation_connector_occupancies occupancy
                WHERE occupancy.component_candidate_id = item.component_candidate_id
                  AND occupancy.world_connector_id = item.world_connector_id) > item.capacity))::integer
           AS invalid_relation_count
FROM component_repo.candidates candidate
JOIN component_repo.imports import_job
  ON import_job.id = candidate.import_id AND import_job.owner_id = candidate.owner_id
JOIN component_repo.scene_snapshots snapshot ON snapshot.id = candidate.scene_snapshot_id
JOIN component_repo.artifacts source_artifact ON source_artifact.id = import_job.source_artifact_id
LEFT JOIN component_repo.artifacts exchange_artifact ON exchange_artifact.id = import_job.exchange_artifact_id
JOIN component_repo.component_versions version
  ON version.component_candidate_id = candidate.id AND version.deleted_at IS NULL
LEFT JOIN component_repo.part_library_versions part_library
  ON part_library.id = version.part_library_version_id
WHERE candidate.id = sqlc.arg(candidate_id)
  AND candidate.owner_id = sqlc.arg(owner_id)
  AND version.id = sqlc.arg(version_id);

-- name: CreateValidationReport :one
INSERT INTO component_repo.validation_reports (
    id, component_candidate_id, component_version_id, owner_id, task_id,
    validation_level, passed, checks, issues, validator_version,
    interface_signature, structure_hash, geometry_hash
) VALUES (
    sqlc.arg(id), sqlc.arg(component_candidate_id), sqlc.arg(component_version_id),
    sqlc.arg(owner_id), sqlc.arg(task_id), sqlc.arg(validation_level),
    sqlc.arg(passed), sqlc.arg(checks), sqlc.arg(issues), sqlc.arg(validator_version),
    sqlc.arg(interface_signature), sqlc.arg(structure_hash), sqlc.arg(geometry_hash)
)
RETURNING id, component_candidate_id, component_version_id, validation_level,
          passed, checks, issues, validator_version, created_at;

-- name: GetValidationReportByTask :one
SELECT id, component_candidate_id, component_version_id, validation_level,
       passed, checks, issues, validator_version, created_at,
       interface_signature, structure_hash, geometry_hash
FROM component_repo.validation_reports
WHERE task_id = sqlc.arg(task_id)
  AND owner_id = sqlc.arg(owner_id);

-- name: GetOwnedValidationReport :one
SELECT id, component_candidate_id, component_version_id, validation_level,
       passed, checks, issues, validator_version, created_at
FROM component_repo.validation_reports
WHERE id = sqlc.arg(report_id)
  AND owner_id = sqlc.arg(owner_id);

-- name: AttachPassingValidationReport :exec
UPDATE component_repo.component_versions
SET validation_report_id = sqlc.arg(report_id)
WHERE id = sqlc.arg(version_id)
  AND component_candidate_id = sqlc.arg(candidate_id)
  AND status = 'draft'
  AND interface_signature = sqlc.arg(interface_signature)
  AND structure_hash = sqlc.arg(structure_hash)
  AND geometry_hash = sqlc.arg(geometry_hash);

-- name: GetOwnedVersionPreviewState :one
SELECT version.id, version.component_id, component.owner_id,
       version.status, version.source_artifact_id, version.scene_snapshot_id,
       version.preview_artifact_id, version.preview_status,
       version.preview_generator_version, version.preview_failure_code,
       version.preview_failure_params, version.preview_task_id,
       version.preview_generation, component.content_locale,
       version.part_library_version_id, version.structure_hash, version.geometry_hash,
       part_library.source_hash AS part_library_source_hash,
       import_job.timezone
FROM component_repo.component_versions version
JOIN component_repo.components component ON component.id = version.component_id
JOIN component_repo.candidates candidate ON candidate.id = version.component_candidate_id
JOIN component_repo.imports import_job ON import_job.id = candidate.import_id
JOIN component_repo.part_library_versions part_library ON part_library.id = version.part_library_version_id
WHERE version.id = sqlc.arg(version_id)
  AND component.owner_id = sqlc.arg(actor_id)
  AND version.deleted_at IS NULL
  AND component.deleted_at IS NULL;

-- name: LockOwnedVersionPreviewState :one
SELECT version.id, version.component_id, component.owner_id,
       version.status, version.source_artifact_id, version.scene_snapshot_id,
       version.preview_artifact_id, version.preview_status,
       version.preview_generator_version, version.preview_failure_code,
       version.preview_failure_params, version.preview_task_id,
       version.preview_generation, component.content_locale,
       version.part_library_version_id, version.structure_hash, version.geometry_hash,
       part_library.source_hash AS part_library_source_hash,
       import_job.timezone
FROM component_repo.component_versions version
JOIN component_repo.components component ON component.id = version.component_id
JOIN component_repo.candidates candidate ON candidate.id = version.component_candidate_id
JOIN component_repo.imports import_job ON import_job.id = candidate.import_id
JOIN component_repo.part_library_versions part_library ON part_library.id = version.part_library_version_id
WHERE version.id = sqlc.arg(version_id)
  AND component.owner_id = sqlc.arg(actor_id)
  AND version.deleted_at IS NULL
  AND component.deleted_at IS NULL
FOR UPDATE OF version;

-- name: SetVersionPreviewTask :exec
UPDATE component_repo.component_versions
SET preview_task_id = sqlc.arg(task_id), preview_status = 'pending',
    preview_generator_version = sqlc.arg(generator_version),
    preview_failure_code = NULL, preview_failure_params = NULL,
    preview_generation = sqlc.arg(preview_generation)
WHERE id = sqlc.arg(version_id);

-- name: GetPreviewTaskInput :one
SELECT version.id AS version_id, component.owner_id, version.source_artifact_id,
       version.scene_snapshot_id, version.preview_generation,
       version.preview_generator_version, version.preview_artifact_id,
       version.preview_status, version.part_library_version_id,
       version.structure_hash, version.geometry_hash,
       part_library.source_hash AS part_library_source_hash,
       snapshot.document
FROM component_repo.component_versions version
JOIN component_repo.components component ON component.id = version.component_id
JOIN component_repo.part_library_versions part_library ON part_library.id = version.part_library_version_id
JOIN component_repo.scene_snapshots snapshot ON snapshot.id = version.scene_snapshot_id
WHERE version.id = sqlc.arg(version_id)
  AND component.owner_id = sqlc.arg(owner_id)
  AND version.preview_task_id = sqlc.arg(task_id)
  AND version.preview_status IN ('pending', 'running', 'ready');

-- name: ListReadyPartGeometryForPreview :many
SELECT geometry.ldraw_part_num,
       geometry.source_relative_path,
       geometry.source_file_hash
FROM component_repo.part_geometries geometry
JOIN unnest(sqlc.arg(ldraw_part_nums)::text[]) requested(ldraw_part_num)
  ON geometry.ldraw_part_num = requested.ldraw_part_num
WHERE geometry.part_library_version_id = sqlc.arg(part_library_version_id)
  AND geometry.geometry_status = 'ready'
ORDER BY geometry.ldraw_part_num;

-- name: MarkVersionPreviewRunning :exec
UPDATE component_repo.component_versions
SET preview_status = 'running'
WHERE id = sqlc.arg(version_id)
  AND preview_task_id = sqlc.arg(task_id)
  AND preview_status IN ('pending', 'running');

-- name: UpsertPreviewArtifact :one
INSERT INTO component_repo.artifacts (
    id, owner_id, artifact_type, source_kind, original_filename,
    storage_provider, storage_bucket, storage_key, sha256, file_size,
    mime_type, immutable, verification_status, verified_at, uploaded_by,
    metadata, derived_from_artifact_id
) VALUES (
    sqlc.arg(id), sqlc.arg(owner_id), 'component_preview_glb', 'derived',
    sqlc.arg(original_filename), sqlc.arg(storage_provider), sqlc.arg(storage_bucket),
    sqlc.arg(storage_key), sqlc.arg(sha256), sqlc.arg(file_size), 'model/gltf-binary',
    true, 'verified', now(), sqlc.arg(uploaded_by), sqlc.arg(metadata),
    sqlc.arg(derived_from_artifact_id)
)
ON CONFLICT (id) DO UPDATE SET
    storage_key = EXCLUDED.storage_key,
    sha256 = EXCLUDED.sha256,
    file_size = EXCLUDED.file_size,
    verification_status = 'verified',
    verified_at = now(),
    metadata = EXCLUDED.metadata,
    deleted_at = NULL
RETURNING id, owner_id, artifact_type, source_kind, original_filename,
          storage_provider, storage_bucket, storage_key, sha256, file_size,
          mime_type, immutable, verification_status, verified_at, uploaded_by,
          uploaded_at, metadata, deleted_at, derived_from_artifact_id;

-- name: MarkVersionPreviewReady :exec
UPDATE component_repo.component_versions
SET preview_artifact_id = sqlc.arg(artifact_id), preview_status = 'ready',
    preview_generator_version = sqlc.arg(generator_version),
    preview_failure_code = NULL, preview_failure_params = NULL
WHERE id = sqlc.arg(version_id)
  AND preview_task_id = sqlc.arg(task_id)
  AND preview_generation = sqlc.arg(preview_generation);

-- name: MarkVersionPreviewFailed :exec
UPDATE component_repo.component_versions
SET preview_status = 'failed', preview_failure_code = sqlc.arg(failure_code),
    preview_failure_params = sqlc.arg(failure_params)
WHERE id = sqlc.arg(version_id)
  AND preview_task_id = sqlc.arg(task_id);

-- name: GetVisibleVersionPreview :one
SELECT version.id, version.preview_artifact_id, version.preview_status,
       version.preview_generator_version, version.preview_failure_code,
       version.preview_failure_params, artifact.storage_key,
       artifact.sha256, artifact.file_size
FROM component_repo.component_versions version
JOIN component_repo.components component ON component.id = version.component_id
LEFT JOIN component_repo.artifacts artifact
  ON artifact.id = version.preview_artifact_id
 AND artifact.owner_id = component.owner_id
 AND artifact.source_kind = 'derived'
 AND artifact.verification_status = 'verified'
 AND artifact.deleted_at IS NULL
WHERE version.id = sqlc.arg(version_id)
  AND version.deleted_at IS NULL
  AND component.deleted_at IS NULL
  AND (
      component.owner_id = sqlc.arg(actor_id)
      OR (component.status = 'active' AND version.status <> 'draft')
  );

-- name: GetVisibleVersionBOM :one
SELECT version.id, version.part_library_version_id, snapshot.bom
FROM component_repo.component_versions version
JOIN component_repo.components component ON component.id = version.component_id
JOIN component_repo.scene_snapshots snapshot ON snapshot.id = version.scene_snapshot_id
WHERE version.id = sqlc.arg(version_id)
  AND version.deleted_at IS NULL
  AND component.deleted_at IS NULL
  AND (
      component.owner_id = sqlc.arg(actor_id)
      OR (component.status = 'active' AND version.status <> 'draft')
  );

-- name: ListLocalizedParts :many
SELECT requested.ldraw_part_num::text AS ldraw_part_num,
       translation.name AS translated_name,
       translation.locale AS translated_locale,
       part.source_name,
       part.content_locale AS source_locale
FROM unnest(sqlc.arg(ldraw_part_nums)::text[]) requested(ldraw_part_num)
LEFT JOIN component_repo.parts part
  ON part.part_library_version_id = sqlc.arg(part_library_version_id)
 AND part.ldraw_part_num = requested.ldraw_part_num
LEFT JOIN component_repo.part_translations translation
  ON translation.part_library_version_id = part.part_library_version_id
 AND translation.ldraw_part_num = part.ldraw_part_num
 AND translation.locale = sqlc.arg(locale)
 AND translation.translation_status = 'reviewed'
ORDER BY requested.ldraw_part_num;
