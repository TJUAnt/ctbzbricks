"""Stable public API error response models."""

from typing import Any

from pydantic import BaseModel, Field


class ApiErrorDetail(BaseModel):
    """Machine-readable error details. Values are never translated by the API."""

    code: str
    params: dict[str, Any] = Field(default_factory=dict)
    traceId: str


class ApiErrorResponse(BaseModel):
    error: ApiErrorDetail

