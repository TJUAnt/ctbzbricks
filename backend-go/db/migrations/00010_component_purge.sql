-- +goose Up

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
        IF current_setting('component_repo.component_redaction', true) = 'on'
           AND NEW.owner_id = OLD.owner_id
           AND NEW.task_type = OLD.task_type
           AND NEW.status = OLD.status
           AND NEW.attempts = OLD.attempts
           AND NEW.max_attempts = OLD.max_attempts
           AND NEW.task_job_id = OLD.task_job_id
           AND NEW.execution_number = OLD.execution_number
           AND NEW.retry_of_task_id IS NOT DISTINCT FROM OLD.retry_of_task_id
           AND NEW.created_by = OLD.created_by
           AND NEW.created_at = OLD.created_at
           AND NEW.started_at IS NOT DISTINCT FROM OLD.started_at
           AND NEW.finished_at IS NOT DISTINCT FROM OLD.finished_at THEN
            RETURN NEW;
        END IF;

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
CREATE OR REPLACE FUNCTION component_repo.protect_source_artifact()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.source_kind = 'source' THEN
            RAISE EXCEPTION USING
                ERRCODE = '23514',
                MESSAGE = 'source artifact cannot be deleted';
        END IF;
        RETURN OLD;
    END IF;

    IF OLD.source_kind = 'source'
       AND current_setting('component_repo.component_redaction', true) = 'on'
       AND (
           NEW.owner_id, NEW.artifact_type, NEW.source_kind, NEW.original_filename,
           NEW.storage_provider, NEW.storage_bucket, NEW.storage_key, NEW.sha256,
           NEW.file_size, NEW.mime_type, NEW.immutable, NEW.uploaded_by,
           NEW.uploaded_at
       ) IS DISTINCT FROM (
           OLD.owner_id, OLD.artifact_type, OLD.source_kind, OLD.original_filename,
           OLD.storage_provider, OLD.storage_bucket, OLD.storage_key, OLD.sha256,
           OLD.file_size, OLD.mime_type, OLD.immutable, OLD.uploaded_by,
           OLD.uploaded_at
       ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'source artifact structure is immutable';
    ELSIF OLD.source_kind = 'source'
       AND current_setting('component_repo.component_redaction', true) IS DISTINCT FROM 'on'
       AND (
           NEW.owner_id, NEW.artifact_type, NEW.source_kind, NEW.original_filename,
           NEW.storage_provider, NEW.storage_bucket, NEW.storage_key, NEW.sha256,
           NEW.file_size, NEW.mime_type, NEW.immutable, NEW.uploaded_by,
           NEW.uploaded_at, NEW.deleted_at
       ) IS DISTINCT FROM (
           OLD.owner_id, OLD.artifact_type, OLD.source_kind, OLD.original_filename,
           OLD.storage_provider, OLD.storage_bucket, OLD.storage_key, OLD.sha256,
           OLD.file_size, OLD.mime_type, OLD.immutable, OLD.uploaded_by,
           OLD.uploaded_at, OLD.deleted_at
       ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'source artifact structure is immutable';
    END IF;

    IF OLD.source_kind <> 'source' AND NEW.source_kind = 'source' THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'derived artifact cannot replace source artifact';
    END IF;

    IF OLD.verification_status IN ('verified', 'failed')
       AND NEW.verification_status <> OLD.verification_status THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'artifact verification status is terminal';
    END IF;

    RETURN NEW;
END;
$$;
-- +goose StatementEnd

-- +goose StatementBegin
CREATE OR REPLACE FUNCTION component_repo.protect_published_component_version()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.status IN ('published', 'deprecated', 'archived')
       AND current_setting('component_repo.component_redaction', true) = 'on' THEN
        IF (NEW.component_id, NEW.component_candidate_id, NEW.revision,
            NEW.source_artifact_id, NEW.exchange_artifact_id, NEW.scene_snapshot_id,
            NEW.parser_version, NEW.part_library_version_id, NEW.interface_signature,
            NEW.structure_hash, NEW.geometry_hash, NEW.status)
           IS DISTINCT FROM
           (OLD.component_id, OLD.component_candidate_id, OLD.revision,
            OLD.source_artifact_id, OLD.exchange_artifact_id, OLD.scene_snapshot_id,
            OLD.parser_version, OLD.part_library_version_id, OLD.interface_signature,
            OLD.structure_hash, OLD.geometry_hash, OLD.status) THEN
            RAISE EXCEPTION USING
                ERRCODE = '23514',
                MESSAGE = 'published component version structure is immutable';
        END IF;
        RETURN NEW;
    END IF;

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

-- +goose StatementBegin
CREATE FUNCTION component_repo.redact_owned_component(
    p_actor_id uuid,
    p_component_id uuid,
    p_current_task_id uuid
)
RETURNS TABLE (
    component_redacted boolean,
    versions_redacted integer,
    artifacts_tombstoned integer,
    related_tasks_redacted integer
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_component_id uuid;
    v_version_ids uuid[] := ARRAY[]::uuid[];
    v_candidate_ids uuid[] := ARRAY[]::uuid[];
    v_import_ids uuid[] := ARRAY[]::uuid[];
    v_upload_session_ids uuid[] := ARRAY[]::uuid[];
    v_artifact_ids uuid[] := ARRAY[]::uuid[];
    v_task_ids uuid[] := ARRAY[]::uuid[];
    v_tombstone_artifact_ids uuid[] := ARRAY[]::uuid[];
    v_count integer;
BEGIN
    SELECT component.id
    INTO v_component_id
    FROM component_repo.components component
    WHERE component.id = p_component_id
      AND component.owner_id = p_actor_id
      AND component.content_kind = 'user'
    FOR UPDATE;

    IF v_component_id IS NULL THEN
        RETURN QUERY SELECT false, 0, 0, 0;
        RETURN;
    END IF;

    SELECT COALESCE(array_agg(version.id), ARRAY[]::uuid[])
    INTO v_version_ids
    FROM component_repo.component_versions version
    WHERE version.component_id = p_component_id;

    SELECT COALESCE(array_agg(DISTINCT candidate.id), ARRAY[]::uuid[])
    INTO v_candidate_ids
    FROM component_repo.candidates candidate
    WHERE candidate.id IN (
        SELECT version.component_candidate_id
        FROM component_repo.component_versions version
        WHERE version.component_id = p_component_id
          AND version.component_candidate_id IS NOT NULL
    );

    SELECT COALESCE(array_agg(DISTINCT import_job.id), ARRAY[]::uuid[])
    INTO v_import_ids
    FROM component_repo.imports import_job
    WHERE import_job.owner_id = p_actor_id
      AND (
          import_job.target_component_id = p_component_id
          OR import_job.base_version_id = ANY(v_version_ids)
          OR import_job.id IN (
              SELECT candidate.import_id
              FROM component_repo.candidates candidate
              WHERE candidate.id = ANY(v_candidate_ids)
          )
      );

    SELECT COALESCE(array_agg(DISTINCT candidate.id), ARRAY[]::uuid[])
    INTO v_candidate_ids
    FROM component_repo.candidates candidate
    WHERE candidate.owner_id = p_actor_id
      AND (
          candidate.import_id = ANY(v_import_ids)
          OR candidate.id = ANY(v_candidate_ids)
      );

    SELECT COALESCE(array_agg(DISTINCT upload_session.id), ARRAY[]::uuid[])
    INTO v_upload_session_ids
    FROM component_repo.upload_sessions upload_session
    WHERE upload_session.owner_id = p_actor_id
      AND (
          upload_session.target_component_id = p_component_id
          OR upload_session.base_version_id = ANY(v_version_ids)
      );

    WITH RECURSIVE base_artifacts AS (
        SELECT version.source_artifact_id AS id
        FROM component_repo.component_versions version
        WHERE version.id = ANY(v_version_ids)
        UNION
        SELECT version.exchange_artifact_id
        FROM component_repo.component_versions version
        WHERE version.id = ANY(v_version_ids)
          AND version.exchange_artifact_id IS NOT NULL
        UNION
        SELECT version.preview_artifact_id
        FROM component_repo.component_versions version
        WHERE version.id = ANY(v_version_ids)
          AND version.preview_artifact_id IS NOT NULL
        UNION
        SELECT import_job.source_artifact_id
        FROM component_repo.imports import_job
        WHERE import_job.id = ANY(v_import_ids)
        UNION
        SELECT import_job.exchange_artifact_id
        FROM component_repo.imports import_job
        WHERE import_job.id = ANY(v_import_ids)
          AND import_job.exchange_artifact_id IS NOT NULL
        UNION
        SELECT upload_file.artifact_id
        FROM component_repo.upload_session_files upload_file
        WHERE upload_file.upload_session_id = ANY(v_upload_session_ids)
          AND upload_file.artifact_id IS NOT NULL
    ), artifact_tree AS (
        SELECT artifact.id
        FROM component_repo.artifacts artifact
        JOIN base_artifacts base ON base.id = artifact.id
        WHERE artifact.owner_id = p_actor_id
        UNION
        SELECT child.id
        FROM component_repo.artifacts child
        JOIN artifact_tree parent ON child.derived_from_artifact_id = parent.id
        WHERE child.owner_id = p_actor_id
    )
    SELECT COALESCE(array_agg(DISTINCT id), ARRAY[]::uuid[])
    INTO v_artifact_ids
    FROM artifact_tree;

    SELECT COALESCE(array_agg(DISTINCT task.id), ARRAY[]::uuid[])
    INTO v_task_ids
    FROM component_repo.tasks task
    WHERE task.owner_id = p_actor_id
      AND task.id IS DISTINCT FROM p_current_task_id
      AND (
          task.id IN (
              SELECT import_job.parse_task_id
              FROM component_repo.imports import_job
              WHERE import_job.id = ANY(v_import_ids)
                AND import_job.parse_task_id IS NOT NULL
          )
          OR task.id IN (
              SELECT candidate.relation_detection_task_id
              FROM component_repo.candidates candidate
              WHERE candidate.id = ANY(v_candidate_ids)
                AND candidate.relation_detection_task_id IS NOT NULL
          )
          OR task.id IN (
              SELECT version.preview_task_id
              FROM component_repo.component_versions version
              WHERE version.id = ANY(v_version_ids)
                AND version.preview_task_id IS NOT NULL
          )
          OR task.id IN (
              SELECT report.task_id
              FROM component_repo.validation_reports report
              WHERE report.component_version_id = ANY(v_version_ids)
                 OR report.component_candidate_id = ANY(v_candidate_ids)
          )
          OR task.result_artifact_id = ANY(v_artifact_ids)
          OR task.payload ->> 'componentId' = p_component_id::text
          OR EXISTS (
              SELECT 1
              FROM unnest(v_version_ids) AS version_id
              WHERE task.payload ->> 'versionId' = version_id::text
          )
          OR EXISTS (
              SELECT 1
              FROM unnest(v_candidate_ids) AS candidate_id
              WHERE task.payload ->> 'candidateId' = candidate_id::text
          )
          OR EXISTS (
              SELECT 1
              FROM unnest(v_import_ids) AS import_id
              WHERE task.payload ->> 'importId' = import_id::text
          )
          OR EXISTS (
              SELECT 1
              FROM unnest(v_artifact_ids) AS artifact_id
              WHERE task.payload ->> 'artifactId' = artifact_id::text
          )
      );

    SELECT COALESCE(array_agg(DISTINCT artifact.id), ARRAY[]::uuid[])
    INTO v_tombstone_artifact_ids
    FROM component_repo.artifacts artifact
    WHERE artifact.id = ANY(v_artifact_ids)
      AND artifact.owner_id = p_actor_id
      AND NOT EXISTS (
          SELECT 1
          FROM component_repo.component_versions version
          WHERE version.id <> ALL(v_version_ids)
            AND version.deleted_at IS NULL
            AND (
                version.source_artifact_id = artifact.id
                OR version.exchange_artifact_id = artifact.id
                OR version.preview_artifact_id = artifact.id
            )
      )
      AND NOT EXISTS (
          SELECT 1
          FROM component_repo.imports import_job
          WHERE import_job.id <> ALL(v_import_ids)
            AND (
                import_job.source_artifact_id = artifact.id
                OR import_job.exchange_artifact_id = artifact.id
            )
      )
      AND NOT EXISTS (
          SELECT 1
          FROM component_repo.upload_session_files upload_file
          WHERE upload_file.upload_session_id <> ALL(v_upload_session_ids)
            AND upload_file.artifact_id = artifact.id
      )
      AND NOT EXISTS (
          SELECT 1
          FROM component_repo.tasks task
          WHERE task.id <> ALL(v_task_ids)
            AND task.id IS DISTINCT FROM p_current_task_id
            AND task.result_artifact_id = artifact.id
      );

    PERFORM set_config('component_repo.component_redaction', 'on', true);

    UPDATE component_repo.components component
    SET status = 'archived',
        current_version_id = NULL,
        name = '[deleted component]',
        description = NULL,
        tags = ARRAY[]::text[],
        category = NULL,
        logical_width_stud = NULL,
        logical_depth_stud = NULL,
        logical_height_plate = NULL,
        metadata = jsonb_build_object(
            'redacted', true,
            'redactedBy', p_actor_id::text,
            'redactionVersion', 'component-redaction-v1'
        ),
        deleted_at = COALESCE(deleted_at, now()),
        deleted_by = COALESCE(deleted_by, p_actor_id),
        updated_at = now()
    WHERE component.id = p_component_id
      AND component.owner_id = p_actor_id
      AND component.content_kind = 'user';
    GET DIAGNOSTICS v_count = ROW_COUNT;
    component_redacted := v_count = 1;

    UPDATE component_repo.component_versions version
    SET version_label = 'deleted-' || version.id::text,
        release_note = NULL,
        release_note_locale = NULL,
        metadata = jsonb_build_object(
            'redacted', true,
            'redactionVersion', 'component-redaction-v1'
        ),
        deleted_at = COALESCE(deleted_at, now()),
        deleted_by = COALESCE(deleted_by, p_actor_id)
    WHERE version.id = ANY(v_version_ids)
      AND version.component_id = p_component_id;
    GET DIAGNOSTICS versions_redacted = ROW_COUNT;

    UPDATE component_repo.artifacts artifact
    SET deleted_at = COALESCE(deleted_at, now()),
        metadata = jsonb_build_object(
            'redacted', true,
            'redactionVersion', 'component-redaction-v1'
        )
    WHERE artifact.id = ANY(v_tombstone_artifact_ids)
      AND artifact.owner_id = p_actor_id;
    GET DIAGNOSTICS artifacts_tombstoned = ROW_COUNT;

    UPDATE component_repo.task_events event
    SET params = CASE WHEN event.code IS NULL THEN NULL ELSE '{}'::jsonb END
    WHERE event.task_id = ANY(v_task_ids);

    UPDATE component_repo.outbox_events event
    SET payload = jsonb_build_object('redactedTaskId', event.aggregate_id::text),
        last_error_params = CASE WHEN event.last_error_code IS NULL THEN NULL ELSE '{}'::jsonb END
    WHERE event.aggregate_type = 'task'
      AND event.aggregate_id = ANY(v_task_ids);

    UPDATE component_repo.tasks task
    SET payload = jsonb_build_object('redactedComponentId', p_component_id::text),
        result = NULL,
        result_artifact_id = NULL,
        progress_params = CASE WHEN task.progress_code IS NULL THEN NULL ELSE '{}'::jsonb END,
        error_params = CASE WHEN task.error_code IS NULL THEN NULL ELSE '{}'::jsonb END,
        updated_at = now()
    WHERE task.id = ANY(v_task_ids);
    GET DIAGNOSTICS related_tasks_redacted = ROW_COUNT;

    UPDATE component_repo.task_jobs job
    SET logical_key = 'redacted:' || job.id::text,
        input_hash = repeat('0', 64),
        successful_task_id = NULL,
        updated_at = now()
    WHERE job.id IN (
        SELECT DISTINCT task.task_job_id
        FROM component_repo.tasks task
        WHERE task.id = ANY(v_task_ids)
    );

    RETURN NEXT;
END;
$$;
-- +goose StatementEnd

-- +goose Down

DROP FUNCTION IF EXISTS component_repo.redact_owned_component(uuid, uuid, uuid);

-- +goose StatementBegin
CREATE OR REPLACE FUNCTION component_repo.protect_published_component_version()
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

-- +goose StatementBegin
CREATE OR REPLACE FUNCTION component_repo.protect_source_artifact()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.source_kind = 'source' THEN
            RAISE EXCEPTION USING
                ERRCODE = '23514',
                MESSAGE = 'source artifact cannot be deleted';
        END IF;
        RETURN OLD;
    END IF;

    IF OLD.source_kind = 'source'
       AND (
           NEW.owner_id, NEW.artifact_type, NEW.source_kind, NEW.original_filename,
           NEW.storage_provider, NEW.storage_bucket, NEW.storage_key, NEW.sha256,
           NEW.file_size, NEW.mime_type, NEW.immutable, NEW.uploaded_by,
           NEW.uploaded_at, NEW.deleted_at
       ) IS DISTINCT FROM (
           OLD.owner_id, OLD.artifact_type, OLD.source_kind, OLD.original_filename,
           OLD.storage_provider, OLD.storage_bucket, OLD.storage_key, OLD.sha256,
           OLD.file_size, OLD.mime_type, OLD.immutable, OLD.uploaded_by,
           OLD.uploaded_at, OLD.deleted_at
       ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'source artifact structure is immutable';
    END IF;

    IF OLD.source_kind <> 'source' AND NEW.source_kind = 'source' THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'derived artifact cannot replace source artifact';
    END IF;

    IF OLD.verification_status IN ('verified', 'failed')
       AND NEW.verification_status <> OLD.verification_status THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'artifact verification status is terminal';
    END IF;

    RETURN NEW;
END;
$$;
-- +goose StatementEnd

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
