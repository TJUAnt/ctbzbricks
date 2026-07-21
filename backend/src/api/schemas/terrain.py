"""Terrain API schemas."""

from typing import Any

from pydantic import BaseModel

from src.api.schemas.task import StructuredMessageResponse, TaskContextRequest, TaskProgressResponse
from src.api.schemas.domain_content import ContentLocaleRequest


class TerrainJobRequest(TaskContextRequest):
    source_name: str
    geojson: dict[str, Any]
    dem_dataset_key: str


class TerrainSaveRequest(ContentLocaleRequest):
    name: str
    asset: dict[str, Any]


class TerrainJobResponse(BaseModel):
    jobId: str
    status: str
    progress: TaskProgressResponse
    sourceName: str
    asset: dict[str, Any] | None
    model: dict[str, Any] | None
    error: StructuredMessageResponse | None
    locale: str
    timezone: str
