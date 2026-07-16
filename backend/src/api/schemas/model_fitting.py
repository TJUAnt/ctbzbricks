"""Model fitting API schemas."""

from typing import Any

from pydantic import BaseModel, Field


class ModelFittingCreateJobRequest(BaseModel):
    modelId: str
    name: str | None = None
    scaleToLdu: float | None = None
    modelTypeHint: str | None = None
    semanticPreset: str | None = None
    targetWidthStud: float | None = None


class ModelFittingTargetBlockResponse(BaseModel):
    id: str
    jobId: str
    schema_: str = Field(alias="schema")
    blockType: str
    name: str
    bbox: dict[str, Any]
    profile: dict[str, Any]
    recallQuery: dict[str, Any]
    candidateSummary: dict[str, Any]
    createdAt: str
    updatedAt: str | None


class ModelFittingSolutionPlacementResponse(BaseModel):
    id: str
    targetBlockId: str
    candidateType: str
    candidateId: str
    colorCode: str | None
    position: dict[str, Any]
    orientation: dict[str, Any]
    bbox: dict[str, Any]
    score: float
    scoreReasons: list[str]
    locked: bool
    source: str
    createdAt: str
    updatedAt: str | None


class ModelFittingSolutionResponse(BaseModel):
    id: str
    jobId: str
    schema_: str = Field(alias="schema")
    status: str
    version: int
    metrics: dict[str, Any]
    bom: list[dict[str, Any]]
    ldrawContent: str
    placements: list[ModelFittingSolutionPlacementResponse]
    createdAt: str
    updatedAt: str | None


class ModelFittingJobResponse(BaseModel):
    id: str
    sourceModelId: str
    name: str
    schema_: str = Field(alias="schema")
    status: str
    settings: dict[str, Any]
    targetAnalysis: dict[str, Any]
    errorMessage: str | None
    createdAt: str
    updatedAt: str | None
    blocks: list[ModelFittingTargetBlockResponse]
    solutions: list[ModelFittingSolutionResponse]


class ModelFittingBlocksResponse(BaseModel):
    jobId: str
    blocks: list[ModelFittingTargetBlockResponse]
