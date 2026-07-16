"""Pixel art API schemas."""

from typing import Any

from pydantic import BaseModel, Field


class PixelArtCropConfig(BaseModel):
    x: int
    y: int
    width: int
    height: int


class PixelArtPreprocessingConfig(BaseModel):
    brightness: float
    contrast: float
    saturation: float
    sharpness: float
    localContrast: float
    preserveLightDetails: bool


class PixelArtGenerateSettings(BaseModel):
    algorithm: str
    gridWidth: int
    gridHeight: int
    colorCount: int
    crop: PixelArtCropConfig
    preprocessing: PixelArtPreprocessingConfig


class PixelArtProjectResponse(BaseModel):
    modelId: str
    name: str
    source: str
    createdAt: str
    assetSchema: str = Field(alias="schema")
    gridWidth: int
    gridHeight: int
    colorCount: int
    palette: list[dict[str, Any]]
    pixels: list[dict[str, Any]]
    previewImage: str


class PixelArtPixelsUpdateRequest(BaseModel):
    palette: list[dict[str, Any]]
    pixels: list[dict[str, Any]]


class PixelArtProjectSummary(BaseModel):
    modelId: str
    name: str
    source: str
    createdAt: str
    gridWidth: int
    gridHeight: int
    colorCount: int
    previewImage: str


class PixelArtProjectListResponse(BaseModel):
    page: int
    pageSize: int
    total: int
    items: list[PixelArtProjectSummary]
