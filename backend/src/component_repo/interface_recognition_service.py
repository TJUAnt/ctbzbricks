"""Deterministic external-interface recognition for Component candidates."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import delete, insert, literal, select, union_all

from src.component_repo.geometry_service import component_preview_parts
from src.component_repo.relation_service import (
    dict_to_vector,
    expanded_world_parts,
    normalize_vector,
    part_library_version_id_for_candidate,
    transform_point,
    vector_to_dict,
    world_connectors_for_parts,
)
from src.model.models import (
    ComponentAssemblyRelation,
    ComponentCandidate,
    ComponentConnectorAnalysis,
    ComponentConnectorAnalysisBlocker,
    ComponentConnectorAnalysisItem,
    ComponentConnectorAnalysisPathNode,
    ComponentConnectorAnalysisRelation,
    ComponentSceneSnapshot,
    PartConnectorDefinition,
)


def analyze_component_connectors(
    session: object,
    config: dict[str, Any],
    component_candidate_id: str,
) -> dict[str, Any]:
    """Classify every physical connector and derive read-only external interfaces.

    Scheme B deliberately requires four independent conditions: the connector is not
    consumed by an internal relation, its normalized type is supported, an outward
    access direction can be selected, and the mating corridor is not obstructed by
    another Part instance.
    """
    candidate = session.get(ComponentCandidate, component_candidate_id)
    if candidate is None:
        raise ValueError(f"Component candidate not found: {component_candidate_id}")
    snapshot = session.get(ComponentSceneSnapshot, candidate.scene_snapshot_id)
    if snapshot is None:
        raise ValueError(f"Component scene snapshot not found: {candidate.scene_snapshot_id}")

    recognition = config["interface_recognition"]
    recognition_version = recognition["version"]
    part_library_version_id = part_library_version_id_for_candidate(
        session,
        component_candidate_id,
    )
    world_parts = expanded_world_parts(snapshot.document_json)
    connectors = world_connectors_for_parts(
        session,
        world_parts,
        part_library_version_id,
    )
    if not connectors:
        return {
            "componentCandidateId": component_candidate_id,
            "partLibraryVersionId": part_library_version_id,
            "recognitionMethod": "automatic",
            "recognitionVersion": recognition_version,
            "connectors": [],
            "externalInterfaces": [],
        }
    preview_parts = component_preview_parts(session, snapshot.document_json)
    part_boxes = world_part_aabbs(preview_parts or [])
    component_center = aabb_center(union_aabb(list(part_boxes.values())))
    occupied = occupied_connector_relations(session, component_candidate_id)
    supported_types = supported_connector_types(config)

    classified = []
    external_interfaces = []
    for connector in connectors:
        connector_id = connector["worldConnectorId"]
        connector_type = connector.get("connectorType")
        own_part_id = connector["partInstanceId"]
        source_axis = normalize_vector(dict_to_vector(connector["axis"]))
        access_axis, outward_score = outward_access_axis(
            dict_to_vector(connector["position"]),
            source_axis,
            component_center,
        )
        blockers = clearance_blockers(
            connector,
            access_axis,
            part_boxes,
            own_part_id,
            recognition,
        )
        has_geometry = own_part_id in part_boxes
        eligibility = {
            "unoccupied": connector_id not in occupied,
            "supportedType": bool(connector_type and connector_type in supported_types),
            "outwardFacing": outward_score >= float(recognition["minimum_outward_score"]),
            "clearanceDataAvailable": has_geometry,
            "clearanceAvailable": has_geometry and not blockers,
        }
        eligible = all(eligibility.values())
        if connector_id in occupied:
            state = "internal"
        elif not eligibility["supportedType"]:
            state = "unsupported"
        elif not eligibility["clearanceDataAvailable"]:
            state = "unresolved"
        elif blockers or not eligibility["outwardFacing"]:
            state = "blocked"
        else:
            state = "external"

        interface_id = (
            automatic_interface_id(component_candidate_id, connector_id, recognition_version)
            if eligible
            else None
        )
        classified_connector = {
            **connector,
            "state": state,
            "occupiedByRelationIds": occupied.get(connector_id, []),
            "accessAxis": vector_to_dict(access_axis),
            "externalInterfaceId": interface_id,
            "recognition": {
                "method": "automatic",
                "version": recognition_version,
                "eligibility": eligibility,
                "outwardScore": round(outward_score, 6),
                "blockedByPartInstanceIds": blockers,
            },
        }
        classified.append(classified_connector)
        if eligible and interface_id is not None:
            external_interfaces.append(
                automatic_interface_response(
                    candidate,
                    classified_connector,
                    interface_id,
                    recognition_version,
                )
            )

    return {
        "componentCandidateId": component_candidate_id,
        "partLibraryVersionId": part_library_version_id,
        "recognitionMethod": "automatic",
        "recognitionVersion": recognition_version,
        "connectors": classified,
        "externalInterfaces": external_interfaces,
    }


def persist_component_connector_analysis(
    session: object,
    config: dict[str, Any],
    component_candidate_id: str,
    analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Replace one candidate's normalized connector analysis in the current transaction."""
    result = analysis or analyze_component_connectors(
        session,
        config,
        component_candidate_id,
    )
    existing_item_ids = list(
        session.scalars(
            select(ComponentConnectorAnalysisItem.id).where(
                ComponentConnectorAnalysisItem.component_candidate_id
                == component_candidate_id
            )
        ).all()
    )
    if existing_item_ids:
        session.execute(
            delete(ComponentConnectorAnalysisPathNode).where(
                ComponentConnectorAnalysisPathNode.analysis_item_id.in_(
                    existing_item_ids
                )
            )
        )
        session.execute(
            delete(ComponentConnectorAnalysisBlocker).where(
                ComponentConnectorAnalysisBlocker.analysis_item_id.in_(
                    existing_item_ids
                )
            )
        )
        session.execute(
            delete(ComponentConnectorAnalysisRelation).where(
                ComponentConnectorAnalysisRelation.analysis_item_id.in_(
                    existing_item_ids
                )
            )
        )
        session.execute(
            delete(ComponentConnectorAnalysisItem).where(
                ComponentConnectorAnalysisItem.id.in_(existing_item_ids)
            )
        )
    session.execute(
        delete(ComponentConnectorAnalysis).where(
            ComponentConnectorAnalysis.component_candidate_id
            == component_candidate_id
        )
    )
    session.execute(
        insert(ComponentConnectorAnalysis),
        [
            {
                "component_candidate_id": component_candidate_id,
                "part_library_version_id": result["partLibraryVersionId"],
                "recognition_method": result["recognitionMethod"],
                "recognition_version": result["recognitionVersion"],
                "calculated_at": datetime.now(timezone.utc),
            }
        ],
    )

    item_rows = []
    path_rows = []
    blocker_rows = []
    relation_rows = []
    for connector in (
        connector
        for connector in result["connectors"]
        if connector["state"] == "external"
    ):
        item_id = connector_analysis_item_id(
            component_candidate_id,
            connector["worldConnectorId"],
        )
        matrix = connector["matrix"]
        eligibility = connector["recognition"]["eligibility"]
        item_rows.append(
            {
                "id": item_id,
                "component_candidate_id": component_candidate_id,
                "part_connector_definition_id": int(connector["connectorId"]),
                "world_connector_id": connector["worldConnectorId"],
                "part_instance_id": connector["partInstanceId"],
                "part_ref": connector["partRef"],
                "connector_type": connector["connectorType"],
                "connector_kind": connector["connectorKind"],
                "connector_gender": connector["connectorGender"],
                "direction_label": connector["directionLabel"],
                "direction_group": connector["directionGroup"],
                "state": connector["state"],
                "position_x": connector["position"]["x"],
                "position_y": connector["position"]["y"],
                "position_z": connector["position"]["z"],
                "axis_x": connector["axis"]["x"],
                "axis_y": connector["axis"]["y"],
                "axis_z": connector["axis"]["z"],
                "matrix_11": matrix[0],
                "matrix_12": matrix[1],
                "matrix_13": matrix[2],
                "matrix_21": matrix[3],
                "matrix_22": matrix[4],
                "matrix_23": matrix[5],
                "matrix_31": matrix[6],
                "matrix_32": matrix[7],
                "matrix_33": matrix[8],
                "access_axis_x": connector["accessAxis"]["x"],
                "access_axis_y": connector["accessAxis"]["y"],
                "access_axis_z": connector["accessAxis"]["z"],
                "external_interface_id": connector["externalInterfaceId"],
                "eligibility_unoccupied": eligibility["unoccupied"],
                "eligibility_supported_type": eligibility["supportedType"],
                "eligibility_outward_facing": eligibility["outwardFacing"],
                "eligibility_clearance_data_available": eligibility[
                    "clearanceDataAvailable"
                ],
                "eligibility_clearance_available": eligibility[
                    "clearanceAvailable"
                ],
                "outward_score": connector["recognition"]["outwardScore"],
            }
        )
        path_rows.extend(
            {
                "analysis_item_id": item_id,
                "ordinal": ordinal,
                "instance_id": instance_id,
            }
            for ordinal, instance_id in enumerate(connector["instancePath"])
        )
        blocker_rows.extend(
            {
                "analysis_item_id": item_id,
                "blocker_part_instance_id": blocker_id,
            }
            for blocker_id in connector["recognition"][
                "blockedByPartInstanceIds"
            ]
        )
        relation_rows.extend(
            {
                "analysis_item_id": item_id,
                "assembly_relation_id": relation_id,
            }
            for relation_id in connector["occupiedByRelationIds"]
        )
    if item_rows:
        session.execute(insert(ComponentConnectorAnalysisItem), item_rows)
    if path_rows:
        session.execute(insert(ComponentConnectorAnalysisPathNode), path_rows)
    if blocker_rows:
        session.execute(insert(ComponentConnectorAnalysisBlocker), blocker_rows)
    if relation_rows:
        session.execute(insert(ComponentConnectorAnalysisRelation), relation_rows)
    session.flush()
    return result


def read_component_connector_analysis(
    session: object,
    config: dict[str, Any],
    component_candidate_id: str,
) -> dict[str, Any]:
    """Read connector analysis exclusively from normalized database rows."""
    header_row = session.execute(
        select(ComponentConnectorAnalysis, ComponentCandidate)
        .join(
            ComponentCandidate,
            ComponentCandidate.id
            == ComponentConnectorAnalysis.component_candidate_id,
        )
        .where(
            ComponentConnectorAnalysis.component_candidate_id
            == component_candidate_id
        )
    ).one_or_none()
    if header_row is None:
        raise ValueError(
            f"Component connector analysis not found: {component_candidate_id}"
        )
    header, candidate = header_row
    item_rows = session.execute(
        select(
            ComponentConnectorAnalysisItem,
            PartConnectorDefinition.id.label("definition_id"),
            PartConnectorDefinition.source_connector_id.label(
                "definition_source_connector_id"
            ),
            PartConnectorDefinition.normalized_connector_type.label(
                "definition_connector_type"
            ),
            PartConnectorDefinition.connector_gender.label(
                "definition_connector_gender"
            ),
            PartConnectorDefinition.connector_kind.label(
                "definition_connector_kind"
            ),
            PartConnectorDefinition.connector_group.label(
                "definition_connector_group"
            ),
            PartConnectorDefinition.direction_label.label(
                "definition_direction_label"
            ),
            PartConnectorDefinition.direction_group.label(
                "definition_direction_group"
            ),
            PartConnectorDefinition.radius.label("definition_radius"),
            PartConnectorDefinition.length.label("definition_length"),
            PartConnectorDefinition.confidence.label("definition_confidence"),
        )
        .join(
            PartConnectorDefinition,
            PartConnectorDefinition.id
            == ComponentConnectorAnalysisItem.part_connector_definition_id,
        )
        .where(
            ComponentConnectorAnalysisItem.component_candidate_id
            == component_candidate_id
        )
        .order_by(ComponentConnectorAnalysisItem.world_connector_id)
    ).all()
    paths: dict[str, list[tuple[int, str]]] = {}
    blockers: dict[str, list[str]] = {}
    relations: dict[str, list[str]] = {}
    if item_rows:
        association_rows = session.execute(
            union_all(
                select(
                    ComponentConnectorAnalysisPathNode.analysis_item_id.label(
                        "analysis_item_id"
                    ),
                    literal("path").label("association_kind"),
                    ComponentConnectorAnalysisPathNode.ordinal.label("ordinal"),
                    ComponentConnectorAnalysisPathNode.instance_id.label("value"),
                )
                .join(
                    ComponentConnectorAnalysisItem,
                    ComponentConnectorAnalysisItem.id
                    == ComponentConnectorAnalysisPathNode.analysis_item_id,
                )
                .where(
                    ComponentConnectorAnalysisItem.component_candidate_id
                    == component_candidate_id
                ),
                select(
                    ComponentConnectorAnalysisBlocker.analysis_item_id,
                    literal("blocker"),
                    literal(0),
                    ComponentConnectorAnalysisBlocker.blocker_part_instance_id,
                )
                .join(
                    ComponentConnectorAnalysisItem,
                    ComponentConnectorAnalysisItem.id
                    == ComponentConnectorAnalysisBlocker.analysis_item_id,
                )
                .where(
                    ComponentConnectorAnalysisItem.component_candidate_id
                    == component_candidate_id
                ),
                select(
                    ComponentConnectorAnalysisRelation.analysis_item_id,
                    literal("relation"),
                    literal(0),
                    ComponentConnectorAnalysisRelation.assembly_relation_id,
                )
                .join(
                    ComponentConnectorAnalysisItem,
                    ComponentConnectorAnalysisItem.id
                    == ComponentConnectorAnalysisRelation.analysis_item_id,
                )
                .where(
                    ComponentConnectorAnalysisItem.component_candidate_id
                    == component_candidate_id
                ),
            )
        ).all()
        for item_id, association_kind, ordinal, value in association_rows:
            if association_kind == "path":
                paths.setdefault(item_id, []).append((ordinal, value))
            elif association_kind == "blocker":
                blockers.setdefault(item_id, []).append(value)
            else:
                relations.setdefault(item_id, []).append(value)

    connectors = []
    for row in item_rows:
        item = row[0]
        connectors.append(
            connector_analysis_item_response(
                item,
                row._mapping,
                header,
                paths.get(item.id, []),
                blockers.get(item.id, []),
                relations.get(item.id, []),
            )
        )
    external_interfaces = [
        automatic_interface_response(
            candidate,
            connector,
            connector["externalInterfaceId"],
            header.recognition_version,
        )
        for connector in connectors
        if connector["externalInterfaceId"] is not None
    ]
    return {
        "componentCandidateId": component_candidate_id,
        "partLibraryVersionId": header.part_library_version_id,
        "recognitionMethod": header.recognition_method,
        "recognitionVersion": header.recognition_version,
        "connectors": connectors,
        "externalInterfaces": external_interfaces,
    }


def read_component_connector_summary(
    session: object,
    component_candidate_id: str,
) -> dict[str, Any]:
    """Read only fields required by the interactive Component UI."""
    header_row = session.execute(
        select(
            ComponentConnectorAnalysis.part_library_version_id,
            ComponentConnectorAnalysis.recognition_method,
            ComponentConnectorAnalysis.recognition_version,
            ComponentCandidate.created_at,
        )
        .join(
            ComponentCandidate,
            ComponentCandidate.id
            == ComponentConnectorAnalysis.component_candidate_id,
        )
        .where(
            ComponentConnectorAnalysis.component_candidate_id
            == component_candidate_id
        )
    ).one_or_none()
    if header_row is None:
        raise ValueError(
            f"Component connector analysis not found: {component_candidate_id}"
        )
    (
        part_library_version_id,
        recognition_method,
        recognition_version,
        candidate_created_at,
    ) = header_row
    rows = session.execute(
        select(
            ComponentConnectorAnalysisItem.world_connector_id,
            ComponentConnectorAnalysisItem.part_instance_id,
            ComponentConnectorAnalysisItem.part_ref,
            ComponentConnectorAnalysisItem.part_connector_definition_id,
            ComponentConnectorAnalysisItem.connector_type,
            ComponentConnectorAnalysisItem.connector_kind,
            ComponentConnectorAnalysisItem.connector_gender,
            ComponentConnectorAnalysisItem.direction_label,
            ComponentConnectorAnalysisItem.direction_group,
            ComponentConnectorAnalysisItem.state,
            ComponentConnectorAnalysisItem.position_x,
            ComponentConnectorAnalysisItem.position_y,
            ComponentConnectorAnalysisItem.position_z,
            ComponentConnectorAnalysisItem.access_axis_x,
            ComponentConnectorAnalysisItem.access_axis_y,
            ComponentConnectorAnalysisItem.access_axis_z,
            ComponentConnectorAnalysisItem.external_interface_id,
        )
        .where(
            ComponentConnectorAnalysisItem.component_candidate_id
            == component_candidate_id
        )
        .order_by(ComponentConnectorAnalysisItem.world_connector_id)
    ).all()
    connectors = [
        {
            "worldConnectorId": row.world_connector_id,
            "partInstanceId": row.part_instance_id,
            "partRef": row.part_ref,
            "connectorId": str(row.part_connector_definition_id),
            "connectorType": row.connector_type,
            "connectorKind": row.connector_kind or "unknown",
            "state": row.state,
            "position": {
                "x": row.position_x,
                "y": row.position_y,
                "z": row.position_z,
            },
            "accessAxis": {
                "x": row.access_axis_x,
                "y": row.access_axis_y,
                "z": row.access_axis_z,
            },
            "externalInterfaceId": row.external_interface_id,
        }
        for row in rows
    ]
    external_interfaces = [
        automatic_interface_summary_response(
            component_candidate_id,
            candidate_created_at,
            recognition_method,
            recognition_version,
            row,
        )
        for row in rows
        if row.external_interface_id is not None
    ]
    return {
        "componentCandidateId": component_candidate_id,
        "partLibraryVersionId": part_library_version_id,
        "recognitionMethod": recognition_method,
        "recognitionVersion": recognition_version,
        "connectors": connectors,
        "externalInterfaces": external_interfaces,
    }


def automatic_interface_summary_response(
    component_candidate_id: str,
    candidate_created_at: datetime,
    recognition_method: str,
    recognition_version: str,
    row: Any,
) -> dict[str, Any]:
    connector_type = row.connector_type or row.connector_kind or "unknown"
    group_key = ":".join(
        [
            str(connector_type),
            str(row.connector_gender or "neutral"),
            str(row.direction_group or row.direction_label or "any"),
        ]
    )
    interface_group_id = str(
        uuid5(
            NAMESPACE_URL,
            f"brickbuilder:{component_candidate_id}:group:{group_key}:{recognition_version}",
        )
    )
    source_connector = {
        "worldConnectorId": row.world_connector_id,
        "partInstanceId": row.part_instance_id,
        "partRef": row.part_ref,
        "connectorId": str(row.part_connector_definition_id),
        "connectorType": row.connector_type,
        "connectorGender": row.connector_gender,
        "connectorKind": row.connector_kind or "unknown",
        "directionLabel": row.direction_label,
        "directionGroup": row.direction_group,
        "position": {
            "x": row.position_x,
            "y": row.position_y,
            "z": row.position_z,
        },
        "accessAxis": {
            "x": row.access_axis_x,
            "y": row.access_axis_y,
            "z": row.access_axis_z,
        },
    }
    return {
        "id": row.external_interface_id,
        "componentCandidateId": component_candidate_id,
        "worldConnectorId": row.world_connector_id,
        "name": row.world_connector_id,
        "exposure": "external",
        "defaultBehavior": "free",
        "sourceConnector": source_connector,
        "mechanicalRoles": [str(connector_type)],
        "businessRoles": ["external_connection"],
        "requirements": {
            "method": recognition_method,
            "version": recognition_version,
        },
        "reviewStatus": "confirmed",
        "createdBy": "system",
        "createdAt": candidate_created_at.isoformat(),
        "updatedAt": None,
        "recognitionMethod": recognition_method,
        "recognitionVersion": recognition_version,
        "interfaceGroupId": interface_group_id,
    }


def ensure_component_connector_analysis(
    session: object,
    config: dict[str, Any],
    component_candidate_id: str,
) -> dict[str, Any]:
    """Read a persisted analysis, calculating it only for legacy/background paths."""
    try:
        return read_component_connector_analysis(
            session,
            config,
            component_candidate_id,
        )
    except ValueError as error:
        if not str(error).startswith("Component connector analysis not found:"):
            raise
    return persist_component_connector_analysis(
        session,
        config,
        component_candidate_id,
    )


def mark_connectors_occupied_by_relation(
    session: object,
    component_candidate_id: str,
    world_connector_ids: list[str],
) -> None:
    """Remove newly occupied endpoints from the external-only analysis store."""
    item_ids = list(
        session.scalars(
            select(ComponentConnectorAnalysisItem.id).where(
                ComponentConnectorAnalysisItem.component_candidate_id
                == component_candidate_id,
                ComponentConnectorAnalysisItem.world_connector_id.in_(
                    world_connector_ids
                ),
            )
        ).all()
    )
    if not item_ids:
        return
    session.execute(
        delete(ComponentConnectorAnalysisPathNode).where(
            ComponentConnectorAnalysisPathNode.analysis_item_id.in_(item_ids)
        )
    )
    session.execute(
        delete(ComponentConnectorAnalysisBlocker).where(
            ComponentConnectorAnalysisBlocker.analysis_item_id.in_(item_ids)
        )
    )
    session.execute(
        delete(ComponentConnectorAnalysisRelation).where(
            ComponentConnectorAnalysisRelation.analysis_item_id.in_(item_ids)
        )
    )
    session.execute(
        delete(ComponentConnectorAnalysisItem).where(
            ComponentConnectorAnalysisItem.id.in_(item_ids)
        )
    )


def connector_analysis_item_id(
    component_candidate_id: str,
    world_connector_id: str,
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"brickbuilder:{component_candidate_id}:connector-analysis:{world_connector_id}",
        )
    )


def connector_analysis_item_response(
    item: ComponentConnectorAnalysisItem,
    definition: Mapping[str, Any],
    header: ComponentConnectorAnalysis,
    path_nodes: list[tuple[int, str]],
    blocker_ids: list[str],
    relation_ids: list[str],
) -> dict[str, Any]:
    eligibility = {
        "unoccupied": item.eligibility_unoccupied,
        "supportedType": item.eligibility_supported_type,
        "outwardFacing": item.eligibility_outward_facing,
        "clearanceDataAvailable": item.eligibility_clearance_data_available,
        "clearanceAvailable": item.eligibility_clearance_available,
    }
    return {
        "worldConnectorId": item.world_connector_id,
        "partInstanceId": item.part_instance_id,
        "instancePath": [
            value for _ordinal, value in sorted(path_nodes, key=lambda row: row[0])
        ],
        "partRef": item.part_ref,
        "connectorId": str(definition["definition_id"]),
        "sourceConnectorId": str(
            definition["definition_source_connector_id"]
        ),
        "partLibraryVersionId": header.part_library_version_id,
        "connectorType": definition["definition_connector_type"],
        "connectorGender": definition["definition_connector_gender"],
        "connectorKind": definition["definition_connector_kind"],
        "connectorGroup": definition["definition_connector_group"],
        "position": {
            "x": item.position_x,
            "y": item.position_y,
            "z": item.position_z,
        },
        "axis": {"x": item.axis_x, "y": item.axis_y, "z": item.axis_z},
        "matrix": [
            item.matrix_11,
            item.matrix_12,
            item.matrix_13,
            item.matrix_21,
            item.matrix_22,
            item.matrix_23,
            item.matrix_31,
            item.matrix_32,
            item.matrix_33,
        ],
        "directionLabel": definition["definition_direction_label"],
        "directionGroup": definition["definition_direction_group"],
        "metadata": {
            "radius": definition["definition_radius"],
            "length": definition["definition_length"],
            "confidence": float(
                definition["definition_confidence"] or 1.0
            ),
        },
        "state": item.state,
        "occupiedByRelationIds": sorted(relation_ids),
        "accessAxis": {
            "x": item.access_axis_x,
            "y": item.access_axis_y,
            "z": item.access_axis_z,
        },
        "externalInterfaceId": item.external_interface_id,
        "recognition": {
            "method": header.recognition_method,
            "version": header.recognition_version,
            "eligibility": eligibility,
            "outwardScore": item.outward_score,
            "blockedByPartInstanceIds": sorted(blocker_ids),
        },
    }


def supported_connector_types(config: dict[str, Any]) -> set[str]:
    configured = config["interface_recognition"].get("supported_connector_types") or []
    if configured:
        return {str(value) for value in configured}
    return {
        str(rule[key])
        for rule in config["relations"]["compatibility"]
        for key in ("connector_type_a", "connector_type_b")
    }


def occupied_connector_relations(
    session: object,
    component_candidate_id: str,
) -> dict[str, list[str]]:
    occupied: dict[str, list[str]] = {}
    relations = session.scalars(
        select(ComponentAssemblyRelation).where(
            ComponentAssemblyRelation.component_candidate_id == component_candidate_id
        )
    ).all()
    for relation in relations:
        for endpoint in (relation.endpoint_a_json, relation.endpoint_b_json):
            connector_id = endpoint.get("worldConnectorId")
            if connector_id:
                occupied.setdefault(connector_id, []).append(relation.id)
    return occupied


def world_part_aabbs(parts: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    result = {}
    for part in parts:
        bounds = part["bbox"]
        points = [
            transform_point(part["transform"], (x, y, z))
            for x in (bounds["minX"], bounds["maxX"])
            for y in (bounds["minY"], bounds["maxY"])
            for z in (bounds["minZ"], bounds["maxZ"])
        ]
        result[part["instanceId"]] = {
            "minX": min(point[0] for point in points),
            "minY": min(point[1] for point in points),
            "minZ": min(point[2] for point in points),
            "maxX": max(point[0] for point in points),
            "maxY": max(point[1] for point in points),
            "maxZ": max(point[2] for point in points),
        }
    return result


def union_aabb(boxes: list[dict[str, float]]) -> dict[str, float] | None:
    if not boxes:
        return None
    return {
        "minX": min(box["minX"] for box in boxes),
        "minY": min(box["minY"] for box in boxes),
        "minZ": min(box["minZ"] for box in boxes),
        "maxX": max(box["maxX"] for box in boxes),
        "maxY": max(box["maxY"] for box in boxes),
        "maxZ": max(box["maxZ"] for box in boxes),
    }


def aabb_center(box: dict[str, float] | None) -> tuple[float, float, float]:
    if box is None:
        return (0.0, 0.0, 0.0)
    return (
        (box["minX"] + box["maxX"]) / 2.0,
        (box["minY"] + box["maxY"]) / 2.0,
        (box["minZ"] + box["maxZ"]) / 2.0,
    )


def outward_access_axis(
    position: tuple[float, float, float],
    axis: tuple[float, float, float],
    center: tuple[float, float, float],
) -> tuple[tuple[float, float, float], float]:
    radial = normalize_vector(tuple(position[index] - center[index] for index in range(3)))
    forward_score = dot(axis, radial)
    reverse_axis = tuple(-value for value in axis)
    reverse_score = dot(reverse_axis, radial)
    if reverse_score > forward_score:
        return reverse_axis, reverse_score
    return axis, forward_score


def clearance_blockers(
    connector: dict[str, Any],
    access_axis: tuple[float, float, float],
    boxes: dict[str, dict[str, float]],
    own_part_id: str,
    recognition: dict[str, Any],
) -> list[str]:
    position = dict_to_vector(connector["position"])
    radius = max(
        float(recognition["minimum_clearance_radius_ldu"]),
        float((connector.get("metadata") or {}).get("radius") or 0.0),
    )
    connector_length = float((connector.get("metadata") or {}).get("length") or 0.0)
    start = max(
        float(recognition["clearance_start_ldu"]),
        connector_length * float(recognition["connector_length_start_ratio"]),
    )
    end = max(start, float(recognition["clearance_length_ldu"]))
    return sorted(
        part_id
        for part_id, box in boxes.items()
        if part_id != own_part_id
        and segment_intersects_expanded_aabb(position, access_axis, start, end, box, radius)
    )


def segment_intersects_expanded_aabb(
    origin: tuple[float, float, float],
    direction: tuple[float, float, float],
    start: float,
    end: float,
    box: dict[str, float],
    radius: float,
) -> bool:
    minimums = (
        box["minX"] - radius,
        box["minY"] - radius,
        box["minZ"] - radius,
    )
    maximums = (
        box["maxX"] + radius,
        box["maxY"] + radius,
        box["maxZ"] + radius,
    )
    minimum_t = start
    maximum_t = end
    for index in range(3):
        if abs(direction[index]) < 1e-9:
            if origin[index] < minimums[index] or origin[index] > maximums[index]:
                return False
            continue
        first = (minimums[index] - origin[index]) / direction[index]
        second = (maximums[index] - origin[index]) / direction[index]
        if first > second:
            first, second = second, first
        minimum_t = max(minimum_t, first)
        maximum_t = min(maximum_t, second)
        if minimum_t > maximum_t:
            return False
    return True


def automatic_interface_id(
    component_candidate_id: str,
    world_connector_id: str,
    recognition_version: str,
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"brickbuilder:{component_candidate_id}:{world_connector_id}:{recognition_version}",
        )
    )


def automatic_interface_response(
    candidate: ComponentCandidate,
    connector: dict[str, Any],
    interface_id: str,
    recognition_version: str,
) -> dict[str, Any]:
    return automatic_interface_response_for_candidate(
        candidate.id,
        candidate.created_at,
        connector,
        interface_id,
        recognition_version,
    )


def automatic_interface_response_for_candidate(
    component_candidate_id: str,
    candidate_created_at: datetime,
    connector: dict[str, Any],
    interface_id: str,
    recognition_version: str,
) -> dict[str, Any]:
    connector_type = connector.get("connectorType") or connector["connectorKind"]
    group_key = ":".join(
        [
            str(connector_type),
            str(connector.get("connectorGender") or "neutral"),
            str(connector.get("directionGroup") or connector.get("directionLabel") or "any"),
        ]
    )
    interface_group_id = str(
        uuid5(
            NAMESPACE_URL,
            f"brickbuilder:{component_candidate_id}:group:{group_key}:{recognition_version}",
        )
    )
    return {
        "id": interface_id,
        "componentCandidateId": component_candidate_id,
        "worldConnectorId": connector["worldConnectorId"],
        "name": connector["worldConnectorId"],
        "exposure": "external",
        "defaultBehavior": "free",
        "sourceConnector": connector,
        "mechanicalRoles": [str(connector_type)],
        "businessRoles": ["external_connection"],
        "requirements": connector["recognition"],
        "reviewStatus": "confirmed",
        "createdBy": "system",
        "createdAt": candidate_created_at.isoformat(),
        "updatedAt": None,
        "recognitionMethod": "automatic",
        "recognitionVersion": recognition_version,
        "interfaceGroupId": interface_group_id,
    }


def automatic_interface_signature(interfaces: list[dict[str, Any]]) -> str:
    import hashlib
    import json

    payload = [
        {
            "id": interface["id"],
            "worldConnectorId": interface["worldConnectorId"],
            "connectorType": interface["sourceConnector"].get("connectorType"),
            "connectorGender": interface["sourceConnector"].get("connectorGender"),
            "recognitionVersion": interface["recognitionVersion"],
        }
        for interface in interfaces
    ]
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def dot(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> float:
    return sum(left[index] * right[index] for index in range(3))
