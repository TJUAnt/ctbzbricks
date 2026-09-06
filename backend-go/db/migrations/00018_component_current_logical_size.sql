-- +goose Up

-- Star 尺寸筛选从 actor 关系驱动，但不应为每条候选重复读取当前 Version 并计算轴无关尺寸。
-- 这三个字段只保存当前公开 Version 的升序规范化投影；原始宽/深/高仍由 ComponentVersion 持有。
ALTER TABLE component_repo.components
    ADD COLUMN current_logical_size_a numeric(12, 4),
    ADD COLUMN current_logical_size_b numeric(12, 4),
    ADD COLUMN current_logical_size_c numeric(12, 4),
    ADD CONSTRAINT components_current_logical_size_check CHECK (
        (
            current_logical_size_a IS NULL
            AND current_logical_size_b IS NULL
            AND current_logical_size_c IS NULL
        )
        OR (
            current_logical_size_a IS NOT NULL
            AND current_logical_size_b IS NOT NULL
            AND current_logical_size_c IS NOT NULL
            AND current_logical_size_a >= 0
            AND current_logical_size_a <= current_logical_size_b
            AND current_logical_size_b <= current_logical_size_c
        )
    );

-- 升级时一次性回填现有 active Component。Version Preview 尺寸优先，缺失时保持既有 Component
-- 历史尺寸回退语义；后续发布和 Preview 完成路径负责在业务事务内维护该投影。
WITH projection_source AS (
    SELECT component.id,
           COALESCE(version.logical_width_stud, component.logical_width_stud) AS size_x,
           COALESCE(version.logical_depth_stud, component.logical_depth_stud) AS size_y,
           COALESCE(version.logical_height_plate, component.logical_height_plate) AS size_z
    FROM component_repo.components component
    LEFT JOIN component_repo.component_versions version
      ON version.id = component.current_version_id
     AND version.deleted_at IS NULL
    WHERE component.deleted_at IS NULL
      AND component.status = 'active'
), normalized AS (
    SELECT id,
           LEAST(size_x, size_y, size_z) AS size_a,
           size_x + size_y + size_z - LEAST(size_x, size_y, size_z) - GREATEST(size_x, size_y, size_z) AS size_b,
           GREATEST(size_x, size_y, size_z) AS size_c
    FROM projection_source
    WHERE size_x IS NOT NULL AND size_y IS NOT NULL AND size_z IS NOT NULL
)
UPDATE component_repo.components component
SET current_logical_size_a = normalized.size_a,
    current_logical_size_b = normalized.size_b,
    current_logical_size_c = normalized.size_c
FROM normalized
WHERE component.id = normalized.id;

COMMENT ON COLUMN component_repo.components.current_logical_size_a IS
    '当前公开版本轴无关逻辑尺寸的最小值';
COMMENT ON COLUMN component_repo.components.current_logical_size_b IS
    '当前公开版本轴无关逻辑尺寸的中间值';
COMMENT ON COLUMN component_repo.components.current_logical_size_c IS
    '当前公开版本轴无关逻辑尺寸的最大值';

-- +goose Down

ALTER TABLE component_repo.components
    DROP CONSTRAINT components_current_logical_size_check,
    DROP COLUMN current_logical_size_c,
    DROP COLUMN current_logical_size_b,
    DROP COLUMN current_logical_size_a;
