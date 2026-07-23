"""Fitting candidate recall API schemas."""

from typing import Any

from pydantic import BaseModel, Field

from src.api.schemas.task import StructuredMessageResponse


class FittingCandidateRecallBBoxRequest(BaseModel):
    widthLdu: float | None = None
    heightLdu: float | None = None
    depthLdu: float | None = None
    toleranceLdu: float | None = None


class FittingCandidateRecallLogicalSizeRequest(BaseModel):
    widthStud: float | None = None
    depthStud: float | None = None
    heightPlate: float | None = None
    tolerance: float | None = None


class FittingCandidateRecallConnectorRequest(BaseModel):
    connectorType: str
    connectorGender: str | None = None
    minCount: int | None = None


class FittingCandidateRecallRequest(BaseModel):
    candidateTypes: list[str] | None = None
    profileStatuses: list[str] | None = None
    bbox: FittingCandidateRecallBBoxRequest | None = None
    logicalSize: FittingCandidateRecallLogicalSizeRequest | None = None
    connectors: list[FittingCandidateRecallConnectorRequest] | None = None
    categories: list[str] | None = None
    colorCodes: list[str] | None = None
    key: str | None = None
    allowPlanarRotation: bool = True
    includeIrregular: bool | None = None
    page: int = Field(default=1, ge=1)
    pageSize: int | None = Field(default=None, ge=1)
    limit: int | None = None


class FittingCandidateRecallCandidateResponse(BaseModel):
    candidateType: str
    candidateId: str
    profileStatus: str
    source: str
    score: float
    scoreReasons: list[str]
    name: str | None = None
    description: str | None = None
    contentLocale: str = "en-US"
    translationStatus: str = "source"
    matchedName: str | None = None
    keyScore: float | None = None
    imageUrl: str | None = None
    bbox: dict[str, Any] | None
    logicalSize: dict[str, Any] | None
    appearanceTags: dict[str, Any] | None
    colorSummary: list[dict[str, Any]] | None
    connectorSummary: dict[str, Any] | None
    sourceMetadata: dict[str, Any] | None
    profileError: StructuredMessageResponse | None
    profileErrorType: str | None


class FittingCandidateRecallResponse(BaseModel):
    total: int
    returned: int
    page: int
    pageSize: int
    totalPages: int
    includeIrregular: bool
    candidates: list[FittingCandidateRecallCandidateResponse]
