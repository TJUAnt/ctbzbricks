"""Part search API schemas."""
from pydantic import BaseModel


class PartSearchRequest(BaseModel):
    query: str
    strict_bbox: bool
    include_substitutes: bool
    page: int = 1
    page_size: int = 24


class PartSearchCandidateResponse(BaseModel):
    ldrawPartNum: str
    name: str | None
    category: str | None
    relationType: str | None
    rebrickablePartNum: str | None
    score: float
    scoreReason: str
    connectorCounts: dict[str, int]
    logicalSize: list[float | None]
    bbox: list[float | None]
    imageUrl: str | None


class PartSearchResponse(BaseModel):
    query: str
    parsed: dict
    count: int
    candidates: list[PartSearchCandidateResponse]
