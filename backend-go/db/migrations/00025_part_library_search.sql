-- +goose Up

-- 精确尺寸搜索只接受 importer 明确标记为 derived_exact 的标称值。索引顺序与查询的版本范围、
-- 平面旋转规范化及独立高度谓词一致；近似 bbox 不进入该索引，避免误导搜索结果并减少写放大。
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

-- +goose Down

DROP INDEX IF EXISTS component_repo.part_geometries_exact_logical_size_idx;
