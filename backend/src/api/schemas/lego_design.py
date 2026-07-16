"""LEGO design API schemas."""

from pydantic import BaseModel


class LegoDesignColorResponse(BaseModel):
    id: int
    name: str
    rgb: str
    isTrans: bool


class LegoDesignPartResponse(BaseModel):
    ldrawPartNum: str
    rebrickablePartNum: str | None
    legoDesignId: str | None
    name: str | None
    partRole: str
    width: int
    height: int
    logicalHeightPlate: int
    area: int


class LegoDesignMetadataResponse(BaseModel):
    colors: list[LegoDesignColorResponse]
    parts: list[LegoDesignPartResponse]
    terrainParts: list[LegoDesignPartResponse]


class LegoDesignCandidatePartsResponse(BaseModel):
    parts: list[LegoDesignPartResponse]


class LegoDesignJobRequest(BaseModel):
    projectId: str


class LegoPlacementResponse(BaseModel):
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
    yLdu: int | None = None
    moduleId: str | None = None
    moduleStage: str | None = None


class LegoColorMappingResponse(BaseModel):
    sourceRgb: str
    colorId: int
    colorName: str
    colorRgb: str
    ldrawColorCode: str


class LegoBomItemResponse(BaseModel):
    key: str
    partId: str
    rebrickablePartNum: str | None
    legoDesignId: str | None
    colorId: int
    colorName: str
    colorRgb: str
    ldrawColorCode: str
    width: int
    height: int
    quantity: int


class LegoTerrainModuleResponse(BaseModel):
    id: str
    moduleType: str
    originX: int
    originZ: int
    originYPlate: int
    width: int
    depth: int
    heightPlate: int
    wallThickness: int


class LegoModelDimensionsResponse(BaseModel):
    lengthStud: int
    widthStud: int
    heightPlate: int
    lengthCm: float
    widthCm: float
    heightCm: float


class LegoDesignResultResponse(BaseModel):
    width: int
    height: int
    placements: list[LegoPlacementResponse]
    bom: list[LegoBomItemResponse]
    colorMappings: list[LegoColorMappingResponse]
    modules: list[LegoTerrainModuleResponse] | None = None
    modelDimensions: LegoModelDimensionsResponse


class LegoDesignJobResponse(BaseModel):
    jobId: str
    status: str
    progress: int
    projectId: str
    result: LegoDesignResultResponse | None
    error: str | None
