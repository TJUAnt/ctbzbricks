"""Connection recognition and review services for Component Repo."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import sessionmaker

from src.model.models import (
    ComponentAssemblyRelation,
    ComponentCandidate,
    ComponentRelationCandidate,
    ComponentSceneSnapshot,
    ComponentVersion,
    ConnectorInstance,
    PartConnectorDefinition,
    PartLibraryVersion,
)


def ensure_part_library_version(
    engine: Engine,
    config: dict[str, Any],
    version_id: str | None = None,
) -> dict[str, Any]:
    """Create or return the default frozen connector library snapshot metadata."""
    version_id = version_id or config["part_library"]["default_version_id"]
    Session = sessionmaker(bind=engine)
    with Session() as session:
        existing = session.get(PartLibraryVersion, version_id)
        if existing is not None:
            return part_library_version_response(existing)
        source_connectors = session.scalars(select(ConnectorInstance).order_by(ConnectorInstance.id)).all()
        connector_count = len(source_connectors)
        source_hash = connector_source_hash(session)
        now = datetime.now(timezone.utc)
        version = PartLibraryVersion(
            id=version_id,
            source_table=config["part_library"]["source_table"],
            source_hash=source_hash,
            connector_count=connector_count,
            status=config["part_library"]["status"]["active"],
            metadata_json={
                "snapshotMode": "frozen_definitions",
                "sourceTable": config["part_library"]["source_table"],
            },
            created_by=config["audit"]["system_user"],
            created_at=now,
        )
        session.add(version)
        next_definition_id = (session.scalar(select(func.max(PartConnectorDefinition.id))) or 0) + 1
        for offset, connector in enumerate(source_connectors):
            session.add(
                part_connector_definition_from_instance(
                    next_definition_id + offset,
                    version_id,
                    connector,
                    now,
                )
            )
        session.commit()
        session.refresh(version)
        return part_library_version_response(version)


def detect_relation_candidates(
    engine: Engine,
    config: dict[str, Any],
    component_candidate_id: str,
    part_library_version_id: str | None = None,
) -> list[dict[str, Any]]:
    """Detect compatible connector pairs for a parsed component candidate."""
    part_library = ensure_part_library_version(engine, config, part_library_version_id)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        candidate = session.get(ComponentCandidate, component_candidate_id)
        if candidate is None:
            raise ValueError(f"Component candidate not found: {component_candidate_id}")
        ensure_candidate_not_published(session, config, component_candidate_id)
        snapshot = session.get(ComponentSceneSnapshot, candidate.scene_snapshot_id)
        if snapshot is None:
            raise ValueError(f"Component scene snapshot not found: {candidate.scene_snapshot_id}")
        world_parts = expanded_world_parts(snapshot.document_json)
        connectors = world_connectors_for_parts(session, world_parts, part_library["id"])
        existing = session.scalars(
            select(ComponentRelationCandidate).where(
                ComponentRelationCandidate.component_candidate_id == component_candidate_id
            )
        ).all()
        if existing:
            candidate.status = config["candidates"]["status"]["in_review"]
            candidate.review_decisions_json = {
                **(candidate.review_decisions_json or {}),
                "relationDetectionCompleted": True,
                "partLibraryVersionId": part_library["id"],
            }
            session.commit()
            return [relation_candidate_response(row) for row in existing]
        rows = []
        for index_a, connector_a in enumerate(connectors):
            for connector_b in connectors[index_a + 1 :]:
                rule = compatibility_rule(config, connector_a, connector_b)
                if rule is None:
                    continue
                metrics = connector_pair_metrics(connector_a, connector_b)
                if metrics["positionResidual"] > float(rule["candidate_lateral_ldu"]):
                    continue
                if metrics["rotationResidual"] > float(rule["candidate_axis_angle_deg"]):
                    continue
                verified = (
                    metrics["positionResidual"] <= float(rule["verified_lateral_ldu"])
                    and metrics["rotationResidual"] <= float(rule["verified_axis_angle_deg"])
                )
                relation = ComponentRelationCandidate(
                    id=str(uuid4()),
                    component_candidate_id=component_candidate_id,
                    part_library_version_id=part_library["id"],
                    endpoint_a_json=connector_endpoint(connector_a),
                    endpoint_b_json=connector_endpoint(connector_b),
                    connection_type=rule["connection_type"],
                    joint_type=rule["joint_type"],
                    position_residual=metrics["positionResidual"],
                    rotation_residual=metrics["rotationResidual"],
                    verified_by_tolerance=verified,
                    confidence=confidence_from_metrics(metrics, rule),
                    status=config["relations"]["candidate_status"]["pending"],
                    detection_method=config["relations"]["detection_method"]["automatic"],
                    metadata_json={
                        "rule": rule,
                        "metrics": metrics,
                    },
                    created_at=datetime.now(timezone.utc),
                )
                session.add(relation)
                rows.append(relation)
        candidate.status = config["candidates"]["status"]["in_review"]
        candidate.review_decisions_json = {
            **(candidate.review_decisions_json or {}),
            "relationDetectionCompleted": True,
            "partLibraryVersionId": part_library["id"],
        }
        session.commit()
        for row in rows:
            session.refresh(row)
        return [relation_candidate_response(row) for row in rows]


def list_relation_candidates(
    engine: Engine,
    component_candidate_id: str,
) -> list[dict[str, Any]]:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        rows = session.scalars(
            select(ComponentRelationCandidate)
            .where(ComponentRelationCandidate.component_candidate_id == component_candidate_id)
            .order_by(ComponentRelationCandidate.created_at.asc())
        ).all()
        return [relation_candidate_response(row) for row in rows]


def confirm_relation_candidate(
    engine: Engine,
    config: dict[str, Any],
    relation_candidate_id: str,
    confirmed_by: str | None = None,
    component_candidate_id: str | None = None,
) -> dict[str, Any]:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        relation = session.get(ComponentRelationCandidate, relation_candidate_id)
        if relation is None:
            raise ValueError(f"Component relation candidate not found: {relation_candidate_id}")
        if component_candidate_id is not None and relation.component_candidate_id != component_candidate_id:
            raise ValueError(
                f"Component relation candidate {relation_candidate_id} does not belong to candidate {component_candidate_id}"
            )
        ensure_candidate_not_published(session, config, relation.component_candidate_id)
        existing = session.scalar(
            select(ComponentAssemblyRelation).where(
                ComponentAssemblyRelation.relation_candidate_id == relation_candidate_id
            )
        )
        if existing is not None:
            return assembly_relation_response(existing)
        if relation.status == config["relations"]["candidate_status"]["rejected"]:
            raise ValueError(f"Component relation candidate already rejected: {relation_candidate_id}")
        occupied = {
            connector_id
            for assembly in session.scalars(
                select(ComponentAssemblyRelation).where(
                    ComponentAssemblyRelation.component_candidate_id == relation.component_candidate_id
                )
            ).all()
            for connector_id in (
                assembly.endpoint_a_json.get("worldConnectorId"),
                assembly.endpoint_b_json.get("worldConnectorId"),
            )
        }
        relation_connector_ids = {
            relation.endpoint_a_json.get("worldConnectorId"),
            relation.endpoint_b_json.get("worldConnectorId"),
        }
        if occupied & relation_connector_ids:
            raise ValueError("component_repo.connector_capacity_exceeded")
        relation.status = config["relations"]["candidate_status"]["confirmed"]
        assembly = ComponentAssemblyRelation(
            id=str(uuid4()),
            component_candidate_id=relation.component_candidate_id,
            relation_candidate_id=relation.id,
            endpoint_a_json=relation.endpoint_a_json,
            endpoint_b_json=relation.endpoint_b_json,
            connection_type=relation.connection_type,
            joint_type=relation.joint_type,
            placement_json={
                "positionResidual": relation.position_residual,
                "rotationResidual": relation.rotation_residual,
                "verifiedByTolerance": relation.verified_by_tolerance,
            },
            confirmed_by=confirmed_by or config["audit"]["system_user"],
            confirmed_at=datetime.now(timezone.utc),
        )
        session.add(assembly)
        session.commit()
        session.refresh(assembly)
        session.refresh(relation)
        return assembly_relation_response(assembly)


def reject_relation_candidate(
    engine: Engine,
    config: dict[str, Any],
    relation_candidate_id: str,
    component_candidate_id: str | None = None,
) -> dict[str, Any]:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        relation = session.get(ComponentRelationCandidate, relation_candidate_id)
        if relation is None:
            raise ValueError(f"Component relation candidate not found: {relation_candidate_id}")
        if component_candidate_id is not None and relation.component_candidate_id != component_candidate_id:
            raise ValueError(
                f"Component relation candidate {relation_candidate_id} does not belong to candidate {component_candidate_id}"
            )
        ensure_candidate_not_published(session, config, relation.component_candidate_id)
        assembly = session.scalar(
            select(ComponentAssemblyRelation).where(
                ComponentAssemblyRelation.relation_candidate_id == relation_candidate_id
            )
        )
        if assembly is not None:
            raise ValueError("component_repo.confirmed_relation_cannot_be_rejected")
        relation.status = config["relations"]["candidate_status"]["rejected"]
        session.commit()
        session.refresh(relation)
        return relation_candidate_response(relation)


def list_free_connectors(
    engine: Engine,
    component_candidate_id: str,
) -> list[dict[str, Any]]:
    """Return world connectors not occupied by confirmed assembly relations."""
    Session = sessionmaker(bind=engine)
    with Session() as session:
        candidate = session.get(ComponentCandidate, component_candidate_id)
        if candidate is None:
            raise ValueError(f"Component candidate not found: {component_candidate_id}")
        snapshot = session.get(ComponentSceneSnapshot, candidate.scene_snapshot_id)
        if snapshot is None:
            raise ValueError(f"Component scene snapshot not found: {candidate.scene_snapshot_id}")
        part_library_version_id = part_library_version_id_for_candidate(session, component_candidate_id)
        connectors = world_connectors_for_parts(
            session,
            expanded_world_parts(snapshot.document_json),
            part_library_version_id,
        )
        occupied = set()
        relations = session.scalars(
            select(ComponentAssemblyRelation).where(
                ComponentAssemblyRelation.component_candidate_id == component_candidate_id
            )
        ).all()
        for relation in relations:
            occupied.add(relation.endpoint_a_json["worldConnectorId"])
            occupied.add(relation.endpoint_b_json["worldConnectorId"])
        return [
            connector
            for connector in connectors
            if connector["worldConnectorId"] not in occupied
        ]


def expanded_world_parts(document: dict[str, Any]) -> list[dict[str, Any]]:
    models = {model["modelId"]: model for model in document["models"]}
    root_model_id = document["rootModelId"]
    if root_model_id is None or root_model_id not in models:
        return []
    return expand_model(models, root_model_id, identity_transform(), [])


def expand_model(
    models: dict[str, dict[str, Any]],
    model_id: str,
    parent_transform: dict[str, Any],
    path: list[str],
) -> list[dict[str, Any]]:
    model = models[model_id]
    parts = []
    for reference in model["references"]:
        world_transform = compose_transform(parent_transform, reference["transform"])
        if reference["referenceKind"] == "submodel" and reference["targetModelId"] in models:
            parts.extend(
                expand_model(
                    models,
                    reference["targetModelId"],
                    world_transform,
                    [*path, reference["instanceId"]],
                )
            )
        elif reference["referenceKind"] == "part":
            parts.append(
                {
                    **reference,
                    "worldTransform": world_transform,
                    "instancePath": [*path, reference["instanceId"]],
                }
            )
    return parts


def world_connectors_for_parts(session, world_parts: list[dict[str, Any]], part_library_version_id: str) -> list[dict[str, Any]]:
    part_names = sorted({part["referenceName"].lower() for part in world_parts})
    connector_rows = session.scalars(
        select(PartConnectorDefinition).where(
            PartConnectorDefinition.part_library_version_id == part_library_version_id,
            PartConnectorDefinition.ldraw_part_num.in_(part_names),
        )
    ).all()
    connectors_by_part: dict[str, list[PartConnectorDefinition]] = {}
    for connector in connector_rows:
        connectors_by_part.setdefault(connector.ldraw_part_num.lower(), []).append(connector)
    world_connectors = []
    for part in world_parts:
        for connector in connectors_by_part.get(part["referenceName"].lower(), []):
            world_connectors.append(world_connector(part, connector))
    return world_connectors


def world_connector(part: dict[str, Any], connector: PartConnectorDefinition) -> dict[str, Any]:
    local_position = (connector.pos_x, connector.pos_y, connector.pos_z)
    local_matrix = (
        connector.ori_11,
        connector.ori_12,
        connector.ori_13,
        connector.ori_21,
        connector.ori_22,
        connector.ori_23,
        connector.ori_31,
        connector.ori_32,
        connector.ori_33,
    )
    transform = part["worldTransform"]
    position = transform_point(transform, local_position)
    matrix = matrix_mul(tuple(transform["matrix"]), local_matrix)
    local_axis = (
        connector.direction_x if connector.direction_x is not None else local_matrix[1],
        connector.direction_y if connector.direction_y is not None else local_matrix[4],
        connector.direction_z if connector.direction_z is not None else local_matrix[7],
    )
    axis = normalize_vector(matrix_vector_mul(tuple(transform["matrix"]), local_axis))
    return {
        "worldConnectorId": f"{part['instanceId']}:{connector.id}",
        "partInstanceId": part["instanceId"],
        "instancePath": part["instancePath"],
        "partRef": part["referenceName"].lower(),
        "connectorId": str(connector.id),
        "sourceConnectorId": str(connector.source_connector_id),
        "partLibraryVersionId": connector.part_library_version_id,
        "connectorType": connector.normalized_connector_type,
        "connectorGender": connector.connector_gender,
        "connectorKind": connector.connector_kind,
        "connectorGroup": connector.connector_group,
        "position": vector_to_dict(position),
        "axis": vector_to_dict(axis),
        "matrix": list(matrix),
        "directionLabel": connector.direction_label,
        "directionGroup": connector.direction_group,
        "metadata": {
            "radius": connector.radius,
            "length": connector.length,
            "confidence": float(connector.confidence or 1.0),
        },
    }


def compatibility_rule(
    config: dict[str, Any],
    connector_a: dict[str, Any],
    connector_b: dict[str, Any],
) -> dict[str, Any] | None:
    for rule in config["relations"]["compatibility"]:
        if rule_matches(rule, connector_a, connector_b):
            return rule
        if rule_matches(rule, connector_b, connector_a):
            return {
                **rule,
                "connector_type_a": rule["connector_type_b"],
                "connector_type_b": rule["connector_type_a"],
                "gender_a": rule["gender_b"],
                "gender_b": rule["gender_a"],
            }
    return None


def rule_matches(rule: dict[str, Any], connector_a: dict[str, Any], connector_b: dict[str, Any]) -> bool:
    return (
        connector_a["connectorType"] == rule["connector_type_a"]
        and connector_b["connectorType"] == rule["connector_type_b"]
        and connector_a["connectorGender"] == rule["gender_a"]
        and connector_b["connectorGender"] == rule["gender_b"]
    )


def connector_pair_metrics(connector_a: dict[str, Any], connector_b: dict[str, Any]) -> dict[str, float]:
    position_a = dict_to_vector(connector_a["position"])
    position_b = dict_to_vector(connector_b["position"])
    axis_a = dict_to_vector(connector_a["axis"])
    axis_b = dict_to_vector(connector_b["axis"])
    return {
        "positionResidual": distance(position_a, position_b),
        "rotationResidual": axis_angle_degrees(axis_a, axis_b),
    }


def confidence_from_metrics(metrics: dict[str, float], rule: dict[str, Any]) -> float:
    position_score = 1.0 - min(1.0, metrics["positionResidual"] / float(rule["candidate_lateral_ldu"]))
    angle_score = 1.0 - min(1.0, metrics["rotationResidual"] / float(rule["candidate_axis_angle_deg"]))
    return round(max(0.0, (position_score + angle_score) / 2.0), 4)


def connector_endpoint(connector: dict[str, Any]) -> dict[str, Any]:
    return connector


def connector_source_hash(session) -> str:
    rows = session.execute(
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
    ).all()
    payload = json.dumps([tuple(row) for row in rows], sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def active_part_library_version_id(session) -> str:
    version = session.scalar(
        select(PartLibraryVersion)
        .where(PartLibraryVersion.status == "active")
        .order_by(PartLibraryVersion.created_at.desc())
    )
    if version is None:
        raise ValueError("No active part library version exists")
    return version.id


def part_library_version_id_for_candidate(session, component_candidate_id: str) -> str:
    relation = session.scalar(
        select(ComponentRelationCandidate)
        .where(ComponentRelationCandidate.component_candidate_id == component_candidate_id)
        .order_by(ComponentRelationCandidate.created_at.desc())
    )
    if relation is not None:
        return relation.part_library_version_id
    return active_part_library_version_id(session)


def ensure_candidate_not_published(
    session,
    config: dict[str, Any],
    component_candidate_id: str,
) -> None:
    candidate = session.get(ComponentCandidate, component_candidate_id)
    if candidate is not None and candidate.status == config["candidates"]["status"]["published"]:
        raise ValueError(f"Published component candidate is immutable: {component_candidate_id}")
    published = session.scalar(
        select(ComponentVersion).where(
            ComponentVersion.component_candidate_id == component_candidate_id,
            ComponentVersion.status == config["versions"]["status"]["published"],
        )
    )
    if published is not None:
        raise ValueError(f"Published component candidate is immutable: {component_candidate_id}")


def part_connector_definition_from_instance(
    definition_id: int,
    part_library_version_id: str,
    connector: ConnectorInstance,
    created_at: datetime,
) -> PartConnectorDefinition:
    return PartConnectorDefinition(
        id=definition_id,
        part_library_version_id=part_library_version_id,
        source_connector_id=connector.id,
        ldraw_part_num=connector.ldraw_part_num.lower(),
        connector_kind=connector.connector_kind,
        normalized_connector_type=connector.normalized_connector_type,
        connector_group=connector.connector_group,
        connector_gender=connector.connector_gender,
        pos_x=connector.pos_x,
        pos_y=connector.pos_y,
        pos_z=connector.pos_z,
        ori_11=connector.ori_11,
        ori_12=connector.ori_12,
        ori_13=connector.ori_13,
        ori_21=connector.ori_21,
        ori_22=connector.ori_22,
        ori_23=connector.ori_23,
        ori_31=connector.ori_31,
        ori_32=connector.ori_32,
        ori_33=connector.ori_33,
        direction_x=connector.direction_x,
        direction_y=connector.direction_y,
        direction_z=connector.direction_z,
        direction_label=connector.direction_label,
        direction_group=connector.direction_group,
        radius=connector.radius,
        length=connector.length,
        caps=connector.caps,
        center_flag=connector.center_flag,
        slide_flag=connector.slide_flag,
        confidence=connector.confidence,
        raw_params=connector.raw_params,
        created_at=created_at,
    )


def identity_transform() -> dict[str, Any]:
    return {
        "position": {"x": 0.0, "y": 0.0, "z": 0.0},
        "matrix": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
    }


def compose_transform(parent: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    parent_matrix = tuple(parent["matrix"])
    child_matrix = tuple(child["matrix"])
    child_position = dict_to_vector(child["position"])
    parent_position = dict_to_vector(parent["position"])
    rotated_position = matrix_vector_mul(parent_matrix, child_position)
    return {
        "position": vector_to_dict(vector_add(parent_position, rotated_position)),
        "matrix": list(matrix_mul(parent_matrix, child_matrix)),
    }


def transform_point(transform: dict[str, Any], point: tuple[float, float, float]) -> tuple[float, float, float]:
    return vector_add(dict_to_vector(transform["position"]), matrix_vector_mul(tuple(transform["matrix"]), point))


def matrix_vector_mul(matrix: tuple[float, ...], vector: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        matrix[0] * vector[0] + matrix[1] * vector[1] + matrix[2] * vector[2],
        matrix[3] * vector[0] + matrix[4] * vector[1] + matrix[5] * vector[2],
        matrix[6] * vector[0] + matrix[7] * vector[1] + matrix[8] * vector[2],
    )


def matrix_mul(left: tuple[float, ...], right: tuple[float, ...]) -> tuple[float, ...]:
    return (
        left[0] * right[0] + left[1] * right[3] + left[2] * right[6],
        left[0] * right[1] + left[1] * right[4] + left[2] * right[7],
        left[0] * right[2] + left[1] * right[5] + left[2] * right[8],
        left[3] * right[0] + left[4] * right[3] + left[5] * right[6],
        left[3] * right[1] + left[4] * right[4] + left[5] * right[7],
        left[3] * right[2] + left[4] * right[5] + left[5] * right[8],
        left[6] * right[0] + left[7] * right[3] + left[8] * right[6],
        left[6] * right[1] + left[7] * right[4] + left[8] * right[7],
        left[6] * right[2] + left[7] * right[5] + left[8] * right[8],
    )


def vector_add(left: tuple[float, float, float], right: tuple[float, float, float]) -> tuple[float, float, float]:
    return (left[0] + right[0], left[1] + right[1], left[2] + right[2])


def dict_to_vector(value: dict[str, float]) -> tuple[float, float, float]:
    return (float(value["x"]), float(value["y"]), float(value["z"]))


def vector_to_dict(value: tuple[float, float, float]) -> dict[str, float]:
    return {"x": value[0], "y": value[1], "z": value[2]}


def distance(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return math.sqrt(sum((left[index] - right[index]) ** 2 for index in range(3)))


def normalize_vector(value: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(sum(component * component for component in value))
    if length == 0:
        return (0.0, 1.0, 0.0)
    return (value[0] / length, value[1] / length, value[2] / length)


def axis_angle_degrees(axis_a: tuple[float, float, float], axis_b: tuple[float, float, float]) -> float:
    a = normalize_vector(axis_a)
    b = normalize_vector(axis_b)
    dot = max(-1.0, min(1.0, sum(a[index] * b[index] for index in range(3))))
    angle = math.degrees(math.acos(dot))
    return min(angle, 180.0 - angle)


def part_library_version_response(version: PartLibraryVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "sourceTable": version.source_table,
        "sourceHash": version.source_hash,
        "connectorCount": version.connector_count,
        "status": version.status,
        "metadata": version.metadata_json,
        "createdBy": version.created_by,
        "createdAt": version.created_at.isoformat(),
    }


def relation_candidate_response(relation: ComponentRelationCandidate) -> dict[str, Any]:
    return {
        "id": relation.id,
        "componentCandidateId": relation.component_candidate_id,
        "partLibraryVersionId": relation.part_library_version_id,
        "endpointA": relation.endpoint_a_json,
        "endpointB": relation.endpoint_b_json,
        "connectionType": relation.connection_type,
        "jointType": relation.joint_type,
        "positionResidual": relation.position_residual,
        "rotationResidual": relation.rotation_residual,
        "verifiedByTolerance": relation.verified_by_tolerance,
        "confidence": relation.confidence,
        "status": relation.status,
        "detectionMethod": relation.detection_method,
        "metadata": relation.metadata_json,
        "createdAt": relation.created_at.isoformat(),
        "updatedAt": relation.updated_at.isoformat() if relation.updated_at else None,
    }


def assembly_relation_response(relation: ComponentAssemblyRelation) -> dict[str, Any]:
    return {
        "id": relation.id,
        "componentCandidateId": relation.component_candidate_id,
        "relationCandidateId": relation.relation_candidate_id,
        "endpointA": relation.endpoint_a_json,
        "endpointB": relation.endpoint_b_json,
        "connectionType": relation.connection_type,
        "jointType": relation.joint_type,
        "placement": relation.placement_json,
        "confirmedBy": relation.confirmed_by,
        "confirmedAt": relation.confirmed_at.isoformat(),
    }
