"""LEGO heightmap API schemas."""

from typing import Any

from pydantic import BaseModel, Field
from src.api.schemas.domain_content import ContentLocaleRequest


class LegoHeightmapSaveRequest(ContentLocaleRequest):
    name: str
    asset: dict[str, Any]


class LegoHeightmapScaleRequest(BaseModel):
    horizontalKmPerStud: float = Field(gt=0)
    verticalMetersPerPlate: float = Field(gt=0)
    aggregation: str
    minCoverageRatio: float = Field(ge=0, le=1)


class LegoHeightmapFromDemRequest(ContentLocaleRequest):
    name: str
    modelId: str
    scale: LegoHeightmapScaleRequest
