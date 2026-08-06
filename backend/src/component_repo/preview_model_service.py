"""Storage-backed GLB preview cache for Component Repo resources."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from src.component_repo.glb_service import build_meshopt_glb
from src.component_repo.storage import ArtifactStorage
from src.model.models import ComponentArtifact, ComponentVersion


_preview_build_locks_guard = Lock()
_preview_build_locks: dict[str, tuple[Lock, int]] = {}

PREVIEW_PENDING = "pending"
PREVIEW_READY = "ready"
PREVIEW_FAILED = "failed"
PREVIEW_STALE = "stale"


def component_version_preview_model(
    engine: Engine,
    config: dict[str, Any],
    storage: ArtifactStorage,
    version_id: str,
) -> dict[str, Any] | None:
    """Return a version-linked GLB without loading its scene snapshot or Part meshes."""
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as session:
        row = session.execute(
            select(ComponentVersion, ComponentArtifact)
            .outerjoin(
                ComponentArtifact,
                ComponentArtifact.id == ComponentVersion.preview_artifact_id,
            )
            .where(
                ComponentVersion.id == version_id,
                ComponentVersion.deleted_at.is_(None),
            )
        ).one_or_none()
    if row is None:
        return None
    version, artifact = row
    generator_version = str(config["preview"]["generator_version"])
    if (
        artifact is None
        or version.preview_status != PREVIEW_READY
        or version.preview_generator_version != generator_version
    ):
        return {
            "versionId": version.id,
            "status": (
                PREVIEW_STALE
                if artifact is not None
                and version.preview_generator_version != generator_version
                else version.preview_status
            ),
            "model": None,
            "failure": structured_preview_failure(version),
        }
    return version_preview_with_artifact(version.id, artifact, storage, config)


def materialize_component_version_preview_model(
    engine: Engine,
    config: dict[str, Any],
    storage: ArtifactStorage,
    preview: dict[str, Any],
    version_id: str,
    *,
    owner_id: str,
    uploaded_by: str,
) -> dict[str, Any]:
    """Generate a missing version GLB once, then persist its direct artifact relation."""
    generator_version = str(config["preview"]["generator_version"])
    artifact_id = component_version_preview_artifact_id(
        storage,
        version_id,
        generator_version,
    )
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with preview_build_lock(artifact_id):
        cached = component_version_preview_model(engine, config, storage, version_id)
        if cached is None:
            raise ValueError("component_repo.version_not_found")
        if cached["model"] is not None:
            return cached
        with Session() as session:
            version = session.get(ComponentVersion, version_id)
            if version is None or version.deleted_at is not None:
                raise ValueError("component_repo.version_not_found")
            version.preview_status = PREVIEW_PENDING
            version.preview_failure_code = None
            version.preview_failure_params_json = None
            session.commit()
        try:
            with Session() as session:
                artifact = session.get(ComponentArtifact, artifact_id)
            if artifact is None:
                content = build_meshopt_glb(preview, config)
                storage_key = component_version_preview_storage_key(
                    config,
                    owner_id,
                    version_id,
                    generator_version,
                )
                content_type = config["storage"]["content_type_glb"]
                storage_uri = storage.write_bytes(storage_key, content, content_type)
                now = datetime.now(timezone.utc)
                artifact = ComponentArtifact(
                    id=artifact_id,
                    artifact_type=config["artifacts"]["component_preview_glb"],
                    original_filename=f"{version_id}.glb",
                    storage_provider=storage.provider,
                    storage_bucket=storage.bucket,
                    storage_key=storage_key,
                    storage_uri=storage_uri,
                    sha256=hashlib.sha256(content).hexdigest(),
                    file_size=len(content),
                    mime_type=content_type,
                    immutable=True,
                    uploaded_by=uploaded_by,
                    uploaded_at=now,
                    metadata_json={
                        "versionId": version_id,
                        "generatorVersion": generator_version,
                        "compression": "EXT_meshopt_compression",
                        "verification": {
                            "status": "verified",
                            "verifiedAt": now.isoformat(),
                        },
                    },
                )
                with Session() as session:
                    session.add(artifact)
                    session.commit()
            with Session() as session:
                version = session.get(ComponentVersion, version_id)
                if version is None or version.deleted_at is not None:
                    raise ValueError("component_repo.version_not_found")
                version.preview_artifact_id = artifact.id
                version.preview_status = PREVIEW_READY
                version.preview_generator_version = generator_version
                version.preview_failure_code = None
                version.preview_failure_params_json = None
                version.metadata_json = {
                    **(version.metadata_json or {}),
                    "preview": preview_summary(preview, artifact.id, generator_version),
                }
                session.commit()
            return version_preview_with_artifact(
                version_id,
                artifact,
                storage,
                config,
            )
        except Exception:
            with Session() as session:
                version = session.get(ComponentVersion, version_id)
                if version is not None and version.deleted_at is None:
                    version.preview_status = PREVIEW_FAILED
                    version.preview_failure_code = "component_repo.preview_unavailable"
                    version.preview_failure_params_json = {"versionId": version_id}
                    session.commit()
            raise


def preview_summary(
    preview: dict[str, Any],
    artifact_id: str,
    generator_version: str,
) -> dict[str, Any]:
    availability = {
        str(item["partRef"]): str(item["availability"])
        for item in preview.get("partCatalog", [])
    }
    return {
        "artifactId": artifact_id,
        "generatorVersion": generator_version,
        "partCount": int(preview.get("partCount", 0)),
        "renderablePartCount": int(preview.get("renderablePartCount", 0)),
        "logicalSize": preview.get("logicalSize") or {},
        "partAvailability": availability,
    }


def structured_preview_failure(version: ComponentVersion) -> dict[str, Any] | None:
    if not version.preview_failure_code:
        return None
    return {
        "code": version.preview_failure_code,
        "params": version.preview_failure_params_json or {},
    }


def mark_component_version_preview_failed(
    engine: Engine,
    version_id: str,
    code: str = "component_repo.preview_unavailable",
) -> None:
    """Persist a stable machine failure when preparation fails before GLB encoding."""
    Session = sessionmaker(bind=engine)
    with Session() as session:
        version = session.get(ComponentVersion, version_id)
        if version is None or version.deleted_at is not None:
            return
        version.preview_status = PREVIEW_FAILED
        version.preview_failure_code = code
        version.preview_failure_params_json = {"versionId": version_id}
        session.commit()


def component_version_preview_artifact_id(
    storage: ArtifactStorage,
    version_id: str,
    generator_version: str,
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            (
                "brickbuilder:component-version-preview:"
                f"{storage.provider}:{storage.bucket}:{version_id}:{generator_version}"
            ),
        )
    )


def component_version_preview_storage_key(
    config: dict[str, Any],
    owner_id: str,
    version_id: str,
    generator_version: str,
) -> str:
    return str(
        Path(owner_id)
        / config["storage"]["object_prefix"]
        / "previews"
        / "versions"
        / version_id
        / generator_version
        / f"{version_id}.glb"
    )


def version_preview_with_artifact(
    version_id: str,
    artifact: ComponentArtifact,
    storage: ArtifactStorage,
    config: dict[str, Any],
) -> dict[str, Any]:
    return {
        "versionId": version_id,
        "status": PREVIEW_READY,
        "model": preview_artifact_model(artifact, storage, config),
        "failure": None,
    }


def materialize_preview_model(
    engine: Engine,
    config: dict[str, Any],
    storage: ArtifactStorage,
    preview: dict[str, Any],
    *,
    owner_id: str,
    uploaded_by: str,
) -> dict[str, Any]:
    """Replace large JSON meshes with one cached, directly loadable GLB descriptor."""
    cache_key = preview_cache_key(preview, config)
    artifact_id = preview_artifact_id(storage, owner_id, cache_key)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with preview_build_lock(artifact_id):
        with Session() as session:
            artifact = session.get(ComponentArtifact, artifact_id)
        if artifact is None:
            content = build_meshopt_glb(preview, config)
            storage_key = preview_storage_key(config, owner_id, cache_key)
            content_type = config["storage"]["content_type_glb"]
            storage_uri = storage.write_bytes(storage_key, content, content_type)
            now = datetime.now(timezone.utc)
            artifact = ComponentArtifact(
                id=artifact_id,
                artifact_type=config["artifacts"]["component_preview_glb"],
                original_filename=f"{cache_key}.glb",
                storage_provider=storage.provider,
                storage_bucket=storage.bucket,
                storage_key=storage_key,
                storage_uri=storage_uri,
                sha256=hashlib.sha256(content).hexdigest(),
                file_size=len(content),
                mime_type=content_type,
                immutable=True,
                uploaded_by=uploaded_by,
                uploaded_at=now,
                metadata_json={
                    "cacheKey": cache_key,
                    "ownerId": owner_id,
                    "generatorVersion": config["preview"]["generator_version"],
                    "compression": "EXT_meshopt_compression",
                    "verification": {
                        "status": "verified",
                        "verifiedAt": now.isoformat(),
                    },
                },
            )
            with Session() as session:
                session.add(artifact)
                session.commit()
        return preview_with_artifact(preview, artifact, storage, config, cache_key)


def cached_preview_model(
    engine: Engine,
    config: dict[str, Any],
    storage: ArtifactStorage,
    preview: dict[str, Any],
    *,
    owner_id: str,
) -> dict[str, Any] | None:
    """Return an existing preview cache without creating storage or database state."""
    cache_key = preview_cache_key(preview, config)
    artifact_id = preview_artifact_id(storage, owner_id, cache_key)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        artifact = session.get(ComponentArtifact, artifact_id)
    if artifact is None:
        return None
    return preview_with_artifact(preview, artifact, storage, config, cache_key)


@contextmanager
def preview_build_lock(artifact_id: str):
    """Serialize duplicate materialization attempts without retaining lock entries."""
    with _preview_build_locks_guard:
        lock, user_count = _preview_build_locks.get(artifact_id, (Lock(), 0))
        _preview_build_locks[artifact_id] = (lock, user_count + 1)
    lock.acquire()
    try:
        yield
    finally:
        lock.release()
        with _preview_build_locks_guard:
            current_lock, current_user_count = _preview_build_locks[artifact_id]
            if current_user_count == 1:
                del _preview_build_locks[artifact_id]
            else:
                _preview_build_locks[artifact_id] = (
                    current_lock,
                    current_user_count - 1,
                )


def preview_cache_key(preview: dict[str, Any], config: dict[str, Any]) -> str:
    payload = {
        "generatorVersion": config["preview"]["generator_version"],
        "partLibraryVersion": config["part_library"]["default_version_id"],
        "parts": preview["parts"],
        "meshes": preview["meshes"],
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def preview_artifact_id(
    storage: ArtifactStorage,
    owner_id: str,
    cache_key: str,
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            (
                "brickbuilder:component-preview:"
                f"{storage.provider}:{storage.bucket}:{owner_id}:{cache_key}"
            ),
        )
    )


def preview_storage_key(
    config: dict[str, Any],
    owner_id: str,
    cache_key: str,
) -> str:
    return str(
        Path(owner_id)
        / config["storage"]["object_prefix"]
        / "previews"
        / cache_key[:2]
        / f"{cache_key}.glb"
    )


def preview_with_artifact(
    preview: dict[str, Any],
    artifact: ComponentArtifact,
    storage: ArtifactStorage,
    config: dict[str, Any],
    cache_key: str,
) -> dict[str, Any]:
    model = preview_artifact_model(artifact, storage, config)
    model["cacheKey"] = cache_key
    return {
        **{key: value for key, value in preview.items() if key != "meshes"},
        "model": model,
    }


def preview_artifact_model(
    artifact: ComponentArtifact,
    storage: ArtifactStorage,
    config: dict[str, Any],
) -> dict[str, Any]:
    model_url = storage.create_download_url(
        artifact.storage_key,
        int(config["preview"]["signed_url_ttl_seconds"]),
    )
    if model_url is None:
        model_url = config["routes"]["component_preview_model"].format(
            artifact_id=artifact.id
        )
    return {
        "artifactId": artifact.id,
        "format": "glb",
        "compression": "meshopt",
        "url": model_url,
        "sha256": artifact.sha256,
        "byteLength": artifact.file_size,
    }
