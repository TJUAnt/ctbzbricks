-- +goose Up

ALTER TABLE component_repo.tasks
    ADD CONSTRAINT tasks_id_owner_unique UNIQUE (id, owner_id);

CREATE TABLE component_repo.task_dependencies (
    task_id uuid NOT NULL,
    prerequisite_task_id uuid NOT NULL,
    owner_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (task_id, prerequisite_task_id),
    CONSTRAINT task_dependencies_not_self_check CHECK (task_id <> prerequisite_task_id),
    CONSTRAINT task_dependencies_task_owner_fk
        FOREIGN KEY (task_id, owner_id)
        REFERENCES component_repo.tasks (id, owner_id) ON DELETE CASCADE,
    CONSTRAINT task_dependencies_prerequisite_owner_fk
        FOREIGN KEY (prerequisite_task_id, owner_id)
        REFERENCES component_repo.tasks (id, owner_id) ON DELETE CASCADE
);

CREATE INDEX task_dependencies_prerequisite_idx
    ON component_repo.task_dependencies (prerequisite_task_id, task_id);

ALTER TABLE component_repo.artifacts
    ADD COLUMN derived_from_artifact_id uuid,
    ADD CONSTRAINT artifacts_derived_source_owner_fk
        FOREIGN KEY (derived_from_artifact_id, owner_id)
        REFERENCES component_repo.artifacts (id, owner_id),
    ADD CONSTRAINT artifacts_derived_lineage_check CHECK (
        derived_from_artifact_id IS NULL OR source_kind = 'derived'
    );

ALTER TABLE component_repo.imports
    ADD COLUMN upload_session_id uuid,
    ADD COLUMN parse_task_id uuid,
    ADD CONSTRAINT imports_upload_session_unique UNIQUE (upload_session_id),
    ADD CONSTRAINT imports_parse_task_unique UNIQUE (parse_task_id),
    ADD CONSTRAINT imports_upload_session_fk
        FOREIGN KEY (upload_session_id)
        REFERENCES component_repo.upload_sessions (id),
    ADD CONSTRAINT imports_parse_task_owner_fk
        FOREIGN KEY (parse_task_id, owner_id)
        REFERENCES component_repo.tasks (id, owner_id),
    ADD CONSTRAINT imports_pipeline_required_check CHECK (
        upload_session_id IS NOT NULL
        AND parse_task_id IS NOT NULL
        AND parser_version IS NOT NULL
        AND parser_version <> ''
    );

ALTER TABLE component_repo.scene_snapshots
    ADD CONSTRAINT scene_snapshots_import_unique UNIQUE (import_id),
    ADD CONSTRAINT scene_snapshots_document_object_check CHECK (jsonb_typeof(document) = 'object'),
    ADD CONSTRAINT scene_snapshots_bom_object_check CHECK (jsonb_typeof(bom) = 'object'),
    ADD CONSTRAINT scene_snapshots_parse_issues_array_check CHECK (jsonb_typeof(parse_issues) = 'array');

ALTER TABLE component_repo.candidates
    ALTER COLUMN interface_signature SET NOT NULL,
    ALTER COLUMN structure_hash SET NOT NULL,
    ALTER COLUMN geometry_hash SET NOT NULL,
    ADD CONSTRAINT candidates_import_unique UNIQUE (import_id),
    ADD CONSTRAINT candidates_summary_object_check CHECK (jsonb_typeof(summary) = 'object'),
    ADD CONSTRAINT candidates_review_decisions_object_check CHECK (
        jsonb_typeof(review_decisions) = 'object'
    );

CREATE UNIQUE INDEX component_versions_candidate_active_unique
    ON component_repo.component_versions (component_candidate_id)
    WHERE component_candidate_id IS NOT NULL AND deleted_at IS NULL;

-- +goose StatementBegin
CREATE FUNCTION component_repo.require_import_pipeline_integrity()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM component_repo.upload_sessions upload_session
        JOIN component_repo.tasks parse_task
          ON parse_task.id = NEW.parse_task_id
         AND parse_task.owner_id = NEW.owner_id
        WHERE upload_session.id = NEW.upload_session_id
          AND upload_session.owner_id = NEW.owner_id
          AND upload_session.locale = NEW.locale
          AND upload_session.timezone = NEW.timezone
          AND (
              upload_session.target_component_id IS NULL
              OR upload_session.target_component_id = NEW.target_component_id
          )
          AND upload_session.base_version_id IS NOT DISTINCT FROM NEW.base_version_id
          AND parse_task.task_type = 'component.import.parse'
          AND parse_task.locale = NEW.locale
          AND parse_task.timezone = NEW.timezone
          AND parse_task.payload ->> 'importId' = NEW.id::text
          AND parse_task.payload ->> 'parserVersion' = NEW.parser_version
          AND EXISTS (
              SELECT 1
              FROM component_repo.task_dependencies dependency
              JOIN component_repo.tasks prerequisite
                ON prerequisite.id = dependency.prerequisite_task_id
              WHERE dependency.task_id = parse_task.id
                AND prerequisite.task_type = 'component.artifact.verify'
                AND prerequisite.payload ->> 'artifactId' = NEW.source_artifact_id::text
          )
          AND (
              NEW.exchange_artifact_id IS NULL
              OR EXISTS (
                  SELECT 1
                  FROM component_repo.artifacts exchange_artifact
                  WHERE exchange_artifact.id = NEW.exchange_artifact_id
                    AND exchange_artifact.owner_id = NEW.owner_id
                    AND exchange_artifact.source_kind = 'derived'
                    AND exchange_artifact.derived_from_artifact_id = NEW.source_artifact_id
                    AND exchange_artifact.verification_status = 'verified'
              )
              OR EXISTS (
                  SELECT 1
                  FROM component_repo.task_dependencies dependency
                  JOIN component_repo.tasks prerequisite
                    ON prerequisite.id = dependency.prerequisite_task_id
                  WHERE dependency.task_id = parse_task.id
                    AND prerequisite.task_type = 'component.artifact.verify'
                    AND prerequisite.payload ->> 'artifactId' = NEW.exchange_artifact_id::text
              )
          )
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'component import pipeline lineage is invalid';
    END IF;
    RETURN NEW;
END;
$$;
-- +goose StatementEnd

CREATE TRIGGER imports_require_pipeline_integrity
BEFORE INSERT OR UPDATE OF owner_id, upload_session_id, parse_task_id, source_artifact_id,
    exchange_artifact_id, parser_version, locale, timezone
ON component_repo.imports
FOR EACH ROW EXECUTE FUNCTION component_repo.require_import_pipeline_integrity();

-- +goose StatementBegin
CREATE FUNCTION component_repo.protect_scene_snapshot()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION USING
        ERRCODE = '23514',
        MESSAGE = 'component scene snapshots are immutable';
END;
$$;
-- +goose StatementEnd

CREATE TRIGGER scene_snapshots_protect_immutable
BEFORE UPDATE OR DELETE ON component_repo.scene_snapshots
FOR EACH ROW EXECUTE FUNCTION component_repo.protect_scene_snapshot();

DROP TRIGGER component_versions_require_source_integrity
    ON component_repo.component_versions;
DROP FUNCTION component_repo.require_component_version_source_integrity();

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
                  exchange_artifact.immutable
                  AND exchange_artifact.verification_status = 'verified'
                  AND exchange_artifact.deleted_at IS NULL
                  AND (
                      exchange_artifact.source_kind = 'source'
                      OR (
                          exchange_artifact.source_kind = 'derived'
                          AND exchange_artifact.derived_from_artifact_id = source_artifact.id
                      )
                  )
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

-- +goose StatementBegin
CREATE OR REPLACE FUNCTION component_repo.protect_task_transition()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'queued' OR NEW.attempts <> 0 THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'task must start queued';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.status IN ('succeeded', 'failed', 'cancelled') THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'terminal task is immutable';
    END IF;

    IF NOT (
        NEW.status = OLD.status
        OR (OLD.status = 'queued' AND NEW.status IN ('running', 'cancelled'))
        OR (OLD.status = 'queued' AND NEW.status = 'failed' AND EXISTS (
            SELECT 1
            FROM component_repo.task_dependencies dependency
            JOIN component_repo.tasks prerequisite
              ON prerequisite.id = dependency.prerequisite_task_id
            WHERE dependency.task_id = OLD.id
              AND prerequisite.status IN ('failed', 'cancelled')
        ))
        OR (OLD.status = 'running' AND NEW.status IN ('queued', 'succeeded', 'failed', 'cancelled'))
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'invalid task status transition';
    END IF;

    IF OLD.status = 'queued' AND NEW.status = 'running' THEN
        IF NEW.attempts <> OLD.attempts + 1 THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'task claim must increment attempts';
        END IF;
    ELSIF NEW.attempts <> OLD.attempts THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'task attempts may only change on claim';
    END IF;

    RETURN NEW;
END;
$$;
-- +goose StatementEnd

-- +goose StatementBegin
CREATE FUNCTION component_repo.sync_import_parse_task_state()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.task_type <> 'component.import.parse' OR NEW.status = OLD.status THEN
        RETURN NEW;
    END IF;

    IF NEW.status = 'running' THEN
        UPDATE component_repo.imports
        SET status = 'running', started_at = COALESCE(started_at, now()),
            failure_code = NULL, failure_params = NULL
        WHERE parse_task_id = NEW.id AND status = 'queued';
    ELSIF NEW.status = 'queued' THEN
        UPDATE component_repo.imports
        SET status = 'queued'
        WHERE parse_task_id = NEW.id AND status = 'running';
    ELSIF NEW.status = 'failed' THEN
        UPDATE component_repo.imports
        SET status = 'failed', failure_code = COALESCE(NEW.error_code, 'common.internal_error'),
            failure_params = COALESCE(NEW.error_params, '{}'::jsonb), completed_at = now()
        WHERE parse_task_id = NEW.id AND status IN ('queued', 'running');
    ELSIF NEW.status = 'cancelled' THEN
        UPDATE component_repo.imports
        SET status = 'cancelled', failure_code = NULL, failure_params = NULL,
            completed_at = now()
        WHERE parse_task_id = NEW.id AND status IN ('queued', 'running');
    ELSIF NEW.status = 'succeeded' AND EXISTS (
        SELECT 1 FROM component_repo.imports
        WHERE parse_task_id = NEW.id AND status <> 'succeeded'
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'parse task cannot succeed before its import result';
    END IF;
    RETURN NEW;
END;
$$;
-- +goose StatementEnd

CREATE TRIGGER tasks_sync_import_parse_state
AFTER UPDATE OF status ON component_repo.tasks
FOR EACH ROW EXECUTE FUNCTION component_repo.sync_import_parse_task_state();

ALTER TABLE component_repo.task_dependencies ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON component_repo.task_dependencies FROM PUBLIC;

-- +goose Down

DROP TRIGGER IF EXISTS imports_require_pipeline_integrity ON component_repo.imports;
DROP FUNCTION IF EXISTS component_repo.require_import_pipeline_integrity();

DROP TRIGGER IF EXISTS tasks_sync_import_parse_state ON component_repo.tasks;
DROP FUNCTION IF EXISTS component_repo.sync_import_parse_task_state();

DROP TRIGGER IF EXISTS component_versions_require_source_integrity
    ON component_repo.component_versions;
DROP FUNCTION IF EXISTS component_repo.require_component_version_source_integrity();

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

DROP TRIGGER IF EXISTS scene_snapshots_protect_immutable
    ON component_repo.scene_snapshots;
DROP FUNCTION IF EXISTS component_repo.protect_scene_snapshot();

DROP INDEX IF EXISTS component_repo.component_versions_candidate_active_unique;

ALTER TABLE component_repo.candidates
    DROP CONSTRAINT IF EXISTS candidates_review_decisions_object_check,
    DROP CONSTRAINT IF EXISTS candidates_summary_object_check,
    DROP CONSTRAINT IF EXISTS candidates_import_unique,
    ALTER COLUMN geometry_hash DROP NOT NULL,
    ALTER COLUMN structure_hash DROP NOT NULL,
    ALTER COLUMN interface_signature DROP NOT NULL;

ALTER TABLE component_repo.scene_snapshots
    DROP CONSTRAINT IF EXISTS scene_snapshots_parse_issues_array_check,
    DROP CONSTRAINT IF EXISTS scene_snapshots_bom_object_check,
    DROP CONSTRAINT IF EXISTS scene_snapshots_document_object_check,
    DROP CONSTRAINT IF EXISTS scene_snapshots_import_unique;

ALTER TABLE component_repo.imports
    DROP CONSTRAINT IF EXISTS imports_pipeline_required_check,
    DROP CONSTRAINT IF EXISTS imports_parse_task_owner_fk,
    DROP CONSTRAINT IF EXISTS imports_upload_session_fk,
    DROP CONSTRAINT IF EXISTS imports_parse_task_unique,
    DROP CONSTRAINT IF EXISTS imports_upload_session_unique,
    DROP COLUMN IF EXISTS parse_task_id,
    DROP COLUMN IF EXISTS upload_session_id;

ALTER TABLE component_repo.artifacts
    DROP CONSTRAINT IF EXISTS artifacts_derived_lineage_check,
    DROP CONSTRAINT IF EXISTS artifacts_derived_source_owner_fk,
    DROP COLUMN IF EXISTS derived_from_artifact_id;

-- +goose StatementBegin
CREATE OR REPLACE FUNCTION component_repo.protect_task_transition()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'queued' OR NEW.attempts <> 0 THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'task must start queued';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.status IN ('succeeded', 'failed', 'cancelled') THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'terminal task is immutable';
    END IF;

    IF NOT (
        NEW.status = OLD.status
        OR (OLD.status = 'queued' AND NEW.status IN ('running', 'cancelled'))
        OR (OLD.status = 'running' AND NEW.status IN ('queued', 'succeeded', 'failed', 'cancelled'))
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'invalid task status transition';
    END IF;

    IF OLD.status = 'queued' AND NEW.status = 'running' THEN
        IF NEW.attempts <> OLD.attempts + 1 THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'task claim must increment attempts';
        END IF;
    ELSIF NEW.attempts <> OLD.attempts THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'task attempts may only change on claim';
    END IF;

    RETURN NEW;
END;
$$;
-- +goose StatementEnd

DROP TABLE IF EXISTS component_repo.task_dependencies;

ALTER TABLE component_repo.tasks
    DROP CONSTRAINT IF EXISTS tasks_id_owner_unique;
