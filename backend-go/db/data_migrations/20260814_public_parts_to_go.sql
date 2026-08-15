-- One-time Part content/geometry authority handoff from Alembic-owned public
-- tables to the Goose-owned component_repo schema.
--
-- Preconditions:
--   * Goose migrations 00001 through 00008 are applied.
--   * public.ldraw_parts, public.ldraw_part_geometry, and public.part_translations
--     still contain the verified legacy development data.
--   * LDRAW_ROOT on Go preview Workers resolves the same immutable library whose
--     source hash is recorded by each component_repo.part_library_versions row.
--
-- This migration is idempotent. It does not delete or modify the legacy tables;
-- their retirement is a separate, explicitly verified operation.

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

INSERT INTO component_repo.parts (
    part_library_version_id, ldraw_part_num, source_name, content_locale, metadata
)
SELECT library.id, lower(part.ldraw_part_num),
       COALESCE(NULLIF(part.name, ''), lower(part.ldraw_part_num)),
       COALESCE(NULLIF(part.content_locale, ''), 'en-US'),
       jsonb_strip_nulls(jsonb_build_object(
           'category', part.category,
           'source', part.source,
           'legacyImportStatus', part.import_status
       ))
FROM component_repo.part_library_versions library
CROSS JOIN public.ldraw_parts part
WHERE lower(part.ldraw_part_num) <> ''
ON CONFLICT (part_library_version_id, ldraw_part_num) DO UPDATE
SET source_name = EXCLUDED.source_name,
    content_locale = EXCLUDED.content_locale,
    metadata = component_repo.parts.metadata || EXCLUDED.metadata;

INSERT INTO component_repo.part_geometries (
    part_library_version_id, ldraw_part_num,
    source_relative_path, source_file_hash,
    bbox_min, bbox_max,
    logical_width_stud, logical_depth_stud, logical_height_plate,
    vertex_count, face_count, geometry_status
)
SELECT library.id, lower(part.ldraw_part_num),
       lower(replace(part.relative_path, chr(92), '/')), lower(part.file_hash),
       ARRAY[geometry.bbox_min_x, geometry.bbox_min_y, geometry.bbox_min_z]::double precision[],
       ARRAY[geometry.bbox_max_x, geometry.bbox_max_y, geometry.bbox_max_z]::double precision[],
       geometry.logical_width_stud, geometry.logical_depth_stud,
       geometry.logical_height_plate,
       COALESCE(geometry.vertex_count, 0), COALESCE(geometry.face_count, 0), 'ready'
FROM component_repo.part_library_versions library
CROSS JOIN public.ldraw_parts part
JOIN public.ldraw_part_geometry geometry ON geometry.ldraw_part_id = part.id
WHERE part.file_hash ~ '^[0-9a-fA-F]{64}$'
  AND part.relative_path IS NOT NULL AND part.relative_path <> ''
  AND geometry.geometry_status = 'parsed'
  AND geometry.geometry_error_code IS NULL
  AND geometry.bbox_min_x IS NOT NULL AND geometry.bbox_min_y IS NOT NULL
  AND geometry.bbox_min_z IS NOT NULL AND geometry.bbox_max_x IS NOT NULL
  AND geometry.bbox_max_y IS NOT NULL AND geometry.bbox_max_z IS NOT NULL
  AND geometry.logical_width_stud IS NOT NULL
  AND geometry.logical_depth_stud IS NOT NULL
  AND geometry.logical_height_plate IS NOT NULL
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

INSERT INTO component_repo.part_translations (
    part_library_version_id, ldraw_part_num, locale, name,
    translation_status, reviewed_by, reviewed_at, created_at, updated_at
)
SELECT library.id, lower(part.ldraw_part_num), translation.locale,
       translation.name, 'reviewed', library.created_by,
       COALESCE(translation.reviewed_at, translation.updated_at, translation.created_at, now()),
       COALESCE(translation.created_at, now()), COALESCE(translation.updated_at, now())
FROM component_repo.part_library_versions library
CROSS JOIN public.ldraw_parts part
JOIN public.part_translations translation ON translation.ldraw_part_id = part.id
WHERE translation.translation_status = 'reviewed'
  AND translation.locale <> '' AND translation.name <> ''
ON CONFLICT (part_library_version_id, ldraw_part_num, locale) DO UPDATE
SET name = EXCLUDED.name,
    translation_status = 'reviewed',
    reviewed_by = EXCLUDED.reviewed_by,
    reviewed_at = EXCLUDED.reviewed_at,
    updated_at = EXCLUDED.updated_at;

COMMIT;

-- Verification queries (run and retain output before retiring legacy reads):
-- SELECT count(*) FROM public.ldraw_parts;
-- SELECT count(*) FROM component_repo.parts GROUP BY part_library_version_id;
-- SELECT count(*) FROM component_repo.part_geometries GROUP BY part_library_version_id;
-- SELECT count(*) FROM component_repo.part_translations GROUP BY part_library_version_id;
