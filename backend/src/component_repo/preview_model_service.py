"""Storage-backed GLB preview cache for Component Repo resources."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from src.component_repo.glb_service import build_meshopt_glb
from src.component_repo.storage import ArtifactStorage
from src.model.models import ComponentArtifact


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
    Session = sessionmaker(bind=engine)
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
            session.add(artifact)
            session.commit()
            session.refresh(artifact)
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
    model_url = storage.create_download_url(
        artifact.storage_key,
        int(config["preview"]["signed_url_ttl_seconds"]),
    )
    if model_url is None:
        model_url = config["routes"]["component_preview_model"].format(
            artifact_id=artifact.id
        )
    return {
        **{key: value for key, value in preview.items() if key != "meshes"},
        "model": {
            "artifactId": artifact.id,
            "format": "glb",
            "compression": "meshopt",
            "url": model_url,
            "sha256": artifact.sha256,
            "byteLength": artifact.file_size,
            "cacheKey": cache_key,
        },
    }
