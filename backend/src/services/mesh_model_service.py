"""Direct GLB mesh model import service."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from src.mesh.glb_color import extract_glb_material_color_summary
from src.model.models import ModelAsset
from src.services.model_asset_service import model_asset_response


def save_uploaded_mesh_model(
    engine: Engine,
    config: dict[str, Any],
    name: str,
    source_name: str,
    content_type: str,
    file_bytes: bytes,
    content_locale: str,
) -> dict[str, Any]:
    validate_upload(config, source_name, content_type, file_bytes)
    model_id = uuid4().hex[: int(config["storage"]["model_id_hex_length"])]
    asset_path = mesh_model_path(config, model_id)
    asset_path.write_bytes(file_bytes)
    color_summary = extract_glb_material_color_summary(config, file_bytes)
    created_at = datetime.now(timezone.utc)
    model_asset = ModelAsset(
        id=model_id,
        name=name,
        content_locale=content_locale,
        model_type=config["model_asset"]["model_type"],
        source_type=config["model_asset"]["source_type"],
        source_name=source_name,
        asset_path=str(asset_path),
        preview_path=None,
        status=config["model_asset"]["complete_status"],
        columns=None,
        rows=None,
        min_elevation=None,
        max_elevation=None,
        valid_sample_count=None,
        metadata_json={
            config["metadata_keys"]["file_size_bytes"]: len(file_bytes),
            config["metadata_keys"]["content_type"]: content_type,
            config["metadata_keys"]["original_extension"]: Path(source_name).suffix.lower(),
            config["metadata_keys"]["color_summary"]: color_summary,
        },
        created_at=created_at,
    )
    Session = sessionmaker(bind=engine)
    with Session() as session:
        persisted_model_asset = session.merge(model_asset)
        session.commit()
        return model_asset_response(persisted_model_asset)


def validate_upload(
    config: dict[str, Any],
    source_name: str,
    content_type: str,
    file_bytes: bytes,
) -> None:
    if Path(source_name).suffix.lower() not in config["upload"]["allowed_extensions"]:
        raise ValueError(config["errors"]["unsupported_extension"])
    if content_type not in config["upload"]["allowed_content_types"]:
        raise ValueError(config["errors"]["unsupported_content_type"])
    if len(file_bytes) > int(config["upload"]["max_file_size_bytes"]):
        raise ValueError(config["errors"]["file_too_large"])


def mesh_model_path(config: dict[str, Any], model_id: str) -> Path:
    store_path = Path(config["storage"]["model_store_path"])
    store_path.mkdir(parents=True, exist_ok=True)
    return store_path / f"{model_id}{config['storage']['model_file_extension']}"


def mesh_model_file_path(engine: Engine, config: dict[str, Any], model_id: str) -> Path | None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        model_asset = session.get(ModelAsset, model_id)
        if model_asset is None:
            return None
        if model_asset.model_type != config["model_asset"]["model_type"]:
            return None
        return Path(model_asset.asset_path)
