"""Component Repo artifact and import services."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, inspect, select, text, update
from sqlalchemy.orm import sessionmaker

from src.i18n.domain_content import USER_CONTENT, normalize_content_locale
from src.i18n.messages import error_from_exception, locale_catalog, message
from src.component_repo.ldraw_deserializer import deserialize_ldraw_document
from src.component_repo.geometry_service import backfill_component_logical_sizes
from src.component_repo.storage import ArtifactStorage
from src.model.models import (
    ComponentArtifact,
    ComponentAssemblyRelation,
    Component,
    ComponentTranslation,
    ComponentCandidate,
    ComponentImport,
    ComponentInterface,
    ComponentRelationCandidate,
    ComponentSceneSnapshot,
    ComponentUploadSession,
    ComponentValidationReport,
    ComponentVersion,
    PartConnectorDefinition,
    PartLibraryVersion,
)


def ensure_component_repo_tables(engine: Engine) -> None:
    """Create Component Repo MVP tables for local tests and transitional startup."""
    ComponentArtifact.__table__.create(bind=engine, checkfirst=True)
    ComponentUploadSession.__table__.create(bind=engine, checkfirst=True)
    ComponentImport.__table__.create(bind=engine, checkfirst=True)
    ComponentSceneSnapshot.__table__.create(bind=engine, checkfirst=True)
    ComponentCandidate.__table__.create(bind=engine, checkfirst=True)
    PartLibraryVersion.__table__.create(bind=engine, checkfirst=True)
    PartConnectorDefinition.__table__.create(bind=engine, checkfirst=True)
    ComponentRelationCandidate.__table__.create(bind=engine, checkfirst=True)
    ComponentAssemblyRelation.__table__.create(bind=engine, checkfirst=True)
    Component.__table__.create(bind=engine, checkfirst=True)
    ComponentTranslation.__table__.create(bind=engine, checkfirst=True)
    ComponentInterface.__table__.create(bind=engine, checkfirst=True)
    ComponentVersion.__table__.create(bind=engine, checkfirst=True)
    ComponentValidationReport.__table__.create(bind=engine, checkfirst=True)
    ensure_component_repo_schema_columns(engine)


def ensure_component_repo_schema_columns(engine: Engine) -> None:
    """Upgrade Component Repo tables created by pre-i18n/error-contract releases."""
    default_locale = str(locale_catalog()["default_locale"])
    ensure_table_columns(
        engine,
        ComponentImport.__tablename__,
        {
            "failure_code": "VARCHAR(160) NULL",
            "failure_params_json": "JSON NULL",
        },
    )
    ensure_table_columns(
        engine,
        Component.__tablename__,
        {
            "content_kind": (
                "VARCHAR(16) NOT NULL DEFAULT "
                f"'{sql_literal(USER_CONTENT)}'"
            ),
            "content_locale": (
                "VARCHAR(16) NOT NULL DEFAULT "
                f"'{sql_literal(default_locale)}'"
            ),
            "logical_width_stud": "DOUBLE PRECISION NULL",
            "logical_depth_stud": "DOUBLE PRECISION NULL",
            "logical_height_plate": "DOUBLE PRECISION NULL",
        },
    )
    component_columns = {
        column["name"]
        for column in inspect(engine).get_columns(Component.__tablename__)
    }
    logical_index_columns = {
        "status",
        "logical_height_plate",
        "logical_width_stud",
        "logical_depth_stud",
    }
    if logical_index_columns.issubset(component_columns):
        for index in Component.__table__.indexes:
            if index.name == "idx_components_logical_size":
                index.create(bind=engine, checkfirst=True)
    if {"current_version_id", *logical_index_columns}.issubset(component_columns):
        backfill_component_logical_sizes(engine)
    migrate_legacy_component_import_failures(engine)


def ensure_table_columns(
    engine: Engine,
    table_name: str,
    column_definitions: dict[str, str],
) -> None:
    inspector = inspect(engine)
    if not inspector.has_table(table_name):
        return
    existing = {column["name"] for column in inspector.get_columns(table_name)}
    preparer = engine.dialect.identifier_preparer
    quoted_table = preparer.quote(table_name)
    for column_name, definition in column_definitions.items():
        if column_name in existing:
            continue
        quoted_column = preparer.quote(column_name)
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"ALTER TABLE {quoted_table} ADD COLUMN "
                    f"{quoted_column} {definition}"
                )
            )


def migrate_legacy_component_import_failures(engine: Engine) -> None:
    columns = {
        column["name"]
        for column in inspect(engine).get_columns(ComponentImport.__tablename__)
    }
    if "failure_reason" not in columns:
        return
    with engine.begin() as connection:
        rows = connection.execute(
            text(
                "SELECT id, failure_reason FROM component_imports "
                "WHERE failure_reason IS NOT NULL AND failure_code IS NULL"
            )
        ).all()
        for import_id, failure_reason in rows:
            connection.execute(
                update(ComponentImport)
                .where(ComponentImport.id == import_id)
                .values(
                    failure_code="component_repo.legacy_failure",
                    failure_params_json={"legacyMessage": str(failure_reason)},
                )
            )


def sql_literal(value: str) -> str:
    return value.replace("'", "''")


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
    content_locale: str | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    """Create an upload/parse task for a Component Repo import."""
    normalized_content_locale = (
        normalize_content_locale(content_locale) if content_locale is not None else None
    )
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
        failure_code=None,
        failure_params_json=None,
        metadata_json=(
            {"contentLocale": normalized_content_locale}
            if normalized_content_locale is not None
            else {}
        ),
    )
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(import_row)
        session.commit()
        session.refresh(import_row)
        return import_response(import_row)


def create_component_upload_session(
    engine: Engine,
    config: dict[str, Any],
    owner_id: str,
    source_filename: str,
    source_content_type: str | None = None,
    exchange_filename: str | None = None,
    exchange_content_type: str | None = None,
    target_component_id: str | None = None,
    base_version_id: str | None = None,
    content_locale: str | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    """Create a direct-to-storage upload session with server-generated object paths."""

    normalized_content_locale = (
        normalize_content_locale(content_locale) if content_locale is not None else None
    )
    session_id = str(uuid4())
    expected_uploads = [
        expected_upload(
            config,
            owner_id,
            session_id,
            "source",
            source_filename,
            source_content_type,
        )
    ]
    if exchange_filename:
        expected_uploads.append(
            expected_upload(
                config,
                owner_id,
                session_id,
                "exchange",
                exchange_filename,
                exchange_content_type,
            )
        )
    upload_session = ComponentUploadSession(
        id=session_id,
        owner_id=owner_id,
        status=config["imports"]["upload_session_status"]["pending"],
        expected_uploads_json=expected_uploads,
        created_by=created_by or config["audit"]["system_user"],
        created_at=datetime.now(timezone.utc),
        completed_at=None,
        failure_code=None,
        failure_params_json=None,
        metadata_json={
            "targetComponentId": target_component_id,
            "baseVersionId": base_version_id,
            "contentLocale": normalized_content_locale,
        },
    )
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(upload_session)
        session.commit()
        session.refresh(upload_session)
        return upload_session_response(upload_session, config)


def complete_component_upload_session(
    engine: Engine,
    config: dict[str, Any],
    storage: ArtifactStorage,
    upload_session_id: str,
    owner_id: str,
    completed_by: str | None = None,
) -> dict[str, Any]:
    """Verify uploaded storage objects and create ComponentImport metadata."""

    Session = sessionmaker(bind=engine)
    with Session() as session:
        upload_session = session.get(ComponentUploadSession, upload_session_id)
        if upload_session is None:
            raise ValueError(f"Component upload session not found: {upload_session_id}")
        if upload_session.owner_id != owner_id:
            raise ValueError(f"Component upload session does not belong to current user: {upload_session_id}")
        if upload_session.status == config["imports"]["upload_session_status"]["completed"]:
            import_id = (upload_session.metadata_json or {}).get("importId")
            if import_id:
                import_row = session.get(ComponentImport, import_id)
                if import_row is not None:
                    source_artifact = session.get(ComponentArtifact, import_row.source_artifact_id)
                    exchange_artifact = (
                        session.get(ComponentArtifact, import_row.exchange_artifact_id)
                        if import_row.exchange_artifact_id
                        else None
                    )
                    return {
                        "importJob": import_response(import_row),
                        "sourceArtifact": artifact_response(source_artifact),
                        "exchangeArtifact": artifact_response(exchange_artifact) if exchange_artifact else None,
                    }
        if upload_session.status != config["imports"]["upload_session_status"]["pending"]:
            raise ValueError(f"Component upload session is not pending: {upload_session_id}")

        artifacts_by_role: dict[str, ComponentArtifact] = {}
        now = datetime.now(timezone.utc)
        try:
            for upload in upload_session.expected_uploads_json:
                content = storage.read_bytes(upload["objectPath"])
                artifact = create_component_artifact_row_from_storage(
                    config,
                    storage,
                    {**upload, "uploadSessionId": upload_session.id},
                    content,
                    completed_by,
                    now,
                )
                session.add(artifact)
                session.flush()
                artifacts_by_role[upload["role"]] = artifact
            source_artifact = artifacts_by_role["source"]
            exchange_artifact = artifacts_by_role.get("exchange")
            if (
                exchange_artifact is None
                and source_artifact.artifact_type
                in (config["artifacts"]["ldraw_ldr"], config["artifacts"]["ldraw_mpd"])
            ):
                exchange_artifact = source_artifact
            import_row = ComponentImport(
                id=str(uuid4()),
                source_artifact_id=source_artifact.id,
                exchange_artifact_id=exchange_artifact.id if exchange_artifact else None,
                target_component_id=(upload_session.metadata_json or {}).get("targetComponentId"),
                base_version_id=(upload_session.metadata_json or {}).get("baseVersionId"),
                status=config["imports"]["status"]["uploaded"],
                parser_version=None,
                part_library_version=None,
                created_by=completed_by or config["audit"]["system_user"],
                created_at=now,
                completed_at=None,
                failure_code=None,
                failure_params_json=None,
                metadata_json={
                    "uploadSessionId": upload_session.id,
                    "uploadMethod": "direct_storage",
                    "contentLocale": (upload_session.metadata_json or {}).get("contentLocale"),
                },
            )
            session.add(import_row)
            upload_session.status = config["imports"]["upload_session_status"]["completed"]
            upload_session.completed_at = now
            upload_session.metadata_json = {
                **(upload_session.metadata_json or {}),
                "importId": import_row.id,
            }
            session.commit()
            session.refresh(import_row)
            session.refresh(source_artifact)
            if exchange_artifact is not None:
                session.refresh(exchange_artifact)
            return {
                "importJob": import_response(import_row),
                "sourceArtifact": artifact_response(source_artifact),
                "exchangeArtifact": artifact_response(exchange_artifact) if exchange_artifact else None,
            }
        except Exception as error:
            session.rollback()
            upload_session = session.get(ComponentUploadSession, upload_session_id)
            if upload_session is not None:
                failure = error_from_exception(
                    error,
                    "component_repo.upload_session_complete_failed",
                    {"uploadSessionId": upload_session_id},
                )
                upload_session.failure_code = failure["code"]
                upload_session.failure_params_json = failure["params"]
                session.commit()
            raise


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
        existing_candidate = session.scalar(
            select(ComponentCandidate)
            .where(ComponentCandidate.import_id == import_id)
            .order_by(ComponentCandidate.created_at.desc())
        )
        if existing_candidate is not None:
            existing_snapshot = session.get(
                ComponentSceneSnapshot,
                existing_candidate.scene_snapshot_id,
            )
            if existing_snapshot is None:
                raise ValueError(
                    f"Component scene snapshot not found: {existing_candidate.scene_snapshot_id}"
                )
            from src.component_repo.component_service import ensure_component_candidate_draft

            draft = ensure_component_candidate_draft(
                engine,
                config,
                existing_candidate.id,
                created_by=import_row.created_by,
            )
            session.expire(existing_candidate)
            session.refresh(existing_candidate)
            return {
                "importJob": import_response(import_row),
                "sceneSnapshot": scene_snapshot_response(existing_snapshot),
                "candidate": candidate_response(existing_candidate),
                "component": draft["component"],
                "version": draft["version"],
            }
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
        try:
            content = storage.read_bytes(exchange_artifact.storage_key)
            if sha256_bytes(content) != exchange_artifact.sha256:
                import_row.failure_code = config["errors"]["hash_mismatch"]
                import_row.failure_params_json = {"artifactId": exchange_artifact.id}
                raise ValueError(import_row.failure_code)
            document = deserialize_ldraw_document(
                content.decode("utf-8-sig"),
                config,
            )
        except Exception as error:
            import_row.status = config["imports"]["status"]["failed"]
            if import_row.failure_code is None:
                failure = error_from_exception(
                    error,
                    "component_repo.import_parse_failed",
                    {"importId": import_id},
                )
                import_row.failure_code = failure["code"]
                import_row.failure_params_json = failure["params"]
            session.commit()
            raise
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
        import_row.failure_code = None
        import_row.failure_params_json = None
        session.add(snapshot)
        session.add(candidate)
        session.commit()
        session.refresh(snapshot)
        session.refresh(candidate)
        session.refresh(import_row)
        from src.component_repo.component_service import ensure_component_candidate_draft

        draft = ensure_component_candidate_draft(
            engine,
            config,
            candidate.id,
            created_by=import_row.created_by,
        )
        session.expire(import_row)
        session.expire(candidate)
        session.refresh(import_row)
        session.refresh(candidate)
        return {
            "importJob": import_response(import_row),
            "sceneSnapshot": scene_snapshot_response(snapshot),
            "candidate": candidate_response(candidate),
            "component": draft["component"],
            "version": draft["version"],
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


def get_component_candidate(
    engine: Engine,
    candidate_id: str,
) -> dict[str, Any] | None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        candidate = session.get(ComponentCandidate, candidate_id)
        return candidate_response(candidate) if candidate is not None else None


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


def list_component_imports(
    engine: Engine,
    created_by: str | None = None,
) -> list[dict[str, Any]]:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        statement = select(ComponentImport).order_by(ComponentImport.created_at.desc())
        if created_by is not None:
            statement = statement.where(ComponentImport.created_by == created_by)
        imports = session.scalars(statement).all()
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


def upload_session_storage_key(
    config: dict[str, Any],
    owner_id: str,
    upload_session_id: str,
    artifact_type: str,
    artifact_id: str,
    role: str,
    original_filename: str,
) -> str:
    suffix = Path(original_filename).suffix.lower()
    object_filename = f"{role}{suffix}" if suffix else role
    return (
        f"{owner_id}/"
        f"{config['storage']['object_prefix']}/"
        f"imports/"
        f"{upload_session_id}/"
        f"{artifact_type}/"
        f"{artifact_id}/"
        f"{object_filename}"
    )


def expected_upload(
    config: dict[str, Any],
    owner_id: str,
    upload_session_id: str,
    role: str,
    filename: str,
    content_type: str | None,
) -> dict[str, Any]:
    artifact_type = artifact_type_for_filename(config, filename)
    artifact_id = str(uuid4())
    return {
        "role": role,
        "artifactId": artifact_id,
        "artifactType": artifact_type,
        "originalFilename": Path(filename).name,
        "bucket": config["storage"]["bucket"],
        "objectPath": upload_session_storage_key(
            config,
            owner_id,
            upload_session_id,
            artifact_type,
            artifact_id,
            role,
            filename,
        ),
        "contentType": content_type or default_mime_type(config, artifact_type),
    }


def create_component_artifact_row_from_storage(
    config: dict[str, Any],
    storage: ArtifactStorage,
    upload: dict[str, Any],
    content: bytes,
    uploaded_by: str | None,
    uploaded_at: datetime,
) -> ComponentArtifact:
    validate_artifact_type(config, upload["artifactType"])
    return ComponentArtifact(
        id=upload["artifactId"],
        artifact_type=upload["artifactType"],
        original_filename=Path(upload["originalFilename"]).name,
        storage_provider=storage.provider,
        storage_bucket=storage.bucket,
        storage_key=upload["objectPath"],
        storage_uri=f"{storage.provider}://{storage.bucket}/{upload['objectPath']}",
        sha256=sha256_bytes(content),
        file_size=len(content),
        mime_type=upload["contentType"],
        immutable=True,
        uploaded_by=uploaded_by or config["audit"]["system_user"],
        uploaded_at=uploaded_at,
        metadata_json={
            "uploadSessionId": upload.get("uploadSessionId"),
            "uploadRole": upload["role"],
            "uploadMethod": "direct_storage",
        },
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


def upload_session_response(upload_session: ComponentUploadSession, config: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": upload_session.id,
        "ownerId": upload_session.owner_id,
        "status": upload_session.status,
        "bucket": config["storage"]["bucket"],
        "uploads": [
            {
                **upload,
                "uploadSessionId": upload_session.id,
            }
            for upload in upload_session.expected_uploads_json
        ],
        "createdBy": upload_session.created_by,
        "createdAt": upload_session.created_at.isoformat(),
        "completedAt": upload_session.completed_at.isoformat() if upload_session.completed_at else None,
        "failure": (
            message(upload_session.failure_code, upload_session.failure_params_json)
            if upload_session.failure_code
            else None
        ),
        "metadata": upload_session.metadata_json or {},
    }


def import_response(import_row: ComponentImport) -> dict[str, Any]:
    source_artifact = import_row.source_artifact
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
        "failure": (
            message(import_row.failure_code, import_row.failure_params_json)
            if import_row.failure_code
            else None
        ),
        "metadata": import_row.metadata_json or {},
        "sourceFilename": source_artifact.original_filename if source_artifact else None,
        "sourceFileSize": source_artifact.file_size if source_artifact else None,
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
