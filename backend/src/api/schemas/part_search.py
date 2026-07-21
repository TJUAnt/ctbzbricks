"""Part search API schemas."""
from pydantic import BaseModel, field_validator

from src.i18n.domain_content import normalize_content_locale


class PartSearchRequest(BaseModel):
    query: str
    strict_bbox: bool
    include_substitutes: bool
    page: int = 1
    page_size: int = 24
    contentLocale: str

    @field_validator("contentLocale")
    @classmethod
    def validate_content_locale(cls, value: str) -> str:
        return normalize_content_locale(value)


class PartSearchCandidateResponse(BaseModel):
    ldrawPartNum: str
    name: str | None
    description: str | None
    contentLocale: str
    translationStatus: str
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
    requestedContentLocale: str
    parsed: dict
    count: int
    candidates: list[PartSearchCandidateResponse]
