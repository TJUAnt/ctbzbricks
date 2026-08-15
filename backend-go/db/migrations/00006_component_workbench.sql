-- +goose Up

ALTER TABLE component_repo.candidates
    ADD CONSTRAINT candidates_id_owner_unique UNIQUE (id, owner_id),
    ADD COLUMN relation_detection_task_id uuid,
    ADD COLUMN relation_detection_version text;

ALTER TABLE component_repo.relation_candidates
    ADD COLUMN owner_id uuid,
    ADD COLUMN endpoint_a_world_connector_id text GENERATED ALWAYS AS (endpoint_a ->> 'worldConnectorId') STORED,
    ADD COLUMN endpoint_b_world_connector_id text GENERATED ALWAYS AS (endpoint_b ->> 'worldConnectorId') STORED;

UPDATE component_repo.relation_candidates relation
SET owner_id = candidate.owner_id
FROM component_repo.candidates candidate
WHERE candidate.id = relation.component_candidate_id;

ALTER TABLE component_repo.relation_candidates
    ALTER COLUMN owner_id SET NOT NULL,
    ADD CONSTRAINT relation_candidates_candidate_owner_fk
        FOREIGN KEY (component_candidate_id, owner_id)
        REFERENCES component_repo.candidates (id, owner_id)
        ON DELETE CASCADE,
    ADD CONSTRAINT relation_candidates_endpoint_shape_check CHECK (
        endpoint_a_world_connector_id IS NOT NULL
        AND endpoint_a_world_connector_id <> ''
        AND endpoint_b_world_connector_id IS NOT NULL
        AND endpoint_b_world_connector_id <> ''
        AND endpoint_a_world_connector_id <> endpoint_b_world_connector_id
    );

CREATE UNIQUE INDEX relation_candidates_endpoint_pair_unique
    ON component_repo.relation_candidates (
        component_candidate_id,
        LEAST(endpoint_a_world_connector_id, endpoint_b_world_connector_id),
        GREATEST(endpoint_a_world_connector_id, endpoint_b_world_connector_id)
    );

ALTER TABLE component_repo.assembly_relations
    ADD COLUMN owner_id uuid,
    ADD COLUMN endpoint_a_world_connector_id text GENERATED ALWAYS AS (endpoint_a ->> 'worldConnectorId') STORED,
    ADD COLUMN endpoint_b_world_connector_id text GENERATED ALWAYS AS (endpoint_b ->> 'worldConnectorId') STORED;

UPDATE component_repo.assembly_relations relation
SET owner_id = candidate.owner_id
FROM component_repo.candidates candidate
WHERE candidate.id = relation.component_candidate_id;

ALTER TABLE component_repo.assembly_relations
    ALTER COLUMN owner_id SET NOT NULL,
    ADD CONSTRAINT assembly_relations_candidate_owner_fk
        FOREIGN KEY (component_candidate_id, owner_id)
        REFERENCES component_repo.candidates (id, owner_id)
        ON DELETE CASCADE,
    ADD CONSTRAINT assembly_relations_endpoint_shape_check CHECK (
        endpoint_a_world_connector_id IS NOT NULL
        AND endpoint_a_world_connector_id <> ''
        AND endpoint_b_world_connector_id IS NOT NULL
        AND endpoint_b_world_connector_id <> ''
        AND endpoint_a_world_connector_id <> endpoint_b_world_connector_id
    );

ALTER TABLE component_repo.interfaces
    ADD COLUMN owner_id uuid;

UPDATE component_repo.interfaces interface_row
SET owner_id = candidate.owner_id
FROM component_repo.candidates candidate
WHERE candidate.id = interface_row.component_candidate_id;

ALTER TABLE component_repo.interfaces
    ALTER COLUMN owner_id SET NOT NULL,
    ADD CONSTRAINT interfaces_candidate_owner_fk
        FOREIGN KEY (component_candidate_id, owner_id)
        REFERENCES component_repo.candidates (id, owner_id)
        ON DELETE CASCADE;

ALTER TABLE component_repo.connector_analyses
    ADD COLUMN owner_id uuid;

UPDATE component_repo.connector_analyses analysis
SET owner_id = candidate.owner_id
FROM component_repo.candidates candidate
WHERE candidate.id = analysis.component_candidate_id;

ALTER TABLE component_repo.connector_analyses
    ALTER COLUMN owner_id SET NOT NULL,
    ADD CONSTRAINT connector_analyses_candidate_owner_fk
        FOREIGN KEY (component_candidate_id, owner_id)
        REFERENCES component_repo.candidates (id, owner_id)
        ON DELETE CASCADE,
    ADD CONSTRAINT connector_analyses_candidate_owner_unique
        UNIQUE (component_candidate_id, owner_id);

ALTER TABLE component_repo.connector_analysis_items
    ADD COLUMN owner_id uuid;

UPDATE component_repo.connector_analysis_items item
SET owner_id = analysis.owner_id
FROM component_repo.connector_analyses analysis
WHERE analysis.component_candidate_id = item.component_candidate_id;

ALTER TABLE component_repo.connector_analysis_items
    ALTER COLUMN owner_id SET NOT NULL,
    ADD CONSTRAINT connector_analysis_items_analysis_owner_fk
        FOREIGN KEY (component_candidate_id, owner_id)
        REFERENCES component_repo.connector_analyses (component_candidate_id, owner_id)
        ON DELETE CASCADE;

CREATE TABLE component_repo.assembly_relation_connector_occupancies (
    assembly_relation_id uuid NOT NULL REFERENCES component_repo.assembly_relations(id) ON DELETE CASCADE,
    component_candidate_id uuid NOT NULL,
    world_connector_id text NOT NULL,
    slot integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (assembly_relation_id, world_connector_id),
    CONSTRAINT assembly_relation_connector_occupancies_slot_check CHECK (slot > 0),
    CONSTRAINT assembly_relation_connector_occupancies_slot_unique
        UNIQUE (component_candidate_id, world_connector_id, slot),
    CONSTRAINT assembly_relation_connector_occupancies_connector_fk
        FOREIGN KEY (component_candidate_id, world_connector_id)
        REFERENCES component_repo.connector_analysis_items (component_candidate_id, world_connector_id)
        ON DELETE RESTRICT
);

-- +goose StatementBegin
CREATE FUNCTION component_repo.reserve_assembly_relation_connectors()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    connector_id text;
    connector_capacity integer;
    reserved_slot integer;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM component_repo.relation_candidates relation
        WHERE relation.id = NEW.relation_candidate_id
          AND relation.component_candidate_id = NEW.component_candidate_id
          AND relation.owner_id = NEW.owner_id
          AND relation.endpoint_a = NEW.endpoint_a
          AND relation.endpoint_b = NEW.endpoint_b
          AND relation.connection_type = NEW.connection_type
          AND relation.joint_type = NEW.joint_type
          AND relation.status <> 'rejected'
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'assembly relation source is invalid';
    END IF;

    FOREACH connector_id IN ARRAY ARRAY[
        NEW.endpoint_a_world_connector_id,
        NEW.endpoint_b_world_connector_id
    ] LOOP
        SELECT item.capacity
        INTO connector_capacity
        FROM component_repo.connector_analysis_items item
        WHERE item.component_candidate_id = NEW.component_candidate_id
          AND item.world_connector_id = connector_id
        FOR UPDATE;

        IF connector_capacity IS NULL THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'assembly relation connector is unknown';
        END IF;

        SELECT slot
        INTO reserved_slot
        FROM generate_series(1, connector_capacity) slot
        WHERE NOT EXISTS (
            SELECT 1
            FROM component_repo.assembly_relation_connector_occupancies occupancy
            WHERE occupancy.component_candidate_id = NEW.component_candidate_id
              AND occupancy.world_connector_id = connector_id
              AND occupancy.slot = slot
        )
        ORDER BY slot
        LIMIT 1;

        IF reserved_slot IS NULL THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'connector capacity exceeded';
        END IF;

        INSERT INTO component_repo.assembly_relation_connector_occupancies (
            assembly_relation_id, component_candidate_id, world_connector_id, slot
        ) VALUES (NEW.id, NEW.component_candidate_id, connector_id, reserved_slot);
    END LOOP;

    UPDATE component_repo.relation_candidates
    SET status = 'confirmed', updated_at = now()
    WHERE id = NEW.relation_candidate_id;
    RETURN NEW;
END;
$$;
-- +goose StatementEnd

CREATE TRIGGER assembly_relations_reserve_connectors
AFTER INSERT ON component_repo.assembly_relations
FOR EACH ROW EXECUTE FUNCTION component_repo.reserve_assembly_relation_connectors();

ALTER TABLE component_repo.validation_reports
    ADD COLUMN owner_id uuid,
    ADD COLUMN task_id uuid,
    ADD COLUMN interface_signature text,
    ADD COLUMN structure_hash text,
    ADD COLUMN geometry_hash text;

UPDATE component_repo.validation_reports report
SET owner_id = candidate.owner_id,
    interface_signature = candidate.interface_signature,
    structure_hash = candidate.structure_hash,
    geometry_hash = candidate.geometry_hash
FROM component_repo.candidates candidate
WHERE candidate.id = report.component_candidate_id;

UPDATE component_repo.validation_reports report
SET owner_id = component.owner_id,
    interface_signature = version.interface_signature,
    structure_hash = version.structure_hash,
    geometry_hash = version.geometry_hash
FROM component_repo.component_versions version
JOIN component_repo.components component ON component.id = version.component_id
WHERE version.id = report.component_version_id;

ALTER TABLE component_repo.validation_reports
    ALTER COLUMN owner_id SET NOT NULL,
    ALTER COLUMN task_id SET NOT NULL,
    ALTER COLUMN interface_signature SET NOT NULL,
    ALTER COLUMN structure_hash SET NOT NULL,
    ALTER COLUMN geometry_hash SET NOT NULL,
    ADD CONSTRAINT validation_reports_task_unique UNIQUE (task_id),
    ADD CONSTRAINT validation_reports_task_owner_fk
        FOREIGN KEY (task_id, owner_id)
        REFERENCES component_repo.tasks (id, owner_id),
    ADD CONSTRAINT validation_reports_candidate_owner_fk
        FOREIGN KEY (component_candidate_id, owner_id)
        REFERENCES component_repo.candidates (id, owner_id)
        ON DELETE CASCADE,
    ADD CONSTRAINT validation_reports_hashes_check CHECK (
        interface_signature ~ '^[0-9a-f]{64}$'
        AND structure_hash ~ '^[0-9a-f]{64}$'
        AND geometry_hash ~ '^[0-9a-f]{64}$'
    );

ALTER TABLE component_repo.validation_reports
    DROP CONSTRAINT validation_reports_target_check,
    ADD CONSTRAINT validation_reports_target_check CHECK (
        component_candidate_id IS NOT NULL AND component_version_id IS NOT NULL
    );

-- +goose StatementBegin
CREATE FUNCTION component_repo.require_validation_report_integrity()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM component_repo.component_versions version
        JOIN component_repo.components component ON component.id = version.component_id
        JOIN component_repo.tasks task ON task.id = NEW.task_id
        WHERE version.id = NEW.component_version_id
          AND version.component_candidate_id = NEW.component_candidate_id
          AND component.owner_id = NEW.owner_id
          AND task.owner_id = NEW.owner_id
          AND task.task_type = 'component.validate'
          AND task.payload ->> 'candidateId' = NEW.component_candidate_id::text
          AND task.payload ->> 'versionId' = NEW.component_version_id::text
          AND version.interface_signature = NEW.interface_signature
          AND version.structure_hash = NEW.structure_hash
          AND version.geometry_hash = NEW.geometry_hash
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'validation report lineage is invalid';
    END IF;
    RETURN NEW;
END;
$$;
-- +goose StatementEnd

CREATE TRIGGER validation_reports_require_integrity
BEFORE INSERT OR UPDATE ON component_repo.validation_reports
FOR EACH ROW EXECUTE FUNCTION component_repo.require_validation_report_integrity();

ALTER TABLE component_repo.component_versions
    ADD COLUMN preview_task_id uuid,
    ADD COLUMN preview_generation integer NOT NULL DEFAULT 0,
    ADD CONSTRAINT component_versions_preview_generation_check CHECK (preview_generation >= 0);

CREATE TABLE component_repo.parts (
    part_library_version_id uuid NOT NULL REFERENCES component_repo.part_library_versions(id) ON DELETE CASCADE,
    ldraw_part_num text NOT NULL,
    source_name text NOT NULL,
    content_locale text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (part_library_version_id, ldraw_part_num),
    CONSTRAINT parts_number_check CHECK (ldraw_part_num <> '' AND ldraw_part_num = lower(ldraw_part_num)),
    CONSTRAINT parts_locale_check CHECK (content_locale <> '' AND content_locale = btrim(content_locale))
);

CREATE TABLE component_repo.part_translations (
    part_library_version_id uuid NOT NULL,
    ldraw_part_num text NOT NULL,
    locale text NOT NULL,
    name text NOT NULL,
    translation_status text NOT NULL DEFAULT 'draft',
    reviewed_by uuid,
    reviewed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (part_library_version_id, ldraw_part_num, locale),
    CONSTRAINT part_translations_part_fk
        FOREIGN KEY (part_library_version_id, ldraw_part_num)
        REFERENCES component_repo.parts (part_library_version_id, ldraw_part_num)
        ON DELETE CASCADE,
    CONSTRAINT part_translations_status_check CHECK (translation_status IN ('draft', 'reviewed', 'rejected')),
    CONSTRAINT part_translations_review_check CHECK (
        (translation_status = 'reviewed' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)
        OR translation_status <> 'reviewed'
    )
);

-- +goose StatementBegin
CREATE FUNCTION component_repo.require_valid_publish_report()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.status = 'published' AND OLD.status IS DISTINCT FROM 'published' AND NOT EXISTS (
        SELECT 1
        FROM component_repo.validation_reports report
        WHERE report.id = NEW.validation_report_id
          AND report.component_version_id = NEW.id
          AND report.owner_id = NEW.created_by
          AND report.validation_level = 'publish'
          AND report.passed
          AND EXISTS (
              SELECT 1 FROM component_repo.tasks task
              WHERE task.id = report.task_id AND task.status = 'succeeded'
          )
          AND report.interface_signature = NEW.interface_signature
          AND report.structure_hash = NEW.structure_hash
          AND report.geometry_hash = NEW.geometry_hash
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'publish validation report is missing or stale';
    END IF;
    RETURN NEW;
END;
$$;
-- +goose StatementEnd

CREATE TRIGGER component_versions_require_valid_publish_report
BEFORE UPDATE OF status ON component_repo.component_versions
FOR EACH ROW EXECUTE FUNCTION component_repo.require_valid_publish_report();

-- +goose StatementBegin
CREATE FUNCTION component_repo.sync_workbench_task_terminal_state()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.task_type = 'component.preview.materialize'
       AND NEW.status IN ('failed', 'cancelled')
       AND OLD.status IS DISTINCT FROM NEW.status THEN
        UPDATE component_repo.component_versions
        SET preview_status = 'failed',
            preview_failure_code = COALESCE(NEW.error_code, 'component_repo.preview_unavailable'),
            preview_failure_params = COALESCE(NEW.error_params, jsonb_build_object('versionId', NEW.payload ->> 'versionId'))
        WHERE preview_task_id = NEW.id
          AND preview_status IN ('pending', 'running');
    END IF;
    RETURN NEW;
END;
$$;
-- +goose StatementEnd

CREATE TRIGGER tasks_sync_workbench_terminal_state
AFTER UPDATE OF status ON component_repo.tasks
FOR EACH ROW EXECUTE FUNCTION component_repo.sync_workbench_task_terminal_state();

ALTER TABLE component_repo.candidates
    ADD CONSTRAINT candidates_relation_task_owner_fk
        FOREIGN KEY (relation_detection_task_id, owner_id)
        REFERENCES component_repo.tasks (id, owner_id);

ALTER TABLE component_repo.component_versions
    ADD CONSTRAINT component_versions_preview_task_fk
        FOREIGN KEY (preview_task_id) REFERENCES component_repo.tasks(id);

ALTER TABLE component_repo.assembly_relation_connector_occupancies ENABLE ROW LEVEL SECURITY;
ALTER TABLE component_repo.parts ENABLE ROW LEVEL SECURITY;
ALTER TABLE component_repo.part_translations ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON component_repo.assembly_relation_connector_occupancies FROM PUBLIC;
REVOKE ALL ON component_repo.parts FROM PUBLIC;
REVOKE ALL ON component_repo.part_translations FROM PUBLIC;

-- +goose Down

DROP TRIGGER IF EXISTS component_versions_require_valid_publish_report ON component_repo.component_versions;
DROP FUNCTION IF EXISTS component_repo.require_valid_publish_report();

DROP TRIGGER IF EXISTS tasks_sync_workbench_terminal_state ON component_repo.tasks;
DROP FUNCTION IF EXISTS component_repo.sync_workbench_task_terminal_state();

DROP TRIGGER IF EXISTS validation_reports_require_integrity ON component_repo.validation_reports;
DROP FUNCTION IF EXISTS component_repo.require_validation_report_integrity();

ALTER TABLE component_repo.component_versions
    DROP CONSTRAINT IF EXISTS component_versions_preview_task_fk,
    DROP CONSTRAINT IF EXISTS component_versions_preview_generation_check,
    DROP COLUMN IF EXISTS preview_generation,
    DROP COLUMN IF EXISTS preview_task_id;

DROP TABLE IF EXISTS component_repo.part_translations;
DROP TABLE IF EXISTS component_repo.parts;

ALTER TABLE component_repo.validation_reports
    DROP CONSTRAINT IF EXISTS validation_reports_hashes_check,
    DROP CONSTRAINT IF EXISTS validation_reports_task_owner_fk,
    DROP CONSTRAINT IF EXISTS validation_reports_candidate_owner_fk,
    DROP CONSTRAINT IF EXISTS validation_reports_task_unique,
    DROP COLUMN IF EXISTS geometry_hash,
    DROP COLUMN IF EXISTS structure_hash,
    DROP COLUMN IF EXISTS interface_signature,
    DROP COLUMN IF EXISTS task_id,
    DROP COLUMN IF EXISTS owner_id;

ALTER TABLE component_repo.validation_reports
    DROP CONSTRAINT IF EXISTS validation_reports_target_check,
    ADD CONSTRAINT validation_reports_target_check CHECK (
        num_nonnulls(component_candidate_id, component_version_id) = 1
    );

DROP TRIGGER IF EXISTS assembly_relations_reserve_connectors ON component_repo.assembly_relations;
DROP FUNCTION IF EXISTS component_repo.reserve_assembly_relation_connectors();
DROP TABLE IF EXISTS component_repo.assembly_relation_connector_occupancies;

ALTER TABLE component_repo.connector_analysis_items
    DROP CONSTRAINT IF EXISTS connector_analysis_items_analysis_owner_fk,
    DROP COLUMN IF EXISTS owner_id;

ALTER TABLE component_repo.connector_analyses
    DROP CONSTRAINT IF EXISTS connector_analyses_candidate_owner_unique,
    DROP CONSTRAINT IF EXISTS connector_analyses_candidate_owner_fk,
    DROP COLUMN IF EXISTS owner_id;

ALTER TABLE component_repo.interfaces
    DROP CONSTRAINT IF EXISTS interfaces_candidate_owner_fk,
    DROP COLUMN IF EXISTS owner_id;

ALTER TABLE component_repo.assembly_relations
    DROP CONSTRAINT IF EXISTS assembly_relations_endpoint_shape_check,
    DROP CONSTRAINT IF EXISTS assembly_relations_candidate_owner_fk,
    DROP COLUMN IF EXISTS endpoint_b_world_connector_id,
    DROP COLUMN IF EXISTS endpoint_a_world_connector_id,
    DROP COLUMN IF EXISTS owner_id;

DROP INDEX IF EXISTS component_repo.relation_candidates_endpoint_pair_unique;

ALTER TABLE component_repo.relation_candidates
    DROP CONSTRAINT IF EXISTS relation_candidates_endpoint_shape_check,
    DROP CONSTRAINT IF EXISTS relation_candidates_candidate_owner_fk,
    DROP COLUMN IF EXISTS endpoint_b_world_connector_id,
    DROP COLUMN IF EXISTS endpoint_a_world_connector_id,
    DROP COLUMN IF EXISTS owner_id;

ALTER TABLE component_repo.candidates
    DROP CONSTRAINT IF EXISTS candidates_relation_task_owner_fk,
    DROP COLUMN IF EXISTS relation_detection_version,
    DROP COLUMN IF EXISTS relation_detection_task_id,
    DROP CONSTRAINT IF EXISTS candidates_id_owner_unique;
