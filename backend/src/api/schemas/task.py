"""Shared request and response schemas for locale-stable tasks."""

from typing import Any

from pydantic import BaseModel, field_validator

from src.i18n.messages import normalize_task_locale, normalize_timezone


class TaskContextRequest(BaseModel):
    locale: str
    timezone: str

    @field_validator("locale")
    @classmethod
    def validate_locale(cls, value: str) -> str:
        return normalize_task_locale(value)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return normalize_timezone(value)


class ExportContextResponse(BaseModel):
    locale: str
    timezone: str
    catalogVersion: str

    @field_validator("locale")
    @classmethod
    def validate_locale(cls, value: str) -> str:
        return normalize_task_locale(value)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return normalize_timezone(value)


class StructuredMessageResponse(BaseModel):
    code: str
    params: dict[str, Any]


class StructuredIssueResponse(StructuredMessageResponse):
    severity: str
    path: list[str | int]


class StructuredCheckResponse(StructuredMessageResponse):
    status: str
    path: list[str | int]


class TaskProgressResponse(StructuredMessageResponse):
    percent: int
