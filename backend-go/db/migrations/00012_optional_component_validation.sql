-- +goose Up

-- 发布与质量验证现在是两个独立动作：owner 可以直接发布草稿，验证报告只作为可选的质量状态。
DROP TRIGGER IF EXISTS component_versions_require_valid_publish_report
    ON component_repo.component_versions;
DROP FUNCTION IF EXISTS component_repo.require_valid_publish_report();

-- +goose Down

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
