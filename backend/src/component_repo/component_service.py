"""Component interface, validation, and draft version services."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import selectinload, sessionmaker

from src.i18n.domain_content import normalize_content_locale, validate_content_kind
from src.config.fitting_candidate_profile_config import (
    FITTING_CANDIDATE_PROFILE_CONFIG,
)
from src.services.domain_content_service import (
    component_source_content,
    localized_component_content,
    localized_part_content,
)
from src.services.fitting_candidate_profile_service import (
    remove_component_fitting_candidate_profile,
    upsert_component_fitting_candidate_profile,
)
from src.component_repo.relation_service import (
    expanded_world_parts,
    part_library_version_id_for_candidate,
    world_connectors_for_parts,
)
from src.component_repo.geometry_service import (
    clear_component_logical_size,
    component_geometry,
    component_preview_meshes,
    component_preview_parts,
    part_preview_mesh,
    persist_component_logical_size,
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
    LDrawPart,
    LDrawPartGeometry,
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
        )
        add_check(
            checks,
            issues,
            "exchange_artifact_present",
            exchange_artifact is not None,
        )
        add_check(
            checks,
            issues,
            "parts_resolved",
            int((candidate.summary_json or {}).get("partInstanceCount", 0)) > 0,
        )
        add_check(
            checks,
            issues,
            "transforms_valid",
            document_transforms_valid(snapshot.document_json),
        )
        add_check(
            checks,
            issues,
            "relations_valid",
            relations_valid(session, component_candidate_id),
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
        )
        add_check(
            checks,
            issues,
            "bbox_calculated",
            bounding_box(snapshot.document_json) is not None,
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


def ensure_component_candidate_draft(
    engine: Engine,
    config: dict[str, Any],
    component_candidate_id: str,
    created_by: str | None = None,
) -> dict[str, Any]:
    """Idempotently create the editable ComponentVersion produced by one import."""
    Session = sessionmaker(bind=engine)
    with Session() as session:
        candidate, snapshot, import_row = candidate_context(session, component_candidate_id)
        draft_version_id = (candidate.review_decisions_json or {}).get("draftVersionId")
        if draft_version_id:
            existing_version = session.get(ComponentVersion, draft_version_id)
            if existing_version is not None:
                existing_component = session.get(Component, existing_version.component_id)
                if existing_component is not None:
                    return {
                        "component": component_response(existing_component),
                        "version": component_version_response(existing_version),
                    }
        now = datetime.now(timezone.utc)
        component = (
            session.get(Component, import_row.target_component_id)
            if import_row.target_component_id
            else None
        )
        if import_row.target_component_id and component is None:
            raise ValueError(f"Component not found: {import_row.target_component_id}")
        source_artifact = session.get(ComponentArtifact, import_row.source_artifact_id)
        if source_artifact is None:
            raise ValueError(f"Component artifact not found: {import_row.source_artifact_id}")
        content_locale = normalize_content_locale(
            str((import_row.metadata_json or {}).get("contentLocale") or "zh-CN")
        )
        if component is None:
            component = Component(
                id=str(uuid4()),
                name=source_artifact.original_filename.rsplit(".", 1)[0],
                content_kind=validate_content_kind("user"),
                content_locale=content_locale,
                category=None,
                status=config["components"]["status"]["draft"],
                current_version_id=None,
                description=None,
                tags_json=[],
                metadata_json={},
                created_by=created_by or config["audit"]["system_user"],
                created_at=now,
            )
            session.add(component)
            session.flush()
            import_row.target_component_id = component.id
        base_version_id = import_row.base_version_id or component.current_version_id
        base_version = session.get(ComponentVersion, base_version_id) if base_version_id else None
        if base_version is not None and base_version.component_id != component.id:
            raise ValueError(f"Component version does not belong to component: {base_version_id}")
        version_name = base_version.version if base_version is not None else "0.1.0"
        existing_revisions = session.scalars(
            select(ComponentVersion.revision).where(
                ComponentVersion.component_id == component.id,
                ComponentVersion.version == version_name,
            )
        ).all()
        revision = max(existing_revisions, default=0) + 1
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
            version=version_name,
            revision=revision,
            status=config["versions"]["status"]["draft"],
            source_artifact_id=import_row.source_artifact_id,
            exchange_artifact_id=import_row.exchange_artifact_id,
            scene_snapshot_id=snapshot.id,
            parser_version=snapshot.parser_version,
            part_library_version_id=part_library_version_id,
            validation_report_id=None,
            interface_signature=interface_signature(interfaces),
            structure_hash=stable_hash(snapshot.document_json),
            geometry_hash=stable_hash(bounding_box(snapshot.document_json) or {}),
            metadata_json={
                "summary": candidate.summary_json or {},
                "baseVersionId": base_version_id,
            },
            created_by=created_by or config["audit"]["system_user"],
            created_at=now,
        )
        candidate.status = config["candidates"]["status"]["in_review"]
        candidate.review_decisions_json = {
            **(candidate.review_decisions_json or {}),
            "componentId": component.id,
            "draftVersionId": version_row.id,
        }
        session.add(version_row)
        session.commit()
        session.refresh(component)
        session.refresh(version_row)
        return {
            "component": component_response(component),
            "version": component_version_response(version_row),
        }


def publish_component_version(
    engine: Engine,
    config: dict[str, Any],
    component_version_id: str,
    release_note: str | None = None,
    name: str | None = None,
    category: str | None = None,
    version_name: str | None = None,
    content_locale: str | None = None,
    published_by: str | None = None,
) -> dict[str, Any]:
    """Validate and directly publish one editable version as the Component singleton."""
    Session = sessionmaker(bind=engine)
    with Session() as session:
        version = session.get(ComponentVersion, component_version_id)
        if version is None:
            raise ValueError(f"Component version not found: {component_version_id}")
        if version.status == config["versions"]["status"]["published"]:
            component = session.get(Component, version.component_id)
            snapshot = session.get(ComponentSceneSnapshot, version.scene_snapshot_id)
            if component is not None and snapshot is not None:
                geometry = component_geometry(session, snapshot.document_json)
                if geometry is not None:
                    upsert_component_fitting_candidate_profile(
                        session,
                        FITTING_CANDIDATE_PROFILE_CONFIG,
                        component,
                        version,
                        snapshot,
                        geometry,
                    )
                    session.commit()
            return component_version_response(version)
        candidate_id = version.component_candidate_id
    report = validate_component_candidate(
        engine,
        config,
        candidate_id,
        validation_level=config["validation"]["level"]["publish"],
    )
    if not report["passed"]:
        raise ValueError("component_repo.publish_validation_failed")

    with Session() as session:
        version = session.get(ComponentVersion, component_version_id)
        if version is None:
            raise ValueError(f"Component version not found: {component_version_id}")
        if version.status != config["versions"]["status"]["draft"]:
            raise ValueError(f"Only draft component versions can be published: {component_version_id}")
        source_artifact = session.get(ComponentArtifact, version.source_artifact_id)
        if source_artifact is None or not source_artifact.immutable or not is_sha256(source_artifact.sha256):
            raise ValueError(f"Published component version requires immutable source artifact: {component_version_id}")
        if source_artifact.artifact_type not in config["artifacts"]["allowed_types"]:
            raise ValueError(f"Unsupported component version source artifact: {component_version_id}")
        candidate, snapshot, _import_row = candidate_context(session, version.component_candidate_id)
        interfaces = session.scalars(
            select(ComponentInterface)
            .where(ComponentInterface.component_candidate_id == candidate.id)
            .order_by(ComponentInterface.created_at.asc())
        ).all()
        current_structure_hash = stable_hash(snapshot.document_json)
        current_geometry_hash = stable_hash(bounding_box(snapshot.document_json) or {})
        current_interface_signature = interface_signature(interfaces)
        now = datetime.now(timezone.utc)
        component = session.scalar(
            select(Component)
            .where(Component.id == version.component_id)
            .with_for_update()
        )
        if component is None:
            raise ValueError(f"Component not found: {version.component_id}")
        if name is not None and name.strip():
            component.name = name.strip()
        if category is not None:
            component.category = category.strip() or None
        if content_locale is not None:
            component.content_locale = normalize_content_locale(content_locale)
        if version_name is not None and version_name.strip() and version_name.strip() != version.version:
            duplicate = session.scalar(
                select(ComponentVersion).where(
                    ComponentVersion.component_id == component.id,
                    ComponentVersion.version == version_name.strip(),
                    ComponentVersion.revision == version.revision,
                    ComponentVersion.id != version.id,
                )
            )
            if duplicate is not None:
                raise ValueError("component_repo.version_conflict")
            version.version = version_name.strip()
        previous_published = session.scalars(
            select(ComponentVersion).where(
                ComponentVersion.component_id == component.id,
                ComponentVersion.status == config["versions"]["status"]["published"],
                ComponentVersion.id != version.id,
            )
        ).all()
        for previous in previous_published:
            previous.status = config["versions"]["status"]["draft"]
        version.status = config["versions"]["status"]["published"]
        version.published_at = now
        version.validation_report_id = report["id"]
        version.interface_signature = current_interface_signature
        version.structure_hash = current_structure_hash
        version.geometry_hash = current_geometry_hash
        version.metadata_json = {
            **(version.metadata_json or {}),
            "releaseNote": release_note,
            "validationReportId": report["id"],
            "publishedBy": published_by or config["audit"]["system_user"],
        }
        component.status = config["components"]["status"]["active"]
        component.current_version_id = version.id
        geometry = component_geometry(session, snapshot.document_json)
        if geometry is None:
            raise ValueError(
                f"Component version logical size cannot be calculated: {component_version_id}"
            )
        persist_component_logical_size(component, geometry)
        validation_report = session.get(ComponentValidationReport, report["id"])
        if validation_report is not None:
            validation_report.component_version_id = version.id
        candidate.status = config["candidates"]["status"]["published"]
        candidate.review_decisions_json = {
            **(candidate.review_decisions_json or {}),
            "publishedVersionId": version.id,
        }
        upsert_component_fitting_candidate_profile(
            session,
            FITTING_CANDIDATE_PROFILE_CONFIG,
            component,
            version,
            snapshot,
            geometry,
        )
        session.commit()
        session.refresh(version)
        return component_version_response(version)


def list_components(
    engine: Engine,
    config: dict[str, Any],
    content_locale: str,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """List each logical Component once, optionally filtered by lifecycle status."""
    Session = sessionmaker(bind=engine)
    with Session() as session:
        statement = select(Component).options(selectinload(Component.translations))
        if status is not None:
            statement = statement.where(Component.status == status)
        rows = session.scalars(statement.order_by(Component.created_at.desc())).all()
        return [
            component_response(row, localized_component_content(session, row, content_locale))
            for row in rows
        ]


def first_component_preview(
    engine: Engine,
    config: dict[str, Any],
    content_locale: str,
) -> dict[str, Any] | None:
    """Return the newest previewable assembly with dynamically resolved Part meshes.

    Parsed import/candidate data is preferred so the viewer can inspect work before it
    becomes a published Component. Otherwise the newest Component version is used. The
    locale selects domain content only; transforms and Part geometry are locale-neutral.
    """
    normalized_locale = normalize_content_locale(content_locale)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        import_candidate = session.execute(
            select(ComponentImport, ComponentCandidate)
            .join(ComponentCandidate, ComponentCandidate.import_id == ComponentImport.id)
            .options(selectinload(ComponentImport.source_artifact))
            .order_by(ComponentImport.created_at.desc(), ComponentImport.id.desc())
        ).first()
        if import_candidate is not None:
            import_row, candidate = import_candidate
            snapshot = session.get(ComponentSceneSnapshot, candidate.scene_snapshot_id)
            if snapshot is None:
                raise ValueError("component_repo.preview_unavailable")
            version = session.scalar(
                select(ComponentVersion)
                .where(ComponentVersion.component_candidate_id == candidate.id)
                .order_by(ComponentVersion.created_at.desc(), ComponentVersion.id.desc())
            )
            component = session.get(Component, version.component_id) if version is not None else None
            if component is not None:
                return component_preview_payload(
                    session,
                    snapshot,
                    config,
                    source={
                        "kind": "component",
                        "id": component.id,
                        "name": localized_component_content(
                            session,
                            component,
                            normalized_locale,
                        )["name"],
                        "status": component.status,
                    },
                    component=component_response(
                        component,
                        localized_component_content(session, component, normalized_locale),
                    ),
                    version_id=version.id,
                )
            source_artifact = import_row.source_artifact
            return component_preview_payload(
                session,
                snapshot,
                config,
                source={
                    "kind": "import",
                    "id": import_row.id,
                    "name": (
                        source_artifact.original_filename
                        if source_artifact is not None
                        else import_row.id
                    ),
                    "status": candidate.status,
                },
                component=None,
                version_id=None,
            )

        component = session.scalar(
            select(Component)
            .options(selectinload(Component.translations))
            .order_by(Component.created_at.desc(), Component.id.desc())
        )
        if component is None:
            return None
        version = (
            session.get(ComponentVersion, component.current_version_id)
            if component.current_version_id is not None
            else None
        )
        if version is None:
            version = session.scalar(
                select(ComponentVersion)
                .where(ComponentVersion.component_id == component.id)
                .order_by(ComponentVersion.created_at.desc(), ComponentVersion.id.desc())
            )
        if version is None:
            raise ValueError("component_repo.preview_unavailable")
        snapshot = session.get(ComponentSceneSnapshot, version.scene_snapshot_id)
        if snapshot is None:
            raise ValueError("component_repo.preview_unavailable")
        localized_content = localized_component_content(session, component, normalized_locale)
        return component_preview_payload(
            session,
            snapshot,
            config,
            source={
                "kind": "component",
                "id": component.id,
                "name": localized_content["name"],
                "status": component.status,
            },
            component=component_response(component, localized_content),
            version_id=version.id,
        )


def component_version_preview(
    engine: Engine,
    config: dict[str, Any],
    component_version_id: str,
    content_locale: str,
) -> dict[str, Any] | None:
    """Return the render-ready assembly for one explicit ComponentVersion."""
    normalized_locale = normalize_content_locale(content_locale)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        version = session.get(ComponentVersion, component_version_id)
        if version is None:
            return None
        component = session.get(Component, version.component_id)
        snapshot = session.get(ComponentSceneSnapshot, version.scene_snapshot_id)
        if component is None or snapshot is None:
            raise ValueError("component_repo.preview_unavailable")
        localized_content = localized_component_content(session, component, normalized_locale)
        return component_preview_payload(
            session,
            snapshot,
            config,
            source={
                "kind": "component",
                "id": component.id,
                "name": localized_content["name"],
                "status": version.status,
            },
            component=component_response(component, localized_content),
            version_id=version.id,
        )


def library_item_preview(
    engine: Engine,
    config: dict[str, Any],
    item_type: str,
    item_id: str,
    content_locale: str,
) -> dict[str, Any] | None:
    """Return a render-ready preview for one explicit Component or Part resource."""
    normalized_type = item_type.casefold()
    if normalized_type not in {"component", "part"}:
        raise ValueError("component_repo.preview_type_unsupported")
    normalized_locale = normalize_content_locale(content_locale)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        if normalized_type == "part":
            return part_item_preview(
                session,
                config,
                item_id,
                normalized_locale,
            )

        component = session.scalar(
            select(Component)
            .options(selectinload(Component.translations))
            .where(Component.id == item_id)
        )
        if component is None:
            return None
        version = (
            session.get(ComponentVersion, component.current_version_id)
            if component.current_version_id is not None
            else None
        )
        if version is None:
            version = session.scalar(
                select(ComponentVersion)
                .where(ComponentVersion.component_id == component.id)
                .order_by(ComponentVersion.created_at.desc(), ComponentVersion.id.desc())
            )
        if version is None:
            raise ValueError("component_repo.preview_unavailable")
        snapshot = session.get(ComponentSceneSnapshot, version.scene_snapshot_id)
        if snapshot is None:
            raise ValueError("component_repo.preview_unavailable")
        localized_content = localized_component_content(
            session,
            component,
            normalized_locale,
        )
        return component_preview_payload(
            session,
            snapshot,
            config,
            source={
                "kind": "component",
                "id": component.id,
                "name": localized_content["name"],
                "status": version.status,
            },
            component=component_response(component, localized_content),
            version_id=version.id,
        )


def part_item_preview(
    session: object,
    config: dict[str, Any],
    part_number: str,
    content_locale: str,
) -> dict[str, Any] | None:
    """Return one Part as an identity instance plus its real LDraw surface mesh."""
    row = session.execute(
        select(LDrawPart, LDrawPartGeometry)
        .join(LDrawPartGeometry, LDrawPartGeometry.ldraw_part_id == LDrawPart.id)
        .options(selectinload(LDrawPart.translations))
        .where(LDrawPart.ldraw_part_num == part_number.casefold())
    ).first()
    if row is None:
        return None
    part, geometry = row
    bounds = (
        geometry.bbox_min_x,
        geometry.bbox_min_y,
        geometry.bbox_min_z,
        geometry.bbox_max_x,
        geometry.bbox_max_y,
        geometry.bbox_max_z,
    )
    logical_size = (
        geometry.logical_width_stud,
        geometry.logical_depth_stud,
        geometry.logical_height_plate,
    )
    mesh = part_preview_mesh(part.ldraw_part_num, part.relative_path, config)
    if any(value is None for value in bounds) or any(
        value is None for value in logical_size
    ) or mesh is None:
        raise ValueError("component_repo.preview_unavailable")
    min_x, min_y, min_z, max_x, max_y, max_z = bounds
    width_stud, depth_stud, height_plate = logical_size
    localized_content = localized_part_content(session, part, content_locale)
    return {
        "source": {
            "kind": "part",
            "id": part.ldraw_part_num,
            "name": localized_content["name"] or part.ldraw_part_num,
            "status": part.import_status or geometry.geometry_status or "parsed",
        },
        "component": None,
        "versionId": None,
        "partCount": 1,
        "logicalSize": {
            "widthStud": width_stud,
            "depthStud": depth_stud,
            "heightPlate": height_plate,
        },
        "parts": [
            {
                "instanceId": part.ldraw_part_num,
                "partRef": part.ldraw_part_num,
                "colorCode": "16",
                "transform": {
                    "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                    "matrix": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
                },
                "bbox": {
                    "minX": min_x,
                    "minY": min_y,
                    "minZ": min_z,
                    "maxX": max_x,
                    "maxY": max_y,
                    "maxZ": max_z,
                },
            }
        ],
        "meshes": [mesh],
    }


def component_candidate_preview(
    engine: Engine,
    config: dict[str, Any],
    component_candidate_id: str,
    content_locale: str,
) -> dict[str, Any] | None:
    """Return a candidate snapshot even before a ComponentVersion has been created.

    Older parsed imports may not yet have ``draftVersionId`` review metadata. Their scene
    snapshots are nevertheless complete and can be rendered directly from Part geometry.
    """
    normalized_locale = normalize_content_locale(content_locale)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        candidate = session.get(ComponentCandidate, component_candidate_id)
        if candidate is None:
            return None
        import_row = session.scalar(
            select(ComponentImport)
            .options(selectinload(ComponentImport.source_artifact))
            .where(ComponentImport.id == candidate.import_id)
        )
        snapshot = session.get(ComponentSceneSnapshot, candidate.scene_snapshot_id)
        if import_row is None or snapshot is None:
            raise ValueError("component_repo.preview_unavailable")

        version = session.scalar(
            select(ComponentVersion)
            .where(ComponentVersion.component_candidate_id == candidate.id)
            .order_by(ComponentVersion.created_at.desc(), ComponentVersion.id.desc())
        )
        component = session.get(Component, version.component_id) if version is not None else None
        if component is not None:
            localized_content = localized_component_content(
                session,
                component,
                normalized_locale,
            )
            return component_preview_payload(
                session,
                snapshot,
                config,
                source={
                    "kind": "component",
                    "id": component.id,
                    "name": localized_content["name"],
                    "status": version.status,
                },
                component=component_response(component, localized_content),
                version_id=version.id,
            )

        source_artifact = import_row.source_artifact
        return component_preview_payload(
            session,
            snapshot,
            config,
            source={
                "kind": "import",
                "id": import_row.id,
                "name": (
                    source_artifact.original_filename
                    if source_artifact is not None
                    else import_row.id
                ),
                "status": candidate.status,
            },
            component=None,
            version_id=None,
        )


def component_preview_payload(
    session: object,
    snapshot: ComponentSceneSnapshot,
    config: dict[str, Any],
    *,
    source: dict[str, str],
    component: dict[str, Any] | None,
    version_id: str | None,
) -> dict[str, Any]:
    """Combine Component assembly placement with Part-owned surface geometry.

    Component records do not persist a second geometry collection. Their scene snapshot
    supplies instance references and transforms, while the configured LDraw library is
    parsed for each unique Part mesh. Missing bounds or meshes fail the whole payload to
    prevent a dimensionally incorrect partial preview.
    """
    geometry = component_geometry(session, snapshot.document_json)
    parts = component_preview_parts(session, snapshot.document_json)
    meshes = component_preview_meshes(session, snapshot.document_json, config)
    if geometry is None or parts is None or meshes is None:
        raise ValueError("component_repo.preview_unavailable")
    return {
        "source": source,
        "component": component,
        "versionId": version_id,
        "partCount": geometry["partCount"],
        "logicalSize": {
            "widthStud": geometry["widthStud"],
            "depthStud": geometry["depthStud"],
            "heightPlate": geometry["heightPlate"],
        },
        "parts": parts,
        "meshes": meshes,
    }


def get_component(
    engine: Engine,
    config: dict[str, Any],
    component_id: str,
    content_locale: str,
    status: str | None = None,
) -> dict[str, Any] | None:
    """Get a component, including one that only has editable versions."""
    Session = sessionmaker(bind=engine)
    with Session() as session:
        component = session.scalar(
            select(Component)
            .options(selectinload(Component.translations))
            .where(Component.id == component_id)
        )
        if component is None:
            return None
        if status is not None and component.status != status:
            return None
        return component_response(
            component,
            localized_component_content(session, component, content_locale),
        )


def list_component_versions(
    engine: Engine,
    config: dict[str, Any],
    component_id: str,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """List the complete editable and published version history."""
    Session = sessionmaker(bind=engine)
    with Session() as session:
        statement = select(ComponentVersion).where(ComponentVersion.component_id == component_id)
        if status is not None:
            statement = statement.where(ComponentVersion.status == status)
        rows = session.scalars(statement.order_by(ComponentVersion.created_at.desc())).all()
        return [component_version_response(row) for row in rows]


def get_component_version(
    engine: Engine,
    config: dict[str, Any],
    component_version_id: str,
    status: str | None = None,
) -> dict[str, Any] | None:
    """Get one editable or published version."""
    Session = sessionmaker(bind=engine)
    with Session() as session:
        version = session.get(ComponentVersion, component_version_id)
        if version is None:
            return None
        if status is not None and version.status != status:
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
            clear_component_logical_size(component)
            remove_component_fitting_candidate_profile(
                session,
                FITTING_CANDIDATE_PROFILE_CONFIG,
                component.id,
            )
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
    """Return the immutable source artifact for any stored version."""
    Session = sessionmaker(bind=engine)
    with Session() as session:
        version = session.get(ComponentVersion, component_version_id)
        if version is None:
            raise ValueError(f"Component version not found: {component_version_id}")
        return version.source_artifact_id


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
) -> None:
    status = "pass" if passed else "fail"
    issue_code = f"component_repo.validation.{code}"
    check = {"code": issue_code, "status": status, "params": {}, "path": []}
    checks.append(check)
    if not passed:
        issues.append({"code": issue_code, "severity": "error", "params": {}, "path": []})


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


def component_response(
    component: Component,
    content: dict[str, Any] | None = None,
) -> dict[str, Any]:
    content = content or component_source_content(component)
    return {
        "id": component.id,
        "name": content["name"],
        "contentKind": component.content_kind,
        "contentLocale": content["contentLocale"],
        "translationStatus": content["translationStatus"],
        "category": component.category,
        "status": component.status,
        "currentVersionId": component.current_version_id,
        "description": content["description"],
        "tags": content["tags"],
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
