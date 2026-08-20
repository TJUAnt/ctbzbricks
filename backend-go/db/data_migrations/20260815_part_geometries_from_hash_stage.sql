-- One-time Part geometry completion using an externally audited source hash
-- stage file.
--
-- Usage:
--   psql "$DATABASE_URL" -f backend-go/db/data_migrations/20260815_part_geometries_from_hash_stage.sql
--
-- The stage file must be tab-separated:
--   source_relative_path<TAB>sha256
-- Current expected stage file:
--   /tmp/ctbzbricks_studio_part_hashes.tsv
--
-- This script is idempotent. It only writes Goose-owned component_repo
-- geometry metadata and does not delete or modify legacy public tables.

BEGIN;
SET LOCAL statement_timeout = '30min';
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.goose_db_version
        WHERE version_id = 8 AND is_applied
    ) THEN
        RAISE EXCEPTION 'component_repo must be at Goose version 8';
    END IF;
END;
$$;

CREATE TEMP TABLE part_source_hash_stage (
    source_relative_path text PRIMARY KEY,
    source_file_hash text NOT NULL
) ON COMMIT DROP;

\copy part_source_hash_stage (source_relative_path, source_file_hash) FROM '/tmp/ctbzbricks_studio_part_hashes.tsv' WITH (FORMAT text)

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM part_source_hash_stage
        WHERE source_relative_path = ''
           OR source_relative_path <> lower(source_relative_path)
           OR source_file_hash !~ '^[0-9a-f]{64}$'
    ) THEN
        RAISE EXCEPTION 'invalid part source hash stage data';
    END IF;
END;
$$;

WITH geometry_candidates AS (
    SELECT
        library.id AS part_library_version_id,
        lower(part.ldraw_part_num) AS ldraw_part_num,
        hash.source_relative_path,
        hash.source_file_hash,
        ARRAY[geometry.bbox_min_x, geometry.bbox_min_y, geometry.bbox_min_z]::double precision[] AS bbox_min,
        ARRAY[geometry.bbox_max_x, geometry.bbox_max_y, geometry.bbox_max_z]::double precision[] AS bbox_max,
        geometry.logical_width_stud,
        geometry.logical_depth_stud,
        geometry.logical_height_plate,
        COALESCE(geometry.vertex_count, 0) AS vertex_count,
        COALESCE(geometry.face_count, 0) AS face_count
    FROM component_repo.part_library_versions library
    CROSS JOIN public.ldraw_parts part
    JOIN public.ldraw_part_geometry geometry ON geometry.ldraw_part_id = part.id
    JOIN part_source_hash_stage hash
      ON hash.source_relative_path = lower(replace(part.relative_path, chr(92), '/'))
    WHERE lower(part.ldraw_part_num) <> ''
      AND geometry.geometry_status = 'parsed'
      AND geometry.geometry_error_code IS NULL
      AND geometry.bbox_min_x IS NOT NULL AND geometry.bbox_min_y IS NOT NULL
      AND geometry.bbox_min_z IS NOT NULL AND geometry.bbox_max_x IS NOT NULL
      AND geometry.bbox_max_y IS NOT NULL AND geometry.bbox_max_z IS NOT NULL
      AND geometry.logical_width_stud IS NOT NULL
      AND geometry.logical_depth_stud IS NOT NULL
      AND geometry.logical_height_plate IS NOT NULL
),
deduplicated AS (
    SELECT DISTINCT ON (part_library_version_id, ldraw_part_num)
        part_library_version_id, ldraw_part_num,
        source_relative_path, source_file_hash,
        bbox_min, bbox_max,
        logical_width_stud, logical_depth_stud, logical_height_plate,
        vertex_count, face_count
    FROM geometry_candidates
    ORDER BY part_library_version_id, ldraw_part_num, source_relative_path
)
INSERT INTO component_repo.part_geometries (
    part_library_version_id, ldraw_part_num,
    source_relative_path, source_file_hash,
    bbox_min, bbox_max,
    logical_width_stud, logical_depth_stud, logical_height_plate,
    vertex_count, face_count, geometry_status
)
SELECT
    part_library_version_id, ldraw_part_num,
    source_relative_path, source_file_hash,
    bbox_min, bbox_max,
    logical_width_stud, logical_depth_stud, logical_height_plate,
    vertex_count, face_count, 'ready'
FROM deduplicated
ON CONFLICT (part_library_version_id, ldraw_part_num) DO UPDATE
SET source_relative_path = EXCLUDED.source_relative_path,
    source_file_hash = EXCLUDED.source_file_hash,
    bbox_min = EXCLUDED.bbox_min,
    bbox_max = EXCLUDED.bbox_max,
    logical_width_stud = EXCLUDED.logical_width_stud,
    logical_depth_stud = EXCLUDED.logical_depth_stud,
    logical_height_plate = EXCLUDED.logical_height_plate,
    vertex_count = EXCLUDED.vertex_count,
    face_count = EXCLUDED.face_count,
    geometry_status = 'ready',
    geometry_error_code = NULL,
    geometry_error_params = NULL,
    updated_at = now();

COMMIT;

-- Verification queries:
-- SELECT count(*) FROM component_repo.part_geometries GROUP BY part_library_version_id;
-- SELECT count(*) FROM component_repo.part_previews GROUP BY part_library_version_id;
-- SELECT count(*) FROM component_repo.parts p
-- LEFT JOIN component_repo.part_geometries g
--   ON g.part_library_version_id = p.part_library_version_id
--  AND g.ldraw_part_num = p.ldraw_part_num
-- WHERE g.ldraw_part_num IS NULL;
