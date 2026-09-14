-- +goose Up

-- reviewed translation 是所有公开读取路径唯一允许选择的官方翻译集合；
-- 写入与审核仍直接操作原表，避免把状态规则复制到每个列表查询。
CREATE VIEW component_repo.component_reviewed_translations AS
SELECT translation.id,
       translation.component_id,
       translation.locale,
       translation.name,
       translation.description,
       translation.tags,
       translation.reviewed_by,
       translation.reviewed_at,
       translation.created_at,
       translation.updated_at
FROM component_repo.component_translations translation
WHERE translation.translation_status = 'reviewed';

REVOKE ALL ON component_repo.component_reviewed_translations FROM PUBLIC;
COMMENT ON VIEW component_repo.component_reviewed_translations IS
    'Component Repo 官方已审核翻译共享只读投影；未审核状态不能进入用户读取路径';

-- Version 资格是 Component 目录的高频筛选事实，持久化后避免每一页重复扫描随历史增长的 Version 表。
ALTER TABLE component_repo.components
    ADD COLUMN version_available boolean NOT NULL DEFAULT false,
    ADD COLUMN public_version_available boolean NOT NULL DEFAULT false;

UPDATE component_repo.components component
SET version_available = EXISTS (
        SELECT 1 FROM component_repo.component_versions version
        WHERE version.component_id = component.id AND version.deleted_at IS NULL
    ),
    public_version_available = EXISTS (
        SELECT 1 FROM component_repo.component_versions version
        WHERE version.component_id = component.id
          AND version.deleted_at IS NULL AND version.status <> 'draft'
    );

-- +goose StatementBegin
CREATE FUNCTION component_repo.refresh_component_version_availability()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    target_component_id uuid;
BEGIN
    -- component_id 若被维护命令调整，旧 Component 也必须刷新，不能留下过期的公开资格。
    IF TG_OP = 'UPDATE' AND OLD.component_id IS DISTINCT FROM NEW.component_id THEN
        PERFORM 1 FROM component_repo.components component
        WHERE component.id = OLD.component_id FOR UPDATE;
        UPDATE component_repo.components component
        SET version_available = EXISTS (
                SELECT 1 FROM component_repo.component_versions version
                WHERE version.component_id = OLD.component_id AND version.deleted_at IS NULL
            ),
            public_version_available = EXISTS (
                SELECT 1 FROM component_repo.component_versions version
                WHERE version.component_id = OLD.component_id
                  AND version.deleted_at IS NULL AND version.status <> 'draft'
            )
        WHERE component.id = OLD.component_id;
    END IF;

    target_component_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.component_id ELSE NEW.component_id END;
    -- 先串行化同一 Component 的 Version 变化；随后 SQL 命令取得新快照并读取前一事务的最终状态。
    PERFORM 1 FROM component_repo.components component
    WHERE component.id = target_component_id FOR UPDATE;
    UPDATE component_repo.components component
    SET version_available = EXISTS (
            SELECT 1 FROM component_repo.component_versions version
            WHERE version.component_id = target_component_id AND version.deleted_at IS NULL
        ),
        public_version_available = EXISTS (
            SELECT 1 FROM component_repo.component_versions version
            WHERE version.component_id = target_component_id
              AND version.deleted_at IS NULL AND version.status <> 'draft'
        )
    WHERE component.id = target_component_id;
    RETURN NULL;
END;
$$;
-- +goose StatementEnd

CREATE TRIGGER component_versions_refresh_component_availability
AFTER INSERT OR DELETE OR UPDATE OF component_id, status, deleted_at
ON component_repo.component_versions
FOR EACH ROW EXECUTE FUNCTION component_repo.refresh_component_version_availability();

-- candidate projection 是 Count、搜索和分页的轻量事实源；不能在页面固定前连接 Version 展示数据。
CREATE VIEW component_repo.component_catalog_candidates AS
SELECT component.id,
       component.owner_id,
       component.content_kind,
       component.content_locale,
       component.name,
       component.description,
       component.tags,
       component.category,
       component.status,
       component.current_version_id,
       component.logical_width_stud,
       component.logical_depth_stud,
       component.logical_height_plate,
       component.current_logical_size_a,
       component.current_logical_size_b,
       component.current_logical_size_c,
       component.metadata,
       component.created_by,
       component.created_at,
       component.updated_at,
       component.deleted_at,
       component.deleted_by,
       component.version_available,
       component.public_version_available
FROM component_repo.components component
WHERE component.deleted_at IS NULL;

REVOKE ALL ON component_repo.component_catalog_candidates FROM PUBLIC;
COMMENT ON VIEW component_repo.component_catalog_candidates IS
    'Component Repo Count、搜索和分页共享轻量投影；不执行 Version 展示读取';

-- catalog projection 是 Component、Group、Star、Watch 的共同展示事实源：
-- 页面固定后统一当前展示尺寸；actor 权限与 locale 翻译仍由调用查询按请求决定。
CREATE VIEW component_repo.component_catalog_projection AS
SELECT component.id,
       component.owner_id,
       component.content_kind,
       component.content_locale,
       component.name,
       component.description,
       component.tags,
       component.category,
       component.status,
       component.current_version_id,
       COALESCE(display_version.logical_width_stud, component.logical_width_stud) AS logical_width_stud,
       COALESCE(display_version.logical_depth_stud, component.logical_depth_stud) AS logical_depth_stud,
       COALESCE(display_version.logical_height_plate, component.logical_height_plate) AS logical_height_plate,
       component.current_logical_size_a,
       component.current_logical_size_b,
       component.current_logical_size_c,
       component.metadata,
       component.created_by,
       component.created_at,
       component.updated_at,
       component.deleted_at,
       component.deleted_by,
       component.version_available,
       component.public_version_available
FROM component_repo.component_catalog_candidates component
LEFT JOIN LATERAL (
    SELECT version.logical_width_stud,
           version.logical_depth_stud,
           version.logical_height_plate
    FROM component_repo.component_versions version
    WHERE version.component_id = component.id
      AND version.deleted_at IS NULL
      AND (
          version.id = component.current_version_id
          OR (component.current_version_id IS NULL AND version.status = 'draft')
      )
    ORDER BY (version.id = component.current_version_id) DESC,
             version.created_at DESC,
             version.id DESC
    LIMIT 1
) display_version ON true;

REVOKE ALL ON component_repo.component_catalog_projection FROM PUBLIC;
COMMENT ON VIEW component_repo.component_catalog_projection IS
    'Component Repo 列表共享投影；调用查询负责 actor、locale、筛选、分页和页内 enrichment';

-- Component 目录 keyset 的两个互斥来源分别使用精确排序索引；替换缺少唯一降序 tiebreaker 的旧 owner 索引。
DROP INDEX component_repo.components_owner_updated_idx;
CREATE INDEX components_owner_updated_idx
    ON component_repo.components (owner_id, updated_at DESC, id DESC)
    WHERE deleted_at IS NULL;
CREATE INDEX components_active_updated_idx
    ON component_repo.components (updated_at DESC, id DESC)
    WHERE deleted_at IS NULL AND status = 'active' AND public_version_available;

-- 名称仍保持 contains 语义。pg_trgm 可以让 user 名称与 official reviewed translation 避免全表字符串扫描。
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA component_repo;
-- +goose StatementBegin
DO $$
DECLARE
    trigram_schema text;
BEGIN
    SELECT namespace.nspname
    INTO trigram_schema
    FROM pg_extension extension
    JOIN pg_namespace namespace ON namespace.oid = extension.extnamespace
    WHERE extension.extname = 'pg_trgm';

    EXECUTE format(
        'CREATE INDEX components_name_trgm_idx ON component_repo.components USING gin (name %I.gin_trgm_ops) WHERE deleted_at IS NULL',
        trigram_schema
    );
    EXECUTE format(
        'CREATE INDEX components_id_text_trgm_idx ON component_repo.components USING gin ((id::text) %I.gin_trgm_ops) WHERE deleted_at IS NULL',
        trigram_schema
    );
    EXECUTE format(
        'CREATE INDEX component_translations_reviewed_name_trgm_idx ON component_repo.component_translations USING gin (name %I.gin_trgm_ops) WHERE translation_status = ''reviewed''',
        trigram_schema
    );
END;
$$;
-- +goose StatementEnd

-- +goose Down

DROP INDEX component_repo.component_translations_reviewed_name_trgm_idx;
DROP INDEX component_repo.components_id_text_trgm_idx;
DROP INDEX component_repo.components_name_trgm_idx;
DROP INDEX component_repo.components_active_updated_idx;
DROP INDEX component_repo.components_owner_updated_idx;
CREATE INDEX components_owner_updated_idx
    ON component_repo.components (owner_id, updated_at DESC, id);
DROP VIEW component_repo.component_catalog_projection;
DROP VIEW component_repo.component_catalog_candidates;
DROP VIEW component_repo.component_reviewed_translations;
DROP TRIGGER component_versions_refresh_component_availability ON component_repo.component_versions;
DROP FUNCTION component_repo.refresh_component_version_availability();
ALTER TABLE component_repo.components
    DROP COLUMN public_version_available,
    DROP COLUMN version_available;

-- 只回收本迁移安装在 component_repo 中的扩展；Supabase 已存在于 extensions schema 的共享扩展不属于 Goose。
-- +goose StatementBegin
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_extension extension
        JOIN pg_namespace namespace ON namespace.oid = extension.extnamespace
        WHERE extension.extname = 'pg_trgm'
          AND namespace.nspname = 'component_repo'
    ) THEN
        DROP EXTENSION pg_trgm;
    END IF;
END;
$$;
-- +goose StatementEnd
