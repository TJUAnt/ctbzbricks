"""Python algorithm Worker for Go-owned ``component.relations.detect`` tasks."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID, uuid4, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from src.component_repo.go_import_worker import (
    TASK_COLUMNS,
    ComponentImportWorker,
    LeaseLost,
    WorkerSettings,
    settings_from_environment,
)
from src.component_repo.relation_service import (
    compatibility_rule,
    confidence_from_metrics,
    connector_pair_metrics,
    expanded_world_parts,
    matrix_mul,
    matrix_vector_mul,
    normalize_vector,
    transform_point,
    vector_to_dict,
)
from src.config.app_settings import load_json_config
from src.config.component_repo_config import REQUIRED_COMPONENT_REPO_CONFIG_KEYS


TASK_TYPE = "component.relations.detect"
DERIVED_NAMESPACE = UUID("84224155-30f3-49ae-98e8-eb221059b53a")


class ComponentRelationWorker(ComponentImportWorker):
    def __init__(
        self,
        settings: WorkerSettings,
        component_config: dict[str, Any],
        connect: Callable[..., psycopg.Connection] = psycopg.connect,
    ) -> None:
        super().__init__(settings, None, component_config, connect, task_type=TASK_TYPE)  # type: ignore[arg-type]

    def run_once(self) -> bool:
        self._recover_expired()
        task = self._claim()
        if task is None:
            return False
        stopped = threading.Event()
        lease_lost = threading.Event()
        cancel_requested = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat_loop,
            args=(task["id"], task["attempts"], stopped, lease_lost, cancel_requested),
            daemon=True,
        )
        heartbeat.start()
        try:
            context = self._load_candidate(task)
            result = detect_relations(context, self.config)
            if lease_lost.is_set():
                raise LeaseLost()
            if cancel_requested.is_set():
                self._finish_cancelled(task)
                return True
            self._commit_relation_success(task, context, result)
        except LeaseLost:
            return True
        except (KeyError, TypeError, ValueError):
            self._finish_failure(
                task,
                "component_repo.relation_detect_failed",
                {"candidateId": str(task["payload"].get("candidateId", ""))},
                False,
            )
        except psycopg.Error:
            self._finish_failure(task, "common.internal_error", {}, True)
        finally:
            stopped.set()
            heartbeat.join(timeout=self.settings.heartbeat_interval)
        return True

    def _load_candidate(self, task: dict[str, Any]) -> dict[str, Any]:
        payload = task["payload"]
        if set(payload) != {"candidateId", "detectionVersion", "partLibraryVersionId", "inputHash"}:
            raise ValueError("invalid relation payload")
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT candidate.id, candidate.owner_id, candidate.scene_snapshot_id,
                       candidate.status, candidate.relation_detection_task_id,
                       candidate.relation_detection_version, snapshot.document,
                       snapshot.schema_version, snapshot.parser_version,
                       candidate.structure_hash, candidate.geometry_hash,
                       import_job.part_library_version_id, version.id AS version_id,
                       version.status AS version_status,
                       part_library.source_hash AS part_library_source_hash
                FROM component_repo.candidates candidate
                JOIN component_repo.scene_snapshots snapshot
                  ON snapshot.id = candidate.scene_snapshot_id
                JOIN component_repo.imports import_job
                  ON import_job.id = candidate.import_id
                 AND import_job.owner_id = candidate.owner_id
                JOIN component_repo.component_versions version
                  ON version.component_candidate_id = candidate.id
                 AND version.deleted_at IS NULL
                LEFT JOIN component_repo.part_library_versions part_library
                  ON part_library.id = import_job.part_library_version_id
                WHERE candidate.id = %s AND candidate.owner_id = %s
                """,
                (payload["candidateId"], task["owner_id"]),
            )
            candidate = cursor.fetchone()
            if candidate is None:
                raise ValueError("candidate not found")
            cursor.execute(
                """
                SELECT id, source_connector_id, ldraw_part_num, connector_kind,
                       normalized_connector_type, connector_group, connector_gender,
                       position, orientation, direction, direction_label, direction_group,
                       radius, length, confidence
                FROM component_repo.part_connector_definitions
                WHERE part_library_version_id = %s
                ORDER BY ldraw_part_num, id
                """,
                (payload["partLibraryVersionId"],),
            )
            definitions = cursor.fetchall()
        if (
            candidate["relation_detection_task_id"] != task["id"]
            or candidate["relation_detection_version"] != payload["detectionVersion"]
            or str(candidate["part_library_version_id"]) != payload["partLibraryVersionId"]
            or candidate["version_status"] != "draft"
            or payload["inputHash"] != logical_input_hash(
                candidate["structure_hash"], candidate["geometry_hash"],
                candidate["schema_version"], candidate["parser_version"],
                candidate["part_library_source_hash"] or "", payload["detectionVersion"],
            )
        ):
            raise ValueError("stale relation task")
        return {**candidate, "definitions": definitions}

    def _commit_relation_success(
        self,
        task: dict[str, Any],
        candidate: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        now = datetime.now(timezone.utc)
        with self._connection() as connection, connection.cursor() as cursor:
            current = self._lock_owned_lease(cursor, task, now)
            cursor.execute(
                "SELECT id FROM component_repo.candidates WHERE id = %s AND owner_id = %s FOR UPDATE",
                (candidate["id"], candidate["owner_id"]),
            )
            if cursor.fetchone() is None:
                raise LeaseLost()
            cursor.execute(
                "SELECT count(*) AS count FROM component_repo.relation_candidates WHERE component_candidate_id = %s",
                (candidate["id"],),
            )
            existing_count = int(cursor.fetchone()["count"])
            if existing_count == 0:
                cursor.execute(
                    """
                    INSERT INTO component_repo.connector_analyses (
                        component_candidate_id, owner_id, part_library_version_id,
                        recognition_method, recognition_version, calculated_at
                    ) VALUES (%s, %s, %s, 'automatic', %s, %s)
                    ON CONFLICT (component_candidate_id) DO NOTHING
                    """,
                    (candidate["id"], candidate["owner_id"], candidate["part_library_version_id"],
                     result["recognitionVersion"], now),
                )
                for connector in result["connectors"]:
                    cursor.execute(
                        """
                        INSERT INTO component_repo.connector_analysis_items (
                            id, component_candidate_id, owner_id, part_connector_definition_id,
                            world_connector_id, part_instance_id, part_ref, connector_type,
                            connector_kind, connector_gender, direction_label, direction_group,
                            state, position, axis, matrix, access_axis, external_interface_id,
                            eligibility_unoccupied, eligibility_supported_type,
                            eligibility_outward_facing, eligibility_clearance_data_available,
                            eligibility_clearance_available, outward_score, capacity
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            'external', %s, %s, %s, %s, NULL,
                            true, true, true, true, true, 1.0, %s
                        )
                        """,
                        (connector["analysisItemId"], candidate["id"], candidate["owner_id"],
                         connector["definitionId"], connector["worldConnectorId"],
                         connector["partInstanceId"], connector["partRef"], connector["connectorType"],
                         connector["connectorKind"], connector["connectorGender"],
                         connector["directionLabel"], connector["directionGroup"],
                         connector["positionArray"], connector["axisArray"], connector["matrix"],
                         connector["axisArray"], connector["capacity"]),
                    )
                    cursor.execute(
                        """
                        INSERT INTO component_repo.interfaces (
                            id, component_candidate_id, owner_id, world_connector_id,
                            name, exposure, default_behavior, source_connector,
                            mechanical_roles, business_roles, requirements,
                            review_status, created_by, created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, 'external', %s, %s, '[]', '[]', '{}',
                                  'pending', %s, %s, %s)
                        """,
                        (connector["interfaceId"], candidate["id"], candidate["owner_id"],
                         connector["worldConnectorId"], "auto:" + connector["worldConnectorId"],
                         connector["defaultBehavior"], Jsonb(connector["endpoint"]),
                         candidate["owner_id"], now, now),
                    )
                    cursor.execute(
                        """
                        UPDATE component_repo.connector_analysis_items
                        SET external_interface_id = %s
                        WHERE id = %s
                        """,
                        (connector["interfaceId"], connector["analysisItemId"]),
                    )
                for relation in result["relations"]:
                    cursor.execute(
                        """
                        INSERT INTO component_repo.relation_candidates (
                            id, component_candidate_id, owner_id, part_library_version_id,
                            endpoint_a, endpoint_b, connection_type, joint_type,
                            position_residual, rotation_residual, verified_by_tolerance,
                            confidence, status, detection_method, metadata, created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                  'pending', 'automatic', %s, %s, %s)
                        """,
                        (relation["id"], candidate["id"], candidate["owner_id"],
                         candidate["part_library_version_id"], Jsonb(relation["endpointA"]),
                         Jsonb(relation["endpointB"]), relation["connectionType"], relation["jointType"],
                         relation["positionResidual"], relation["rotationResidual"],
                         relation["verifiedByTolerance"], relation["confidence"],
                         Jsonb(relation["metadata"]), now, now),
                    )
                cursor.execute(
                    """
                    UPDATE component_repo.candidates
                    SET interface_signature = %s,
                        review_decisions = review_decisions || %s,
                        updated_at = %s
                    WHERE id = %s
                    """,
                    (result["interfaceSignature"], Jsonb({
                        "relationDetectionCompleted": True,
                        "partLibraryVersionId": str(candidate["part_library_version_id"]),
                        "relationDetectionVersion": result["detectionVersion"],
                    }), now, candidate["id"]),
                )
                cursor.execute(
                    """
                    UPDATE component_repo.component_versions
                    SET interface_signature = %s, validation_report_id = NULL
                    WHERE id = %s AND status = 'draft'
                    """,
                    (result["interfaceSignature"], candidate["version_id"]),
                )
            self._complete_relation_task(cursor, current, candidate, result, now)

    def _complete_relation_task(
        self,
        cursor: psycopg.Cursor,
        task: dict[str, Any],
        candidate: dict[str, Any],
        result: dict[str, Any],
        now: datetime,
    ) -> None:
        payload = {
            "candidateId": str(candidate["id"]),
            "relationCandidateCount": len(result["relations"]),
            "connectorCount": len(result["connectors"]),
            "interfaceCount": len(result["connectors"]),
            "detectionVersion": result["detectionVersion"],
        }
        cursor.execute(
            f"""
            UPDATE component_repo.tasks
            SET status = 'succeeded', result = %s, lease_owner = NULL,
                lease_expires_at = NULL, progress_percent = 100,
                error_code = NULL, error_params = NULL,
                finished_at = %s, updated_at = %s
            WHERE id = %s AND status = 'running' AND lease_owner = %s
              AND attempts = %s AND lease_expires_at > %s AND cancel_requested_at IS NULL
            RETURNING {TASK_COLUMNS}
            """,
            (Jsonb(payload), now, now, task["id"], self.settings.worker_id, task["attempts"], now),
        )
        completed = cursor.fetchone()
        if completed is None:
            raise LeaseLost()
        self._record_event(cursor, completed, "succeeded", percent=100.0)


def detect_relations(candidate: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    definitions_by_part: dict[str, list[dict[str, Any]]] = {}
    for definition in candidate["definitions"]:
        definitions_by_part.setdefault(definition["ldraw_part_num"].lower(), []).append(definition)
    connectors: list[dict[str, Any]] = []
    for part in expanded_world_parts(candidate["document"]):
        for definition in definitions_by_part.get(part["referenceName"].lower(), []):
            connector = world_connector(
                part,
                definition,
                candidate["id"],
                candidate["part_library_version_id"],
                config,
            )
            connectors.append(connector)
    relations = []
    for index, connector_a in enumerate(connectors):
        for connector_b in connectors[index + 1:]:
            if connector_a["partInstanceId"] == connector_b["partInstanceId"]:
                continue
            rule = compatibility_rule(config, connector_a["endpoint"], connector_b["endpoint"])
            if rule is None:
                continue
            metrics = connector_pair_metrics(connector_a["endpoint"], connector_b["endpoint"])
            if metrics["positionResidual"] > float(rule["candidate_lateral_ldu"]):
                continue
            if metrics["rotationResidual"] > float(rule["candidate_axis_angle_deg"]):
                continue
            endpoint_ids = sorted([connector_a["worldConnectorId"], connector_b["worldConnectorId"]])
            relation_id = uuid5(DERIVED_NAMESPACE, f"{candidate['id']}:relation:{endpoint_ids[0]}:{endpoint_ids[1]}")
            verified = (
                metrics["positionResidual"] <= float(rule["verified_lateral_ldu"])
                and metrics["rotationResidual"] <= float(rule["verified_axis_angle_deg"])
            )
            relations.append({
                "id": relation_id,
                "endpointA": connector_a["endpoint"],
                "endpointB": connector_b["endpoint"],
                "connectionType": rule["connection_type"],
                "jointType": rule["joint_type"],
                "positionResidual": metrics["positionResidual"],
                "rotationResidual": metrics["rotationResidual"],
                "verifiedByTolerance": verified,
                "confidence": confidence_from_metrics(metrics, rule),
                "metadata": {"rule": rule, "metrics": metrics},
            })
    interfaces = [{
        "worldConnectorId": connector["worldConnectorId"],
        "name": "auto:" + connector["worldConnectorId"],
        "exposure": "external",
        "defaultBehavior": connector["defaultBehavior"],
        "connectorType": connector["endpoint"].get("connectorType"),
        "connectorGender": connector["endpoint"].get("connectorGender"),
    } for connector in connectors]
    return {
        "detectionVersion": candidate["relation_detection_version"],
        "recognitionVersion": config["interface_recognition"]["version"],
        "connectors": connectors,
        "relations": relations,
        "interfaceSignature": stable_hash(interfaces),
    }


def logical_input_hash(*values: str) -> str:
    digest = hashlib.sha256()
    for value in values:
        encoded = value.encode("utf-8")
        digest.update(f"{len(encoded)}:".encode("ascii"))
        digest.update(encoded)
    return digest.hexdigest()


def world_connector(
    part: dict[str, Any],
    definition: dict[str, Any],
    candidate_id: UUID,
    part_library_version_id: UUID,
    config: dict[str, Any],
) -> dict[str, Any]:
    transform = part["worldTransform"]
    local_matrix = tuple(float(value) for value in definition["orientation"])
    position = transform_point(transform, tuple(float(value) for value in definition["position"]))
    matrix = matrix_mul(tuple(transform["matrix"]), local_matrix)
    direction = definition["direction"] or [local_matrix[1], local_matrix[4], local_matrix[7]]
    axis = normalize_vector(matrix_vector_mul(tuple(transform["matrix"]), tuple(direction)))
    world_id = f"{part['instanceId']}:{definition['id']}"
    endpoint = {
        "worldConnectorId": world_id,
        "partInstanceId": part["instanceId"],
        "instancePath": part["instancePath"],
        "partRef": part["referenceName"].lower(),
        "connectorId": str(definition["id"]),
        "sourceConnectorId": str(definition["source_connector_id"]),
        "partLibraryVersionId": str(part_library_version_id),
        "connectorType": definition["normalized_connector_type"],
        "connectorGender": definition["connector_gender"],
        "connectorKind": definition["connector_kind"],
        "connectorGroup": definition["connector_group"],
        "position": vector_to_dict(position),
        "axis": vector_to_dict(axis),
        "matrix": list(matrix),
        "directionLabel": definition["direction_label"],
        "directionGroup": definition["direction_group"],
        "metadata": {
            "radius": float(definition["radius"]) if definition["radius"] is not None else None,
            "length": float(definition["length"]) if definition["length"] is not None else None,
            "confidence": float(definition["confidence"] or 1.0),
        },
    }
    kind = "revolute" if definition["normalized_connector_type"] in {"technic_pin", "technic_pin_hole"} else "fixed"
    return {
        "analysisItemId": uuid5(DERIVED_NAMESPACE, f"{candidate_id}:connector:{world_id}"),
        "interfaceId": uuid5(DERIVED_NAMESPACE, f"{candidate_id}:interface:{world_id}:{config['interface_recognition']['version']}"),
        "definitionId": definition["id"],
        "worldConnectorId": world_id,
        "partInstanceId": part["instanceId"],
        "partRef": part["referenceName"].lower(),
        "connectorType": definition["normalized_connector_type"],
        "connectorKind": definition["connector_kind"],
        "connectorGender": definition["connector_gender"],
        "directionLabel": definition["direction_label"],
        "directionGroup": definition["direction_group"],
        "positionArray": list(position),
        "axisArray": list(axis),
        "matrix": list(matrix),
        "capacity": int(config["relations"]["connector_capacity"]),
        "defaultBehavior": kind,
        "endpoint": endpoint,
    }


def stable_hash(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_worker() -> ComponentRelationWorker:
    config = load_json_config("component_repo.json", REQUIRED_COMPONENT_REPO_CONFIG_KEYS)
    base = settings_from_environment()
    worker_id = os.environ.get("PYTHON_RELATION_WORKER_ID", "").strip() or f"{base.worker_id}-relations"
    settings = WorkerSettings(
        database_url=base.database_url,
        worker_id=worker_id,
        poll_interval=base.poll_interval,
        lease_duration=base.lease_duration,
        heartbeat_interval=base.heartbeat_interval,
        retry_delay=base.retry_delay,
    )
    return ComponentRelationWorker(settings, config)
