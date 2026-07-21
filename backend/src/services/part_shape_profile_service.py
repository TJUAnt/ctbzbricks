"""Persisted LDraw part shape profile records."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import JSON, Engine, String, column, inspect, select, table, text
from sqlalchemy.orm import sessionmaker

from src.ldraw.surface_profile import PartSurfaceProfile
from src.i18n.messages import message
from src.model.models import LDrawPart, LDrawPartGeometry, LDrawPartShapeProfile


def ensure_part_shape_profile_table(engine: Engine) -> None:
    LDrawPartShapeProfile.__table__.create(bind=engine, checkfirst=True)
    ensure_part_shape_profile_error_columns(engine)


def ensure_part_shape_profile_error_columns(engine: Engine) -> None:
    table_name = LDrawPartShapeProfile.__tablename__
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    preparer = engine.dialect.identifier_preparer
    quoted_table = preparer.quote(table_name)
    definitions = {
        "profile_error_type": "VARCHAR(64) NULL",
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
        column("profile_error_type", String(length=64)),
        column("profile_error_code", String(length=160)),
        column("profile_error_params_json", JSON()),
    )
    with engine.begin() as connection:
        rows = connection.execute(
            text(
                "SELECT id, ldraw_part_id, profile_error "
                "FROM ldraw_part_shape_profiles "
                "WHERE profile_error IS NOT NULL AND profile_error_code IS NULL"
            )
        ).all()
        for profile_id, part_id, profile_error in rows:
            connection.execute(
                legacy_profiles.update()
                .where(legacy_profiles.c.id == profile_id)
                .values(
                    profile_error_type="unknown",
                    profile_error_code="part_shape_profile.unknown",
                    profile_error_params_json={
                        "ldrawPartId": part_id,
                        "legacyMessage": str(profile_error),
                    },
                )
            )


def save_part_surface_profile(
    engine: Engine,
    config: dict[str, Any],
    part_id: str,
    profile: PartSurfaceProfile,
    source_hash: str,
) -> dict[str, Any]:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        row = session.execute(
            select(LDrawPart, LDrawPartGeometry)
            .join(LDrawPartGeometry, LDrawPartGeometry.ldraw_part_id == LDrawPart.id)
            .where(LDrawPart.ldraw_part_num == part_id.lower())
        ).first()
        if row is None:
            raise ValueError(config["errors"]["part_not_found"].format(part_id=part_id))
        part, geometry = row
        record = part_surface_profile_record(config, part, geometry, profile, source_hash)
        upsert_part_shape_profile(session, record)
        session.commit()
        return load_part_shape_profile(engine, config, part_id)


def save_failed_part_shape_profile(
    engine: Engine,
    config: dict[str, Any],
    part_id: str,
    source_hash: str,
    profile_error: str,
) -> dict[str, Any]:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        part = session.scalar(
            select(LDrawPart).where(LDrawPart.ldraw_part_num == part_id.lower())
        )
        if part is None:
            raise ValueError(config["errors"]["part_not_found"].format(part_id=part_id))
        record = {
            "ldraw_part_id": part.id,
            "profile_key": config["profile"]["default_profile_key"],
            "samples_per_stud_axis": config["profile"]["failed_samples_per_stud_axis"],
            "profile_status": config["profile"]["failed_status"],
            "profile_error_type": classify_profile_error(config, profile_error),
            "source_hash": source_hash,
            "bbox_json": None,
            "logical_size_json": None,
            "surface_profile_json": None,
            "collision_profile_json": None,
            "connection_mask_json": None,
            "profile_error_code": f"part_shape_profile.{classify_profile_error(config, profile_error)}",
            "profile_error_params_json": {"partId": part_id},
        }
        upsert_part_shape_profile(session, record)
        session.commit()
        return load_part_shape_profile(engine, config, part_id)


def part_surface_profile_record(
    config: dict[str, Any],
    part: LDrawPart,
    geometry: LDrawPartGeometry,
    profile: PartSurfaceProfile,
    source_hash: str,
) -> dict[str, Any]:
    return {
        "ldraw_part_id": part.id,
        "profile_key": config["profile"]["default_profile_key"],
        "samples_per_stud_axis": profile.samples_per_stud_axis,
        "profile_status": config["profile"]["ready_status"],
        "profile_error_type": None,
        "source_hash": source_hash,
        "bbox_json": bbox_payload(config, geometry),
        "logical_size_json": logical_size_payload(config, geometry),
        "surface_profile_json": surface_profile_payload(config, profile),
        "collision_profile_json": collision_profile_payload(config, profile),
        "connection_mask_json": connection_mask_payload(config, profile),
        "profile_error_code": None,
        "profile_error_params_json": None,
    }


def upsert_part_shape_profile(session: object, record: dict[str, Any]) -> None:
    existing_profile = session.scalar(
        select(LDrawPartShapeProfile)
        .where(LDrawPartShapeProfile.ldraw_part_id == record["ldraw_part_id"])
        .where(LDrawPartShapeProfile.profile_key == record["profile_key"])
    )
    if existing_profile is None:
        session.add(LDrawPartShapeProfile(**record))
        return
    for key, value in record.items():
        setattr(existing_profile, key, value)


def classify_profile_error(config: dict[str, Any], profile_error: str) -> str:
    for error_type in config["profile"]["profile_error_types"]:
        if re.search(error_type["pattern"], profile_error):
            return error_type["type"]
    return config["profile"]["profile_error_unknown"]


def backfill_profile_error_types(
    engine: Engine,
    config: dict[str, Any],
) -> dict[str, int]:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        profiles = session.scalars(
            select(LDrawPartShapeProfile)
            .where(LDrawPartShapeProfile.profile_error_code.is_not(None))
        ).all()
        for profile in profiles:
            profile.profile_error_type = profile.profile_error_code.rsplit(".", 1)[-1]
        session.commit()
        return {"updated": len(profiles)}


def load_part_shape_profile(
    engine: Engine,
    config: dict[str, Any],
    part_id: str,
) -> dict[str, Any]:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        row = session.execute(
            select(LDrawPart, LDrawPartShapeProfile)
            .join(
                LDrawPartShapeProfile,
                LDrawPartShapeProfile.ldraw_part_id == LDrawPart.id,
            )
            .where(LDrawPart.ldraw_part_num == part_id.lower())
            .where(
                LDrawPartShapeProfile.profile_key
                == config["profile"]["default_profile_key"]
            )
        ).first()
        if row is None:
            raise ValueError(config["errors"]["profile_not_found"].format(part_id=part_id))
        part, profile = row
        return shape_profile_response(config, part, profile)


def bbox_payload(config: dict[str, Any], geometry: LDrawPartGeometry) -> dict[str, float | None]:
    return {
        config["json_keys"]["bbox"]: {
            "minX": geometry.bbox_min_x,
            "minY": geometry.bbox_min_y,
            "minZ": geometry.bbox_min_z,
            "maxX": geometry.bbox_max_x,
            "maxY": geometry.bbox_max_y,
            "maxZ": geometry.bbox_max_z,
            "widthLdu": geometry.width_ldu,
            "heightLdu": geometry.height_ldu,
            "depthLdu": geometry.depth_ldu,
        }
    }


def logical_size_payload(config: dict[str, Any], geometry: LDrawPartGeometry) -> dict[str, float | None]:
    return {
        config["json_keys"]["logical_size"]: {
            "widthStud": geometry.logical_width_stud,
            "depthStud": geometry.logical_depth_stud,
            "heightPlate": geometry.logical_height_plate,
        }
    }


def surface_profile_payload(
    config: dict[str, Any],
    profile: PartSurfaceProfile,
) -> dict[str, Any]:
    keys = config["json_keys"]
    return {
        keys["part_id"]: profile.part_id,
        keys["ldraw_origin_to_base_ldu"]: profile.ldraw_origin_to_base_ldu,
        keys["ldraw_center_x_ldu"]: profile.ldraw_center_x_ldu,
        keys["ldraw_center_z_ldu"]: profile.ldraw_center_z_ldu,
        keys["width_stud"]: profile.width_stud,
        keys["depth_stud"]: profile.depth_stud,
        keys["samples_per_stud_axis"]: profile.samples_per_stud_axis,
        keys["surface_height_plate"]: profile.surface_height_plate,
    }


def collision_profile_payload(
    config: dict[str, Any],
    profile: PartSurfaceProfile,
) -> dict[str, Any]:
    keys = config["json_keys"]
    return {
        keys["collision_intervals_plate"]: profile.collision_intervals_plate,
        keys["bottom_contact"]: profile.bottom_contact,
    }


def connection_mask_payload(
    config: dict[str, Any],
    profile: PartSurfaceProfile,
) -> dict[str, Any]:
    return {
        config["json_keys"]["top_connection_mask"]: profile.top_connection_mask,
    }


def shape_profile_response(
    config: dict[str, Any],
    part: LDrawPart,
    profile: LDrawPartShapeProfile,
) -> dict[str, Any]:
    return {
        config["json_keys"]["part_id"]: part.ldraw_part_num,
        "profileKey": profile.profile_key,
        "samplesPerStudAxis": profile.samples_per_stud_axis,
        "profileStatus": profile.profile_status,
        "profileErrorType": profile.profile_error_type,
        config["json_keys"]["source_hash"]: profile.source_hash,
        "bbox": profile.bbox_json,
        "logicalSize": profile.logical_size_json,
        "surfaceProfile": profile.surface_profile_json,
        "collisionProfile": profile.collision_profile_json,
        "connectionMask": profile.connection_mask_json,
        "profileError": (
            message(profile.profile_error_code, profile.profile_error_params_json)
            if profile.profile_error_code
            else None
        ),
    }
