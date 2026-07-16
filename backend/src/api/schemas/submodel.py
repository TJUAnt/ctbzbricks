"""Reusable LDraw submodel API schemas."""

from typing import Any

from pydantic import BaseModel


class SubmodelVector3(BaseModel):
    x: float
    y: float
    z: float


class SubmodelColorPercentage(BaseModel):
    colorCode: str
    percentage: float


class SubmodelConnectorInput(BaseModel):
    partLineNo: int
    connectorLabel: str
    connectorKind: str
    normalizedConnectorType: str
    connectorGender: str
    position: SubmodelVector3
    orientation: list[float]
    metadata: dict[str, Any]


class SubmodelPartResponse(BaseModel):
    lineNo: int
    colorCode: str
    ldrawPartNum: str
    position: SubmodelVector3
    orientation: list[float]


class SubmodelConnectorResponse(BaseModel):
    partLineNo: int
    connectorLabel: str
    connectorKind: str
    normalizedConnectorType: str
    connectorGender: str
    position: SubmodelVector3
    orientation: list[float]
    metadata: dict[str, Any]


class SubmodelCreateRequest(BaseModel):
    name: str
    ldrawContent: str
    colorPercentages: list[SubmodelColorPercentage]
    remarks: str
    connectionPoints: list[SubmodelConnectorInput]


class SubmodelResponse(BaseModel):
    id: str
    name: str
    ldrawContent: str
    colorPercentages: list[SubmodelColorPercentage]
    remarks: str
    parts: list[SubmodelPartResponse]
    connectionPoints: list[SubmodelConnectorResponse]
    createdAt: str
    updatedAt: str | None


class SubmodelListResponse(BaseModel):
    page: int
    pageSize: int
    total: int
    items: list[SubmodelResponse]
