"""Component interface, validation, and draft version services."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from src.component_repo.relation_service import (
    expanded_world_parts,
    part_library_version_id_for_candidate,
    world_connectors_for_parts,
)
from src.model.models import (
    Component,
    ComponentArtifact,
    ComponentAssemblyRelation,
    ComponentCandidate,
    ComponentImport,
    ComponentInterface,
    ComponentSceneSnapshot,
    ComponentValidationReport,
    ComponentVersion,
)


def create_component_interface(
    engine: Engine,
    config: dict[str, Any],
    component_candidate_id: str,
    world_connector_id: str,
    name: str,
    exposure: str | None = None,
    default_behavior: str | None = None,
    mechanical_roles: list[str] | None = None,
    business_roles: list[str] | None = None,
    requirements: dict[str, Any] | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    """Expose one free world connector as an external component interface."""
    Session = sessionmaker(bind=engine)
    with Session() as session:
        ensure_candidate_not_published(session, config, component_candidate_id)
        candidate, snapshot, _import_row = candidate_context(session, component_candidate_id)
        part_library_version_id = part_library_version_id_for_candidate(session, component_candidate_id)
        connectors = world_connectors_for_parts(
            session,
            expanded_world_parts(snapshot.document_json),
            part_library_version_id,
        )
        occupied = occupied_world_connector_ids(session, component_candidate_id)
        connector = next(
            (item for item in connectors if item["worldConnectorId"] == world_connector_id),
            None,
        )
        if connector is None:
            raise ValueError(f"World connector not found: {world_connector_id}")
        if world_connector_id in occupied:
            raise ValueError(f"World connector is occupied by an internal relation: {world_connector_id}")
        existing = session.scalar(
            select(ComponentInterface).where(
                ComponentInterface.component_candidate_id == component_candidate_id,
                ComponentInterface.world_connector_id == world_connector_id,
            )
        )
        now = datetime.now(timezone.utc)
        if existing is not None:
            existing.name = name
            existing.exposure = exposure or config["interfaces"]["exposure"]["external"]
            existing.default_behavior = default_behavior or config["interfaces"]["default_behavior"]["fixed"]
            existing.source_connector_json = connector
            existing.mechanical_roles_json = mechanical_roles or []
            existing.business_roles_json = business_roles or []
            existing.requirements_json = requirements or {}
            existing.review_status = config["interfaces"]["status"]["confirmed"]
            session.commit()
            session.refresh(existing)
            return component_interface_response(existing)
        interface = ComponentInterface(
            id=str(uuid4()),
            component_candidate_id=candidate.id,
            world_connector_id=world_connector_id,
            name=name,
            exposure=exposure or config["interfaces"]["exposure"]["external"],
            default_behavior=default_behavior or config["interfaces"]["default_behavior"]["fixed"],
            source_connector_json=connector,
            mechanical_roles_json=mechanical_roles or [],
            business_roles_json=business_roles or [],
            requirements_json=requirements or {},
            review_status=config["interfaces"]["status"]["confirmed"],
            created_by=created_by or config["audit"]["system_user"],
            created_at=now,
        )
        session.add(interface)
        session.commit()
        session.refresh(interface)
        return component_interface_response(interface)


def list_component_interfaces(
    engine: Engine,
    component_candidate_id: str,
) -> list[dict[str, Any]]:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        rows = session.scalars(
            select(ComponentInterface)
            .where(ComponentInterface.component_candidate_id == component_candidate_id)
            .order_by(ComponentInterface.created_at.asc())
        ).all()
        return [component_interface_response(row) for row in rows]


def validate_component_candidate(
    engine: Engine,
    config: dict[str, Any],
    component_candidate_id: str,
    validation_level: str | None = None,
) -> dict[str, Any]:
    """Run draft validation and persist a validation report."""
    Session = sessionmaker(bind=engine)
    with Session() as session:
        candidate, snapshot, import_row = candidate_context(session, component_candidate_id)
        source_artifact = session.get(ComponentArtifact, import_row.source_artifact_id)
        exchange_artifact = (
            session.get(ComponentArtifact, import_row.exchange_artifact_id)
            if import_row.exchange_artifact_id is not None
            else None
        )
        checks = []
        issues = []
        add_check(
            checks,
            issues,
            "source_hash_valid",
            source_artifact is not None and is_sha256(source_artifact.sha256),
            "source artifact exists and has a SHA-256 digest",
        )
        add_check(
            checks,
            issues,
            "exchange_artifact_present",
            exchange_artifact is not None,
            "LDraw exchange artifact is attached",
        )
        add_check(
            checks,
            issues,
            "parts_resolved",
            int((candidate.summary_json or {}).get("partInstanceCount", 0)) > 0,
            "candidate contains at least one leaf part instance",
        )
        add_check(
            checks,
            issues,
            "transforms_valid",
            document_transforms_valid(snapshot.document_json),
            "all scene references have valid LDraw transform payloads",
        )
        add_check(
            checks,
            issues,
            "relations_valid",
            relations_valid(session, component_candidate_id),
            "confirmed assembly relations have non-overlapping endpoints",
        )
        interfaces = session.scalars(
            select(ComponentInterface).where(
                ComponentInterface.component_candidate_id == component_candidate_id,
                ComponentInterface.review_status == config["interfaces"]["status"]["confirmed"],
            )
        ).all()
        add_check(
            checks,
            issues,
            "interfaces_valid",
            interfaces_valid(session, snapshot, component_candidate_id, interfaces),
            "at least one confirmed external interface maps to a free connector",
        )
        add_check(
            checks,
            issues,
            "bbox_calculated",
            bounding_box(snapshot.document_json) is not None,
            "candidate bounding box can be calculated from part transforms",
        )
        passed = not any(check["status"] == config["validation"]["check_status"]["fail"] for check in checks)
        report = ComponentValidationReport(
            id=str(uuid4()),
            component_candidate_id=candidate.id,
            component_version_id=None,
            validation_level=validation_level or config["validation"]["level"]["draft"],
            passed=passed,
            checks_json=checks,
            issues_json=issues,
            validator_version=config["validation"]["validator_version"],
            created_at=datetime.now(timezone.utc),
        )
        candidate.review_decisions_json = {
            **(candidate.review_decisions_json or {}),
            "lastValidationReportId": report.id,
            "lastValidationPassed": passed,
        }
        session.add(report)
        session.commit()
        session.refresh(report)
        return validation_report_response(report)


def approve_component_candidate(
    engine: Engine,
    config: dict[str, Any],
    component_candidate_id: str,
    name: str,
    category: str | None = None,
    component_id: str | None = None,
    version: str = "0.1.0",
    revision: int = 1,
    description: str | None = None,
    tags: list[str] | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    """Validate a candidate and create a draft ComponentVersion."""
    report = validate_component_candidate(engine, config, component_candidate_id)
    if not report["passed"]:
        raise ValueError(f"Component candidate validation failed: {report['id']}")
    Session = sessionmaker(bind=engine)
    with Session() as session:
        candidate, snapshot, import_row = candidate_context(session, component_candidate_id)
        now = datetime.now(timezone.utc)
        component = session.get(Component, component_id) if component_id else None
        if component is None:
            component = Component(
                id=component_id or str(uuid4()),
                name=name,
                category=category,
                status=config["components"]["status"]["draft"],
                current_version_id=None,
                description=description,
                tags_json=tags or [],
                metadata_json={},
                created_by=created_by or config["audit"]["system_user"],
                created_at=now,
            )
            session.add(component)
            session.flush()
        else:
            component.name = name or component.name
            component.category = category or component.category
            component.description = description if description is not None else component.description
            component.tags_json = tags if tags is not None else component.tags_json
        duplicate = session.scalar(
            select(ComponentVersion).where(
                ComponentVersion.component_id == component.id,
                ComponentVersion.version == version,
                ComponentVersion.revision == revision,
            )
        )
        if duplicate is not None:
            raise ValueError(
                f"Component version already exists: component={component.id}, version={version}, revision={revision}"
            )
        interfaces = session.scalars(
            select(ComponentInterface)
            .where(ComponentInterface.component_candidate_id == component_candidate_id)
            .order_by(ComponentInterface.created_at.asc())
        ).all()
        part_library_version_id = safe_part_library_version_id_for_candidate(session, component_candidate_id)
        version_row = ComponentVersion(
            id=str(uuid4()),
            component_id=component.id,
            component_candidate_id=candidate.id,
            version=version,
            revision=revision,
            status=config["versions"]["status"]["draft"],
            source_artifact_id=import_row.source_artifact_id,
            exchange_artifact_id=import_row.exchange_artifact_id,
            scene_snapshot_id=snapshot.id,
            parser_version=snapshot.parser_version,
            part_library_version_id=part_library_version_id,
            validation_report_id=report["id"],
            interface_signature=interface_signature(interfaces),
            structure_hash=stable_hash(snapshot.document_json),
            geometry_hash=stable_hash(bounding_box(snapshot.document_json) or {}),
            metadata_json={
                "validationReportId": report["id"],
                "summary": candidate.summary_json or {},
            },
            created_by=created_by or config["audit"]["system_user"],
            created_at=now,
        )
        validation_report = session.get(ComponentValidationReport, report["id"])
        if validation_report is not None:
            validation_report.component_version_id = version_row.id
        candidate.status = config["candidates"]["status"]["approved"]
        candidate.review_decisions_json = {
            **(candidate.review_decisions_json or {}),
            "approvedComponentId": component.id,
            "draftVersionId": version_row.id,
        }
        session.add(version_row)
        session.commit()
        session.refresh(component)
        session.refresh(version_row)
        return {
            "component": component_response(component),
            "version": component_version_response(version_row),
            "validationReport": report,
        }


def publish_component_version(
    engine: Engine,
    config: dict[str, Any],
    component_version_id: str,
    release_note: str | None = None,
    published_by: str | None = None,
) -> dict[str, Any]:
    """Publish a draft ComponentVersion and mark it queryable downstream."""
    Session = sessionmaker(bind=engine)
    with Session() as session:
        version = session.get(ComponentVersion, component_version_id)
        if version is None:
            raise ValueError(f"Component version not found: {component_version_id}")
        if version.status == config["versions"]["status"]["published"]:
            return component_version_response(version)
        if version.status != config["versions"]["status"]["draft"]:
            raise ValueError(f"Only draft component versions can be published: {component_version_id}")
        source_artifact = session.get(ComponentArtifact, version.source_artifact_id)
        if source_artifact is None or not source_artifact.immutable or not is_sha256(source_artifact.sha256):
            raise ValueError(f"Published component version requires immutable source artifact: {component_version_id}")
        if source_artifact.artifact_type != config["artifacts"]["studio_io"]:
            raise ValueError(f"Published component version source must be a Studio .io artifact: {component_version_id}")
        report = (
            session.get(ComponentValidationReport, version.validation_report_id)
            if version.validation_report_id is not None
            else None
        )
        if report is None or not report.passed:
            raise ValueError(f"Component version must have a passing validation report: {component_version_id}")
        candidate, snapshot, _import_row = candidate_context(session, version.component_candidate_id)
        interfaces = session.scalars(
            select(ComponentInterface)
            .where(ComponentInterface.component_candidate_id == candidate.id)
            .order_by(ComponentInterface.created_at.asc())
        ).all()
        current_structure_hash = stable_hash(snapshot.document_json)
        current_geometry_hash = stable_hash(bounding_box(snapshot.document_json) or {})
        current_interface_signature = interface_signature(interfaces)
        if version.structure_hash != current_structure_hash:
            raise ValueError(f"Component version structure hash changed before publish: {component_version_id}")
        if version.geometry_hash != current_geometry_hash:
            raise ValueError(f"Component version geometry hash changed before publish: {component_version_id}")
        if version.interface_signature != current_interface_signature:
            raise ValueError(f"Component version interface signature changed before publish: {component_version_id}")
        now = datetime.now(timezone.utc)
        version.status = config["versions"]["status"]["published"]
        version.published_at = now
        version.metadata_json = {
            **(version.metadata_json or {}),
            "releaseNote": release_note,
            "publishedBy": published_by or config["audit"]["system_user"],
        }
        component = session.get(Component, version.component_id)
        if component is None:
            raise ValueError(f"Component not found: {version.component_id}")
        component.status = config["components"]["status"]["active"]
        component.current_version_id = version.id
        candidate.review_decisions_json = {
            **(candidate.review_decisions_json or {}),
            "publishedVersionId": version.id,
        }
        session.commit()
        session.refresh(version)
        return component_version_response(version)


def list_components(
    engine: Engine,
    config: dict[str, Any],
    status: str | None = None,
) -> list[dict[str, Any]]:
    """List components. Defaults to published/active components only."""
    Session = sessionmaker(bind=engine)
    with Session() as session:
        target_status = status or config["components"]["status"]["active"]
        rows = session.scalars(
            select(Component)
            .where(Component.status == target_status)
            .order_by(Component.created_at.desc())
        ).all()
        return [component_response(row) for row in rows]


def get_component(
    engine: Engine,
    config: dict[str, Any],
    component_id: str,
    status: str | None = None,
) -> dict[str, Any] | None:
    """Get a component. Defaults to published/active components only."""
    Session = sessionmaker(bind=engine)
    with Session() as session:
        component = session.get(Component, component_id)
        if component is None:
            return None
        target_status = status or config["components"]["status"]["active"]
        if component.status != target_status:
            return None
        return component_response(component)


def list_component_versions(
    engine: Engine,
    config: dict[str, Any],
    component_id: str,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """List component versions. Defaults to published versions only."""
    Session = sessionmaker(bind=engine)
    with Session() as session:
        target_status = status or config["versions"]["status"]["published"]
        rows = session.scalars(
            select(ComponentVersion)
            .where(
                ComponentVersion.component_id == component_id,
                ComponentVersion.status == target_status,
            )
            .order_by(ComponentVersion.created_at.desc())
        ).all()
        return [component_version_response(row) for row in rows]


def get_component_version(
    engine: Engine,
    config: dict[str, Any],
    component_version_id: str,
    status: str | None = None,
) -> dict[str, Any] | None:
    """Get one version. Defaults to published versions only."""
    Session = sessionmaker(bind=engine)
    with Session() as session:
        version = session.get(ComponentVersion, component_version_id)
        if version is None:
            return None
        target_status = status or config["versions"]["status"]["published"]
        if version.status != target_status:
            return None
        return component_version_response(version)


def set_component_version_lifecycle_status(
    engine: Engine,
    config: dict[str, Any],
    component_version_id: str,
    status: str,
) -> dict[str, Any]:
    """Mark a published version deprecated or archived."""
    allowed = {
        config["versions"]["status"]["deprecated"],
        config["versions"]["status"]["archived"],
    }
    if status not in allowed:
        raise ValueError(f"Unsupported component version lifecycle status: {status}")
    Session = sessionmaker(bind=engine)
    with Session() as session:
        version = session.get(ComponentVersion, component_version_id)
        if version is None:
            raise ValueError(f"Component version not found: {component_version_id}")
        if version.status != config["versions"]["status"]["published"]:
            raise ValueError(f"Only published component versions can change lifecycle status: {component_version_id}")
        version.status = status
        component = session.get(Component, version.component_id)
        if component is not None and component.current_version_id == version.id:
            component.current_version_id = None
            if status == config["versions"]["status"]["archived"]:
                component.status = config["components"]["status"]["archived"]
        session.commit()
        session.refresh(version)
        return component_version_response(version)


def component_version_source_artifact_id(
    engine: Engine,
    config: dict[str, Any],
    component_version_id: str,
) -> str:
    """Return source artifact id for a published component version."""
    Session = sessionmaker(bind=engine)
    with Session() as session:
        version = session.get(ComponentVersion, component_version_id)
        if version is None:
            raise ValueError(f"Component version not found: {component_version_id}")
        if version.status != config["versions"]["status"]["published"]:
            raise ValueError(f"Component version source is only available after publish: {component_version_id}")
        return version.source_artifact_id


def ensure_candidate_not_published(
    session,
    config: dict[str, Any],
    component_candidate_id: str,
) -> None:
    published = session.scalar(
        select(ComponentVersion).where(
            ComponentVersion.component_candidate_id == component_candidate_id,
            ComponentVersion.status == config["versions"]["status"]["published"],
        )
    )
    if published is not None:
        raise ValueError(f"Published component candidate is immutable: {component_candidate_id}")


def candidate_context(session, component_candidate_id: str):
    candidate = session.get(ComponentCandidate, component_candidate_id)
    if candidate is None:
        raise ValueError(f"Component candidate not found: {component_candidate_id}")
    snapshot = session.get(ComponentSceneSnapshot, candidate.scene_snapshot_id)
    if snapshot is None:
        raise ValueError(f"Component scene snapshot not found: {candidate.scene_snapshot_id}")
    import_row = session.get(ComponentImport, candidate.import_id)
    if import_row is None:
        raise ValueError(f"Component import not found: {candidate.import_id}")
    return candidate, snapshot, import_row


def occupied_world_connector_ids(session, component_candidate_id: str) -> set[str]:
    occupied = set()
    relations = session.scalars(
        select(ComponentAssemblyRelation).where(
            ComponentAssemblyRelation.component_candidate_id == component_candidate_id
        )
    ).all()
    for relation in relations:
        occupied.add(relation.endpoint_a_json["worldConnectorId"])
        occupied.add(relation.endpoint_b_json["worldConnectorId"])
    return occupied


def relations_valid(session, component_candidate_id: str) -> bool:
    occupied = []
    relations = session.scalars(
        select(ComponentAssemblyRelation).where(
            ComponentAssemblyRelation.component_candidate_id == component_candidate_id
        )
    ).all()
    for relation in relations:
        occupied.append(relation.endpoint_a_json.get("worldConnectorId"))
        occupied.append(relation.endpoint_b_json.get("worldConnectorId"))
    return len(occupied) == len(set(occupied))


def interfaces_valid(
    session,
    snapshot: ComponentSceneSnapshot,
    component_candidate_id: str,
    interfaces: list[ComponentInterface],
) -> bool:
    if not interfaces:
        return False
    part_library_version_id = part_library_version_id_for_candidate(session, component_candidate_id)
    connectors = world_connectors_for_parts(
        session,
        expanded_world_parts(snapshot.document_json),
        part_library_version_id,
    )
    free_ids = {
        connector["worldConnectorId"]
        for connector in connectors
        if connector["worldConnectorId"] not in occupied_world_connector_ids(session, component_candidate_id)
    }
    return all(interface.world_connector_id in free_ids for interface in interfaces)


def document_transforms_valid(document: dict[str, Any]) -> bool:
    for model in document.get("models", []):
        for reference in model.get("references", []):
            transform = reference.get("transform", {})
            position = transform.get("position", {})
            matrix = transform.get("matrix", [])
            if sorted(position.keys()) != ["x", "y", "z"]:
                return False
            if len(matrix) != 9:
                return False
            values = [position["x"], position["y"], position["z"], *matrix]
            if not all(isinstance(value, int | float) for value in values):
                return False
    return True


def bounding_box(document: dict[str, Any]) -> dict[str, float] | None:
    parts = expanded_world_parts(document)
    if not parts:
        return None
    xs = [part["transform"]["position"]["x"] for part in parts]
    ys = [part["transform"]["position"]["y"] for part in parts]
    zs = [part["transform"]["position"]["z"] for part in parts]
    return {
        "minX": min(xs),
        "minY": min(ys),
        "minZ": min(zs),
        "maxX": max(xs),
        "maxY": max(ys),
        "maxZ": max(zs),
    }


def add_check(
    checks: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    code: str,
    passed: bool,
    message: str,
) -> None:
    status = "pass" if passed else "fail"
    checks.append({"code": code, "status": status, "message": message})
    if not passed:
        issues.append({"code": code, "severity": "error", "message": message})


def is_sha256(value: str | None) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def safe_part_library_version_id_for_candidate(session, component_candidate_id: str) -> str | None:
    try:
        return part_library_version_id_for_candidate(session, component_candidate_id)
    except ValueError:
        return None


def stable_hash(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def interface_signature(interfaces: list[ComponentInterface]) -> str:
    payload = [
        {
            "worldConnectorId": interface.world_connector_id,
            "name": interface.name,
            "exposure": interface.exposure,
            "defaultBehavior": interface.default_behavior,
            "connectorType": (interface.source_connector_json or {}).get("connectorType"),
            "connectorGender": (interface.source_connector_json or {}).get("connectorGender"),
        }
        for interface in interfaces
    ]
    return stable_hash(payload)


def component_interface_response(interface: ComponentInterface) -> dict[str, Any]:
    return {
        "id": interface.id,
        "componentCandidateId": interface.component_candidate_id,
        "worldConnectorId": interface.world_connector_id,
        "name": interface.name,
        "exposure": interface.exposure,
        "defaultBehavior": interface.default_behavior,
        "sourceConnector": interface.source_connector_json,
        "mechanicalRoles": interface.mechanical_roles_json or [],
        "businessRoles": interface.business_roles_json or [],
        "requirements": interface.requirements_json or {},
        "reviewStatus": interface.review_status,
        "createdBy": interface.created_by,
        "createdAt": interface.created_at.isoformat(),
        "updatedAt": interface.updated_at.isoformat() if interface.updated_at else None,
    }


def validation_report_response(report: ComponentValidationReport) -> dict[str, Any]:
    return {
        "id": report.id,
        "componentCandidateId": report.component_candidate_id,
        "componentVersionId": report.component_version_id,
        "validationLevel": report.validation_level,
        "passed": report.passed,
        "checks": report.checks_json,
        "issues": report.issues_json,
        "validatorVersion": report.validator_version,
        "createdAt": report.created_at.isoformat(),
    }


def component_response(component: Component) -> dict[str, Any]:
    return {
        "id": component.id,
        "name": component.name,
        "category": component.category,
        "status": component.status,
        "currentVersionId": component.current_version_id,
        "description": component.description,
        "tags": component.tags_json or [],
        "metadata": component.metadata_json or {},
        "createdBy": component.created_by,
        "createdAt": component.created_at.isoformat(),
        "updatedAt": component.updated_at.isoformat() if component.updated_at else None,
    }


def component_version_response(version: ComponentVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "componentId": version.component_id,
        "componentCandidateId": version.component_candidate_id,
        "version": version.version,
        "revision": version.revision,
        "status": version.status,
        "sourceArtifactId": version.source_artifact_id,
        "exchangeArtifactId": version.exchange_artifact_id,
        "sceneSnapshotId": version.scene_snapshot_id,
        "parserVersion": version.parser_version,
        "partLibraryVersionId": version.part_library_version_id,
        "validationReportId": version.validation_report_id,
        "interfaceSignature": version.interface_signature,
        "structureHash": version.structure_hash,
        "geometryHash": version.geometry_hash,
        "metadata": version.metadata_json or {},
        "createdBy": version.created_by,
        "createdAt": version.created_at.isoformat(),
        "publishedAt": version.published_at.isoformat() if version.published_at else None,
    }
