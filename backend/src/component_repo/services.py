"""Component Repo artifact and import services."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from src.component_repo.ldraw_deserializer import deserialize_ldraw_document
from src.component_repo.storage import ArtifactStorage
from src.model.models import (
    ComponentArtifact,
    ComponentAssemblyRelation,
    Component,
    ComponentCandidate,
    ComponentImport,
    ComponentInterface,
    ComponentRelationCandidate,
    ComponentSceneSnapshot,
    ComponentValidationReport,
    ComponentVersion,
    PartConnectorDefinition,
    PartLibraryVersion,
)


def ensure_component_repo_tables(engine: Engine) -> None:
    """Create Component Repo MVP tables for local tests and transitional startup."""
    ComponentArtifact.__table__.create(bind=engine, checkfirst=True)
    ComponentImport.__table__.create(bind=engine, checkfirst=True)
    ComponentSceneSnapshot.__table__.create(bind=engine, checkfirst=True)
    ComponentCandidate.__table__.create(bind=engine, checkfirst=True)
    PartLibraryVersion.__table__.create(bind=engine, checkfirst=True)
    PartConnectorDefinition.__table__.create(bind=engine, checkfirst=True)
    ComponentRelationCandidate.__table__.create(bind=engine, checkfirst=True)
    ComponentAssemblyRelation.__table__.create(bind=engine, checkfirst=True)
    Component.__table__.create(bind=engine, checkfirst=True)
    ComponentInterface.__table__.create(bind=engine, checkfirst=True)
    ComponentVersion.__table__.create(bind=engine, checkfirst=True)
    ComponentValidationReport.__table__.create(bind=engine, checkfirst=True)


def create_component_artifact(
    engine: Engine,
    config: dict[str, Any],
    storage: ArtifactStorage,
    artifact_type: str,
    original_filename: str,
    content: bytes,
    mime_type: str | None = None,
    uploaded_by: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Store an immutable artifact and persist its metadata."""
    validate_artifact_type(config, artifact_type)
    artifact_id = str(uuid4())
    now = datetime.now(timezone.utc)
    digest = sha256_bytes(content)
    clean_filename = Path(original_filename).name
    storage_key = artifact_storage_key(config, artifact_type, artifact_id, clean_filename)
    content_type = mime_type or default_mime_type(config, artifact_type)
    storage_uri = storage.write_bytes(storage_key, content, content_type)
    artifact = ComponentArtifact(
        id=artifact_id,
        artifact_type=artifact_type,
        original_filename=clean_filename,
        storage_provider=storage.provider,
        storage_bucket=storage.bucket,
        storage_key=storage_key,
        storage_uri=storage_uri,
        sha256=digest,
        file_size=len(content),
        mime_type=content_type,
        immutable=True,
        uploaded_by=uploaded_by or config["audit"]["system_user"],
        uploaded_at=now,
        metadata_json=metadata or {},
    )
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(artifact)
        session.commit()
        session.refresh(artifact)
        return artifact_response(artifact)


def create_component_import(
    engine: Engine,
    config: dict[str, Any],
    source_artifact_id: str,
    exchange_artifact_id: str | None = None,
    target_component_id: str | None = None,
    base_version_id: str | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    """Create an upload/parse task for a Component Repo import."""
    import_row = ComponentImport(
        id=str(uuid4()),
        source_artifact_id=source_artifact_id,
        exchange_artifact_id=exchange_artifact_id,
        target_component_id=target_component_id,
        base_version_id=base_version_id,
        status=config["imports"]["status"]["uploaded"],
        parser_version=None,
        part_library_version=None,
        created_by=created_by or config["audit"]["system_user"],
        created_at=datetime.now(timezone.utc),
        completed_at=None,
        failure_reason=None,
        metadata_json={},
    )
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(import_row)
        session.commit()
        session.refresh(import_row)
        return import_response(import_row)


def get_component_import(engine: Engine, import_id: str) -> dict[str, Any] | None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        import_row = session.get(ComponentImport, import_id)
        if import_row is None:
            return None
        return import_response(import_row)


def parse_component_import(
    engine: Engine,
    config: dict[str, Any],
    storage: ArtifactStorage,
    import_id: str,
) -> dict[str, Any]:
    """Parse an import's exchange artifact into a reviewable candidate."""
    Session = sessionmaker(bind=engine)
    with Session() as session:
        import_row = session.get(ComponentImport, import_id)
        if import_row is None:
            raise ValueError(f"Component import not found: {import_id}")
        if import_row.exchange_artifact_id is None:
            raise ValueError(f"Component import has no exchange artifact: {import_id}")
        exchange_artifact = session.get(ComponentArtifact, import_row.exchange_artifact_id)
        if exchange_artifact is None:
            raise ValueError(
                config["errors"]["artifact_not_found"].format(
                    artifact_id=import_row.exchange_artifact_id,
                )
            )
        import_row.status = config["imports"]["status"]["parsing"]
        session.flush()
        content = storage.read_bytes(exchange_artifact.storage_key)
        if sha256_bytes(content) != exchange_artifact.sha256:
            import_row.status = config["imports"]["status"]["failed"]
            import_row.failure_reason = config["errors"]["hash_mismatch"].format(
                artifact_id=exchange_artifact.id,
            )
            session.commit()
            raise ValueError(import_row.failure_reason)
        document = deserialize_ldraw_document(
            content.decode("utf-8-sig"),
            config,
        )
        now = datetime.now(timezone.utc)
        snapshot = ComponentSceneSnapshot(
            id=str(uuid4()),
            import_id=import_row.id,
            schema=config["schema"],
            parser_version=document.parser_version,
            root_model_id=document.root_model_id,
            document_json=document.to_dict(),
            bom_json=document.bom(),
            parse_issues_json=[issue.to_dict() for issue in document.parse_issues],
            created_at=now,
        )
        candidate = ComponentCandidate(
            id=str(uuid4()),
            import_id=import_row.id,
            scene_snapshot_id=snapshot.id,
            status=config["candidates"]["status"]["pending_review"],
            summary_json=candidate_summary(document),
            review_decisions_json={},
            created_at=now,
        )
        import_row.status = config["imports"]["status"]["parsed"]
        import_row.parser_version = document.parser_version
        import_row.completed_at = now
        import_row.failure_reason = None
        session.add(snapshot)
        session.add(candidate)
        session.commit()
        session.refresh(snapshot)
        session.refresh(candidate)
        session.refresh(import_row)
        return {
            "importJob": import_response(import_row),
            "sceneSnapshot": scene_snapshot_response(snapshot),
            "candidate": candidate_response(candidate),
        }


def get_component_candidate_for_import(
    engine: Engine,
    import_id: str,
) -> dict[str, Any] | None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        candidate = session.scalar(
            select(ComponentCandidate)
            .where(ComponentCandidate.import_id == import_id)
            .order_by(ComponentCandidate.created_at.desc())
        )
        if candidate is None:
            return None
        return candidate_response(candidate)


def read_component_artifact(
    engine: Engine,
    config: dict[str, Any],
    storage: ArtifactStorage,
    artifact_id: str,
) -> tuple[dict[str, Any], bytes]:
    """Read an artifact and verify its SHA-256 digest."""
    Session = sessionmaker(bind=engine)
    with Session() as session:
        artifact = session.get(ComponentArtifact, artifact_id)
        if artifact is None:
            raise ValueError(config["errors"]["artifact_not_found"].format(artifact_id=artifact_id))
        content = storage.read_bytes(artifact.storage_key)
        if sha256_bytes(content) != artifact.sha256:
            raise ValueError(config["errors"]["hash_mismatch"].format(artifact_id=artifact_id))
        return artifact_response(artifact), content


def get_component_artifact(engine: Engine, artifact_id: str) -> dict[str, Any] | None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        artifact = session.get(ComponentArtifact, artifact_id)
        if artifact is None:
            return None
        return artifact_response(artifact)


def list_component_imports(engine: Engine) -> list[dict[str, Any]]:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        imports = session.scalars(select(ComponentImport).order_by(ComponentImport.created_at.desc())).all()
        return [import_response(row) for row in imports]


def candidate_summary(document: Any) -> dict[str, Any]:
    return {
        "modelCount": len(document.models),
        "partInstanceCount": len(document.leaf_part_references()),
        "submodelInstanceCount": len(document.submodel_references()),
        "bom": document.bom(),
        "parseIssueCount": len(document.parse_issues),
    }


def validate_artifact_type(config: dict[str, Any], artifact_type: str) -> None:
    if artifact_type not in config["artifacts"]["allowed_types"]:
        raise ValueError(
            config["errors"]["invalid_artifact_type"].format(artifact_type=artifact_type)
        )


def artifact_type_for_filename(config: dict[str, Any], filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".io":
        return config["artifacts"]["studio_io"]
    if suffix == ".ldr":
        return config["artifacts"]["ldraw_ldr"]
    if suffix == ".mpd":
        return config["artifacts"]["ldraw_mpd"]
    raise ValueError(config["errors"]["invalid_artifact_type"].format(artifact_type=suffix or filename))


def artifact_storage_key(
    config: dict[str, Any],
    artifact_type: str,
    artifact_id: str,
    original_filename: str,
) -> str:
    clean_filename = Path(original_filename).name
    return (
        f"{config['storage']['object_prefix']}/"
        f"{artifact_type}/"
        f"{artifact_id}/"
        f"{clean_filename}"
    )


def default_mime_type(config: dict[str, Any], artifact_type: str) -> str:
    if artifact_type in (
        config["artifacts"]["ldraw_ldr"],
        config["artifacts"]["ldraw_mpd"],
    ):
        return config["storage"]["content_type_ldraw"]
    return config["storage"]["content_type_binary"]


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def artifact_response(artifact: ComponentArtifact) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "artifactType": artifact.artifact_type,
        "originalFilename": artifact.original_filename,
        "storageProvider": artifact.storage_provider,
        "storageBucket": artifact.storage_bucket,
        "storageKey": artifact.storage_key,
        "storageUri": artifact.storage_uri,
        "sha256": artifact.sha256,
        "fileSize": artifact.file_size,
        "mimeType": artifact.mime_type,
        "immutable": artifact.immutable,
        "uploadedBy": artifact.uploaded_by,
        "uploadedAt": artifact.uploaded_at.isoformat(),
        "metadata": artifact.metadata_json or {},
    }


def import_response(import_row: ComponentImport) -> dict[str, Any]:
    return {
        "id": import_row.id,
        "sourceArtifactId": import_row.source_artifact_id,
        "exchangeArtifactId": import_row.exchange_artifact_id,
        "targetComponentId": import_row.target_component_id,
        "baseVersionId": import_row.base_version_id,
        "status": import_row.status,
        "parserVersion": import_row.parser_version,
        "partLibraryVersion": import_row.part_library_version,
        "createdBy": import_row.created_by,
        "createdAt": import_row.created_at.isoformat(),
        "completedAt": import_row.completed_at.isoformat() if import_row.completed_at else None,
        "failureReason": import_row.failure_reason,
        "metadata": import_row.metadata_json or {},
    }


def scene_snapshot_response(snapshot: ComponentSceneSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.id,
        "importId": snapshot.import_id,
        "snapshotSchema": snapshot.schema,
        "parserVersion": snapshot.parser_version,
        "rootModelId": snapshot.root_model_id,
        "document": snapshot.document_json,
        "bom": snapshot.bom_json,
        "parseIssues": snapshot.parse_issues_json,
        "createdAt": snapshot.created_at.isoformat(),
    }


def candidate_response(candidate: ComponentCandidate) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "importId": candidate.import_id,
        "sceneSnapshotId": candidate.scene_snapshot_id,
        "status": candidate.status,
        "summary": candidate.summary_json,
        "reviewDecisions": candidate.review_decisions_json,
        "createdAt": candidate.created_at.isoformat(),
        "updatedAt": candidate.updated_at.isoformat() if candidate.updated_at else None,
    }
