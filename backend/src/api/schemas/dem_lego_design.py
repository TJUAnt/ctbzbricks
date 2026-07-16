"""Schemas for the independent DEM LEGO design API."""

from typing import Any

from pydantic import BaseModel, StrictInt


class DemBaseHStructureRequest(BaseModel):
    baseH: list[list[StrictInt]]


class DemBaseHPlacementResponse(BaseModel):
    partId: str
    rebrickablePartNum: str | None
    legoDesignId: str | None
    role: str
    colorId: int
    colorName: str
    colorRgb: str
    ldrawColorCode: str
    x: int
    z: int
    basePlate: int
    width: int
    depth: int
    heightPlate: int
    rotation: int


class DemBaseHBomItemResponse(BaseModel):
    partId: str
    rebrickablePartNum: str | None
    legoDesignId: str | None
    role: str
    colorId: int
    colorName: str
    colorRgb: str
    width: int
    depth: int
    heightPlate: int
    quantity: int


class DemBaseHValidationResponse(BaseModel):
    targetVolumeStudPlate: int
    placedVolumeStudPlate: int
    unsupportedPlacementCount: int


class DemBaseHStructureResponse(BaseModel):
    strategy: str
    widthStud: int
    depthStud: int
    baseH: list[list[int]]
    placements: list[DemBaseHPlacementResponse]
    bom: list[DemBaseHBomItemResponse]
    validation: DemBaseHValidationResponse


class DemPartSurfaceProfileResponse(BaseModel):
    partId: str
    ldrawOriginToBaseLdu: float
    ldrawCenterXLdu: float
    ldrawCenterZLdu: float
    widthStud: int
    depthStud: int
    samplesPerStudAxis: int
    surfaceHeightPlate: list[list[float | None]]
    collisionIntervalsPlate: list[list[list[tuple[float, float]]]]
    bottomContact: list[list[bool]]
    topConnectMask: list[list[bool]]


class DemSurfacePatchCandidatesRequest(BaseModel):
    targetSurfacePlate: list[list[float]]
    targetColorId: list[list[StrictInt]]
    partIds: list[str]


class DemSurfacePlanRequest(DemSurfacePatchCandidatesRequest):
    targetHeightPlate: list[list[StrictInt]]


class DemFinalDesignModelRequest(BaseModel):
    modelId: str
    strategy: str
    horizontalKmPerStud: float
    verticalMetersPerPlate: float
    aggregation: str
    minCoverageRatio: float


class DemSurfacePatchCandidateResponse(BaseModel):
    partId: str
    ldrawOriginToBaseLdu: float
    ldrawCenterXLdu: float
    ldrawCenterZLdu: float
    xStud: int
    zStud: int
    widthStud: int
    depthStud: int
    rotationDegrees: int
    basePlate: int
    colorId: int
    targetColorId: int
    colorDistance: int
    usesNearestColor: bool
    usesApproximateGeometry: bool
    coveredCells: list[tuple[int, int]]
    requiredSupportCells: list[tuple[int, int]]
    baseHeightCells: list[tuple[int, int, int]]
    topConnectCells: list[tuple[int, int]]
    topConnectionClass: str
    slopeEdges: list[tuple[int, int, int, int, str]]
    slopeDirections: list[str]
    matchedSlopeDirectionCount: int
    surfaceHeightPlate: list[list[float | None]]
    collisionIntervalsPlate: list[list[list[tuple[float, float]]]]
    maximumAbsoluteErrorPlate: float
    totalAbsoluteErrorPlate: float
    rootMeanSquareErrorPlate: float


class DemSurfacePatchCandidatesResponse(BaseModel):
    widthStud: int
    depthStud: int
    samplesPerStudAxis: int
    candidates: list[DemSurfacePatchCandidateResponse]


class DemSurfacePlanValidationResponse(BaseModel):
    targetSlopeEdgeCount: int
    solvedSlopeEdgeCount: int
    unresolvedSlopeEdgeCount: int
    coveredCellCount: int
    overlapCellCount: int
    unsupportedPlacementCount: int
    baseHCollisionSampleCount: int
    topConnectedPlacementCount: int
    topFinishedPlacementCount: int


class DemSurfaceReplacementPhaseResponse(BaseModel):
    connectionClass: str
    placements: list[DemSurfacePatchCandidateResponse]
    baseH: list[list[int]]
    solvedSlopeEdgeCount: int
    unresolvedSlopeEdgeCount: int


class DemSurfacePlanResponse(BaseModel):
    strategy: str
    widthStud: int
    depthStud: int
    samplesPerStudAxis: int
    candidateCount: int
    placements: list[DemSurfacePatchCandidateResponse]
    replacementPhases: list[DemSurfaceReplacementPhaseResponse]
    baseH: list[list[int]]
    maximumAbsoluteErrorPlate: float
    totalAbsoluteErrorPlate: float
    seamErrorPlate: float
    partCount: int
    validation: DemSurfacePlanValidationResponse


class DemFinalSurfacePlacementResponse(DemSurfacePatchCandidateResponse):
    role: str
    rebrickablePartNum: str | None
    legoDesignId: str | None
    colorName: str
    colorRgb: str
    ldrawColorCode: str
    heightPlate: float


class DemSupportBasePlacementResponse(BaseModel):
    partId: str
    rebrickablePartNum: str | None
    legoDesignId: str | None
    colorId: int
    colorName: str
    colorRgb: str
    ldrawColorCode: str
    x: int
    y: int
    width: int
    height: int
    logicalHeightPlate: int
    rotation: int
    yLdu: int


class DemFinalBomItemResponse(BaseModel):
    partId: str
    rebrickablePartNum: str | None
    legoDesignId: str | None
    role: str
    colorId: int
    colorName: str
    colorRgb: str
    ldrawColorCode: str
    widthStud: int
    depthStud: int
    heightPlate: float
    quantity: int


class DemFinalStepPlacementRefResponse(BaseModel):
    kind: str
    index: int


class DemFinalStepResponse(BaseModel):
    id: str
    name: str
    order: int
    stage: str
    basePlate: int
    placementRefs: list[DemFinalStepPlacementRefResponse]


class DemFinalValidationResponse(BaseModel):
    rejectedBaseHCount: int
    inventoryColorMappingCount: int
    approximateGeometryPlacementCount: int
    excludedColorCandidateCount: int
    totalPlacementCount: int
    stepPlacementCount: int
    surfaceCollisionSampleCount: int
    surfaceUnsupportedPlacementCount: int
    structureUnsupportedPlacementCount: int
    targetVolumeStudPlate: int
    placedVolumeStudPlate: int
    verticalContinuity: list["DemVerticalContinuityResponse"]


class DemVerticalContinuityGapResponse(BaseModel):
    xLdu: float
    zLdu: float
    lowerLdu: float
    upperLdu: float


class DemVerticalContinuityResponse(BaseModel):
    connectionClass: str
    checkedColumnCount: int
    occupiedColumnCount: int
    discontinuousColumnCount: int
    gapCount: int
    maximumGapLdu: float
    gapExamples: list[DemVerticalContinuityGapResponse]


class DemFinalDesignResponse(BaseModel):
    strategy: str
    surfacePlan: DemSurfacePlanResponse
    supportBase: dict[str, list[DemSupportBasePlacementResponse]]
    baseStructure: DemBaseHStructureResponse
    surfacePlacements: list[DemFinalSurfacePlacementResponse]
    bom: list[DemFinalBomItemResponse]
    steps: list[DemFinalStepResponse]
    validation: DemFinalValidationResponse
    replacementDiagnostics: dict[str, Any] | None
