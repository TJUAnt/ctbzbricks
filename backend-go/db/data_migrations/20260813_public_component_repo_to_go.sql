-- One-time development data migration from the Alembic-owned public Component
-- Repo tables to the Goose-owned component_repo schema at version 7.
--
-- Preconditions:
--   * Goose migrations 00001 through 00007 are applied.
--   * component_repo business tables are empty.
--   * legacy public tables remain available for verification and rollback.
--
-- Legacy timestamps were written as naive UTC values. User-authored content is
-- copied verbatim; locale fields are preserved or filled from their persisted
-- upload context. Machine IDs/statuses are normalized to the Go contract.

BEGIN;
SET LOCAL statement_timeout = '15min';
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.goose_db_version
        WHERE version_id = 7 AND is_applied
    ) THEN
        RAISE EXCEPTION 'component_repo must be at Goose version 7';
    END IF;
    IF EXISTS (SELECT 1 FROM component_repo.components)
       OR EXISTS (SELECT 1 FROM component_repo.artifacts)
       OR EXISTS (SELECT 1 FROM component_repo.imports)
       OR EXISTS (SELECT 1 FROM component_repo.tasks) THEN
        RAISE EXCEPTION 'component_repo target is not empty';
    END IF;
END;
$$;

CREATE TEMP TABLE legacy_context ON COMMIT DROP AS
SELECT regexp_replace(created_by, '^auth:', '')::uuid AS owner_id
FROM public.components
WHERE created_by ~ '^auth:[0-9a-f-]{36}$'
GROUP BY created_by;

DO $$
BEGIN
    IF (SELECT count(*) FROM legacy_context) <> 1 THEN
        RAISE EXCEPTION 'legacy data must have exactly one resolvable owner';
    END IF;
END;
$$;

CREATE TEMP TABLE legacy_part_libraries ON COMMIT DROP AS
SELECT id AS legacy_id, md5('legacy:part-library:' || id)::uuid AS id
FROM public.part_library_versions;

CREATE TEMP TABLE legacy_imports ON COMMIT DROP AS
SELECT i.*,
       regexp_replace(i.created_by, '^auth:', '')::uuid AS owner_id,
       COALESCE(
           NULLIF(i.metadata_json ->> 'uploadSessionId', '')::uuid,
           md5('legacy:upload-session:' || i.id)::uuid
       ) AS go_upload_session_id,
       md5('legacy:parse-task:' || i.id)::uuid AS parse_task_id,
       COALESCE(i.target_component_id, version_row.component_id) AS go_target_component_id,
       COALESCE(i.part_library_version, version_row.part_library_version_id,
                analysis.part_library_version_id) AS go_part_library_version,
       COALESCE(i.parser_version, 'component-repo-legacy-unparsed-v1') AS go_parser_version,
       COALESCE(NULLIF(i.metadata_json ->> 'contentLocale', ''), 'zh-CN') AS go_locale,
       CASE i.status
           WHEN 'parsed' THEN 'succeeded'
           WHEN 'uploaded' THEN 'queued'
           WHEN 'failed' THEN 'failed'
           ELSE 'failed'
       END AS go_status
FROM public.component_imports i
LEFT JOIN public.component_candidates candidate ON candidate.import_id = i.id
LEFT JOIN public.component_versions version_row
       ON version_row.component_candidate_id = candidate.id
LEFT JOIN public.component_connector_analyses analysis
       ON analysis.component_candidate_id = candidate.id;

CREATE TEMP TABLE legacy_artifacts ON COMMIT DROP AS
SELECT artifact.*,
       context.owner_id,
       CASE
           WHEN artifact.artifact_type = 'component_preview_glb' THEN 'derived'
           WHEN (artifact.metadata_json::jsonb) ? 'derivedFromArtifactId' THEN 'derived'
           WHEN EXISTS (
               SELECT 1 FROM public.component_imports import_row
               WHERE import_row.exchange_artifact_id = artifact.id
                 AND import_row.source_artifact_id <> artifact.id
           ) THEN 'derived'
           ELSE 'source'
       END AS source_kind,
       COALESCE(
           NULLIF(artifact.metadata_json ->> 'derivedFromArtifactId', '')::uuid,
           (SELECT import_row.source_artifact_id::uuid
            FROM public.component_imports import_row
            WHERE import_row.exchange_artifact_id = artifact.id
              AND import_row.source_artifact_id <> artifact.id
            ORDER BY import_row.created_at LIMIT 1)
       ) AS derived_from_artifact_id,
       CASE
           WHEN artifact.metadata_json #>> '{verification,status}' = 'verified' THEN 'verified'
           WHEN EXISTS (
               SELECT 1 FROM legacy_imports import_row
               WHERE import_row.go_status = 'succeeded'
                 AND artifact.id IN (import_row.source_artifact_id,
                                     import_row.exchange_artifact_id)
           ) THEN 'verified'
           ELSE 'pending'
       END AS verification_status
FROM public.component_artifacts artifact
CROSS JOIN legacy_context context;

INSERT INTO component_repo.components (
    id, owner_id, content_kind, content_locale, name, description, tags,
    category, status, current_version_id, logical_width_stud,
    logical_depth_stud, logical_height_plate, metadata, created_by,
    created_at, updated_at, deleted_at, deleted_by
)
SELECT id::uuid, regexp_replace(created_by, '^auth:', '')::uuid,
       content_kind, content_locale, name, description,
       COALESCE(ARRAY(SELECT json_array_elements_text(tags_json)), '{}'::text[]),
       category, status, NULL,
       logical_width_stud, logical_depth_stud, logical_height_plate,
       COALESCE(metadata_json, '{}'::json)::jsonb,
       regexp_replace(created_by, '^auth:', '')::uuid,
       created_at AT TIME ZONE 'UTC', updated_at AT TIME ZONE 'UTC',
       deleted_at AT TIME ZONE 'UTC',
       NULLIF(regexp_replace(COALESCE(deleted_by, ''), '^auth:', ''), '')::uuid
FROM public.components;

INSERT INTO component_repo.artifacts (
    id, owner_id, artifact_type, source_kind, original_filename,
    storage_provider, storage_bucket, storage_key, sha256, file_size,
    mime_type, immutable, verification_status, verified_at, uploaded_by,
    uploaded_at, metadata, deleted_at, derived_from_artifact_id
)
SELECT id::uuid, owner_id, artifact_type, source_kind, original_filename,
       storage_provider, storage_bucket, storage_key, sha256, file_size,
       mime_type, immutable, verification_status,
       CASE WHEN verification_status = 'verified' THEN
           COALESCE(NULLIF(metadata_json #>> '{verification,verifiedAt}', '')::timestamptz,
                    uploaded_at AT TIME ZONE 'UTC')
       END,
       owner_id, uploaded_at AT TIME ZONE 'UTC',
       COALESCE(metadata_json, '{}'::json)::jsonb, NULL,
       CASE WHEN source_kind = 'derived' THEN derived_from_artifact_id END
FROM legacy_artifacts;

INSERT INTO component_repo.part_library_versions (
    id, source_name, source_hash, connector_count, status, metadata,
    created_by, created_at
)
SELECT mapping.id, source.source_table, source.source_hash,
       source.connector_count, source.status,
       COALESCE(source.metadata_json, '{}'::json)::jsonb,
       context.owner_id, source.created_at AT TIME ZONE 'UTC'
FROM public.part_library_versions source
JOIN legacy_part_libraries mapping ON mapping.legacy_id = source.id
CROSS JOIN legacy_context context;

INSERT INTO component_repo.part_connector_definitions (
    id, part_library_version_id, source_connector_id, ldraw_part_num,
    connector_kind, normalized_connector_type, connector_group,
    connector_gender, position, orientation, direction, direction_label,
    direction_group, radius, length, caps, center_flag, slide_flag,
    confidence, raw_params, created_at
) OVERRIDING SYSTEM VALUE
SELECT definition.id, mapping.id, definition.source_connector_id,
       lower(definition.ldraw_part_num), definition.connector_kind,
       definition.normalized_connector_type, definition.connector_group,
       definition.connector_gender,
       ARRAY[definition.pos_x, definition.pos_y, definition.pos_z],
       ARRAY[definition.ori_11, definition.ori_12, definition.ori_13,
             definition.ori_21, definition.ori_22, definition.ori_23,
             definition.ori_31, definition.ori_32, definition.ori_33],
       CASE WHEN definition.direction_x IS NULL THEN NULL ELSE
           ARRAY[definition.direction_x, definition.direction_y,
                 definition.direction_z] END,
       definition.direction_label, definition.direction_group,
       definition.radius, definition.length, definition.caps,
       definition.center_flag, definition.slide_flag, definition.confidence,
       COALESCE(definition.raw_params, '{}'::json)::jsonb,
       definition.created_at AT TIME ZONE 'UTC'
FROM public.part_connector_definitions definition
JOIN legacy_part_libraries mapping
  ON mapping.legacy_id = definition.part_library_version_id;

SELECT setval(
    pg_get_serial_sequence('component_repo.part_connector_definitions', 'id'),
    COALESCE((SELECT max(id) FROM component_repo.part_connector_definitions), 1),
    true
);

INSERT INTO component_repo.parts (
    part_library_version_id, ldraw_part_num, source_name, content_locale
)
SELECT DISTINCT mapping.id, lower(definition.ldraw_part_num),
       source.source_table, 'en-US'
FROM public.part_connector_definitions definition
JOIN public.part_library_versions source
  ON source.id = definition.part_library_version_id
JOIN legacy_part_libraries mapping ON mapping.legacy_id = source.id
UNION
SELECT DISTINCT mapping.id, lower(bom_part.part_number),
       source.source_table, 'en-US'
FROM public.component_scene_snapshots snapshot
JOIN public.component_candidates candidate ON candidate.scene_snapshot_id = snapshot.id
JOIN public.component_connector_analyses analysis
  ON analysis.component_candidate_id = candidate.id
JOIN public.part_library_versions source
  ON source.id = analysis.part_library_version_id
JOIN legacy_part_libraries mapping ON mapping.legacy_id = source.id
CROSS JOIN LATERAL json_object_keys(snapshot.bom_json)
  AS bom_part(part_number);

-- Preserve all historical upload sessions. Old pending sessions are already
-- expired at migration time, so they are represented as expired, not runnable.
INSERT INTO component_repo.upload_sessions (
    id, owner_id, status, target_component_id, base_version_id, locale,
    timezone, failure_code, failure_params, metadata, created_by, created_at,
    expires_at, completed_at
)
SELECT session.id::uuid, session.owner_id::uuid,
       CASE WHEN session.status = 'pending' THEN 'expired' ELSE session.status END,
       NULLIF(session.metadata_json ->> 'targetComponentId', '')::uuid,
       NULL, COALESCE(NULLIF(session.metadata_json ->> 'contentLocale', ''), 'zh-CN'),
       'Asia/Shanghai',
       CASE WHEN session.status = 'pending'
            THEN 'component_repo.upload_session.expired'
            ELSE session.failure_code END,
       CASE WHEN session.status = 'pending'
            THEN '{}'::jsonb
            ELSE NULLIF(session.failure_params_json::jsonb, 'null'::jsonb) END,
       COALESCE(session.metadata_json, '{}'::json)::jsonb,
       regexp_replace(session.created_by, '^auth:', '')::uuid,
       session.created_at AT TIME ZONE 'UTC',
       (session.created_at + interval '24 hours') AT TIME ZONE 'UTC',
       session.completed_at AT TIME ZONE 'UTC'
FROM public.component_upload_sessions session;

-- Imports created before upload sessions were linked get a deterministic
-- synthetic session that records their actual persisted source artifact.
INSERT INTO component_repo.upload_sessions (
    id, owner_id, status, target_component_id, base_version_id, locale,
    timezone, failure_code, failure_params, metadata, created_by, created_at,
    expires_at, completed_at
)
SELECT import_row.go_upload_session_id, import_row.owner_id,
       CASE import_row.go_status
           WHEN 'succeeded' THEN 'completed'
           WHEN 'failed' THEN 'failed'
           ELSE 'expired'
       END,
       import_row.go_target_component_id::uuid,
       import_row.base_version_id::uuid, import_row.go_locale,
       'Asia/Shanghai',
       CASE WHEN import_row.go_status = 'queued'
            THEN 'component_repo.upload_session.expired'
            ELSE import_row.failure_code END,
       CASE WHEN import_row.go_status = 'queued'
            THEN '{}'::jsonb
            ELSE NULLIF(import_row.failure_params_json::jsonb, 'null'::jsonb) END,
       jsonb_build_object('legacyImportId', import_row.id),
       import_row.owner_id, import_row.created_at AT TIME ZONE 'UTC',
       (import_row.created_at + interval '24 hours') AT TIME ZONE 'UTC',
       import_row.completed_at AT TIME ZONE 'UTC'
FROM legacy_imports import_row
WHERE NOT EXISTS (
    SELECT 1 FROM public.component_upload_sessions session
    WHERE session.id::uuid = import_row.go_upload_session_id
);

INSERT INTO component_repo.upload_session_files (
    id, upload_session_id, ordinal, artifact_type, original_filename,
    expected_size, expected_sha256, storage_provider, storage_bucket,
    storage_key, artifact_id, status, created_at, completed_at
)
SELECT md5('legacy:upload-file:' || session.id || ':' || (entry.ordinality - 1))::uuid,
       session.id::uuid, (entry.ordinality - 1)::integer,
       entry.value ->> 'artifactType', entry.value ->> 'originalFilename',
       COALESCE((entry.value ->> 'fileSize')::bigint, 0),
       NULLIF(entry.value ->> 'expectedSha256', ''), 'supabase',
       entry.value ->> 'bucket', entry.value ->> 'objectPath', artifact.id::uuid,
       CASE WHEN artifact.id IS NOT NULL THEN 'verified' ELSE 'pending' END,
       session.created_at AT TIME ZONE 'UTC',
       CASE WHEN artifact.id IS NOT NULL THEN artifact.uploaded_at AT TIME ZONE 'UTC' END
FROM public.component_upload_sessions session
CROSS JOIN LATERAL json_array_elements(session.expected_uploads_json)
     WITH ORDINALITY AS entry(value, ordinality)
LEFT JOIN public.component_artifacts artifact
  ON artifact.id = entry.value ->> 'artifactId';

INSERT INTO component_repo.upload_session_files (
    id, upload_session_id, ordinal, artifact_type, original_filename,
    expected_size, expected_sha256, storage_provider, storage_bucket,
    storage_key, artifact_id, status, created_at, completed_at
)
SELECT md5('legacy:upload-file:' || import_row.go_upload_session_id::text || ':0')::uuid,
       import_row.go_upload_session_id, 0, artifact.artifact_type,
       artifact.original_filename, artifact.file_size, artifact.sha256,
       artifact.storage_provider, artifact.storage_bucket, artifact.storage_key,
       artifact.id::uuid, artifact.verification_status,
       import_row.created_at AT TIME ZONE 'UTC',
       CASE WHEN artifact.verification_status = 'verified'
            THEN artifact.uploaded_at AT TIME ZONE 'UTC' END
FROM legacy_imports import_row
JOIN legacy_artifacts artifact ON artifact.id = import_row.source_artifact_id
WHERE NOT EXISTS (
    SELECT 1 FROM public.component_upload_sessions session
    WHERE session.id::uuid = import_row.go_upload_session_id
);

CREATE TEMP TABLE legacy_task_states (
    id uuid PRIMARY KEY,
    desired_status text NOT NULL,
    error_code text,
    error_params jsonb
) ON COMMIT DROP;

INSERT INTO legacy_task_states (id, desired_status)
SELECT DISTINCT md5('legacy:verify-task:' || artifact_id)::uuid,
       CASE WHEN artifact.verification_status = 'verified' THEN 'succeeded' ELSE 'queued' END
FROM (
    SELECT source_artifact_id AS artifact_id FROM legacy_imports
    UNION SELECT exchange_artifact_id FROM legacy_imports WHERE exchange_artifact_id IS NOT NULL
) referenced
JOIN legacy_artifacts artifact ON artifact.id = referenced.artifact_id;

INSERT INTO legacy_task_states (id, desired_status, error_code, error_params)
SELECT parse_task_id, go_status, failure_code,
       NULLIF(failure_params_json::jsonb, 'null'::jsonb)
FROM legacy_imports;

INSERT INTO component_repo.tasks (
    id, owner_id, task_type, status, payload, locale, timezone, created_by,
    attempts, max_attempts, available_at, created_at, updated_at,
    task_job_id, execution_number
)
SELECT state.id, artifact.owner_id, 'component.artifact.verify', 'queued',
       jsonb_build_object('artifactId', artifact.id, 'legacyMigration', true),
       'zh-CN', 'Asia/Shanghai', artifact.owner_id, 0, 3,
       artifact.uploaded_at AT TIME ZONE 'UTC',
       artifact.uploaded_at AT TIME ZONE 'UTC',
       artifact.uploaded_at AT TIME ZONE 'UTC', NULL, NULL
FROM legacy_task_states state
JOIN legacy_artifacts artifact
  ON state.id = md5('legacy:verify-task:' || artifact.id)::uuid;

INSERT INTO component_repo.tasks (
    id, owner_id, task_type, status, payload, locale, timezone, created_by,
    attempts, max_attempts, available_at, created_at, updated_at,
    task_job_id, execution_number
)
SELECT state.id, import_row.owner_id, 'component.import.parse', 'queued',
       jsonb_build_object('importId', import_row.id,
                          'parserVersion', import_row.go_parser_version,
                          'legacyMigration', true),
       import_row.go_locale, 'Asia/Shanghai', import_row.owner_id, 0, 3,
       import_row.created_at AT TIME ZONE 'UTC',
       import_row.created_at AT TIME ZONE 'UTC',
       import_row.created_at AT TIME ZONE 'UTC', NULL, NULL
FROM legacy_task_states state
JOIN legacy_imports import_row ON import_row.parse_task_id = state.id;

INSERT INTO component_repo.task_dependencies (task_id, prerequisite_task_id, owner_id)
SELECT import_row.parse_task_id,
       md5('legacy:verify-task:' || dependency.artifact_id)::uuid,
       import_row.owner_id
FROM legacy_imports import_row
CROSS JOIN LATERAL (
    SELECT import_row.source_artifact_id AS artifact_id
    UNION SELECT import_row.exchange_artifact_id
    WHERE import_row.exchange_artifact_id IS NOT NULL
) dependency;

UPDATE component_repo.tasks task
SET status = 'running', attempts = 1, lease_owner = 'legacy-migration',
    lease_expires_at = now() + interval '15 minutes',
    started_at = task.created_at, updated_at = now()
FROM legacy_task_states state
WHERE task.id = state.id AND state.desired_status IN ('succeeded', 'failed');

UPDATE component_repo.tasks task
SET status = state.desired_status,
    result = CASE WHEN state.desired_status = 'succeeded'
                  THEN jsonb_build_object('legacyMigration', true) END,
    error_code = state.error_code,
    error_params = state.error_params,
    lease_owner = NULL, lease_expires_at = NULL,
    finished_at = now(), updated_at = now()
FROM legacy_task_states state
WHERE task.id = state.id AND state.desired_status IN ('succeeded', 'failed');

INSERT INTO component_repo.imports (
    id, owner_id, source_artifact_id, exchange_artifact_id,
    target_component_id, base_version_id, status, parser_version,
    part_library_version_id, locale, timezone, failure_code, failure_params,
    metadata, created_by, created_at, started_at, completed_at,
    upload_session_id, parse_task_id
)
SELECT import_row.id::uuid, import_row.owner_id,
       import_row.source_artifact_id::uuid, import_row.exchange_artifact_id::uuid,
       import_row.go_target_component_id::uuid, import_row.base_version_id::uuid,
       import_row.go_status, import_row.go_parser_version, mapping.id,
       import_row.go_locale, 'Asia/Shanghai', import_row.failure_code,
       NULLIF(import_row.failure_params_json::jsonb, 'null'::jsonb),
       COALESCE(import_row.metadata_json, '{}'::json)::jsonb,
       import_row.owner_id, import_row.created_at AT TIME ZONE 'UTC',
       CASE WHEN import_row.go_status <> 'queued'
            THEN import_row.created_at AT TIME ZONE 'UTC' END,
       import_row.completed_at AT TIME ZONE 'UTC',
       import_row.go_upload_session_id, import_row.parse_task_id
FROM legacy_imports import_row
LEFT JOIN legacy_part_libraries mapping
  ON mapping.legacy_id = import_row.go_part_library_version;

INSERT INTO component_repo.scene_snapshots (
    id, import_id, schema_version, parser_version, root_model_id,
    document, bom, parse_issues, created_at
)
SELECT id::uuid, import_id::uuid, schema, parser_version, root_model_id,
       document_json::jsonb, bom_json::jsonb, parse_issues_json::jsonb,
       created_at AT TIME ZONE 'UTC'
FROM public.component_scene_snapshots;

CREATE TEMP TABLE legacy_candidates ON COMMIT DROP AS
SELECT candidate.*,
       import_row.owner_id,
       COALESCE(version_row.interface_signature,
                md5('legacy:interface:' || candidate.id) || md5(candidate.id)) AS go_interface_signature,
       COALESCE(version_row.structure_hash,
                md5('legacy:structure:' || candidate.id) || md5(candidate.id)) AS go_structure_hash,
       COALESCE(version_row.geometry_hash,
                md5('legacy:geometry:' || candidate.id) || md5(candidate.id)) AS go_geometry_hash,
       CASE candidate.status
           WHEN 'pending_review' THEN 'pending_review'
           WHEN 'in_review' THEN 'accepted'
           WHEN 'published' THEN 'accepted'
           ELSE 'pending_review'
       END AS go_status
FROM public.component_candidates candidate
JOIN legacy_imports import_row ON import_row.id = candidate.import_id
LEFT JOIN public.component_versions version_row
  ON version_row.component_candidate_id = candidate.id;

INSERT INTO component_repo.candidates (
    id, owner_id, import_id, scene_snapshot_id, status, summary,
    review_decisions, created_at, updated_at, interface_signature,
    structure_hash, geometry_hash, relation_detection_task_id,
    relation_detection_version
)
SELECT id::uuid, owner_id, import_id::uuid, scene_snapshot_id::uuid,
       go_status, summary_json::jsonb, review_decisions_json::jsonb,
       created_at AT TIME ZONE 'UTC', updated_at AT TIME ZONE 'UTC',
       go_interface_signature, go_structure_hash, go_geometry_hash,
       NULL, NULL
FROM legacy_candidates;

INSERT INTO component_repo.connector_analyses (
    component_candidate_id, part_library_version_id, recognition_method,
    recognition_version, calculated_at, owner_id
)
SELECT analysis.component_candidate_id::uuid, mapping.id,
       analysis.recognition_method, analysis.recognition_version,
       analysis.calculated_at AT TIME ZONE 'UTC', candidate.owner_id
FROM public.component_connector_analyses analysis
JOIN legacy_part_libraries mapping
  ON mapping.legacy_id = analysis.part_library_version_id
JOIN legacy_candidates candidate ON candidate.id = analysis.component_candidate_id;

-- The legacy relational connector rollout persisted one stable Interface ID
-- per external Connector but did not materialize component_interfaces rows.
-- Restore those one-to-one rows from the immutable Connector facts.
INSERT INTO component_repo.interfaces (
    id, component_candidate_id, world_connector_id, name, exposure,
    default_behavior, source_connector, mechanical_roles, business_roles,
    requirements, review_status, created_by, created_at, updated_at, owner_id
)
SELECT item.external_interface_id::uuid, item.component_candidate_id::uuid,
       item.world_connector_id, item.world_connector_id, 'external', 'default',
       jsonb_build_object('worldConnectorId', item.world_connector_id,
                          'partInstanceId', item.part_instance_id,
                          'partRef', item.part_ref),
       '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, 'pending',
       candidate.owner_id, candidate.created_at AT TIME ZONE 'UTC',
       candidate.updated_at AT TIME ZONE 'UTC', candidate.owner_id
FROM public.component_connector_analysis_items item
JOIN legacy_candidates candidate ON candidate.id = item.component_candidate_id
WHERE item.external_interface_id IS NOT NULL;

INSERT INTO component_repo.connector_analysis_items (
    id, component_candidate_id, part_connector_definition_id,
    world_connector_id, part_instance_id, part_ref, connector_type,
    connector_kind, connector_gender, direction_label, direction_group,
    state, position, axis, matrix, access_axis, external_interface_id,
    eligibility_unoccupied, eligibility_supported_type,
    eligibility_outward_facing, eligibility_clearance_data_available,
    eligibility_clearance_available, outward_score, capacity, owner_id
)
SELECT item.id::uuid, item.component_candidate_id::uuid,
       item.part_connector_definition_id, item.world_connector_id,
       item.part_instance_id, item.part_ref, item.connector_type,
       item.connector_kind, item.connector_gender, item.direction_label,
       item.direction_group, item.state,
       ARRAY[item.position_x, item.position_y, item.position_z],
       ARRAY[item.axis_x, item.axis_y, item.axis_z],
       ARRAY[item.matrix_11, item.matrix_12, item.matrix_13,
             item.matrix_21, item.matrix_22, item.matrix_23,
             item.matrix_31, item.matrix_32, item.matrix_33],
       ARRAY[COALESCE(item.access_axis_x, item.axis_x),
             COALESCE(item.access_axis_y, item.axis_y),
             COALESCE(item.access_axis_z, item.axis_z)],
       item.external_interface_id::uuid,
       COALESCE(item.eligibility_unoccupied, false),
       COALESCE(item.eligibility_supported_type, false),
       COALESCE(item.eligibility_outward_facing, false),
       COALESCE(item.eligibility_clearance_data_available, false),
       COALESCE(item.eligibility_clearance_available, false),
       COALESCE(item.outward_score, 0), 1, candidate.owner_id
FROM public.component_connector_analysis_items item
JOIN legacy_candidates candidate ON candidate.id = item.component_candidate_id;

INSERT INTO component_repo.connector_analysis_path_nodes (
    analysis_item_id, ordinal, instance_id
)
SELECT analysis_item_id::uuid, ordinal, instance_id
FROM public.component_connector_analysis_path_nodes;

CREATE TEMP TABLE legacy_versions ON COMMIT DROP AS
SELECT version_row.*, candidate.owner_id,
       import_row.go_part_library_version
FROM public.component_versions version_row
JOIN legacy_candidates candidate ON candidate.id = version_row.component_candidate_id
JOIN legacy_imports import_row ON import_row.id = candidate.import_id;

-- Insert every version as draft first. Published state is restored only after
-- its migrated validation report and durable validation task exist.
INSERT INTO component_repo.component_versions (
    id, component_id, component_candidate_id, version_label, revision,
    status, source_artifact_id, exchange_artifact_id, scene_snapshot_id,
    parser_version, part_library_version_id, validation_report_id,
    interface_signature, structure_hash, geometry_hash, preview_artifact_id,
    preview_status, preview_generator_version, preview_failure_code,
    preview_failure_params, metadata, created_by, created_at, published_at,
    deleted_at, deleted_by, preview_task_id, preview_generation
)
SELECT version_row.id::uuid, version_row.component_id::uuid,
       version_row.component_candidate_id::uuid, version_row.version,
       version_row.revision, 'draft', version_row.source_artifact_id::uuid,
       version_row.exchange_artifact_id::uuid, version_row.scene_snapshot_id::uuid,
       version_row.parser_version, mapping.id, NULL,
       version_row.interface_signature, version_row.structure_hash,
       version_row.geometry_hash, version_row.preview_artifact_id::uuid,
       version_row.preview_status, version_row.preview_generator_version,
       version_row.preview_failure_code,
       NULLIF(version_row.preview_failure_params_json::jsonb, 'null'::jsonb),
       COALESCE(version_row.metadata_json, '{}'::json)::jsonb,
       version_row.owner_id, version_row.created_at AT TIME ZONE 'UTC',
       version_row.published_at AT TIME ZONE 'UTC',
       version_row.deleted_at AT TIME ZONE 'UTC',
       NULLIF(regexp_replace(COALESCE(version_row.deleted_by, ''), '^auth:', ''), '')::uuid,
       NULL, CASE WHEN version_row.preview_status = 'ready' THEN 1 ELSE 0 END
FROM legacy_versions version_row
LEFT JOIN legacy_part_libraries mapping
  ON mapping.legacy_id = version_row.go_part_library_version;

CREATE TEMP TABLE legacy_validation_tasks ON COMMIT DROP AS
SELECT report.id AS report_id,
       md5('legacy:validation-task:' || report.id)::uuid AS task_id,
       report.passed,
       candidate.owner_id,
       report.component_candidate_id::uuid AS candidate_id,
       COALESCE(report.component_version_id, inferred_version.id)::uuid AS version_id,
       report.created_at
FROM public.component_validation_reports report
JOIN legacy_candidates candidate ON candidate.id = report.component_candidate_id
LEFT JOIN LATERAL (
    SELECT version_row.id
    FROM public.component_versions version_row
    WHERE version_row.component_candidate_id = report.component_candidate_id
    ORDER BY version_row.created_at, version_row.id
    LIMIT 1
) inferred_version ON true
WHERE COALESCE(report.component_version_id, inferred_version.id) IS NOT NULL;

INSERT INTO component_repo.tasks (
    id, owner_id, task_type, status, payload, locale, timezone, created_by,
    attempts, max_attempts, available_at, created_at, updated_at,
    task_job_id, execution_number
)
SELECT task_id, owner_id, 'component.validate', 'queued',
       jsonb_build_object('candidateId', candidate_id, 'versionId', version_id,
                          'legacyMigration', true),
       'zh-CN', 'Asia/Shanghai', owner_id, 0, 3,
       created_at AT TIME ZONE 'UTC', created_at AT TIME ZONE 'UTC',
       created_at AT TIME ZONE 'UTC', NULL, NULL
FROM legacy_validation_tasks;

UPDATE component_repo.tasks task
SET status = 'running', attempts = 1, lease_owner = 'legacy-migration',
    lease_expires_at = now() + interval '15 minutes',
    started_at = task.created_at, updated_at = now()
FROM legacy_validation_tasks legacy
WHERE task.id = legacy.task_id;

UPDATE component_repo.tasks task
SET status = 'succeeded',
    result = jsonb_build_object('reportId', legacy.report_id,
                                'passed', legacy.passed,
                                'legacyMigration', true),
    lease_owner = NULL, lease_expires_at = NULL,
    finished_at = now(), updated_at = now()
FROM legacy_validation_tasks legacy
WHERE task.id = legacy.task_id;

INSERT INTO component_repo.validation_reports (
    id, component_candidate_id, component_version_id, validation_level,
    passed, checks, issues, validator_version, created_at, owner_id,
    task_id, interface_signature, structure_hash, geometry_hash
)
SELECT report.id::uuid, report.component_candidate_id::uuid,
       task.version_id, report.validation_level,
       report.passed, report.checks_json::jsonb, report.issues_json::jsonb,
       report.validator_version, report.created_at AT TIME ZONE 'UTC',
       candidate.owner_id, task.task_id, version_row.interface_signature,
       version_row.structure_hash, version_row.geometry_hash
FROM public.component_validation_reports report
JOIN legacy_candidates candidate ON candidate.id = report.component_candidate_id
JOIN legacy_validation_tasks task ON task.report_id = report.id
JOIN public.component_versions version_row ON version_row.id::uuid = task.version_id;

UPDATE component_repo.component_versions target
SET validation_report_id = source.validation_report_id::uuid
FROM public.component_versions source
WHERE target.id = source.id::uuid AND source.validation_report_id IS NOT NULL;

UPDATE component_repo.component_versions target
SET status = 'published'
FROM public.component_versions source
WHERE target.id = source.id::uuid AND source.status = 'published';

UPDATE component_repo.components target
SET current_version_id = source.current_version_id::uuid
FROM public.components source
WHERE target.id = source.id::uuid AND source.current_version_id IS NOT NULL;

INSERT INTO component_repo.component_groups (
    id, owner_id, parent_group_id, group_type, name, normalized_name,
    content_locale, sort_order, created_at, updated_at
)
SELECT id::uuid, owner_id::uuid, parent_group_id::uuid, group_type, name,
       normalized_name, content_locale, sort_order,
       created_at AT TIME ZONE 'UTC', updated_at AT TIME ZONE 'UTC'
FROM public.component_groups
ORDER BY CASE WHEN parent_group_id IS NULL THEN 0 ELSE 1 END, sort_order;

INSERT INTO component_repo.component_group_memberships (
    owner_id, group_id, component_id, added_by, added_at
)
SELECT group_row.owner_id::uuid, membership.group_id::uuid,
       membership.component_id::uuid,
       regexp_replace(membership.added_by, '^auth:', '')::uuid,
       membership.added_at AT TIME ZONE 'UTC'
FROM public.component_group_memberships membership
JOIN public.component_groups group_row ON group_row.id = membership.group_id;

DO $$
DECLARE
    migrated_reports bigint;
BEGIN
    IF (SELECT count(*) FROM component_repo.components)
       <> (SELECT count(*) FROM public.components) THEN
        RAISE EXCEPTION 'component count mismatch';
    END IF;
    IF (SELECT count(*) FROM component_repo.artifacts)
       <> (SELECT count(*) FROM public.component_artifacts) THEN
        RAISE EXCEPTION 'artifact count mismatch';
    END IF;
    IF (SELECT count(*) FROM component_repo.imports)
       <> (SELECT count(*) FROM public.component_imports) THEN
        RAISE EXCEPTION 'import count mismatch';
    END IF;
    IF (SELECT count(*) FROM component_repo.candidates)
       <> (SELECT count(*) FROM public.component_candidates) THEN
        RAISE EXCEPTION 'candidate count mismatch';
    END IF;
    IF (SELECT count(*) FROM component_repo.component_versions)
       <> (SELECT count(*) FROM public.component_versions) THEN
        RAISE EXCEPTION 'version count mismatch';
    END IF;
    IF (SELECT count(*) FROM component_repo.connector_analysis_items)
       <> (SELECT count(*) FROM public.component_connector_analysis_items) THEN
        RAISE EXCEPTION 'connector item count mismatch';
    END IF;
    IF (SELECT count(*) FROM component_repo.component_groups)
       <> (SELECT count(*) FROM public.component_groups) THEN
        RAISE EXCEPTION 'group count mismatch';
    END IF;
    SELECT count(*) INTO migrated_reports
    FROM public.component_validation_reports report
    WHERE report.component_version_id IS NOT NULL
       OR EXISTS (
           SELECT 1 FROM public.component_versions version_row
           WHERE version_row.component_candidate_id = report.component_candidate_id
       );
    IF (SELECT count(*) FROM component_repo.validation_reports) <> migrated_reports THEN
        RAISE EXCEPTION 'validation report count mismatch';
    END IF;
END;
$$;

COMMIT;
