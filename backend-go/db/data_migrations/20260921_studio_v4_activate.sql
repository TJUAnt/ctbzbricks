-- 本维护脚本只激活已确认的 2026-09-21 Studio v4 快照，不执行 DDL 或删除旧版本。
-- 必须通过 psql -X -v ON_ERROR_STOP=1 -f 执行；运行前另行核对数据库身份与预览任务终态。
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

DO $activation$
DECLARE
    old_status text;
    new_status text;
    new_hash text;
    new_importer text;
    new_preview_ready boolean;
    new_relation_ready boolean;
    task_status text;
    geometry_ready_count bigint;
    verified_preview_count bigint;
BEGIN
    -- 同一事务锁定两个版本；目标不达标时抛错回滚，在线搜索始终可见唯一 active。
    SELECT status INTO STRICT old_status
    FROM component_repo.part_library_versions
    WHERE id = 'c8176a73-eccb-4db3-ba72-30edf5f9fd23'
    FOR UPDATE;
    SELECT status, source_hash, metadata->>'studioImporterVersion', preview_ready, relation_ready
    INTO STRICT new_status, new_hash, new_importer, new_preview_ready, new_relation_ready
    FROM component_repo.part_library_versions
    WHERE id = '4cafdd06-3359-4259-b1c7-aa9ad6b59db3'
    FOR UPDATE;

    IF old_status <> 'active' OR new_status <> 'building'
       OR new_hash <> 'c8df4312df4b0e2a6e8d9e7c6740ca927da51c1146aa8da3bab1fd68325934d2'
       OR new_importer <> 'studio-part-library-importer-v4'
       OR NOT new_preview_ready OR NOT new_relation_ready THEN
        RAISE EXCEPTION 'Part Library version/hash/capability precondition failed';
    END IF;

    SELECT status INTO STRICT task_status
    FROM component_repo.tasks
    WHERE id = '2bcf71c3-e07c-4475-8078-13b4d2f32d36'
      AND task_type = 'component.part_preview.prebuild';
    IF task_status <> 'succeeded' THEN
        RAISE EXCEPTION 'Part Preview prebuild task is not succeeded';
    END IF;

    SELECT count(*) INTO geometry_ready_count
    FROM component_repo.part_geometries
    WHERE part_library_version_id = '4cafdd06-3359-4259-b1c7-aa9ad6b59db3'
      AND geometry_status = 'ready';
    SELECT count(*) INTO verified_preview_count
    FROM component_repo.part_previews preview
    JOIN component_repo.part_geometries geometry
      ON geometry.part_library_version_id = preview.part_library_version_id
     AND geometry.ldraw_part_num = preview.ldraw_part_num
    JOIN component_repo.artifacts artifact ON artifact.id = preview.artifact_id
    WHERE preview.part_library_version_id = '4cafdd06-3359-4259-b1c7-aa9ad6b59db3'
      AND geometry.geometry_status = 'ready'
      AND preview.status = 'ready'
      AND preview.generator_version = 'part-preview-ldraw-meshopt-glb-v2'
      AND artifact.verification_status = 'verified';
    IF geometry_ready_count <> 24899 OR verified_preview_count <> geometry_ready_count THEN
        RAISE EXCEPTION 'Part Preview coverage incomplete: ready geometry %, verified preview %',
            geometry_ready_count, verified_preview_count;
    END IF;

    UPDATE component_repo.part_library_versions
    SET status = 'retired'
    WHERE id = 'c8176a73-eccb-4db3-ba72-30edf5f9fd23';
    UPDATE component_repo.part_library_versions
    SET status = 'active'
    WHERE id = '4cafdd06-3359-4259-b1c7-aa9ad6b59db3';
END
$activation$;

COMMIT;

SELECT id, status, source_hash, metadata->>'studioImporterVersion' AS importer
FROM component_repo.part_library_versions
WHERE id IN ('c8176a73-eccb-4db3-ba72-30edf5f9fd23',
             '4cafdd06-3359-4259-b1c7-aa9ad6b59db3')
ORDER BY status, id;
