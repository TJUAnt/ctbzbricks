-- One-time external Part ID handoff from legacy public.xref_part_numbers
-- into the Goose-owned component_repo schema.
--
-- Preconditions:
--   * Goose migrations 00001 through 00009 are applied.
--   * public.xref_part_numbers contains the audited legacy cross-reference data.
--
-- This script is idempotent. It does not delete or modify legacy public tables.

BEGIN;
SET LOCAL statement_timeout = '30min';
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.goose_db_version
        WHERE version_id = 9 AND is_applied
    ) THEN
        RAISE EXCEPTION 'component_repo must be at Goose version 9';
    END IF;
END;
$$;

INSERT INTO component_repo.part_external_ids (
    part_library_version_id, ldraw_part_num,
    id_system, external_id, relation_type, confidence, source, metadata
)
SELECT
    part.part_library_version_id,
    part.ldraw_part_num,
    'ldraw',
    part.ldraw_part_num,
    'exact',
    1.0000,
    'component_repo.parts',
    '{}'::jsonb
FROM component_repo.parts part
ON CONFLICT (part_library_version_id, ldraw_part_num, id_system, external_id, relation_type)
DO UPDATE SET
    confidence = EXCLUDED.confidence,
    source = EXCLUDED.source,
    metadata = EXCLUDED.metadata,
    updated_at = now();

WITH mapped_external_ids AS (
    SELECT
        part.part_library_version_id,
        part.ldraw_part_num,
        mapped.id_system,
        mapped.external_id,
        CASE
            WHEN xref.relation_type IN ('exact', 'alias', 'print_variant', 'color_variant', 'shortcut', 'unknown')
                THEN xref.relation_type
            WHEN xref.relation_type IS NULL OR xref.relation_type = ''
                THEN 'unknown'
            ELSE 'unknown'
        END AS relation_type,
        LEAST(GREATEST(COALESCE(xref.confidence, 0.7500), 0), 1) AS confidence,
        COALESCE(NULLIF(xref.source, ''), 'public.xref_part_numbers') AS source,
        jsonb_strip_nulls(jsonb_build_object(
            'legacyRelationType', NULLIF(xref.relation_type, ''),
            'legacySource', NULLIF(xref.source, '')
        )) AS metadata
    FROM public.xref_part_numbers xref
    JOIN component_repo.parts part
      ON part.ldraw_part_num = lower(xref.ldraw_part_num)
    CROSS JOIN LATERAL (
        VALUES
            ('rebrickable', NULLIF(btrim(xref.rebrickable_part_num), '')),
            ('bricklink', NULLIF(btrim(xref.bricklink_part_num), '')),
            ('lego_design', NULLIF(btrim(xref.lego_design_id), ''))
    ) AS mapped(id_system, external_id)
    WHERE mapped.external_id IS NOT NULL
),
deduplicated AS (
    SELECT DISTINCT ON (
        part_library_version_id, ldraw_part_num, id_system, external_id, relation_type
    )
        part_library_version_id, ldraw_part_num,
        id_system, external_id, relation_type, confidence, source, metadata
    FROM mapped_external_ids
    ORDER BY
        part_library_version_id, ldraw_part_num, id_system, external_id, relation_type,
        confidence DESC, source
)
INSERT INTO component_repo.part_external_ids (
    part_library_version_id, ldraw_part_num,
    id_system, external_id, relation_type, confidence, source, metadata
)
SELECT
    part_library_version_id, ldraw_part_num,
    id_system, external_id, relation_type, confidence, source, metadata
FROM deduplicated
ON CONFLICT (part_library_version_id, ldraw_part_num, id_system, external_id, relation_type)
DO UPDATE SET
    confidence = EXCLUDED.confidence,
    source = EXCLUDED.source,
    metadata = EXCLUDED.metadata,
    updated_at = now();

COMMIT;

-- Verification queries:
-- SELECT id_system, count(*) FROM component_repo.part_external_ids GROUP BY id_system ORDER BY id_system;
-- SELECT count(DISTINCT ldraw_part_num) FROM component_repo.part_external_ids WHERE id_system <> 'ldraw';
