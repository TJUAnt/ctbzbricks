-- +goose Up

-- +goose StatementBegin
CREATE FUNCTION component_repo.protect_source_artifact()
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

CREATE TRIGGER artifacts_protect_source_update
BEFORE UPDATE ON component_repo.artifacts
FOR EACH ROW EXECUTE FUNCTION component_repo.protect_source_artifact();

CREATE TRIGGER artifacts_protect_source_delete
BEFORE DELETE ON component_repo.artifacts
FOR EACH ROW EXECUTE FUNCTION component_repo.protect_source_artifact();

-- +goose Down

DROP TRIGGER IF EXISTS artifacts_protect_source_delete ON component_repo.artifacts;
DROP TRIGGER IF EXISTS artifacts_protect_source_update ON component_repo.artifacts;
DROP FUNCTION IF EXISTS component_repo.protect_source_artifact();
