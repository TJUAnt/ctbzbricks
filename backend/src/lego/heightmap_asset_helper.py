"""Persist LEGO heightmap assets."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def save_heightmap_asset(config: dict[str, Any], asset: dict[str, Any], model_name: str) -> dict[str, Any]:
    model_id = uuid4().hex[: int(config["model_id_hex_length"])]
    created_at = datetime.now(timezone.utc).isoformat()
    saved_asset = {
        **asset,
        "modelId": model_id,
        "createdAt": created_at,
        "name": model_name,
    }
    metadata = heightmap_metadata(model_id, created_at, saved_asset)
    heightmap_asset_path(config, model_id).write_text(
        json.dumps(saved_asset, ensure_ascii=False, separators=(",", ":")),
        encoding=config["text_encoding"],
    )
    return metadata


def load_heightmap_asset(config: dict[str, Any], model_id: str) -> dict[str, Any]:
    path = heightmap_asset_path(config, model_id)
    if not path.exists():
        raise ValueError("LEGO heightmap model not found")
    return json.loads(path.read_text(encoding=config["text_encoding"]))


def heightmap_asset_path(config: dict[str, Any], model_id: str) -> Path:
    store_path = Path(config["model_store_path"])
    store_path.mkdir(parents=True, exist_ok=True)
    return store_path / f"{model_id}{config['model_file_extension']}"


def heightmap_metadata(model_id: str, created_at: str, asset: dict[str, Any]) -> dict[str, Any]:
    metrics = asset["metrics"]
    return {
        "modelId": model_id,
        "name": asset["name"],
        "source": asset["source"],
        "createdAt": created_at,
        "columns": metrics["widthStud"],
        "rows": metrics["depthStud"],
        "maxHeightPlate": metrics["maxHeightPlate"],
        "validCellCount": metrics["validCellCount"],
        "totalCellCount": metrics["totalCellCount"],
    }
