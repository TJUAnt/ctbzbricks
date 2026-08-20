-- +goose Up

ALTER TABLE component_repo.part_geometries
    DROP CONSTRAINT part_geometries_size_check;

ALTER TABLE component_repo.part_geometries
    ALTER COLUMN logical_width_stud DROP NOT NULL,
    ALTER COLUMN logical_depth_stud DROP NOT NULL,
    ALTER COLUMN logical_height_plate DROP NOT NULL;

ALTER TABLE component_repo.part_geometries
    ADD COLUMN logical_size_derivation_status text NOT NULL DEFAULT 'legacy_imported',
    ADD CONSTRAINT part_geometries_logical_size_derivation_status_check CHECK (
        logical_size_derivation_status IN (
            'legacy_imported',
            'derived_exact',
            'derived_approximate',
            'not_applicable',
            'failed'
        )
    ),
    ADD CONSTRAINT part_geometries_logical_size_check CHECK (
        (
            logical_size_derivation_status IN ('legacy_imported', 'derived_exact', 'derived_approximate')
            AND logical_width_stud IS NOT NULL
            AND logical_depth_stud IS NOT NULL
            AND logical_height_plate IS NOT NULL
            AND logical_width_stud >= 0
            AND logical_depth_stud >= 0
            AND logical_height_plate >= 0
        )
        OR (
            logical_size_derivation_status IN ('not_applicable', 'failed')
            AND logical_width_stud IS NULL
            AND logical_depth_stud IS NULL
            AND logical_height_plate IS NULL
        )
    );

CREATE TABLE component_repo.part_external_ids (
    part_library_version_id uuid NOT NULL,
    ldraw_part_num text NOT NULL,
    id_system text NOT NULL,
    external_id text NOT NULL,
    relation_type text NOT NULL DEFAULT 'exact',
    confidence numeric(5,4) NOT NULL DEFAULT 1.0000,
    source text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (part_library_version_id, ldraw_part_num, id_system, external_id, relation_type),
    CONSTRAINT part_external_ids_part_fk
        FOREIGN KEY (part_library_version_id, ldraw_part_num)
        REFERENCES component_repo.parts (part_library_version_id, ldraw_part_num)
        ON DELETE CASCADE,
    CONSTRAINT part_external_ids_system_check CHECK (
        id_system IN ('ldraw', 'rebrickable', 'bricklink', 'lego_design', 'lego_element')
    ),
    CONSTRAINT part_external_ids_value_check CHECK (
        external_id <> '' AND external_id = btrim(external_id)
    ),
    CONSTRAINT part_external_ids_relation_check CHECK (
        relation_type IN ('exact', 'alias', 'print_variant', 'color_variant', 'shortcut', 'unknown')
    ),
    CONSTRAINT part_external_ids_confidence_check CHECK (
        confidence >= 0 AND confidence <= 1
    ),
    CONSTRAINT part_external_ids_source_check CHECK (source <> ''),
    CONSTRAINT part_external_ids_metadata_check CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE INDEX part_external_ids_lookup_idx
    ON component_repo.part_external_ids (
        id_system, external_id, part_library_version_id, ldraw_part_num
    );

CREATE INDEX part_external_ids_part_idx
    ON component_repo.part_external_ids (
        part_library_version_id, ldraw_part_num, id_system
    );

ALTER TABLE component_repo.part_external_ids ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON component_repo.part_external_ids FROM PUBLIC;

-- +goose Down

DROP TABLE IF EXISTS component_repo.part_external_ids;

ALTER TABLE component_repo.part_geometries
    DROP CONSTRAINT IF EXISTS part_geometries_logical_size_check,
    DROP CONSTRAINT IF EXISTS part_geometries_logical_size_derivation_status_check,
    DROP COLUMN IF EXISTS logical_size_derivation_status;

ALTER TABLE component_repo.part_geometries
    ALTER COLUMN logical_width_stud SET NOT NULL,
    ALTER COLUMN logical_depth_stud SET NOT NULL,
    ALTER COLUMN logical_height_plate SET NOT NULL,
    ADD CONSTRAINT part_geometries_size_check CHECK (
        logical_width_stud >= 0 AND logical_depth_stud >= 0 AND logical_height_plate >= 0
    );
