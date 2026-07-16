"""Fitting candidate recall API schemas."""

from typing import Any

from pydantic import BaseModel


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
    includeIrregular: bool | None = None
    limit: int | None = None


class FittingCandidateRecallCandidateResponse(BaseModel):
    candidateType: str
    candidateId: str
    profileStatus: str
    source: str
    score: float
    scoreReasons: list[str]
    bbox: dict[str, Any] | None
    logicalSize: dict[str, Any] | None
    appearanceTags: dict[str, Any] | None
    colorSummary: list[dict[str, Any]] | None
    connectorSummary: dict[str, Any] | None
    sourceMetadata: dict[str, Any] | None
    profileError: str | None
    profileErrorType: str | None


class FittingCandidateRecallResponse(BaseModel):
    total: int
    returned: int
    includeIrregular: bool
    candidates: list[FittingCandidateRecallCandidateResponse]
