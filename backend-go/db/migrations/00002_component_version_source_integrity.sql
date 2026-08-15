-- +goose Up

ALTER TABLE component_repo.artifacts
    ADD CONSTRAINT artifacts_id_owner_unique UNIQUE (id, owner_id);

ALTER TABLE component_repo.imports
    ADD CONSTRAINT imports_id_owner_unique UNIQUE (id, owner_id),
    ADD CONSTRAINT imports_source_owner_fk
        FOREIGN KEY (source_artifact_id, owner_id)
        REFERENCES component_repo.artifacts (id, owner_id),
    ADD CONSTRAINT imports_exchange_owner_fk
        FOREIGN KEY (exchange_artifact_id, owner_id)
        REFERENCES component_repo.artifacts (id, owner_id);

ALTER TABLE component_repo.scene_snapshots
    ADD CONSTRAINT scene_snapshots_id_import_unique UNIQUE (id, import_id);

ALTER TABLE component_repo.candidates
    ADD COLUMN interface_signature text,
    ADD COLUMN structure_hash text,
    ADD COLUMN geometry_hash text,
    ADD CONSTRAINT candidates_import_owner_fk
        FOREIGN KEY (import_id, owner_id)
        REFERENCES component_repo.imports (id, owner_id)
        ON DELETE CASCADE,
    ADD CONSTRAINT candidates_snapshot_import_fk
        FOREIGN KEY (scene_snapshot_id, import_id)
        REFERENCES component_repo.scene_snapshots (id, import_id)
        ON DELETE CASCADE,
    ADD CONSTRAINT candidates_materialized_hashes_check CHECK (
        (interface_signature IS NULL AND structure_hash IS NULL AND geometry_hash IS NULL)
        OR (
            interface_signature ~ '^[0-9a-f]{64}$'
            AND structure_hash ~ '^[0-9a-f]{64}$'
            AND geometry_hash ~ '^[0-9a-f]{64}$'
        )
    );

-- +goose StatementBegin
CREATE FUNCTION component_repo.require_component_version_source_integrity()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM component_repo.components component
        WHERE component.id = NEW.component_id
          AND component.content_kind = 'user'
    ) AND NOT EXISTS (
        SELECT 1
        FROM component_repo.candidates candidate
        JOIN component_repo.scene_snapshots snapshot
          ON snapshot.id = candidate.scene_snapshot_id
         AND snapshot.import_id = candidate.import_id
        JOIN component_repo.imports import_job
          ON import_job.id = candidate.import_id
         AND import_job.owner_id = candidate.owner_id
        JOIN component_repo.components component
          ON component.id = NEW.component_id
         AND component.owner_id = candidate.owner_id
        JOIN component_repo.artifacts source_artifact
          ON source_artifact.id = import_job.source_artifact_id
         AND source_artifact.owner_id = candidate.owner_id
        LEFT JOIN component_repo.artifacts exchange_artifact
          ON exchange_artifact.id = import_job.exchange_artifact_id
         AND exchange_artifact.owner_id = candidate.owner_id
        WHERE candidate.id = NEW.component_candidate_id
          AND candidate.status IN ('pending_review', 'accepted')
          AND import_job.status = 'succeeded'
          AND import_job.target_component_id = NEW.component_id
          AND import_job.parser_version = snapshot.parser_version
          AND NEW.source_artifact_id = import_job.source_artifact_id
          AND NEW.exchange_artifact_id IS NOT DISTINCT FROM import_job.exchange_artifact_id
          AND NEW.scene_snapshot_id = snapshot.id
          AND NEW.parser_version = snapshot.parser_version
          AND NEW.part_library_version_id IS NOT DISTINCT FROM import_job.part_library_version_id
          AND NEW.interface_signature = candidate.interface_signature
          AND NEW.structure_hash = candidate.structure_hash
          AND NEW.geometry_hash = candidate.geometry_hash
          AND source_artifact.source_kind = 'source'
          AND source_artifact.immutable
          AND source_artifact.verification_status = 'verified'
          AND source_artifact.deleted_at IS NULL
          AND (
              import_job.exchange_artifact_id IS NULL
              OR (
                  exchange_artifact.source_kind = 'source'
                  AND exchange_artifact.immutable
                  AND exchange_artifact.verification_status = 'verified'
                  AND exchange_artifact.deleted_at IS NULL
              )
          )
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'user component version source lineage is invalid';
    END IF;
    RETURN NEW;
END;
$$;
-- +goose StatementEnd

CREATE TRIGGER component_versions_require_source_integrity
BEFORE INSERT OR UPDATE OF component_id, component_candidate_id, source_artifact_id,
    exchange_artifact_id, scene_snapshot_id, parser_version, part_library_version_id,
    interface_signature, structure_hash, geometry_hash
ON component_repo.component_versions
FOR EACH ROW EXECUTE FUNCTION component_repo.require_component_version_source_integrity();

-- +goose Down

DROP TRIGGER IF EXISTS component_versions_require_source_integrity
    ON component_repo.component_versions;
DROP FUNCTION IF EXISTS component_repo.require_component_version_source_integrity();

ALTER TABLE component_repo.candidates
    DROP CONSTRAINT IF EXISTS candidates_materialized_hashes_check,
    DROP CONSTRAINT IF EXISTS candidates_snapshot_import_fk,
    DROP CONSTRAINT IF EXISTS candidates_import_owner_fk,
    DROP COLUMN IF EXISTS geometry_hash,
    DROP COLUMN IF EXISTS structure_hash,
    DROP COLUMN IF EXISTS interface_signature;

ALTER TABLE component_repo.scene_snapshots
    DROP CONSTRAINT IF EXISTS scene_snapshots_id_import_unique;

ALTER TABLE component_repo.imports
    DROP CONSTRAINT IF EXISTS imports_exchange_owner_fk,
    DROP CONSTRAINT IF EXISTS imports_source_owner_fk,
    DROP CONSTRAINT IF EXISTS imports_id_owner_unique;

ALTER TABLE component_repo.artifacts
    DROP CONSTRAINT IF EXISTS artifacts_id_owner_unique;
