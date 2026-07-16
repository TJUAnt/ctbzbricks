"""Persistence and parsing for reusable LDraw submodels."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import selectinload, sessionmaker

from src.model.models import (
    LDrawSubmodel,
    LDrawSubmodelConnector,
    LDrawSubmodelPart,
)


def ensure_submodel_tables(engine: Engine) -> None:
    LDrawSubmodel.__table__.create(bind=engine, checkfirst=True)
    LDrawSubmodelPart.__table__.create(bind=engine, checkfirst=True)
    LDrawSubmodelConnector.__table__.create(bind=engine, checkfirst=True)


def create_submodel(
    engine: Engine,
    config: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    parts = parse_ldraw_submodel_parts(payload["ldrawContent"], config)
    validate_submodel_payload(config, payload, parts)
    submodel_id = uuid4().hex[: int(config["storage"]["submodel_id_hex_length"])]
    created_at = datetime.now(timezone.utc)
    submodel = LDrawSubmodel(
        id=submodel_id,
        name=payload["name"],
        ldraw_content=payload["ldrawContent"],
        color_percentages_json=payload["colorPercentages"],
        remarks=payload["remarks"],
        created_at=created_at,
        parts=[
            LDrawSubmodelPart(
                line_no=part["lineNo"],
                color_code=part["colorCode"],
                ldraw_part_num=part["ldrawPartNum"],
                pos_x=part["position"]["x"],
                pos_y=part["position"]["y"],
                pos_z=part["position"]["z"],
                **orientation_columns(part["orientation"], config),
            )
            for part in parts
        ],
        connectors=[
            LDrawSubmodelConnector(
                part_line_no=connector["partLineNo"],
                connector_label=connector["connectorLabel"],
                connector_kind=connector["connectorKind"],
                normalized_connector_type=connector["normalizedConnectorType"],
                connector_gender=connector["connectorGender"],
                pos_x=connector["position"]["x"],
                pos_y=connector["position"]["y"],
                pos_z=connector["position"]["z"],
                **orientation_columns(connector["orientation"], config),
                metadata_json=connector["metadata"],
            )
            for connector in payload["connectionPoints"]
        ],
    )
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(submodel)
        session.commit()
        session.refresh(submodel)
        return submodel_response(submodel)


def parse_ldraw_submodel_parts(
    ldraw_content: str,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    if not ldraw_content.strip():
        raise ValueError(config["errors"]["empty_ldraw_content"])
    indices = config["ldraw"]["indices"]
    parts = []
    lines = ldraw_content.split(config["ldraw"]["line_separator"])
    for line_no, line in enumerate(lines, start=config["ldraw"]["line_number_start"]):
        stripped_line = line.strip()
        if not stripped_line:
            continue
        tokens = stripped_line.split()
        if tokens[indices["line_type"]] != config["ldraw"]["part_line_type"]:
            continue
        if len(tokens) < config["ldraw"]["part_line_token_count"]:
            raise ValueError(
                config["errors"]["invalid_ldraw_part_line"].format(line_number=line_no)
            )
        try:
            parts.append(
                {
                    "lineNo": line_no,
                    "colorCode": tokens[indices["color_code"]],
                    "ldrawPartNum": tokens[indices["ldraw_part_num"]].lower(),
                    "position": {
                        "x": float(tokens[indices["pos_x"]]),
                        "y": float(tokens[indices["pos_y"]]),
                        "z": float(tokens[indices["pos_z"]]),
                    },
                    "orientation": [
                        float(tokens[indices["ori_11"]]),
                        float(tokens[indices["ori_12"]]),
                        float(tokens[indices["ori_13"]]),
                        float(tokens[indices["ori_21"]]),
                        float(tokens[indices["ori_22"]]),
                        float(tokens[indices["ori_23"]]),
                        float(tokens[indices["ori_31"]]),
                        float(tokens[indices["ori_32"]]),
                        float(tokens[indices["ori_33"]]),
                    ],
                }
            )
        except ValueError as error:
            raise ValueError(
                config["errors"]["invalid_ldraw_part_line"].format(line_number=line_no)
            ) from error
    return parts


def validate_submodel_payload(
    config: dict[str, Any],
    payload: dict[str, Any],
    parts: list[dict[str, Any]],
) -> None:
    if len(parts) < config["ldraw"]["minimum_part_count"]:
        raise ValueError(config["errors"]["insufficient_parts"])
    for color_percentage in payload["colorPercentages"]:
        if (
            color_percentage["percentage"]
            < config["color_percentages"]["minimum_percentage"]
            or color_percentage["percentage"]
            > config["color_percentages"]["maximum_percentage"]
        ):
            raise ValueError(config["errors"]["invalid_color_percentage"])
    for connector in payload["connectionPoints"]:
        if (
            len(connector["orientation"])
            != config["connection_points"]["orientation_value_count"]
        ):
            raise ValueError(config["errors"]["invalid_connection_point_orientation"])


def get_submodel(
    engine: Engine,
    submodel_id: str,
) -> dict[str, Any] | None:
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
            return None
        return submodel_response(submodel)


def paginated_submodels(
    engine: Engine,
    config: dict[str, Any],
    page: int,
    page_size: int,
) -> dict[str, Any]:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        total = session.scalar(select(func.count()).select_from(LDrawSubmodel))
        submodels = session.scalars(
            select(LDrawSubmodel)
            .options(
                selectinload(LDrawSubmodel.parts),
                selectinload(LDrawSubmodel.connectors),
            )
            .order_by(LDrawSubmodel.created_at.desc())
            .offset((page - config["pagination"]["default_page"]) * page_size)
            .limit(page_size)
        ).all()
        return {
            "page": page,
            "pageSize": page_size,
            "total": total,
        "items": [submodel_response(submodel) for submodel in submodels],
        }


def orientation_columns(
    orientation: list[float],
    config: dict[str, Any],
) -> dict[str, float]:
    indices = config["connection_points"]["orientation_indices"]
    return {
        "ori_11": orientation[indices["ori_11"]],
        "ori_12": orientation[indices["ori_12"]],
        "ori_13": orientation[indices["ori_13"]],
        "ori_21": orientation[indices["ori_21"]],
        "ori_22": orientation[indices["ori_22"]],
        "ori_23": orientation[indices["ori_23"]],
        "ori_31": orientation[indices["ori_31"]],
        "ori_32": orientation[indices["ori_32"]],
        "ori_33": orientation[indices["ori_33"]],
    }


def stored_orientation(row: object) -> list[float]:
    return [
        row.ori_11,
        row.ori_12,
        row.ori_13,
        row.ori_21,
        row.ori_22,
        row.ori_23,
        row.ori_31,
        row.ori_32,
        row.ori_33,
    ]


def submodel_response(submodel: LDrawSubmodel) -> dict[str, Any]:
    return {
        "id": submodel.id,
        "name": submodel.name,
        "ldrawContent": submodel.ldraw_content,
        "colorPercentages": submodel.color_percentages_json,
        "remarks": submodel.remarks,
        "parts": [
            {
                "lineNo": part.line_no,
                "colorCode": part.color_code,
                "ldrawPartNum": part.ldraw_part_num,
                "position": {"x": part.pos_x, "y": part.pos_y, "z": part.pos_z},
                "orientation": stored_orientation(part),
            }
            for part in sorted(submodel.parts, key=lambda part: part.line_no)
        ],
        "connectionPoints": [
            {
                "partLineNo": connector.part_line_no,
                "connectorLabel": connector.connector_label,
                "connectorKind": connector.connector_kind,
                "normalizedConnectorType": connector.normalized_connector_type,
                "connectorGender": connector.connector_gender,
                "position": {
                    "x": connector.pos_x,
                    "y": connector.pos_y,
                    "z": connector.pos_z,
                },
                "orientation": stored_orientation(connector),
                "metadata": connector.metadata_json,
            }
            for connector in sorted(
                submodel.connectors,
                key=lambda connector: connector.connector_label,
            )
        ],
        "createdAt": submodel.created_at.isoformat(),
        "updatedAt": submodel.updated_at.isoformat() if submodel.updated_at else None,
    }
