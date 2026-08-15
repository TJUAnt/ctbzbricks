-- +goose Up

CREATE TABLE component_repo.part_geometries (
    part_library_version_id uuid NOT NULL,
    ldraw_part_num text NOT NULL,
    source_relative_path text NOT NULL,
    source_file_hash text NOT NULL,
    bbox_min double precision[] NOT NULL,
    bbox_max double precision[] NOT NULL,
    logical_width_stud double precision NOT NULL,
    logical_depth_stud double precision NOT NULL,
    logical_height_plate double precision NOT NULL,
    vertex_count integer NOT NULL,
    face_count integer NOT NULL,
    geometry_status text NOT NULL DEFAULT 'ready',
    geometry_error_code text,
    geometry_error_params jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (part_library_version_id, ldraw_part_num),
    CONSTRAINT part_geometries_part_fk
        FOREIGN KEY (part_library_version_id, ldraw_part_num)
        REFERENCES component_repo.parts (part_library_version_id, ldraw_part_num)
        ON DELETE CASCADE,
    CONSTRAINT part_geometries_source_path_check CHECK (
        source_relative_path <> '' AND source_relative_path = lower(source_relative_path)
    ),
    CONSTRAINT part_geometries_source_hash_check CHECK (source_file_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT part_geometries_bounds_check CHECK (
        cardinality(bbox_min) = 3 AND cardinality(bbox_max) = 3
        AND bbox_min[1] <= bbox_max[1]
        AND bbox_min[2] <= bbox_max[2]
        AND bbox_min[3] <= bbox_max[3]
    ),
    CONSTRAINT part_geometries_size_check CHECK (
        logical_width_stud >= 0 AND logical_depth_stud >= 0 AND logical_height_plate >= 0
    ),
    CONSTRAINT part_geometries_counts_check CHECK (vertex_count >= 0 AND face_count >= 0),
    CONSTRAINT part_geometries_status_check CHECK (geometry_status IN ('ready', 'failed')),
    CONSTRAINT part_geometries_error_check CHECK (
        (geometry_status = 'ready' AND geometry_error_code IS NULL AND geometry_error_params IS NULL)
        OR (geometry_status = 'failed' AND geometry_error_code IS NOT NULL)
    ),
    CONSTRAINT part_geometries_error_params_check CHECK (
        geometry_error_params IS NULL OR jsonb_typeof(geometry_error_params) = 'object'
    )
);

CREATE INDEX part_geometries_logical_size_idx
    ON component_repo.part_geometries (
        logical_width_stud, logical_depth_stud, logical_height_plate,
        part_library_version_id, ldraw_part_num
    );

CREATE TABLE component_repo.part_previews (
    part_library_version_id uuid NOT NULL,
    ldraw_part_num text NOT NULL,
    artifact_id uuid REFERENCES component_repo.artifacts(id),
    status text NOT NULL DEFAULT 'pending',
    generator_version text,
    task_id uuid REFERENCES component_repo.tasks(id),
    generation integer NOT NULL DEFAULT 0,
    failure_code text,
    failure_params jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (part_library_version_id, ldraw_part_num),
    CONSTRAINT part_previews_part_fk
        FOREIGN KEY (part_library_version_id, ldraw_part_num)
        REFERENCES component_repo.parts (part_library_version_id, ldraw_part_num)
        ON DELETE CASCADE,
    CONSTRAINT part_previews_status_check CHECK (status IN ('pending', 'running', 'ready', 'failed')),
    CONSTRAINT part_previews_generation_check CHECK (generation >= 0),
    CONSTRAINT part_previews_ready_check CHECK (
        (status = 'ready' AND artifact_id IS NOT NULL AND generator_version IS NOT NULL)
        OR status <> 'ready'
    ),
    CONSTRAINT part_previews_failure_check CHECK (
        (failure_code IS NULL AND failure_params IS NULL) OR failure_code IS NOT NULL
    ),
    CONSTRAINT part_previews_failure_params_check CHECK (
        failure_params IS NULL OR jsonb_typeof(failure_params) = 'object'
    )
);

INSERT INTO component_repo.part_previews (part_library_version_id, ldraw_part_num)
SELECT part_library_version_id, ldraw_part_num
FROM component_repo.parts;

-- +goose StatementBegin
CREATE OR REPLACE FUNCTION component_repo.create_part_preview_state()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO component_repo.part_previews (part_library_version_id, ldraw_part_num)
    VALUES (NEW.part_library_version_id, NEW.ldraw_part_num)
    ON CONFLICT DO NOTHING;
    RETURN NEW;
END;
$$;
-- +goose StatementEnd

CREATE TRIGGER parts_create_preview_state
AFTER INSERT ON component_repo.parts
FOR EACH ROW EXECUTE FUNCTION component_repo.create_part_preview_state();

-- +goose StatementBegin
CREATE OR REPLACE FUNCTION component_repo.sync_workbench_task_terminal_state()
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
            preview_failure_params = COALESCE(
                NEW.error_params,
                jsonb_build_object('versionId', NEW.payload ->> 'versionId')
            )
        WHERE preview_task_id = NEW.id
          AND preview_status IN ('pending', 'running');
    ELSIF NEW.task_type = 'component.part_preview.materialize'
       AND NEW.status IN ('failed', 'cancelled')
       AND OLD.status IS DISTINCT FROM NEW.status THEN
        UPDATE component_repo.part_previews
        SET status = 'failed',
            failure_code = COALESCE(NEW.error_code, 'component_repo.part_preview_unavailable'),
            failure_params = COALESCE(
                NEW.error_params,
                jsonb_build_object(
                    'partLibraryVersionId', NEW.payload ->> 'partLibraryVersionId',
                    'ldrawPartNum', NEW.payload ->> 'ldrawPartNum'
                )
            ),
            updated_at = now()
        WHERE task_id = NEW.id
          AND status IN ('pending', 'running');
    END IF;
    RETURN NEW;
END;
$$;
-- +goose StatementEnd

ALTER TABLE component_repo.part_geometries ENABLE ROW LEVEL SECURITY;
ALTER TABLE component_repo.part_previews ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON component_repo.part_geometries FROM PUBLIC;
REVOKE ALL ON component_repo.part_previews FROM PUBLIC;

-- +goose Down

-- +goose StatementBegin
CREATE OR REPLACE FUNCTION component_repo.sync_workbench_task_terminal_state()
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

DROP TRIGGER IF EXISTS parts_create_preview_state ON component_repo.parts;
DROP FUNCTION IF EXISTS component_repo.create_part_preview_state();
DROP TABLE IF EXISTS component_repo.part_previews;
DROP TABLE IF EXISTS component_repo.part_geometries;
