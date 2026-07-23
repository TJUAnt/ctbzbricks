"""Schemas for official domain translations and i18n observability."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from src.i18n.domain_content import normalize_content_locale, validate_translation_status


class ContentLocaleRequest(BaseModel):
    contentLocale: str

    @field_validator("contentLocale")
    @classmethod
    def validate_content_locale(cls, value: str) -> str:
        return normalize_content_locale(value)


class TranslationContentRequest(BaseModel):
    name: str
    description: str | None = None
    translationStatus: str

    @field_validator("translationStatus")
    @classmethod
    def validate_status(cls, value: str) -> str:
        return validate_translation_status(value)


class ComponentTranslationRequest(TranslationContentRequest):
    tags: list[str] = []


class ComponentTranslationResponse(ComponentTranslationRequest):
    componentId: str
    locale: str
    reviewedBy: str | None
    reviewedAt: str | None
    updatedAt: str | None


class PartTranslationResponse(TranslationContentRequest):
    ldrawPartNum: str
    locale: str
    reviewedBy: str | None
    reviewedAt: str | None
    updatedAt: str | None


class TranslationFallbackMetric(BaseModel):
    entityType: str
    requestedLocale: str
    contentLocale: str
    count: int


class I18nEventRequest(BaseModel):
    kind: Literal["unknown_key", "unknown_api_code", "locale_fallback"]
    locale: str = Field(min_length=1, max_length=35)
    namespace: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=1, max_length=160)


class I18nEventMetric(I18nEventRequest):
    count: int


class I18nHourlyMetric(I18nEventMetric):
    hour: str


class TranslationMetricsResponse(BaseModel):
    missingOfficialTranslationCount: int
    fallbacks: list[TranslationFallbackMetric]
    unknownKeyCount: int
    unknownApiCodeCount: int
    localeFallbackCount: int
    metricOverflowCount: int
    events: list[I18nEventMetric]
    hourly: list[I18nHourlyMetric]
