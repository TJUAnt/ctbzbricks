"""Terrain API schemas."""

from typing import Any

from pydantic import BaseModel


class TerrainJobRequest(BaseModel):
    source_name: str
    geojson: dict[str, Any]
    dem_dataset_key: str


class TerrainSaveRequest(BaseModel):
    name: str
    asset: dict[str, Any]
