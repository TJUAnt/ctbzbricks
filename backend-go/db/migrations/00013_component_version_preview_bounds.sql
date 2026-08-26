-- +goose Up

-- Preview Box 是特定 ComponentVersion 的派生事实，不能写入 Component 后被并发完成的旧草稿覆盖。
ALTER TABLE component_repo.component_versions
    ADD COLUMN preview_bbox_min double precision[],
    ADD COLUMN preview_bbox_max double precision[],
    ADD COLUMN logical_width_stud numeric(12, 4),
    ADD COLUMN logical_depth_stud numeric(12, 4),
    ADD COLUMN logical_height_plate numeric(12, 4),
    ADD COLUMN preview_bounds_complete boolean;

ALTER TABLE component_repo.component_versions
    ADD CONSTRAINT component_versions_preview_bbox_check CHECK (
        (preview_bbox_min IS NULL AND preview_bbox_max IS NULL)
        OR (
            cardinality(preview_bbox_min) = 3
            AND cardinality(preview_bbox_max) = 3
            AND preview_bbox_min[1] <= preview_bbox_max[1]
            AND preview_bbox_min[2] <= preview_bbox_max[2]
            AND preview_bbox_min[3] <= preview_bbox_max[3]
        )
    ),
    ADD CONSTRAINT component_versions_logical_size_check CHECK (
        (logical_width_stud IS NULL AND logical_depth_stud IS NULL AND logical_height_plate IS NULL)
        OR (
            logical_width_stud >= 0
            AND logical_depth_stud >= 0
            AND logical_height_plate >= 0
        )
    ),
    ADD CONSTRAINT component_versions_preview_bounds_consistency_check CHECK (
        (
            preview_bbox_min IS NULL
            AND preview_bbox_max IS NULL
            AND logical_width_stud IS NULL
            AND logical_depth_stud IS NULL
            AND logical_height_plate IS NULL
            AND preview_bounds_complete IS NULL
        )
        OR (
            preview_bbox_min IS NOT NULL
            AND preview_bbox_max IS NOT NULL
            AND logical_width_stud IS NOT NULL
            AND logical_depth_stud IS NOT NULL
            AND logical_height_plate IS NOT NULL
            AND preview_bounds_complete IS NOT NULL
        )
    );

-- +goose Down

ALTER TABLE component_repo.component_versions
    DROP CONSTRAINT IF EXISTS component_versions_preview_bounds_consistency_check,
    DROP CONSTRAINT IF EXISTS component_versions_logical_size_check,
    DROP CONSTRAINT IF EXISTS component_versions_preview_bbox_check,
    DROP COLUMN IF EXISTS preview_bounds_complete,
    DROP COLUMN IF EXISTS logical_height_plate,
    DROP COLUMN IF EXISTS logical_depth_stud,
    DROP COLUMN IF EXISTS logical_width_stud,
    DROP COLUMN IF EXISTS preview_bbox_max,
    DROP COLUMN IF EXISTS preview_bbox_min;
