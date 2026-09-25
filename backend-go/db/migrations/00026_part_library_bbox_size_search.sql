-- +goose Up

-- 尺寸搜索统一覆盖标准件标称尺寸与非标准件 bbox。平面条件使用 ±0.25 stud、垂直条件使用
-- ±0.625 plate，二者都等于物理 ±2mm；索引表达式与旋转规范化后的范围谓词完全一致。
DROP INDEX IF EXISTS component_repo.part_geometries_exact_logical_size_idx;

CREATE INDEX part_geometries_searchable_logical_size_idx
    ON component_repo.part_geometries (
        part_library_version_id,
        LEAST(logical_width_stud, logical_depth_stud),
        GREATEST(logical_width_stud, logical_depth_stud),
        logical_height_plate,
        ldraw_part_num
    )
    WHERE geometry_status = 'ready'
      AND logical_size_derivation_status IN ('derived_exact', 'derived_approximate');

-- +goose Down

DROP INDEX IF EXISTS component_repo.part_geometries_searchable_logical_size_idx;

CREATE INDEX part_geometries_exact_logical_size_idx
    ON component_repo.part_geometries (
        part_library_version_id,
        LEAST(logical_width_stud, logical_depth_stud),
        GREATEST(logical_width_stud, logical_depth_stud),
        logical_height_plate,
        ldraw_part_num
    )
    WHERE geometry_status = 'ready'
      AND logical_size_derivation_status = 'derived_exact';
