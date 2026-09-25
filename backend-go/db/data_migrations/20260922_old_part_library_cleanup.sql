-- 开发库一次性数据维护：只清理两份旧 Studio Part Library 及其真实引用闭包。
-- 目标：Supabase wkwffflomyrgqpilsozx / postgres；执行前必须另行核对连接目标与恢复导出。
-- 本脚本不修改永久 schema，不删除 Artifact/Task 或 Storage 对象；旧源文件和大 SceneSnapshot 未纳入 CSV 恢复包。
-- 必须使用 psql -X -v ON_ERROR_STOP=1 -f 执行。失败时整个事务回滚。
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '10min';

-- 临时 ID 集合冻结删除范围，避免前序删除改变后续筛选结果。
CREATE TEMP TABLE cleanup_old_libraries ON COMMIT DROP AS
SELECT id FROM component_repo.part_library_versions
WHERE id IN ('c8176a73-eccb-4db3-ba72-30edf5f9fd23',
             'a834780c-6c1b-a698-70a5-2513d4c94c15');
CREATE TEMP TABLE cleanup_old_versions ON COMMIT DROP AS
SELECT id, component_id FROM component_repo.component_versions
WHERE part_library_version_id IN (SELECT id FROM cleanup_old_libraries);
CREATE TEMP TABLE cleanup_old_components ON COMMIT DROP AS
SELECT DISTINCT component_id AS id FROM cleanup_old_versions;
CREATE TEMP TABLE cleanup_old_imports ON COMMIT DROP AS
SELECT id FROM component_repo.imports
WHERE part_library_version_id IN (SELECT id FROM cleanup_old_libraries)
   OR target_component_id IN (SELECT id FROM cleanup_old_components);
CREATE TEMP TABLE cleanup_old_sessions ON COMMIT DROP AS
SELECT id FROM component_repo.upload_sessions
WHERE target_component_id IN (SELECT id FROM cleanup_old_components)
   OR base_version_id IN (SELECT id FROM cleanup_old_versions);

DO $guard$
BEGIN
    -- 数量断言使脚本只能用于预检过的开发快照，不会把新用户数据当作旧库引用清理。
    IF (SELECT count(*) FROM cleanup_old_libraries) <> 2
       OR (SELECT count(*) FROM cleanup_old_versions) <> 23
       OR (SELECT count(*) FROM cleanup_old_components) <> 22
       OR (SELECT count(*) FROM cleanup_old_imports) <> 24
       OR (SELECT count(*) FROM cleanup_old_sessions) <> 4
       OR (SELECT count(*) FROM component_repo.part_library_versions
           WHERE id = '4cafdd06-3359-4259-b1c7-aa9ad6b59db3' AND status = 'active') <> 1
       OR EXISTS (SELECT 1 FROM component_repo.tasks WHERE status IN ('queued', 'running')) THEN
        RAISE EXCEPTION 'Old Part Library cleanup precondition failed';
    END IF;
    IF EXISTS (
        SELECT 1 FROM component_repo.component_domain_events
        WHERE component_version_id NOT IN (SELECT id FROM cleanup_old_versions)
    ) OR EXISTS (
        SELECT 1 FROM component_repo.component_feed_entries
        WHERE component_version_id NOT IN (SELECT id FROM cleanup_old_versions)
    ) OR EXISTS (
        SELECT 1 FROM component_repo.imports
        WHERE base_version_id IN (SELECT id FROM cleanup_old_versions)
          AND id NOT IN (SELECT id FROM cleanup_old_imports)
    ) OR EXISTS (
        SELECT 1 FROM component_repo.upload_sessions
        WHERE base_version_id IN (SELECT id FROM cleanup_old_versions)
          AND id NOT IN (SELECT id FROM cleanup_old_sessions)
    ) OR EXISTS (
        SELECT 1 FROM component_repo.imports
        WHERE upload_session_id IN (SELECT id FROM cleanup_old_sessions)
          AND id NOT IN (SELECT id FROM cleanup_old_imports)
    ) THEN
        RAISE EXCEPTION 'Old Part Library cleanup would affect independent data';
    END IF;
END
$guard$;

-- 这两张事件表当前全部属于旧版本。领域事件禁止逐行 DELETE，成对 TRUNCATE 保持外键一致。
TRUNCATE component_repo.component_feed_entries, component_repo.component_domain_events;

-- 先断开反向引用，再删不可变版本；仅更新马上会被删除的 Import/UploadSession。
UPDATE component_repo.components SET current_version_id = NULL
WHERE id IN (SELECT id FROM cleanup_old_components)
  AND current_version_id IN (SELECT id FROM cleanup_old_versions);
UPDATE component_repo.imports SET base_version_id = NULL
WHERE id IN (SELECT id FROM cleanup_old_imports)
  AND base_version_id IN (SELECT id FROM cleanup_old_versions);
UPDATE component_repo.upload_sessions SET base_version_id = NULL
WHERE id IN (SELECT id FROM cleanup_old_sessions)
  AND base_version_id IN (SELECT id FROM cleanup_old_versions);

DELETE FROM component_repo.component_versions
WHERE id IN (SELECT id FROM cleanup_old_versions);
-- Import 外键级联移除 Candidate、SceneSnapshot、连接分析和审核数据；独立的 4 条 Import 保留。
-- SceneSnapshot 的日常不可变保护会拒绝级联 DELETE；只在本事务的受控删除区间停用这一触发器。
-- ALTER TABLE 是事务性的：任何后续错误都会连同触发器状态一起回滚。
ALTER TABLE component_repo.scene_snapshots
    DISABLE TRIGGER scene_snapshots_protect_immutable;
-- Analysis item 反向引用 Candidate interface；先清理 item 及其级联子表，避免接口删除被 NO ACTION 外键挡住。
DELETE FROM component_repo.connector_analysis_items
WHERE component_candidate_id IN (
    SELECT id FROM component_repo.candidates
    WHERE import_id IN (SELECT id FROM cleanup_old_imports)
);
DELETE FROM component_repo.imports
WHERE id IN (SELECT id FROM cleanup_old_imports);
ALTER TABLE component_repo.scene_snapshots
    ENABLE TRIGGER scene_snapshots_protect_immutable;
DELETE FROM component_repo.upload_sessions
WHERE id IN (SELECT id FROM cleanup_old_sessions);
-- Component 子表的 Group 成员、Watch 等关系按既有 FK 级联；独立 Component 保留。
DELETE FROM component_repo.components
WHERE id IN (SELECT id FROM cleanup_old_components);

-- 最后移除旧库；既有 FK 级联清理 Part、几何、连接点、预览和翻译，不触碰 V4。
DELETE FROM component_repo.part_library_versions
WHERE id IN (SELECT id FROM cleanup_old_libraries);

DO $verify$
BEGIN
    IF (SELECT count(*) FROM component_repo.part_library_versions) <> 1
       OR (SELECT count(*) FROM component_repo.part_library_versions
           WHERE id = '4cafdd06-3359-4259-b1c7-aa9ad6b59db3' AND status = 'active') <> 1
       OR (SELECT count(*) FROM component_repo.components) <> 1
       OR (SELECT count(*) FROM component_repo.imports) <> 4
       OR (SELECT count(*) FROM component_repo.parts
           WHERE part_library_version_id = '4cafdd06-3359-4259-b1c7-aa9ad6b59db3') <> 24954
       OR (SELECT count(*) FROM component_repo.part_geometries
           WHERE part_library_version_id = '4cafdd06-3359-4259-b1c7-aa9ad6b59db3'
             AND geometry_status = 'ready') <> 24899
       OR NOT EXISTS (
           SELECT 1 FROM pg_trigger
           WHERE tgrelid = 'component_repo.scene_snapshots'::regclass
             AND tgname = 'scene_snapshots_protect_immutable'
             AND tgenabled = 'O'
       ) THEN
        RAISE EXCEPTION 'Old Part Library cleanup postcondition failed';
    END IF;
END
$verify$;
COMMIT;

SELECT pg_database_size(current_database()) AS database_bytes,
       (SELECT count(*) FROM component_repo.part_library_versions) AS library_versions,
       (SELECT count(*) FROM component_repo.components) AS components,
       (SELECT count(*) FROM component_repo.imports) AS imports;
