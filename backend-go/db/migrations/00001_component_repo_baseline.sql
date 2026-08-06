-- +goose Up

CREATE SCHEMA component_repo;
COMMENT ON SCHEMA component_repo IS 'Go-owned Component Repo domain; migrations are managed exclusively by Goose.';

REVOKE ALL ON SCHEMA component_repo FROM PUBLIC;

CREATE TABLE component_repo.components (
    id uuid PRIMARY KEY,
    owner_id uuid,
    content_kind text NOT NULL,
    content_locale text NOT NULL,
    name text NOT NULL,
    description text,
    tags text[] NOT NULL DEFAULT '{}',
    category text,
    status text NOT NULL DEFAULT 'draft',
    current_version_id uuid,
    logical_width_stud numeric(12, 4),
    logical_depth_stud numeric(12, 4),
    logical_height_plate numeric(12, 4),
    metadata jsonb NOT NULL DEFAULT '{}',
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,
    deleted_by uuid,
    CONSTRAINT components_content_kind_check CHECK (content_kind IN ('user', 'official')),
    CONSTRAINT components_owner_check CHECK (
        (content_kind = 'user' AND owner_id IS NOT NULL)
        OR (content_kind = 'official' AND owner_id IS NULL)
    ),
    CONSTRAINT components_content_locale_check CHECK (
        content_locale <> '' AND content_locale = btrim(content_locale)
    ),
    CONSTRAINT components_status_check CHECK (status IN ('draft', 'active', 'archived')),
    CONSTRAINT components_dimensions_check CHECK (
        (logical_width_stud IS NULL OR logical_width_stud >= 0)
        AND (logical_depth_stud IS NULL OR logical_depth_stud >= 0)
        AND (logical_height_plate IS NULL OR logical_height_plate >= 0)
    ),
    CONSTRAINT components_deleted_audit_check CHECK (
        (deleted_at IS NULL AND deleted_by IS NULL)
        OR (deleted_at IS NOT NULL AND deleted_by IS NOT NULL)
    )
);

CREATE INDEX components_owner_updated_idx
    ON component_repo.components (owner_id, updated_at DESC, id);
CREATE INDEX components_status_category_idx
    ON component_repo.components (status, category, id)
    WHERE deleted_at IS NULL;

CREATE TABLE component_repo.artifacts (
    id uuid PRIMARY KEY,
    owner_id uuid,
    artifact_type text NOT NULL,
    source_kind text NOT NULL,
    original_filename text NOT NULL,
    storage_provider text NOT NULL,
    storage_bucket text NOT NULL,
    storage_key text NOT NULL,
    sha256 text NOT NULL,
    file_size bigint NOT NULL,
    mime_type text NOT NULL,
    immutable boolean NOT NULL DEFAULT true,
    verification_status text NOT NULL DEFAULT 'pending',
    verified_at timestamptz,
    uploaded_by uuid NOT NULL,
    uploaded_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb NOT NULL DEFAULT '{}',
    deleted_at timestamptz,
    CONSTRAINT artifacts_source_kind_check CHECK (source_kind IN ('source', 'derived')),
    CONSTRAINT artifacts_source_immutable_check CHECK (source_kind <> 'source' OR immutable),
    CONSTRAINT artifacts_sha256_check CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT artifacts_file_size_check CHECK (file_size >= 0),
    CONSTRAINT artifacts_verification_status_check CHECK (
        verification_status IN ('pending', 'verified', 'failed')
    ),
    CONSTRAINT artifacts_verification_time_check CHECK (
        verification_status <> 'verified' OR verified_at IS NOT NULL
    ),
    CONSTRAINT artifacts_storage_object_unique UNIQUE (
        storage_provider, storage_bucket, storage_key
    )
);

CREATE INDEX artifacts_owner_uploaded_idx
    ON component_repo.artifacts (owner_id, uploaded_at DESC, id);
CREATE INDEX artifacts_sha256_idx ON component_repo.artifacts (sha256);

CREATE TABLE component_repo.upload_sessions (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    target_component_id uuid,
    base_version_id uuid,
    locale text NOT NULL,
    timezone text NOT NULL,
    failure_code text,
    failure_params jsonb,
    metadata jsonb NOT NULL DEFAULT '{}',
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    completed_at timestamptz,
    CONSTRAINT upload_sessions_status_check CHECK (
        status IN ('pending', 'completed', 'expired', 'failed', 'cancelled')
    ),
    CONSTRAINT upload_sessions_locale_check CHECK (locale <> '' AND locale = btrim(locale)),
    CONSTRAINT upload_sessions_timezone_check CHECK (timezone <> '' AND timezone = btrim(timezone)),
    CONSTRAINT upload_sessions_expiry_check CHECK (expires_at > created_at),
    CONSTRAINT upload_sessions_failure_check CHECK (
        (failure_code IS NULL AND failure_params IS NULL)
        OR failure_code IS NOT NULL
    )
);

CREATE INDEX upload_sessions_owner_created_idx
    ON component_repo.upload_sessions (owner_id, created_at DESC, id);
CREATE INDEX upload_sessions_expiry_idx
    ON component_repo.upload_sessions (expires_at, id)
    WHERE status = 'pending';

CREATE TABLE component_repo.upload_session_files (
    id uuid PRIMARY KEY,
    upload_session_id uuid NOT NULL REFERENCES component_repo.upload_sessions(id) ON DELETE CASCADE,
    ordinal integer NOT NULL,
    artifact_type text NOT NULL,
    original_filename text NOT NULL,
    expected_size bigint NOT NULL,
    expected_sha256 text,
    storage_provider text NOT NULL,
    storage_bucket text NOT NULL,
    storage_key text NOT NULL,
    artifact_id uuid REFERENCES component_repo.artifacts(id),
    status text NOT NULL DEFAULT 'pending',
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    CONSTRAINT upload_session_files_ordinal_check CHECK (ordinal >= 0),
    CONSTRAINT upload_session_files_size_check CHECK (expected_size >= 0),
    CONSTRAINT upload_session_files_sha256_check CHECK (
        expected_sha256 IS NULL OR expected_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT upload_session_files_status_check CHECK (
        status IN ('pending', 'uploaded', 'verified', 'failed')
    ),
    CONSTRAINT upload_session_files_session_ordinal_unique UNIQUE (upload_session_id, ordinal),
    CONSTRAINT upload_session_files_storage_object_unique UNIQUE (
        storage_provider, storage_bucket, storage_key
    )
);

CREATE INDEX upload_session_files_session_status_idx
    ON component_repo.upload_session_files (upload_session_id, status, ordinal);

CREATE TABLE component_repo.imports (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL,
    source_artifact_id uuid NOT NULL REFERENCES component_repo.artifacts(id),
    exchange_artifact_id uuid REFERENCES component_repo.artifacts(id),
    target_component_id uuid REFERENCES component_repo.components(id),
    base_version_id uuid,
    status text NOT NULL DEFAULT 'queued',
    parser_version text,
    part_library_version_id uuid,
    locale text NOT NULL,
    timezone text NOT NULL,
    failure_code text,
    failure_params jsonb,
    metadata jsonb NOT NULL DEFAULT '{}',
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    completed_at timestamptz,
    CONSTRAINT imports_status_check CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')
    ),
    CONSTRAINT imports_locale_check CHECK (locale <> '' AND locale = btrim(locale)),
    CONSTRAINT imports_timezone_check CHECK (timezone <> '' AND timezone = btrim(timezone)),
    CONSTRAINT imports_failure_check CHECK (
        (failure_code IS NULL AND failure_params IS NULL)
        OR failure_code IS NOT NULL
    )
);

CREATE INDEX imports_owner_created_idx
    ON component_repo.imports (owner_id, created_at DESC, id);
CREATE INDEX imports_status_created_idx
    ON component_repo.imports (status, created_at, id);

CREATE TABLE component_repo.scene_snapshots (
    id uuid PRIMARY KEY,
    import_id uuid NOT NULL REFERENCES component_repo.imports(id) ON DELETE CASCADE,
    schema_version text NOT NULL,
    parser_version text NOT NULL,
    root_model_id text,
    document jsonb NOT NULL,
    bom jsonb NOT NULL,
    parse_issues jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX scene_snapshots_import_created_idx
    ON component_repo.scene_snapshots (import_id, created_at DESC, id);

CREATE TABLE component_repo.candidates (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL,
    import_id uuid NOT NULL REFERENCES component_repo.imports(id) ON DELETE CASCADE,
    scene_snapshot_id uuid NOT NULL REFERENCES component_repo.scene_snapshots(id),
    status text NOT NULL DEFAULT 'pending_review',
    summary jsonb NOT NULL,
    review_decisions jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT candidates_status_check CHECK (
        status IN ('pending_review', 'accepted', 'rejected', 'superseded')
    )
);

CREATE INDEX candidates_owner_created_idx
    ON component_repo.candidates (owner_id, created_at DESC, id);
CREATE INDEX candidates_import_idx ON component_repo.candidates (import_id, id);

CREATE TABLE component_repo.part_library_versions (
    id uuid PRIMARY KEY,
    source_name text NOT NULL,
    source_hash text NOT NULL,
    connector_count integer NOT NULL,
    status text NOT NULL DEFAULT 'building',
    metadata jsonb NOT NULL DEFAULT '{}',
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT part_library_versions_source_hash_check CHECK (source_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT part_library_versions_connector_count_check CHECK (connector_count >= 0),
    CONSTRAINT part_library_versions_status_check CHECK (
        status IN ('building', 'active', 'retired', 'failed')
    )
);

CREATE INDEX part_library_versions_status_created_idx
    ON component_repo.part_library_versions (status, created_at DESC, id);

CREATE TABLE component_repo.part_connector_definitions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    part_library_version_id uuid NOT NULL REFERENCES component_repo.part_library_versions(id) ON DELETE CASCADE,
    source_connector_id bigint NOT NULL,
    ldraw_part_num text NOT NULL,
    connector_kind text NOT NULL,
    normalized_connector_type text,
    connector_group text,
    connector_gender text,
    position double precision[] NOT NULL,
    orientation double precision[] NOT NULL,
    direction double precision[],
    direction_label text,
    direction_group text,
    radius double precision,
    length double precision,
    caps text,
    center_flag boolean NOT NULL DEFAULT false,
    slide_flag boolean NOT NULL DEFAULT false,
    confidence numeric(5, 4) NOT NULL DEFAULT 1.0000,
    raw_params jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT part_connector_definitions_position_check CHECK (cardinality(position) = 3),
    CONSTRAINT part_connector_definitions_orientation_check CHECK (cardinality(orientation) = 9),
    CONSTRAINT part_connector_definitions_direction_check CHECK (
        direction IS NULL OR cardinality(direction) = 3
    ),
    CONSTRAINT part_connector_definitions_confidence_check CHECK (confidence BETWEEN 0 AND 1),
    CONSTRAINT part_connector_definitions_source_unique UNIQUE (
        part_library_version_id, source_connector_id
    )
);

CREATE INDEX part_connector_definitions_part_idx
    ON component_repo.part_connector_definitions (part_library_version_id, ldraw_part_num, id);
CREATE INDEX part_connector_definitions_type_idx
    ON component_repo.part_connector_definitions (normalized_connector_type, connector_gender, id);

CREATE TABLE component_repo.component_versions (
    id uuid PRIMARY KEY,
    component_id uuid NOT NULL REFERENCES component_repo.components(id) ON DELETE CASCADE,
    component_candidate_id uuid REFERENCES component_repo.candidates(id),
    version_label text NOT NULL,
    revision integer NOT NULL DEFAULT 1,
    status text NOT NULL DEFAULT 'draft',
    source_artifact_id uuid NOT NULL REFERENCES component_repo.artifacts(id),
    exchange_artifact_id uuid REFERENCES component_repo.artifacts(id),
    scene_snapshot_id uuid NOT NULL REFERENCES component_repo.scene_snapshots(id),
    parser_version text NOT NULL,
    part_library_version_id uuid REFERENCES component_repo.part_library_versions(id),
    validation_report_id uuid,
    interface_signature text NOT NULL,
    structure_hash text NOT NULL,
    geometry_hash text NOT NULL,
    preview_artifact_id uuid REFERENCES component_repo.artifacts(id),
    preview_status text NOT NULL DEFAULT 'pending',
    preview_generator_version text,
    preview_failure_code text,
    preview_failure_params jsonb,
    release_note text,
    release_note_locale text,
    metadata jsonb NOT NULL DEFAULT '{}',
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    deleted_at timestamptz,
    deleted_by uuid,
    CONSTRAINT component_versions_revision_check CHECK (revision > 0),
    CONSTRAINT component_versions_status_check CHECK (
        status IN ('draft', 'published', 'deprecated', 'archived')
    ),
    CONSTRAINT component_versions_hashes_check CHECK (
        structure_hash ~ '^[0-9a-f]{64}$'
        AND geometry_hash ~ '^[0-9a-f]{64}$'
        AND interface_signature ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT component_versions_preview_status_check CHECK (
        preview_status IN ('pending', 'running', 'ready', 'failed')
    ),
    CONSTRAINT component_versions_preview_failure_check CHECK (
        (preview_failure_code IS NULL AND preview_failure_params IS NULL)
        OR preview_failure_code IS NOT NULL
    ),
    CONSTRAINT component_versions_release_note_locale_check CHECK (
        (release_note IS NULL AND release_note_locale IS NULL)
        OR (release_note IS NOT NULL AND release_note_locale IS NOT NULL AND release_note_locale <> '')
    ),
    CONSTRAINT component_versions_deleted_audit_check CHECK (
        (deleted_at IS NULL AND deleted_by IS NULL)
        OR (deleted_at IS NOT NULL AND deleted_by IS NOT NULL)
    ),
    CONSTRAINT component_versions_revision_unique UNIQUE (component_id, version_label, revision)
);

CREATE INDEX component_versions_component_created_idx
    ON component_repo.component_versions (component_id, created_at DESC, id);
CREATE INDEX component_versions_status_idx
    ON component_repo.component_versions (status, id)
    WHERE deleted_at IS NULL;
CREATE INDEX component_versions_preview_status_idx
    ON component_repo.component_versions (preview_status, id)
    WHERE preview_status IN ('pending', 'running');

ALTER TABLE component_repo.components
    ADD CONSTRAINT components_current_version_fk
    FOREIGN KEY (current_version_id) REFERENCES component_repo.component_versions(id);
ALTER TABLE component_repo.imports
    ADD CONSTRAINT imports_base_version_fk
    FOREIGN KEY (base_version_id) REFERENCES component_repo.component_versions(id);
ALTER TABLE component_repo.imports
    ADD CONSTRAINT imports_part_library_version_fk
    FOREIGN KEY (part_library_version_id) REFERENCES component_repo.part_library_versions(id);
ALTER TABLE component_repo.upload_sessions
    ADD CONSTRAINT upload_sessions_target_component_fk
    FOREIGN KEY (target_component_id) REFERENCES component_repo.components(id);
ALTER TABLE component_repo.upload_sessions
    ADD CONSTRAINT upload_sessions_base_version_fk
    FOREIGN KEY (base_version_id) REFERENCES component_repo.component_versions(id);

CREATE TABLE component_repo.component_translations (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    component_id uuid NOT NULL REFERENCES component_repo.components(id) ON DELETE CASCADE,
    locale text NOT NULL,
    name text NOT NULL,
    description text,
    tags text[] NOT NULL DEFAULT '{}',
    translation_status text NOT NULL DEFAULT 'draft',
    reviewed_by uuid,
    reviewed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT component_translations_locale_check CHECK (locale <> '' AND locale = btrim(locale)),
    CONSTRAINT component_translations_status_check CHECK (
        translation_status IN ('draft', 'reviewed', 'rejected')
    ),
    CONSTRAINT component_translations_review_check CHECK (
        (translation_status = 'reviewed' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)
        OR translation_status <> 'reviewed'
    ),
    CONSTRAINT component_translations_locale_unique UNIQUE (component_id, locale)
);

CREATE INDEX component_translations_selection_idx
    ON component_repo.component_translations (component_id, locale, translation_status);

CREATE TABLE component_repo.component_groups (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL,
    parent_group_id uuid,
    group_type text NOT NULL,
    name text,
    normalized_name text,
    content_locale text,
    sort_order integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT component_groups_identity_unique UNIQUE (id, owner_id),
    CONSTRAINT component_groups_type_check CHECK (group_type IN ('root', 'custom')),
    CONSTRAINT component_groups_shape_check CHECK (
        (group_type = 'root' AND parent_group_id IS NULL AND name IS NULL
            AND normalized_name IS NULL AND content_locale IS NULL)
        OR (group_type = 'custom' AND parent_group_id IS NOT NULL AND name IS NOT NULL
            AND normalized_name IS NOT NULL AND normalized_name <> ''
            AND content_locale IS NOT NULL AND content_locale <> '')
    ),
    CONSTRAINT component_groups_not_self_parent_check CHECK (parent_group_id IS DISTINCT FROM id),
    CONSTRAINT component_groups_parent_fk FOREIGN KEY (parent_group_id, owner_id)
        REFERENCES component_repo.component_groups(id, owner_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX component_groups_root_owner_unique
    ON component_repo.component_groups (owner_id)
    WHERE group_type = 'root';
CREATE UNIQUE INDEX component_groups_sibling_name_unique
    ON component_repo.component_groups (owner_id, parent_group_id, normalized_name)
    WHERE group_type = 'custom';
CREATE INDEX component_groups_owner_parent_sort_idx
    ON component_repo.component_groups (owner_id, parent_group_id, sort_order, id);

CREATE TABLE component_repo.component_group_memberships (
    owner_id uuid NOT NULL,
    group_id uuid NOT NULL,
    component_id uuid NOT NULL REFERENCES component_repo.components(id) ON DELETE CASCADE,
    added_by uuid NOT NULL,
    added_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (group_id, component_id),
    CONSTRAINT component_group_memberships_group_owner_fk FOREIGN KEY (group_id, owner_id)
        REFERENCES component_repo.component_groups(id, owner_id) ON DELETE CASCADE
);

CREATE INDEX component_group_memberships_owner_component_idx
    ON component_repo.component_group_memberships (owner_id, component_id, group_id);

CREATE TABLE component_repo.component_subscriptions (
    owner_id uuid NOT NULL,
    component_id uuid NOT NULL REFERENCES component_repo.components(id) ON DELETE CASCADE,
    subscribed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_id, component_id)
);

CREATE INDEX component_subscriptions_component_idx
    ON component_repo.component_subscriptions (component_id, owner_id);

CREATE TABLE component_repo.relation_candidates (
    id uuid PRIMARY KEY,
    component_candidate_id uuid NOT NULL REFERENCES component_repo.candidates(id) ON DELETE CASCADE,
    part_library_version_id uuid NOT NULL REFERENCES component_repo.part_library_versions(id),
    endpoint_a jsonb NOT NULL,
    endpoint_b jsonb NOT NULL,
    connection_type text NOT NULL,
    joint_type text NOT NULL,
    position_residual double precision NOT NULL,
    rotation_residual double precision NOT NULL,
    verified_by_tolerance boolean NOT NULL,
    confidence numeric(5, 4) NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    detection_method text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT relation_candidates_residual_check CHECK (
        position_residual >= 0 AND rotation_residual >= 0
    ),
    CONSTRAINT relation_candidates_confidence_check CHECK (confidence BETWEEN 0 AND 1),
    CONSTRAINT relation_candidates_status_check CHECK (
        status IN ('pending', 'confirmed', 'rejected')
    )
);

CREATE INDEX relation_candidates_candidate_status_idx
    ON component_repo.relation_candidates (component_candidate_id, status, id);

CREATE TABLE component_repo.assembly_relations (
    id uuid PRIMARY KEY,
    component_candidate_id uuid NOT NULL REFERENCES component_repo.candidates(id) ON DELETE CASCADE,
    relation_candidate_id uuid NOT NULL UNIQUE REFERENCES component_repo.relation_candidates(id),
    endpoint_a jsonb NOT NULL,
    endpoint_b jsonb NOT NULL,
    connection_type text NOT NULL,
    joint_type text NOT NULL,
    placement jsonb NOT NULL,
    confirmed_by uuid NOT NULL,
    confirmed_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX assembly_relations_candidate_idx
    ON component_repo.assembly_relations (component_candidate_id, id);

CREATE TABLE component_repo.interfaces (
    id uuid PRIMARY KEY,
    component_candidate_id uuid NOT NULL REFERENCES component_repo.candidates(id) ON DELETE CASCADE,
    world_connector_id text NOT NULL,
    name text NOT NULL,
    exposure text NOT NULL,
    default_behavior text NOT NULL,
    source_connector jsonb NOT NULL,
    mechanical_roles jsonb NOT NULL,
    business_roles jsonb NOT NULL,
    requirements jsonb NOT NULL,
    review_status text NOT NULL DEFAULT 'pending',
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT interfaces_review_status_check CHECK (
        review_status IN ('pending', 'confirmed', 'rejected')
    ),
    CONSTRAINT interfaces_candidate_connector_unique UNIQUE (
        component_candidate_id, world_connector_id
    )
);

CREATE INDEX interfaces_candidate_status_idx
    ON component_repo.interfaces (component_candidate_id, review_status, id);

CREATE TABLE component_repo.validation_reports (
    id uuid PRIMARY KEY,
    component_candidate_id uuid REFERENCES component_repo.candidates(id) ON DELETE CASCADE,
    component_version_id uuid REFERENCES component_repo.component_versions(id) ON DELETE CASCADE,
    validation_level text NOT NULL,
    passed boolean NOT NULL,
    checks jsonb NOT NULL,
    issues jsonb NOT NULL,
    validator_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT validation_reports_target_check CHECK (
        num_nonnulls(component_candidate_id, component_version_id) = 1
    )
);

CREATE INDEX validation_reports_candidate_idx
    ON component_repo.validation_reports (component_candidate_id, created_at DESC, id);
CREATE INDEX validation_reports_version_idx
    ON component_repo.validation_reports (component_version_id, created_at DESC, id);

ALTER TABLE component_repo.component_versions
    ADD CONSTRAINT component_versions_validation_report_fk
    FOREIGN KEY (validation_report_id) REFERENCES component_repo.validation_reports(id);

CREATE TABLE component_repo.connector_analyses (
    component_candidate_id uuid PRIMARY KEY REFERENCES component_repo.candidates(id) ON DELETE CASCADE,
    part_library_version_id uuid NOT NULL REFERENCES component_repo.part_library_versions(id),
    recognition_method text NOT NULL,
    recognition_version text NOT NULL,
    calculated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE component_repo.connector_analysis_items (
    id uuid PRIMARY KEY,
    component_candidate_id uuid NOT NULL REFERENCES component_repo.connector_analyses(component_candidate_id) ON DELETE CASCADE,
    part_connector_definition_id bigint NOT NULL REFERENCES component_repo.part_connector_definitions(id),
    world_connector_id text NOT NULL,
    part_instance_id text NOT NULL,
    part_ref text NOT NULL,
    connector_type text,
    connector_kind text,
    connector_gender text,
    direction_label text,
    direction_group text,
    state text NOT NULL,
    position double precision[] NOT NULL,
    axis double precision[] NOT NULL,
    matrix double precision[] NOT NULL,
    access_axis double precision[] NOT NULL,
    external_interface_id uuid REFERENCES component_repo.interfaces(id),
    eligibility_unoccupied boolean NOT NULL,
    eligibility_supported_type boolean NOT NULL,
    eligibility_outward_facing boolean NOT NULL,
    eligibility_clearance_data_available boolean NOT NULL,
    eligibility_clearance_available boolean NOT NULL,
    outward_score double precision NOT NULL,
    capacity integer NOT NULL DEFAULT 1,
    CONSTRAINT connector_analysis_items_state_check CHECK (
        state IN ('internal', 'external', 'blocked', 'unsupported', 'unresolved')
    ),
    CONSTRAINT connector_analysis_items_vectors_check CHECK (
        cardinality(position) = 3 AND cardinality(axis) = 3
        AND cardinality(matrix) = 9 AND cardinality(access_axis) = 3
    ),
    CONSTRAINT connector_analysis_items_capacity_check CHECK (capacity > 0),
    CONSTRAINT connector_analysis_items_candidate_world_unique UNIQUE (
        component_candidate_id, world_connector_id
    )
);

CREATE INDEX connector_analysis_items_candidate_state_idx
    ON component_repo.connector_analysis_items (component_candidate_id, state, id);
CREATE INDEX connector_analysis_items_candidate_part_idx
    ON component_repo.connector_analysis_items (component_candidate_id, part_instance_id, id);

CREATE TABLE component_repo.connector_analysis_path_nodes (
    analysis_item_id uuid NOT NULL REFERENCES component_repo.connector_analysis_items(id) ON DELETE CASCADE,
    ordinal integer NOT NULL,
    instance_id text NOT NULL,
    PRIMARY KEY (analysis_item_id, ordinal),
    CONSTRAINT connector_analysis_path_nodes_ordinal_check CHECK (ordinal >= 0)
);

CREATE INDEX connector_analysis_path_nodes_instance_idx
    ON component_repo.connector_analysis_path_nodes (instance_id, analysis_item_id);

CREATE TABLE component_repo.connector_analysis_blockers (
    analysis_item_id uuid NOT NULL REFERENCES component_repo.connector_analysis_items(id) ON DELETE CASCADE,
    blocker_part_instance_id text NOT NULL,
    PRIMARY KEY (analysis_item_id, blocker_part_instance_id)
);

CREATE INDEX connector_analysis_blockers_part_idx
    ON component_repo.connector_analysis_blockers (blocker_part_instance_id, analysis_item_id);

CREATE TABLE component_repo.connector_analysis_relations (
    analysis_item_id uuid NOT NULL REFERENCES component_repo.connector_analysis_items(id) ON DELETE CASCADE,
    assembly_relation_id uuid NOT NULL REFERENCES component_repo.assembly_relations(id) ON DELETE CASCADE,
    PRIMARY KEY (analysis_item_id, assembly_relation_id)
);

CREATE INDEX connector_analysis_relations_relation_idx
    ON component_repo.connector_analysis_relations (assembly_relation_id, analysis_item_id);

CREATE TABLE component_repo.tasks (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL,
    task_type text NOT NULL,
    status text NOT NULL DEFAULT 'queued',
    payload jsonb NOT NULL,
    result jsonb,
    result_artifact_id uuid REFERENCES component_repo.artifacts(id),
    locale text NOT NULL,
    timezone text NOT NULL,
    created_by uuid NOT NULL,
    idempotency_key text,
    attempts integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 3,
    available_at timestamptz NOT NULL DEFAULT now(),
    lease_owner text,
    lease_expires_at timestamptz,
    progress_code text,
    progress_params jsonb,
    progress_percent numeric(5, 2),
    error_code text,
    error_params jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    CONSTRAINT tasks_status_check CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')
    ),
    CONSTRAINT tasks_locale_check CHECK (locale <> '' AND locale = btrim(locale)),
    CONSTRAINT tasks_timezone_check CHECK (timezone <> '' AND timezone = btrim(timezone)),
    CONSTRAINT tasks_attempts_check CHECK (
        attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts
    ),
    CONSTRAINT tasks_lease_check CHECK (
        (lease_owner IS NULL AND lease_expires_at IS NULL)
        OR (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
    ),
    CONSTRAINT tasks_progress_check CHECK (
        progress_percent IS NULL OR progress_percent BETWEEN 0 AND 100
    ),
    CONSTRAINT tasks_progress_params_check CHECK (
        progress_params IS NULL OR progress_code IS NOT NULL
    ),
    CONSTRAINT tasks_error_params_check CHECK (error_params IS NULL OR error_code IS NOT NULL)
);

CREATE UNIQUE INDEX tasks_type_idempotency_unique
    ON component_repo.tasks (task_type, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE INDEX tasks_claim_idx
    ON component_repo.tasks (available_at, created_at, id)
    WHERE status = 'queued';
CREATE INDEX tasks_lease_expiry_idx
    ON component_repo.tasks (lease_expires_at, id)
    WHERE status = 'running';
CREATE INDEX tasks_owner_created_idx
    ON component_repo.tasks (owner_id, created_at DESC, id);

CREATE TABLE component_repo.task_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id uuid NOT NULL REFERENCES component_repo.tasks(id) ON DELETE CASCADE,
    status text NOT NULL,
    code text,
    params jsonb,
    progress_percent numeric(5, 2),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT task_events_status_check CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'retrying')
    ),
    CONSTRAINT task_events_params_check CHECK (params IS NULL OR code IS NOT NULL),
    CONSTRAINT task_events_progress_check CHECK (
        progress_percent IS NULL OR progress_percent BETWEEN 0 AND 100
    )
);

CREATE INDEX task_events_task_created_idx
    ON component_repo.task_events (task_id, created_at, id);

CREATE TABLE component_repo.outbox_events (
    id uuid PRIMARY KEY,
    aggregate_type text NOT NULL,
    aggregate_id uuid NOT NULL,
    topic text NOT NULL,
    event_key text NOT NULL,
    payload jsonb NOT NULL,
    attempts integer NOT NULL DEFAULT 0,
    available_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    last_error_code text,
    last_error_params jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT outbox_events_attempts_check CHECK (attempts >= 0),
    CONSTRAINT outbox_events_error_params_check CHECK (
        last_error_params IS NULL OR last_error_code IS NOT NULL
    ),
    CONSTRAINT outbox_events_key_unique UNIQUE (topic, event_key)
);

CREATE INDEX outbox_events_publish_idx
    ON component_repo.outbox_events (available_at, created_at, id)
    WHERE published_at IS NULL;

-- +goose StatementBegin
CREATE FUNCTION component_repo.protect_published_component_version()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.status IN ('published', 'deprecated', 'archived')
       AND (NEW.component_id, NEW.component_candidate_id, NEW.version_label, NEW.revision,
            NEW.source_artifact_id, NEW.exchange_artifact_id, NEW.scene_snapshot_id,
            NEW.parser_version, NEW.part_library_version_id, NEW.interface_signature,
            NEW.structure_hash, NEW.geometry_hash, NEW.metadata)
           IS DISTINCT FROM
           (OLD.component_id, OLD.component_candidate_id, OLD.version_label, OLD.revision,
            OLD.source_artifact_id, OLD.exchange_artifact_id, OLD.scene_snapshot_id,
            OLD.parser_version, OLD.part_library_version_id, OLD.interface_signature,
            OLD.structure_hash, OLD.geometry_hash, OLD.metadata) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'published component version structure is immutable';
    END IF;
    RETURN NEW;
END;
$$;
-- +goose StatementEnd

CREATE TRIGGER component_versions_protect_published
BEFORE UPDATE ON component_repo.component_versions
FOR EACH ROW EXECUTE FUNCTION component_repo.protect_published_component_version();

-- +goose StatementBegin
CREATE FUNCTION component_repo.require_official_component_translation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM component_repo.components
        WHERE id = NEW.component_id AND content_kind = 'official'
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'translations are only allowed for official components';
    END IF;
    RETURN NEW;
END;
$$;
-- +goose StatementEnd

CREATE TRIGGER component_translations_require_official
BEFORE INSERT OR UPDATE OF component_id ON component_repo.component_translations
FOR EACH ROW EXECUTE FUNCTION component_repo.require_official_component_translation();

-- +goose StatementBegin
DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'components', 'artifacts', 'upload_sessions', 'upload_session_files',
        'imports', 'scene_snapshots', 'candidates', 'part_library_versions',
        'part_connector_definitions', 'component_versions', 'component_translations',
        'component_groups', 'component_group_memberships', 'component_subscriptions',
        'relation_candidates', 'assembly_relations', 'interfaces', 'validation_reports',
        'connector_analyses', 'connector_analysis_items', 'connector_analysis_path_nodes',
        'connector_analysis_blockers', 'connector_analysis_relations', 'tasks',
        'task_events', 'outbox_events'
    ]
    LOOP
        EXECUTE format('ALTER TABLE component_repo.%I ENABLE ROW LEVEL SECURITY', table_name);
    END LOOP;
END;
$$;
-- +goose StatementEnd

REVOKE ALL ON ALL TABLES IN SCHEMA component_repo FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA component_repo FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA component_repo FROM PUBLIC;

-- +goose Down

DROP SCHEMA IF EXISTS component_repo CASCADE;
