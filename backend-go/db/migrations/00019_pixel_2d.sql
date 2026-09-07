-- +goose Up
-- pixel_2d 是独立领域；Goose 独占新 schema，不修改 Alembic 所属 legacy public 对象。
CREATE SCHEMA pixel_2d;
CREATE TABLE pixel_2d.catalogs (
 hash text PRIMARY KEY CHECK (hash ~ '^[0-9a-f]{64}$'),
 document jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE pixel_2d.blobs (
 id uuid PRIMARY KEY,
 owner_id uuid NOT NULL,
 object_key text NOT NULL UNIQUE,
 bucket text NOT NULL,
 kind text NOT NULL CHECK(kind IN ('source','input','project','preview','design','ldraw','plan')),
 sha256 text NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'),
 byte_size bigint NOT NULL CHECK(byte_size>=0),
 content_type text NOT NULL,
 status text NOT NULL DEFAULT 'reserved' CHECK(status IN ('reserved','ready')),
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(id,owner_id)
);
CREATE TABLE pixel_2d.projects (
 id uuid PRIMARY KEY,
 owner_id uuid NOT NULL,
 name text NOT NULL,
 content_locale text NOT NULL CHECK(content_locale IN ('zh-CN','en-US')),
 source_name text NOT NULL,
 source_blob_id uuid NOT NULL,
 grid_width integer NOT NULL CHECK(grid_width BETWEEN 1 AND 128),
 grid_height integer NOT NULL CHECK(grid_height BETWEEN 1 AND 128),
 color_count integer NOT NULL,
 current_revision_id uuid,
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(source_blob_id,owner_id) REFERENCES pixel_2d.blobs(id,owner_id),
 UNIQUE(id,owner_id)
);
-- 项目列表从 actor 的权威所有权索引驱动；精确排序带 UUID 唯一消歧。
CREATE INDEX pixel_projects_owner_created_idx ON pixel_2d.projects(owner_id,created_at DESC,id DESC);
CREATE TABLE pixel_2d.revisions (
 id uuid PRIMARY KEY,
 project_id uuid NOT NULL,
 owner_id uuid NOT NULL,
 parent_revision_id uuid,
 input_blob_id uuid NOT NULL,
 task_id uuid NOT NULL REFERENCES component_repo.tasks(id),
 document_blob_id uuid,
 preview_blob_id uuid,
 settings jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(project_id,owner_id) REFERENCES pixel_2d.projects(id,owner_id),
 FOREIGN KEY(input_blob_id,owner_id) REFERENCES pixel_2d.blobs(id,owner_id),
 FOREIGN KEY(document_blob_id,owner_id) REFERENCES pixel_2d.blobs(id,owner_id),
 FOREIGN KEY(preview_blob_id,owner_id) REFERENCES pixel_2d.blobs(id,owner_id),
 UNIQUE(id,project_id,owner_id)
);
ALTER TABLE pixel_2d.projects ADD CONSTRAINT pixel_project_revision_fk FOREIGN KEY(current_revision_id,id,owner_id) REFERENCES pixel_2d.revisions(id,project_id,owner_id);
ALTER TABLE pixel_2d.revisions ADD CONSTRAINT pixel_parent_revision_fk FOREIGN KEY(parent_revision_id,project_id,owner_id) REFERENCES pixel_2d.revisions(id,project_id,owner_id);
-- 已物化修订和目录不可变；任务重试只允许首次 CAS 填写产物，避免旧 attempt 覆盖新版。
-- +goose StatementBegin
CREATE FUNCTION pixel_2d.guard_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME = 'catalogs' THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='immutable pixel catalog';
 END IF;
 IF OLD.document_blob_id IS NOT NULL THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='immutable pixel document';
 END IF;
 RETURN NEW;
END;
$$;
-- +goose StatementEnd
CREATE TRIGGER pixel_catalog_immutable BEFORE UPDATE OR DELETE ON pixel_2d.catalogs FOR EACH ROW EXECUTE FUNCTION pixel_2d.guard_immutable();
CREATE TRIGGER pixel_revision_immutable BEFORE UPDATE OR DELETE ON pixel_2d.revisions FOR EACH ROW EXECUTE FUNCTION pixel_2d.guard_immutable();

-- +goose Down
DROP SCHEMA pixel_2d CASCADE;
