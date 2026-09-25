-- 开发库一次性维护：在空间不足以并存两份完整快照时删除 importer v4 active Library，为 v5 重建腾出空间。
-- 目标：Supabase wkwffflomyrgqpilsozx / postgres。脚本只删除下列精确 ID，不触碰 Artifact/Task/Storage 对象。
-- 执行后必须 VACUUM FULL 相关大表，再以 importer v5 导入 a33262fd-c702-4bd5-84c6-8966761ca88d。
-- 必须使用 psql -X -v ON_ERROR_STOP=1 -f 执行；任一守卫失败时整个事务回滚。
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '10min';

DO $guard$
BEGIN
    IF current_database() <> 'postgres'
       OR current_user <> 'postgres'
       OR (SELECT count(*) FROM public.goose_db_version WHERE is_applied AND version_id = 26) <> 1
       OR (SELECT count(*) FROM component_repo.part_library_versions) <> 1
       OR (SELECT count(*) FROM component_repo.part_library_versions
           WHERE id = '4cafdd06-3359-4259-b1c7-aa9ad6b59db3'
             AND status = 'active'
             AND source_hash = 'c8df4312df4b0e2a6e8d9e7c6740ca927da51c1146aa8da3bab1fd68325934d2'
             AND metadata->>'studioImporterVersion' = 'studio-part-library-importer-v4') <> 1
       OR (SELECT count(*) FROM component_repo.parts
           WHERE part_library_version_id = '4cafdd06-3359-4259-b1c7-aa9ad6b59db3') <> 24954
       OR (SELECT count(*) FROM component_repo.part_geometries
           WHERE part_library_version_id = '4cafdd06-3359-4259-b1c7-aa9ad6b59db3'
             AND geometry_status = 'ready') <> 24899
       OR (SELECT count(*) FROM component_repo.part_previews preview
           JOIN component_repo.artifacts artifact ON artifact.id = preview.artifact_id
           WHERE preview.part_library_version_id = '4cafdd06-3359-4259-b1c7-aa9ad6b59db3'
             AND preview.status = 'ready'
             AND preview.generator_version = 'part-preview-ldraw-meshopt-glb-v2'
             AND artifact.verification_status = 'verified'
             AND artifact.deleted_at IS NULL) <> 24899
       OR EXISTS (SELECT 1 FROM component_repo.component_versions
                  WHERE part_library_version_id = '4cafdd06-3359-4259-b1c7-aa9ad6b59db3')
       OR EXISTS (SELECT 1 FROM component_repo.imports
                  WHERE part_library_version_id = '4cafdd06-3359-4259-b1c7-aa9ad6b59db3')
       OR EXISTS (SELECT 1 FROM component_repo.tasks
                  WHERE status IN ('queued', 'running', 'retry_wait'))
       OR EXISTS (SELECT 1 FROM component_repo.part_library_versions
                  WHERE id = 'a33262fd-c702-4bd5-84c6-8966761ca88d') THEN
        RAISE EXCEPTION 'Studio v5 replacement precondition failed';
    END IF;
END
$guard$;

-- Library 外键级联删除 Part、geometry、connector、preview 与 translation；内容寻址 Artifact 留待独立 Storage 清理。
DELETE FROM component_repo.part_library_versions
WHERE id = '4cafdd06-3359-4259-b1c7-aa9ad6b59db3';

DO $verify$
BEGIN
    IF EXISTS (SELECT 1 FROM component_repo.part_library_versions)
       OR EXISTS (SELECT 1 FROM component_repo.parts)
       OR EXISTS (SELECT 1 FROM component_repo.part_geometries)
       OR EXISTS (SELECT 1 FROM component_repo.part_connector_definitions)
       OR EXISTS (SELECT 1 FROM component_repo.part_previews) THEN
        RAISE EXCEPTION 'Studio v5 replacement deletion postcondition failed';
    END IF;
END
$verify$;
COMMIT;

SELECT pg_database_size(current_database()) AS database_bytes_after_delete;
