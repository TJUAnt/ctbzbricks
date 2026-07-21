"""Unified fitting candidate profile persistence."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import Boolean, Float, JSON, Engine, String, column, delete, func, inspect, select, table, text
from sqlalchemy.orm import selectinload, sessionmaker

from src.component_repo.geometry_service import component_geometry
from src.config.fitting_candidate_profile_config import (
    FITTING_CANDIDATE_PROFILE_DATABASE_CONFIG,
)
from src.model.models import (
    Component,
    ComponentInterface,
    ComponentSceneSnapshot,
    ComponentVersion,
    ConnectorInstance,
    FittingCandidateProfile,
    LDrawPart,
    LDrawPartShapeProfile,
    LDrawPartGeometry,
    LDrawSubmodel,
    LDrawSubmodelConnector,
    LDrawSubmodelPart,
)
from src.i18n.messages import MACHINE_CODE_PATTERN, message
from src.services.fitting_candidate_search_fields import persisted_search_fields


def ensure_fitting_candidate_profile_table(engine: Engine) -> None:
    ensure_ldraw_part_geometry_error_columns(engine)
    FittingCandidateProfile.__table__.create(bind=engine, checkfirst=True)
    ensure_fitting_candidate_profile_error_columns(engine)
    ensure_fitting_candidate_profile_search_columns(engine)


def ensure_ldraw_part_geometry_error_columns(engine: Engine) -> None:
    table_name = LDrawPartGeometry.__tablename__
    inspector = inspect(engine)
    if not inspector.has_table(table_name):
        return
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    definitions = {
        "geometry_error_code": "VARCHAR(160) NULL",
        "geometry_error_params_json": "JSON NULL",
    }
    ensure_profile_columns(engine, table_name, columns, definitions)
    if "geometry_error" not in columns or not inspector.has_table(LDrawPart.__tablename__):
        return
    geometry = table(
        table_name,
        column("id"),
        column("ldraw_part_id"),
        column("geometry_status", String(length=32)),
        column("geometry_error", String()),
        column("geometry_error_code", String(length=160)),
        column("geometry_error_params_json", JSON()),
    )
    parts = table(
        LDrawPart.__tablename__,
        column("id"),
        column("ldraw_part_num", String(length=128)),
    )
    with engine.begin() as connection:
        rows = connection.execute(
            select(
                geometry.c.id,
                geometry.c.geometry_status,
                parts.c.ldraw_part_num,
            )
            .select_from(
                geometry.join(parts, parts.c.id == geometry.c.ldraw_part_id)
            )
            .where(
                geometry.c.geometry_error.is_not(None),
                geometry.c.geometry_error_code.is_(None),
            )
        ).all()
        for geometry_id, geometry_status, part_number in rows:
            error_code = (
                "ldraw.geometry.build_partial"
                if geometry_status == "partial"
                else "ldraw.geometry.build_failed"
            )
            connection.execute(
                geometry.update()
                .where(geometry.c.id == geometry_id)
                .values(
                    geometry_error_code=error_code,
                    geometry_error_params_json={
                        "partId": part_number,
                        "errorCount": 1,
                    },
                )
            )


def ensure_fitting_candidate_profile_search_columns(engine: Engine) -> None:
    table_name = FittingCandidateProfile.__tablename__
    existing = {
        column["name"] for column in inspect(engine).get_columns(table_name)
    }
    definitions = {
        "width_stud": "DOUBLE PRECISION NULL",
        "depth_stud": "DOUBLE PRECISION NULL",
        "height_plate": "DOUBLE PRECISION NULL",
        "is_sticker": "BOOLEAN NOT NULL DEFAULT FALSE",
        "normalized_type": "VARCHAR(64) NULL",
    }
    ensure_profile_columns(engine, table_name, existing, definitions)
    search_index_names = {
        FITTING_CANDIDATE_PROFILE_DATABASE_CONFIG["indexes"]["dimensions"],
        FITTING_CANDIDATE_PROFILE_DATABASE_CONFIG["indexes"]["sticker"],
        FITTING_CANDIDATE_PROFILE_DATABASE_CONFIG["indexes"]["normalized_type"],
    }
    available_columns = existing | set(definitions)
    for index in FittingCandidateProfile.__table__.indexes:
        if (
            index.name in search_index_names
            and all(column.name in available_columns for column in index.columns)
        ):
            index.create(bind=engine, checkfirst=True)
    required_backfill_columns = {
        "candidate_type",
        "logical_size_json",
        "appearance_tags_json",
    }
    if (
        required_backfill_columns.issubset(existing)
        and any(column_name not in existing for column_name in definitions)
    ):
        backfill_fitting_candidate_profile_search_columns(engine)


def ensure_profile_columns(
    engine: Engine,
    table_name: str,
    existing: set[str],
    definitions: dict[str, str],
) -> None:
    preparer = engine.dialect.identifier_preparer
    quoted_table = preparer.quote(table_name)
    for column_name, definition in definitions.items():
        if column_name in existing:
            continue
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"ALTER TABLE {quoted_table} ADD COLUMN "
                    f"{preparer.quote(column_name)} {definition}"
                )
            )


def backfill_fitting_candidate_profile_search_columns(engine: Engine) -> None:
    profiles = table(
        FittingCandidateProfile.__tablename__,
        column("id"),
        column("candidate_type", String(length=32)),
        column("logical_size_json", JSON()),
        column("appearance_tags_json", JSON()),
        column("width_stud", Float()),
        column("depth_stud", Float()),
        column("height_plate", Float()),
        column("is_sticker", Boolean()),
        column("normalized_type", String(length=64)),
    )
    with engine.begin() as connection:
        rows = connection.execute(
            select(
                profiles.c.id,
                profiles.c.candidate_type,
                profiles.c.logical_size_json,
                profiles.c.appearance_tags_json,
            )
        ).all()
        for profile_id, candidate_type, logical_size, appearance in rows:
            connection.execute(
                profiles.update()
                .where(profiles.c.id == profile_id)
                .values(
                    **persisted_search_fields(
                        candidate_type,
                        logical_size or {},
                        appearance or {},
                    )
                )
            )


def ensure_fitting_candidate_profile_error_columns(engine: Engine) -> None:
    table_name = FittingCandidateProfile.__tablename__
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    preparer = engine.dialect.identifier_preparer
    quoted_table = preparer.quote(table_name)
    definitions = {
        "profile_error_code": "VARCHAR(160) NULL",
        "profile_error_params_json": "JSON NULL",
    }
    for column_name, definition in definitions.items():
        if column_name in columns:
            continue
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"ALTER TABLE {quoted_table} ADD COLUMN "
                    f"{preparer.quote(column_name)} {definition}"
                )
            )
    if "profile_error" not in columns:
        return
    legacy_profiles = table(
        table_name,
        column("id"),
        column("profile_error_code", String(length=160)),
        column("profile_error_params_json", JSON()),
    )
    with engine.begin() as connection:
        rows = connection.execute(
            text(
                "SELECT id, candidate_id, profile_error "
                "FROM fitting_candidate_profiles "
                "WHERE profile_error IS NOT NULL AND profile_error_code IS NULL"
            )
        ).all()
        for profile_id, candidate_id, profile_error in rows:
            connection.execute(
                legacy_profiles.update()
                .where(legacy_profiles.c.id == profile_id)
                .values(
                    profile_error_code="fitting_candidate_profile.generation_failed",
                    profile_error_params_json={
                        "candidateId": str(candidate_id),
                        "legacyMessage": str(profile_error),
                    },
                )
            )


def save_part_fitting_candidate_profile(
    engine: Engine,
    config: dict[str, Any],
    part_id: str,
) -> dict[str, Any]:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        row = session.execute(
            select(LDrawPart, LDrawPartGeometry)
            .join(
                LDrawPartGeometry,
                LDrawPartGeometry.ldraw_part_id == LDrawPart.id,
            )
            .where(LDrawPart.ldraw_part_num == part_id.lower())
        ).first()
        if row is None:
            raise ValueError(
                config["errors"]["candidate_not_found"].format(
                    candidate_type=config["profile"]["candidate_types"]["part"],
                    candidate_id=part_id,
                )
            )
        part, geometry = row
        shape_profile = session.scalar(
            select(LDrawPartShapeProfile)
            .where(LDrawPartShapeProfile.ldraw_part_id == part.id)
            .where(
                LDrawPartShapeProfile.profile_status
                == config["profile"]["ready_status"]
            )
            .order_by(LDrawPartShapeProfile.updated_at.desc())
            .limit(1)
        )
        record = part_candidate_record(
            session,
            config,
            part,
            geometry,
            shape_profile,
        )
        upsert_fitting_candidate_profile(session, record)
        session.commit()
        return load_fitting_candidate_profile(
            engine,
            config,
            config["profile"]["candidate_types"]["part"],
            part.ldraw_part_num,
        )


def save_component_fitting_candidate_profile(
    engine: Engine,
    config: dict[str, Any],
    component_id: str,
) -> dict[str, Any]:
    """Persist one active Component Repo item in the unified basic index."""
    Session = sessionmaker(bind=engine)
    with Session() as session:
        component = session.get(Component, component_id)
        if component is None or component.current_version_id is None:
            raise ValueError(
                config["errors"]["candidate_not_found"].format(
                    candidate_type=config["profile"]["candidate_types"]["component"],
                    candidate_id=component_id,
                )
            )
        version = session.get(ComponentVersion, component.current_version_id)
        if version is None:
            raise ValueError(
                config["errors"]["candidate_not_found"].format(
                    candidate_type=config["profile"]["candidate_types"]["component"],
                    candidate_id=component_id,
                )
            )
        snapshot = session.get(ComponentSceneSnapshot, version.scene_snapshot_id)
        if snapshot is None:
            raise ValueError(
                config["errors"]["candidate_not_found"].format(
                    candidate_type=config["profile"]["candidate_types"]["component"],
                    candidate_id=component_id,
                )
            )
        geometry = component_geometry(session, snapshot.document_json)
        if geometry is None:
            raise ValueError(
                config["errors"]["candidate_not_found"].format(
                    candidate_type=config["profile"]["candidate_types"]["component"],
                    candidate_id=component_id,
                )
            )
        upsert_component_fitting_candidate_profile(
            session,
            config,
            component,
            version,
            snapshot,
            geometry,
        )
        session.commit()
        return load_fitting_candidate_profile(
            engine,
            config,
            config["profile"]["candidate_types"]["component"],
            component.id,
        )


def backfill_basic_fitting_candidate_profiles(
    engine: Engine,
    config: dict[str, Any],
    component_status: str,
    batch_size: int = 500,
) -> dict[str, int]:
    """Synchronize the basic index in idempotent, bounded transactions."""
    if batch_size <= 0:
        raise ValueError("fitting_candidate_profile.invalid_batch_size")
    Session = sessionmaker(bind=engine)
    if engine.dialect.name == "postgresql":
        part_count = backfill_postgresql_basic_part_profiles(engine, config)
    else:
        part_count = backfill_basic_part_profiles_in_batches(
            Session,
            config,
            batch_size,
        )

    with Session() as session:
        components = session.scalars(
            select(Component)
            .where(Component.status == component_status)
            .where(Component.current_version_id.is_not(None))
            .order_by(Component.created_at)
        ).all()
        component_records = []
        for component in components:
            version = session.get(ComponentVersion, component.current_version_id)
            if version is None:
                raise ValueError("fitting_candidate_profile.component_version_not_found")
            snapshot = session.get(ComponentSceneSnapshot, version.scene_snapshot_id)
            if snapshot is None:
                raise ValueError("fitting_candidate_profile.component_snapshot_not_found")
            geometry = component_geometry(session, snapshot.document_json)
            if geometry is None:
                raise ValueError("fitting_candidate_profile.component_geometry_not_found")
            component_records.append(
                component_candidate_record(
                    session,
                    config,
                    component,
                    version,
                    geometry,
                )
            )
        for start in range(0, len(component_records), batch_size):
            upsert_fitting_candidate_profiles(
                session,
                component_records[start : start + batch_size],
            )
            session.flush()
        active_component_ids = [component.id for component in components]
        stale_components = delete(FittingCandidateProfile).where(
            FittingCandidateProfile.candidate_type
            == config["profile"]["candidate_types"]["component"],
            FittingCandidateProfile.profile_key
            == config["profile"]["default_profile_key"],
        )
        if active_component_ids:
            stale_components = stale_components.where(
                FittingCandidateProfile.candidate_id.not_in(active_component_ids)
            )
        session.execute(stale_components)
        session.commit()
        return {
            "part": part_count,
            "component": len(component_records),
            "total": part_count + len(component_records),
        }


def backfill_basic_part_profiles_in_batches(
    Session,
    config: dict[str, Any],
    batch_size: int,
) -> int:
    part_count = 0
    last_part_id = 0
    while True:
        with Session() as session:
            part_rows = session.execute(
                select(LDrawPart, LDrawPartGeometry)
                .join(
                    LDrawPartGeometry,
                    LDrawPartGeometry.ldraw_part_id == LDrawPart.id,
                )
                .where(LDrawPart.id > last_part_id)
                .where(LDrawPartGeometry.logical_width_stud.is_not(None))
                .where(LDrawPartGeometry.logical_depth_stud.is_not(None))
                .where(LDrawPartGeometry.logical_height_plate.is_not(None))
                .order_by(LDrawPart.id)
                .limit(batch_size)
            ).all()
            if not part_rows:
                return part_count
            part_ids = [part.id for part, _geometry in part_rows]
            part_numbers = [part.ldraw_part_num for part, _geometry in part_rows]
            ready_shape_profiles = {
                profile.ldraw_part_id: profile
                for profile in session.scalars(
                    select(LDrawPartShapeProfile).where(
                        LDrawPartShapeProfile.ldraw_part_id.in_(part_ids),
                        LDrawPartShapeProfile.profile_status
                        == config["profile"]["ready_status"],
                    )
                )
            }
            connector_summaries = connector_summaries_by_part(
                session,
                config,
                part_numbers,
            )
            records = [
                part_candidate_record(
                    session,
                    config,
                    part,
                    geometry,
                    ready_shape_profiles.get(part.id),
                    connector_summaries.get(
                        part.ldraw_part_num,
                        empty_connector_summary(config),
                    ),
                )
                for part, geometry in part_rows
            ]
            upsert_fitting_candidate_profiles(session, records)
            session.commit()
            part_count += len(part_rows)
            last_part_id = part_rows[-1][0].id


def backfill_postgresql_basic_part_profiles(
    engine: Engine,
    config: dict[str, Any],
) -> int:
    """Build the Part basic index inside PostgreSQL without transferring rows."""
    statement = text(
        """
        WITH connector_counts AS (
            SELECT ldraw_part_num,
                   normalized_connector_type,
                   connector_gender,
                   count(*) AS connector_count
            FROM connector_instances
            GROUP BY ldraw_part_num, normalized_connector_type, connector_gender
        ), connector_summaries AS (
            SELECT ldraw_part_num,
                   json_build_object(
                       'totalCount', sum(connector_count),
                       'byTypeGender', json_agg(
                           json_build_object(
                               'connectorType', coalesce(
                                   normalized_connector_type,
                                   :unknown_connector_type
                               ),
                               'connectorGender', coalesce(
                                   connector_gender,
                                   :unknown_connector_gender
                               ),
                               'count', connector_count
                           )
                           ORDER BY normalized_connector_type, connector_gender
                       )
                   ) AS connector_summary
            FROM connector_counts
            GROUP BY ldraw_part_num
        ), eligible_parts AS (
            SELECT p.ldraw_part_num, p.file_hash, p.category, p.name,
                   p.content_locale,
                   g.bbox_min_x, g.bbox_min_y, g.bbox_min_z,
                   g.bbox_max_x, g.bbox_max_y, g.bbox_max_z,
                   g.width_ldu, g.height_ldu, g.depth_ldu,
                   g.logical_width_stud, g.logical_depth_stud,
                   g.logical_height_plate,
                   lower(concat_ws(' ', p.category, p.name)) AS search_text
            FROM ldraw_parts p
            JOIN ldraw_part_geometry g ON g.ldraw_part_id = p.id
            WHERE g.logical_width_stud IS NOT NULL
              AND g.logical_depth_stud IS NOT NULL
              AND g.logical_height_plate IS NOT NULL
        )
        INSERT INTO fitting_candidate_profiles (
            candidate_type, candidate_id, profile_key, profile_status,
            source_hash, shape_signature, bbox_json, logical_size_json,
            width_stud, depth_stud, height_plate, is_sticker, normalized_type,
            shape_profile_json, appearance_tags_json, color_summary_json,
            connector_summary_json, source_metadata_json,
            profile_error_code, profile_error_params_json
        )
        SELECT
            :candidate_type,
            p.ldraw_part_num,
            :profile_key,
            :profile_status,
            coalesce(nullif(p.file_hash, ''), lpad(md5(p.ldraw_part_num), 64, '0')),
            left(
                concat(
                    'part', ':', p.ldraw_part_num,
                    ':', 'basic', ':', 'bbox', ':',
                    p.width_ldu, 'x', p.height_ldu, 'x', p.depth_ldu,
                    ':', 'logical', ':', p.logical_width_stud, 'x',
                    p.logical_depth_stud, 'x', p.logical_height_plate
                ),
                255
            ),
            json_build_object(
                'bbox', json_build_object(
                    'minX', p.bbox_min_x, 'minY', p.bbox_min_y, 'minZ', p.bbox_min_z,
                    'maxX', p.bbox_max_x, 'maxY', p.bbox_max_y, 'maxZ', p.bbox_max_z,
                    'widthLdu', p.width_ldu, 'heightLdu', p.height_ldu,
                    'depthLdu', p.depth_ldu
                )
            ),
            json_build_object(
                'logicalSize', json_build_object(
                    'widthStud', p.logical_width_stud,
                    'depthStud', p.logical_depth_stud,
                    'heightPlate', p.logical_height_plate
                )
            ),
            p.logical_width_stud,
            p.logical_depth_stud,
            p.logical_height_plate,
            p.search_text ~ '(sticker|decal)',
            CASE
                WHEN p.search_text ~ '(^|[^[:alnum:]_])slope[[:alnum:]_]*' THEN 'slope'
                WHEN p.search_text ~ '(^|[^[:alnum:]_])tile[[:alnum:]_]*' THEN 'tile'
                WHEN p.search_text ~ '(^|[^[:alnum:]_])plate[[:alnum:]_]*' THEN 'plate'
                ELSE NULL
            END,
            '{}'::json,
            json_build_object('category', p.category, 'name', p.name),
            NULL,
            coalesce(
                c.connector_summary,
                '{"totalCount": 0, "byTypeGender": []}'::json
            ),
            json_build_object('contentLocale', p.content_locale),
            NULL,
            NULL
        FROM eligible_parts p
        LEFT JOIN connector_summaries c
          ON c.ldraw_part_num = p.ldraw_part_num
        ON CONFLICT ON CONSTRAINT uk_fitting_candidate_profile DO UPDATE SET
            profile_status = EXCLUDED.profile_status,
            source_hash = EXCLUDED.source_hash,
            shape_signature = EXCLUDED.shape_signature,
            bbox_json = EXCLUDED.bbox_json,
            logical_size_json = EXCLUDED.logical_size_json,
            width_stud = EXCLUDED.width_stud,
            depth_stud = EXCLUDED.depth_stud,
            height_plate = EXCLUDED.height_plate,
            is_sticker = EXCLUDED.is_sticker,
            normalized_type = EXCLUDED.normalized_type,
            shape_profile_json = EXCLUDED.shape_profile_json,
            appearance_tags_json = EXCLUDED.appearance_tags_json,
            color_summary_json = EXCLUDED.color_summary_json,
            connector_summary_json = EXCLUDED.connector_summary_json,
            source_metadata_json = EXCLUDED.source_metadata_json,
            profile_error_code = EXCLUDED.profile_error_code,
            profile_error_params_json = EXCLUDED.profile_error_params_json,
            updated_at = now()
        """
    )
    parameters = {
        "candidate_type": config["profile"]["candidate_types"]["part"],
        "profile_key": config["profile"]["default_profile_key"],
        "profile_status": config["profile"]["ready_status"],
        "unknown_connector_type": config["profile"]["unknown_connector_type"],
        "unknown_connector_gender": config["profile"]["unknown_connector_gender"],
    }
    with engine.begin() as connection:
        connection.execute(statement, parameters)
        return int(
            connection.scalar(
                select(func.count())
                .select_from(FittingCandidateProfile)
                .where(
                    FittingCandidateProfile.candidate_type
                    == config["profile"]["candidate_types"]["part"],
                    FittingCandidateProfile.profile_key
                    == config["profile"]["default_profile_key"],
                )
            )
            or 0
        )


def save_submodel_fitting_candidate_profile(
    engine: Engine,
    config: dict[str, Any],
    submodel_id: str,
) -> dict[str, Any]:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        submodel = session.scalar(
            select(LDrawSubmodel)
            .options(
                selectinload(LDrawSubmodel.parts),
                selectinload(LDrawSubmodel.connectors),
            )
            .where(LDrawSubmodel.id == submodel_id)
        )
        if submodel is None:
            raise ValueError(
                config["errors"]["submodel_not_found"].format(submodel_id=submodel_id)
            )
        try:
            record = submodel_candidate_record(session, config, submodel)
        except ValueError as error:
            record = failed_submodel_candidate_record(config, submodel, str(error))
        upsert_fitting_candidate_profile(session, record)
        session.commit()
        return load_fitting_candidate_profile(
            engine,
            config,
            config["profile"]["candidate_types"]["submodel"],
            submodel.id,
        )


def part_candidate_record(
    session: object,
    config: dict[str, Any],
    part: LDrawPart,
    geometry: LDrawPartGeometry,
    shape_profile: LDrawPartShapeProfile | None = None,
    connector_summary_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    logical_size = part_logical_size(config, geometry)
    appearance = appearance_payload(config, part)
    record = {
        "candidate_type": config["profile"]["candidate_types"]["part"],
        "candidate_id": part.ldraw_part_num,
        "profile_key": config["profile"]["default_profile_key"],
        "profile_status": config["profile"]["ready_status"],
        "source_hash": part_source_hash(config, part),
        "shape_signature": part_basic_signature(config, part, geometry),
        "bbox_json": geometry_bbox(config, geometry),
        "logical_size_json": logical_size,
        "shape_profile_json": (
            shape_payload(config, shape_profile)
            if shape_profile is not None
            else {}
        ),
        "appearance_tags_json": appearance,
        "color_summary_json": None,
        "connector_summary_json": (
            connector_summary_payload
            if connector_summary_payload is not None
            else connector_summary(session, config, part.ldraw_part_num)
        ),
        "source_metadata_json": source_metadata(
            config,
            shape_profile,
            part.content_locale,
        ),
        "profile_error_code": None,
        "profile_error_params_json": None,
    }
    record.update(
        persisted_search_fields(record["candidate_type"], logical_size, appearance)
    )
    return record


def upsert_component_fitting_candidate_profile(
    session: object,
    config: dict[str, Any],
    component: Component,
    version: ComponentVersion,
    snapshot: ComponentSceneSnapshot,
    geometry: dict[str, Any] | None = None,
) -> None:
    """Upsert a Component profile without committing the caller's transaction."""
    active_geometry = geometry or component_geometry(session, snapshot.document_json)
    if active_geometry is None:
        raise ValueError(
            config["errors"]["candidate_not_found"].format(
                candidate_type=config["profile"]["candidate_types"]["component"],
                candidate_id=component.id,
            )
        )
    record = component_candidate_record(
        session,
        config,
        component,
        version,
        active_geometry,
    )
    upsert_fitting_candidate_profile(session, record)


def remove_component_fitting_candidate_profile(
    session: object,
    config: dict[str, Any],
    component_id: str,
) -> None:
    session.execute(
        delete(FittingCandidateProfile).where(
            FittingCandidateProfile.candidate_type
            == config["profile"]["candidate_types"]["component"],
            FittingCandidateProfile.candidate_id == component_id,
            FittingCandidateProfile.profile_key
            == config["profile"]["default_profile_key"],
        )
    )


def component_candidate_record(
    session: object,
    config: dict[str, Any],
    component: Component,
    version: ComponentVersion,
    geometry: dict[str, Any],
) -> dict[str, Any]:
    keys = config["json_keys"]
    dimensions = config["geometry"]["bbox_dimensions"]
    logical_size = {
        keys["logical_size"]: {
            keys["width_stud"]: geometry["widthStud"],
            keys["depth_stud"]: geometry["depthStud"],
            keys["height_plate"]: geometry["heightPlate"],
        }
    }
    bbox = {
        keys["bbox"]: {
            dimensions["width_ldu"]: geometry["widthLdu"],
            dimensions["height_ldu"]: geometry["heightLdu"],
            dimensions["depth_ldu"]: geometry["depthLdu"],
        }
    }
    appearance = {
        keys["category"]: component.category,
        keys["name"]: component.name,
        keys["remarks"]: component.description,
        "tags": component.tags_json or [],
    }
    record = {
        "candidate_type": config["profile"]["candidate_types"]["component"],
        "candidate_id": component.id,
        "profile_key": config["profile"]["default_profile_key"],
        "profile_status": config["profile"]["ready_status"],
        "source_hash": version.structure_hash,
        "shape_signature": component_basic_signature(
            config,
            component,
            version,
            geometry,
        ),
        "bbox_json": bbox,
        "logical_size_json": logical_size,
        "shape_profile_json": {},
        "appearance_tags_json": appearance,
        "color_summary_json": None,
        "connector_summary_json": component_connector_summary(
            session,
            config,
            version.component_candidate_id,
        ),
        "source_metadata_json": {
            "componentVersionId": version.id,
            "contentLocale": component.content_locale,
            "contentKind": component.content_kind,
            keys["part_summary"]: {
                keys["total_count"]: geometry["partCount"],
                keys["by_category"]: [
                    {keys["category"]: category, keys["count"]: count}
                    for category, count in sorted(geometry["categoryCounts"].items())
                ],
            },
        },
        "profile_error_code": None,
        "profile_error_params_json": None,
    }
    record.update(
        persisted_search_fields(record["candidate_type"], logical_size, appearance)
    )
    return record


def submodel_candidate_record(
    session: object,
    config: dict[str, Any],
    submodel: LDrawSubmodel,
) -> dict[str, Any]:
    part_rows = submodel_part_rows(session, config, submodel)
    bbox = submodel_bbox(config, part_rows)
    connector_summary_payload = submodel_connector_summary(config, submodel.connectors)
    source_hash = submodel_source_hash(config, submodel)
    logical_size = submodel_logical_size(config, bbox)
    appearance = submodel_appearance_payload(config, submodel)
    record = {
        "candidate_type": config["profile"]["candidate_types"]["submodel"],
        "candidate_id": submodel.id,
        "profile_key": config["profile"]["default_profile_key"],
        "profile_status": config["profile"]["ready_status"],
        "source_hash": source_hash,
        "shape_signature": submodel_shape_signature(
            config,
            submodel,
            bbox,
            len(part_rows),
            connector_summary_payload[config["json_keys"]["total_count"]],
        ),
        "bbox_json": {config["json_keys"]["bbox"]: bbox},
        "logical_size_json": logical_size,
        "shape_profile_json": submodel_shape_payload(config, part_rows),
        "appearance_tags_json": appearance,
        "color_summary_json": submodel.color_percentages_json,
        "connector_summary_json": connector_summary_payload,
        "source_metadata_json": submodel_source_metadata(config, submodel, part_rows),
        "profile_error_code": None,
        "profile_error_params_json": None,
    }
    record.update(
        persisted_search_fields(record["candidate_type"], logical_size, appearance)
    )
    return record


def part_basic_signature(
    config: dict[str, Any],
    part: LDrawPart,
    geometry: LDrawPartGeometry,
) -> str:
    dimensions = config["geometry"]["bbox_dimensions"]
    bbox = geometry_bbox(config, geometry)[config["json_keys"]["bbox"]]
    logical_size = part_logical_size(config, geometry)[
        config["json_keys"]["logical_size"]
    ]
    return config["signature"]["part_basic_template"].format(
        candidate_id=part.ldraw_part_num,
        width_ldu=bbox[dimensions["width_ldu"]],
        height_ldu=bbox[dimensions["height_ldu"]],
        depth_ldu=bbox[dimensions["depth_ldu"]],
        width_stud=logical_size[config["json_keys"]["width_stud"]],
        depth_stud=logical_size[config["json_keys"]["depth_stud"]],
        height_plate=logical_size[config["json_keys"]["height_plate"]],
    )


def component_basic_signature(
    config: dict[str, Any],
    component: Component,
    version: ComponentVersion,
    geometry: dict[str, Any],
) -> str:
    return config["signature"]["component_basic_template"].format(
        candidate_id=component.id,
        version_id=version.id,
        width_ldu=geometry["widthLdu"],
        height_ldu=geometry["heightLdu"],
        depth_ldu=geometry["depthLdu"],
        width_stud=geometry["widthStud"],
        depth_stud=geometry["depthStud"],
        height_plate=geometry["heightPlate"],
    )


def part_shape_signature(
    config: dict[str, Any],
    part: LDrawPart,
    shape_profile: LDrawPartShapeProfile,
) -> str:
    bbox = shape_profile.bbox_json[config["json_keys"]["bbox"]]
    logical_size = shape_profile.logical_size_json[config["json_keys"]["logical_size"]]
    dimensions = config["geometry"]["bbox_dimensions"]
    return config["signature"]["part_template"].format(
        candidate_id=part.ldraw_part_num,
        width_ldu=bbox[dimensions["width_ldu"]],
        height_ldu=bbox[dimensions["height_ldu"]],
        depth_ldu=bbox[dimensions["depth_ldu"]],
        width_stud=logical_size[config["json_keys"]["width_stud"]],
        depth_stud=logical_size[config["json_keys"]["depth_stud"]],
        height_plate=logical_size[config["json_keys"]["height_plate"]],
        samples_per_stud_axis=shape_profile.samples_per_stud_axis,
    )


def submodel_shape_signature(
    config: dict[str, Any],
    submodel: LDrawSubmodel,
    bbox: dict[str, float],
    part_count: int,
    connector_count: int,
) -> str:
    dimensions = config["geometry"]["bbox_dimensions"]
    return config["signature"]["submodel_template"].format(
        candidate_id=submodel.id,
        width_ldu=bbox[dimensions["width_ldu"]],
        height_ldu=bbox[dimensions["height_ldu"]],
        depth_ldu=bbox[dimensions["depth_ldu"]],
        part_count=part_count,
        connector_count=connector_count,
    )


def failed_submodel_candidate_record(
    config: dict[str, Any],
    submodel: LDrawSubmodel,
    profile_error: str,
) -> dict[str, Any]:
    source_hash = submodel_source_hash(config, submodel)
    logical_size: dict[str, Any] = {}
    appearance = submodel_appearance_payload(config, submodel)
    record = {
        "candidate_type": config["profile"]["candidate_types"]["submodel"],
        "candidate_id": submodel.id,
        "profile_key": config["profile"]["default_profile_key"],
        "profile_status": config["profile"]["failed_status"],
        "source_hash": source_hash,
        "shape_signature": config["signature"]["failed_submodel_template"].format(
            candidate_id=submodel.id,
            source_hash=source_hash,
        ),
        "bbox_json": {},
        "logical_size_json": logical_size,
        "shape_profile_json": {
            config["json_keys"]["parts"]: submodel_part_placement_rows(
                config,
                submodel,
            ),
        },
        "appearance_tags_json": appearance,
        "color_summary_json": submodel.color_percentages_json,
        "connector_summary_json": submodel_connector_summary(config, submodel.connectors),
        "source_metadata_json": failed_submodel_source_metadata(
            config,
            submodel,
        ),
        "profile_error_code": (
            profile_error
            if MACHINE_CODE_PATTERN.fullmatch(profile_error)
            else "fitting_candidate_profile.generation_failed"
        ),
        "profile_error_params_json": {"candidateId": submodel.id},
    }
    record.update(
        persisted_search_fields(record["candidate_type"], logical_size, appearance)
    )
    return record


def shape_payload(
    config: dict[str, Any],
    shape_profile: LDrawPartShapeProfile,
) -> dict[str, Any]:
    return {
        config["json_keys"]["surface_profile"]: shape_profile.surface_profile_json,
        config["json_keys"]["collision_profile"]: shape_profile.collision_profile_json,
        config["json_keys"]["connection_mask"]: shape_profile.connection_mask_json,
    }


def submodel_shape_payload(
    config: dict[str, Any],
    part_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        config["json_keys"]["parts"]: part_rows,
    }


def appearance_payload(config: dict[str, Any], part: LDrawPart) -> dict[str, Any]:
    return {
        config["json_keys"]["category"]: part.category,
        config["json_keys"]["name"]: part.name,
    }


def submodel_appearance_payload(
    config: dict[str, Any],
    submodel: LDrawSubmodel,
) -> dict[str, Any]:
    return {
        config["json_keys"]["name"]: submodel.name,
        config["json_keys"]["remarks"]: submodel.remarks,
    }


def source_metadata(
    config: dict[str, Any],
    shape_profile: LDrawPartShapeProfile | None,
    content_locale: str,
) -> dict[str, Any]:
    metadata = {"contentLocale": content_locale}
    if shape_profile is not None:
        metadata[config["json_keys"]["source_shape_profile_key"]] = (
            shape_profile.profile_key
        )
    return metadata


def submodel_source_metadata(
    config: dict[str, Any],
    submodel: LDrawSubmodel,
    part_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        config["json_keys"]["part_count"]: len(part_rows),
        config["json_keys"]["connector_count"]: len(submodel.connectors),
        config["json_keys"]["part_summary"]: submodel_part_summary(
            config,
            part_rows,
        ),
        config["json_keys"]["source_submodel_updated_at"]: (
            submodel.updated_at.isoformat()
            if submodel.updated_at
            else submodel.created_at.isoformat()
        ),
    }


def failed_submodel_source_metadata(
    config: dict[str, Any],
    submodel: LDrawSubmodel,
) -> dict[str, Any]:
    return {
        config["json_keys"]["part_count"]: len(submodel.parts),
        config["json_keys"]["connector_count"]: len(submodel.connectors),
        config["json_keys"]["source_submodel_updated_at"]: (
            submodel.updated_at.isoformat()
            if submodel.updated_at
            else submodel.created_at.isoformat()
        ),
    }


def connector_summary(
    session: object,
    config: dict[str, Any],
    part_id: str,
) -> dict[str, Any]:
    rows = session.execute(
        select(
            ConnectorInstance.normalized_connector_type,
            ConnectorInstance.connector_gender,
            func.count(ConnectorInstance.id),
        )
        .where(ConnectorInstance.ldraw_part_num == part_id)
        .group_by(
            ConnectorInstance.normalized_connector_type,
            ConnectorInstance.connector_gender,
        )
        .order_by(
            ConnectorInstance.normalized_connector_type,
            ConnectorInstance.connector_gender,
        )
    )
    connector_rows = [
        {
            config["json_keys"]["connector_type"]: connector_type
            or config["profile"]["unknown_connector_type"],
            config["json_keys"]["connector_gender"]: connector_gender
            or config["profile"]["unknown_connector_gender"],
            config["json_keys"]["count"]: count,
        }
        for connector_type, connector_gender, count in rows
    ]
    return {
        config["json_keys"]["total_count"]: sum(
            item[config["json_keys"]["count"]]
            for item in connector_rows
        ),
        config["json_keys"]["by_type_gender"]: connector_rows,
    }


def empty_connector_summary(config: dict[str, Any]) -> dict[str, Any]:
    return {
        config["json_keys"]["total_count"]: 0,
        config["json_keys"]["by_type_gender"]: [],
    }


def connector_summaries_by_part(
    session: object,
    config: dict[str, Any],
    part_ids: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    statement = (
        select(
            ConnectorInstance.ldraw_part_num,
            ConnectorInstance.normalized_connector_type,
            ConnectorInstance.connector_gender,
            func.count(ConnectorInstance.id),
        )
        .group_by(
            ConnectorInstance.ldraw_part_num,
            ConnectorInstance.normalized_connector_type,
            ConnectorInstance.connector_gender,
        )
        .order_by(
            ConnectorInstance.ldraw_part_num,
            ConnectorInstance.normalized_connector_type,
            ConnectorInstance.connector_gender,
        )
    )
    if part_ids is not None:
        statement = statement.where(ConnectorInstance.ldraw_part_num.in_(part_ids))
    rows = session.execute(statement).all()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for part_id, connector_type, connector_gender, count in rows:
        grouped.setdefault(part_id, []).append(
            {
                config["json_keys"]["connector_type"]: connector_type
                or config["profile"]["unknown_connector_type"],
                config["json_keys"]["connector_gender"]: connector_gender
                or config["profile"]["unknown_connector_gender"],
                config["json_keys"]["count"]: count,
            }
        )
    return {
        part_id: {
            config["json_keys"]["total_count"]: sum(
                row[config["json_keys"]["count"]] for row in connector_rows
            ),
            config["json_keys"]["by_type_gender"]: connector_rows,
        }
        for part_id, connector_rows in grouped.items()
    }


def component_connector_summary(
    session: object,
    config: dict[str, Any],
    component_candidate_id: str,
) -> dict[str, Any]:
    interfaces = session.scalars(
        select(ComponentInterface).where(
            ComponentInterface.component_candidate_id == component_candidate_id
        )
    ).all()
    grouped: dict[tuple[str, str], int] = {}
    for interface in interfaces:
        source = interface.source_connector_json or {}
        connector_type = (
            source.get("connectorType")
            or config["profile"]["unknown_connector_type"]
        )
        connector_gender = (
            source.get("connectorGender")
            or config["profile"]["unknown_connector_gender"]
        )
        key = (connector_type, connector_gender)
        grouped[key] = grouped.get(key, 0) + 1
    return {
        config["json_keys"]["total_count"]: len(interfaces),
        config["json_keys"]["by_type_gender"]: [
            {
                config["json_keys"]["connector_type"]: connector_type,
                config["json_keys"]["connector_gender"]: connector_gender,
                config["json_keys"]["count"]: count,
            }
            for (connector_type, connector_gender), count in sorted(grouped.items())
        ],
    }


def submodel_connector_summary(
    config: dict[str, Any],
    connectors: list[LDrawSubmodelConnector],
) -> dict[str, Any]:
    grouped_connectors: dict[tuple[str, str], int] = {}
    for connector in connectors:
        connector_key = (
            connector.normalized_connector_type
            or config["profile"]["unknown_connector_type"],
            connector.connector_gender
            or config["profile"]["unknown_connector_gender"],
        )
        grouped_connectors[connector_key] = grouped_connectors.get(connector_key, 0) + 1
    return {
        config["json_keys"]["total_count"]: len(connectors),
        config["json_keys"]["by_type_gender"]: [
            {
                config["json_keys"]["connector_type"]: connector_type,
                config["json_keys"]["connector_gender"]: connector_gender,
                config["json_keys"]["count"]: count,
            }
            for (connector_type, connector_gender), count in sorted(grouped_connectors.items())
        ],
        config["json_keys"]["submodel_connectors"]: [
            {
                config["json_keys"]["part_line_no"]: connector.part_line_no,
                config["json_keys"]["connector_label"]: connector.connector_label,
                config["json_keys"]["connector_type"]: connector.normalized_connector_type,
                config["json_keys"]["connector_gender"]: connector.connector_gender,
                config["json_keys"]["position"]: stored_position(config, connector),
                config["json_keys"]["orientation"]: stored_orientation(config, connector),
                config["json_keys"]["metadata"]: connector.metadata_json,
            }
            for connector in sorted(connectors, key=lambda item: item.connector_label)
        ],
    }


def submodel_part_rows(
    session: object,
    config: dict[str, Any],
    submodel: LDrawSubmodel,
) -> list[dict[str, Any]]:
    if len(submodel.parts) == 0:
        raise ValueError(
            config["errors"]["submodel_has_no_parts"].format(submodel_id=submodel.id)
        )
    rows = []
    for submodel_part in sorted(submodel.parts, key=lambda item: item.line_no):
        row = session.execute(
            select(LDrawPart, LDrawPartGeometry)
            .join(LDrawPart, LDrawPartGeometry.ldraw_part_id == LDrawPart.id)
            .where(LDrawPart.ldraw_part_num == submodel_part.ldraw_part_num)
        ).first()
        if row is None:
            raise ValueError(
                config["errors"]["submodel_part_geometry_not_found"].format(
                    ldraw_part_num=submodel_part.ldraw_part_num,
                )
            )
        part, part_geometry = row
        rows.append(
            {
                config["json_keys"]["line_no"]: submodel_part.line_no,
                config["json_keys"]["color_code"]: submodel_part.color_code,
                config["json_keys"]["ldraw_part_num"]: submodel_part.ldraw_part_num,
                config["json_keys"]["category"]: part.category,
                config["json_keys"]["position"]: stored_position(config, submodel_part),
                config["json_keys"]["orientation"]: stored_orientation(config, submodel_part),
                config["json_keys"]["part_bbox"]: geometry_bbox(config, part_geometry),
            }
        )
    return rows


def submodel_part_placement_rows(
    config: dict[str, Any],
    submodel: LDrawSubmodel,
) -> list[dict[str, Any]]:
    return [
        {
            config["json_keys"]["line_no"]: part.line_no,
            config["json_keys"]["color_code"]: part.color_code,
            config["json_keys"]["ldraw_part_num"]: part.ldraw_part_num,
            config["json_keys"]["position"]: stored_position(config, part),
            config["json_keys"]["orientation"]: stored_orientation(config, part),
        }
        for part in sorted(submodel.parts, key=lambda item: item.line_no)
    ]


def submodel_part_summary(
    config: dict[str, Any],
    part_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        config["json_keys"]["total_count"]: len(part_rows),
        config["json_keys"]["by_part"]: grouped_count_rows(
            part_rows,
            config["json_keys"]["ldraw_part_num"],
            config["json_keys"]["count"],
        ),
        config["json_keys"]["by_color"]: grouped_count_rows(
            part_rows,
            config["json_keys"]["color_code"],
            config["json_keys"]["count"],
        ),
        config["json_keys"]["by_category"]: grouped_count_rows(
            part_rows,
            config["json_keys"]["category"],
            config["json_keys"]["count"],
        ),
    }


def grouped_count_rows(
    rows: list[dict[str, Any]],
    group_key: str,
    count_key: str,
) -> list[dict[str, Any]]:
    grouped_counts: dict[str, int] = {}
    for row in rows:
        grouped_counts[row[group_key]] = grouped_counts.get(row[group_key], 0) + 1
    return [
        {
            group_key: group_value,
            count_key: count,
        }
        for group_value, count in sorted(grouped_counts.items())
    ]


def submodel_bbox(config: dict[str, Any], part_rows: list[dict[str, Any]]) -> dict[str, float]:
    transformed_corners = [
        transformed_corner
        for part_row in part_rows
        for transformed_corner in transformed_part_corners(config, part_row)
    ]
    axis_values = {
        axis: [corner[axis] for corner in transformed_corners]
        for axis in config["geometry"]["bbox_axes"]
    }
    coordinate_axes = config["geometry"]["coordinate_axes"]
    bbox = {
        config["geometry"]["bbox_axes"][axis]["min"]: min(axis_values[axis])
        for axis in coordinate_axes
    }
    bbox.update(
        {
            config["geometry"]["bbox_axes"][axis]["max"]: max(axis_values[axis])
            for axis in coordinate_axes
        }
    )
    dimensions = config["geometry"]["bbox_dimensions"]
    bbox.update(
        {
            dimensions[config["geometry"]["bbox_axis_dimensions"][axis]]: (
                bbox[config["geometry"]["bbox_axes"][axis]["max"]]
                - bbox[config["geometry"]["bbox_axes"][axis]["min"]]
            )
            for axis in coordinate_axes
        }
    )
    return bbox


def transformed_part_corners(
    config: dict[str, Any],
    part_row: dict[str, Any],
) -> list[dict[str, float]]:
    bbox = part_row[config["json_keys"]["part_bbox"]][config["json_keys"]["bbox"]]
    position = part_row[config["json_keys"]["position"]]
    orientation = part_row[config["json_keys"]["orientation"]]
    return [
        transform_point(
            config,
            bbox_corner(config, bbox, selector),
            position,
            orientation,
        )
        for selector in config["geometry"]["bbox_corner_selectors"]
    ]


def bbox_corner(
    config: dict[str, Any],
    bbox: dict[str, float],
    selector: dict[str, str],
) -> dict[str, float]:
    axes = config["geometry"]["bbox_axes"]
    return {
        axis: bbox[axes[axis][selector[axis]]]
        for axis in axes
    }


def transform_point(
    config: dict[str, Any],
    point: dict[str, float],
    position: dict[str, float],
    orientation: dict[str, float],
) -> dict[str, float]:
    return {
        axis: sum(
            orientation[field] * point[point_axis]
            for field, point_axis in zip(
                orientation_fields,
                config["geometry"]["coordinate_axes"],
            )
        )
        + position[axis]
        for axis, orientation_fields in config["geometry"]["transform_matrix"].items()
    }


def geometry_bbox(config: dict[str, Any], geometry: LDrawPartGeometry) -> dict[str, Any]:
    return {
        config["json_keys"]["bbox"]: {
            **{
                config["geometry"]["bbox_axes"][axis][bound]: getattr(
                    geometry,
                    config["geometry"]["bbox_model_fields"][axis][bound],
                )
                for axis in config["geometry"]["coordinate_axes"]
                for bound in config["geometry"]["bbox_axes"][axis]
            },
            **{
                config["geometry"]["bbox_dimensions"][dimension_key]: getattr(
                    geometry,
                    model_field,
                )
                for dimension_key, model_field in config["geometry"][
                    "bbox_dimension_model_fields"
                ].items()
            },
        }
    }


def part_logical_size(
    config: dict[str, Any],
    geometry: LDrawPartGeometry,
) -> dict[str, dict[str, float | None]]:
    return {
        config["json_keys"]["logical_size"]: {
            config["json_keys"]["width_stud"]: geometry.logical_width_stud,
            config["json_keys"]["depth_stud"]: geometry.logical_depth_stud,
            config["json_keys"]["height_plate"]: geometry.logical_height_plate,
        }
    }


def part_source_hash(config: dict[str, Any], part: LDrawPart) -> str:
    if part.file_hash:
        return part.file_hash
    return hashlib.sha256(
        part.ldraw_part_num.encode(config["geometry"]["hash_encoding"])
    ).hexdigest()


def submodel_logical_size(
    config: dict[str, Any],
    bbox: dict[str, float],
) -> dict[str, dict[str, float]]:
    dimensions = config["geometry"]["bbox_dimensions"]
    return {
        config["json_keys"]["logical_size"]: {
            config["json_keys"]["width_stud"]: bbox[dimensions["width_ldu"]]
            / config["geometry"]["ldu_per_stud"],
            config["json_keys"]["depth_stud"]: bbox[dimensions["depth_ldu"]]
            / config["geometry"]["ldu_per_stud"],
            config["json_keys"]["height_plate"]: bbox[dimensions["height_ldu"]]
            / config["geometry"]["ldu_per_plate"],
        }
    }


def submodel_source_hash(config: dict[str, Any], submodel: LDrawSubmodel) -> str:
    payload = {
        config["json_keys"]["name"]: submodel.name,
        config["json_keys"]["ldraw_content"]: submodel.ldraw_content,
        config["json_keys"]["color_percentages"]: submodel.color_percentages_json,
        config["json_keys"]["remarks"]: submodel.remarks,
        config["json_keys"]["parts"]: [
            {
                config["json_keys"]["line_no"]: part.line_no,
                config["json_keys"]["ldraw_part_num"]: part.ldraw_part_num,
                config["json_keys"]["position"]: stored_position(config, part),
                config["json_keys"]["orientation"]: stored_orientation(config, part),
            }
            for part in sorted(submodel.parts, key=lambda item: item.line_no)
        ],
    }
    encoded_payload = json.dumps(payload, sort_keys=True).encode(
        config["geometry"]["hash_encoding"]
    )
    return hashlib.sha256(encoded_payload).hexdigest()


def stored_position(config: dict[str, Any], row: object) -> dict[str, float]:
    return {
        axis: getattr(row, field)
        for axis, field in config["geometry"]["position_fields"].items()
    }


def stored_orientation(config: dict[str, Any], row: object) -> dict[str, float]:
    return {
        field: getattr(row, field)
        for field in config["geometry"]["orientation_fields"]
    }


def upsert_fitting_candidate_profile(session: object, record: dict[str, Any]) -> None:
    existing_profile = session.scalar(
        select(FittingCandidateProfile)
        .where(FittingCandidateProfile.candidate_type == record["candidate_type"])
        .where(FittingCandidateProfile.candidate_id == record["candidate_id"])
        .where(FittingCandidateProfile.profile_key == record["profile_key"])
    )
    if existing_profile is None:
        session.add(FittingCandidateProfile(**record))
        return
    for key, value in record.items():
        setattr(existing_profile, key, value)


def upsert_fitting_candidate_profiles(
    session: object,
    records: list[dict[str, Any]],
) -> None:
    if not records:
        return
    candidate_type = records[0]["candidate_type"]
    profile_key = records[0]["profile_key"]
    if any(
        record["candidate_type"] != candidate_type
        or record["profile_key"] != profile_key
        for record in records
    ):
        raise ValueError("fitting_candidate_profile.mixed_batch")
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as postgresql_insert

        statement = postgresql_insert(FittingCandidateProfile).values(records)
        immutable_keys = {"candidate_type", "candidate_id", "profile_key"}
        update_values = {
            key: getattr(statement.excluded, key)
            for key in records[0]
            if key not in immutable_keys
        }
        update_values["updated_at"] = func.now()
        session.execute(
            statement.on_conflict_do_update(
                constraint=FITTING_CANDIDATE_PROFILE_DATABASE_CONFIG[
                    "constraints"
                ]["candidate_profile_unique"],
                set_=update_values,
            )
        )
        return
    candidate_ids = [record["candidate_id"] for record in records]
    existing_profiles = {
        profile.candidate_id: profile
        for profile in session.scalars(
            select(FittingCandidateProfile)
            .where(FittingCandidateProfile.candidate_type == candidate_type)
            .where(FittingCandidateProfile.profile_key == profile_key)
            .where(FittingCandidateProfile.candidate_id.in_(candidate_ids))
        )
    }
    for record in records:
        existing = existing_profiles.get(record["candidate_id"])
        if existing is None:
            session.add(FittingCandidateProfile(**record))
            continue
        for key, value in record.items():
            setattr(existing, key, value)


def load_fitting_candidate_profile(
    engine: Engine,
    config: dict[str, Any],
    candidate_type: str,
    candidate_id: str,
) -> dict[str, Any]:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        profile = session.scalar(
            select(FittingCandidateProfile)
            .where(FittingCandidateProfile.candidate_type == candidate_type)
            .where(FittingCandidateProfile.candidate_id == candidate_id)
            .where(
                FittingCandidateProfile.profile_key
                == config["profile"]["default_profile_key"]
            )
        )
        if profile is None:
            raise ValueError(
                config["errors"]["candidate_not_found"].format(
                    candidate_type=candidate_type,
                    candidate_id=candidate_id,
                )
            )
        return fitting_candidate_response(profile)


def fitting_candidate_response(profile: FittingCandidateProfile) -> dict[str, Any]:
    return {
        "candidateType": profile.candidate_type,
        "candidateId": profile.candidate_id,
        "profileKey": profile.profile_key,
        "profileStatus": profile.profile_status,
        "sourceHash": profile.source_hash,
        "shapeSignature": profile.shape_signature,
        "bbox": profile.bbox_json,
        "logicalSize": profile.logical_size_json,
        "shapeProfile": profile.shape_profile_json,
        "appearanceTags": profile.appearance_tags_json,
        "colorSummary": profile.color_summary_json,
        "connectorSummary": profile.connector_summary_json,
        "sourceMetadata": profile.source_metadata_json,
        "profileError": (
            message(profile.profile_error_code, profile.profile_error_params_json)
            if profile.profile_error_code
            else None
        ),
    }
