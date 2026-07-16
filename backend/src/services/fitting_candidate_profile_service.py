"""Unified fitting candidate profile persistence."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import selectinload, sessionmaker

from src.model.models import (
    ConnectorInstance,
    FittingCandidateProfile,
    LDrawPart,
    LDrawPartShapeProfile,
    LDrawPartGeometry,
    LDrawSubmodel,
    LDrawSubmodelConnector,
    LDrawSubmodelPart,
)


def ensure_fitting_candidate_profile_table(engine: Engine) -> None:
    FittingCandidateProfile.__table__.create(bind=engine, checkfirst=True)


def save_part_fitting_candidate_profile(
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
                LDrawPartShapeProfile.profile_status
                == config["profile"]["ready_status"]
            )
        ).first()
        if row is None:
            raise ValueError(
                config["errors"]["candidate_not_found"].format(
                    candidate_type=config["profile"]["candidate_types"]["part"],
                    candidate_id=part_id,
                )
            )
        part, shape_profile = row
        record = part_candidate_record(
            session,
            config,
            part,
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
    shape_profile: LDrawPartShapeProfile,
) -> dict[str, Any]:
    return {
        "candidate_type": config["profile"]["candidate_types"]["part"],
        "candidate_id": part.ldraw_part_num,
        "profile_key": config["profile"]["default_profile_key"],
        "profile_status": config["profile"]["ready_status"],
        "source_hash": shape_profile.source_hash,
        "shape_signature": part_shape_signature(config, part, shape_profile),
        "bbox_json": shape_profile.bbox_json,
        "logical_size_json": shape_profile.logical_size_json,
        "shape_profile_json": shape_payload(config, shape_profile),
        "appearance_tags_json": appearance_payload(config, part),
        "color_summary_json": None,
        "connector_summary_json": connector_summary(session, config, part.ldraw_part_num),
        "source_metadata_json": source_metadata(config, shape_profile),
        "profile_error": None,
    }


def submodel_candidate_record(
    session: object,
    config: dict[str, Any],
    submodel: LDrawSubmodel,
) -> dict[str, Any]:
    part_rows = submodel_part_rows(session, config, submodel)
    bbox = submodel_bbox(config, part_rows)
    connector_summary_payload = submodel_connector_summary(config, submodel.connectors)
    source_hash = submodel_source_hash(config, submodel)
    return {
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
        "logical_size_json": submodel_logical_size(config, bbox),
        "shape_profile_json": submodel_shape_payload(config, part_rows),
        "appearance_tags_json": submodel_appearance_payload(config, submodel),
        "color_summary_json": submodel.color_percentages_json,
        "connector_summary_json": connector_summary_payload,
        "source_metadata_json": submodel_source_metadata(config, submodel, part_rows),
        "profile_error": None,
    }


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
    return {
        "candidate_type": config["profile"]["candidate_types"]["submodel"],
        "candidate_id": submodel.id,
        "profile_key": config["profile"]["default_profile_key"],
        "profile_status": config["profile"]["failed_status"],
        "source_hash": source_hash,
        "shape_signature": config["signature"]["failed_submodel_template"].format(
            candidate_id=submodel.id,
            source_hash=source_hash,
        ),
        "bbox_json": {
            config["json_keys"]["profile_error"]: profile_error,
        },
        "logical_size_json": {
            config["json_keys"]["profile_error"]: profile_error,
        },
        "shape_profile_json": {
            config["json_keys"]["parts"]: submodel_part_placement_rows(
                config,
                submodel,
            ),
        },
        "appearance_tags_json": submodel_appearance_payload(config, submodel),
        "color_summary_json": submodel.color_percentages_json,
        "connector_summary_json": submodel_connector_summary(config, submodel.connectors),
        "source_metadata_json": failed_submodel_source_metadata(
            config,
            submodel,
        ),
        "profile_error": profile_error,
    }


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
    shape_profile: LDrawPartShapeProfile,
) -> dict[str, Any]:
    return {
        config["json_keys"]["source_shape_profile_key"]: shape_profile.profile_key,
    }


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
        "profileError": profile.profile_error,
    }
