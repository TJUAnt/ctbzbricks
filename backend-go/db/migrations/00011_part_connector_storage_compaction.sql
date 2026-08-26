-- +goose Up

-- Relation detection loads definitions by frozen library + part number. The
-- global type/gender index is not used by the Go query path and costs material
-- space on large Studio snapshots.
DROP INDEX IF EXISTS component_repo.part_connector_definitions_type_idx;

-- +goose Down

CREATE INDEX part_connector_definitions_type_idx
    ON component_repo.part_connector_definitions (normalized_connector_type, connector_gender, id);
