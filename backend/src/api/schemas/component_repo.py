"""API schemas for Component Repo."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ComponentArtifactResponse(BaseModel):
    id: str
    artifactType: str
    originalFilename: str
    storageProvider: str
    storageBucket: str
    storageKey: str
    storageUri: str
    sha256: str
    fileSize: int
    mimeType: str
    immutable: bool
    uploadedBy: str
    uploadedAt: str
    metadata: dict[str, Any]


class ComponentImportResponse(BaseModel):
    id: str
    sourceArtifactId: str
    exchangeArtifactId: str | None
    targetComponentId: str | None
    baseVersionId: str | None
    status: str
    parserVersion: str | None
    partLibraryVersion: str | None
    createdBy: str
    createdAt: str
    completedAt: str | None
    failureReason: str | None
    metadata: dict[str, Any]


class ComponentSceneSnapshotResponse(BaseModel):
    id: str
    importId: str
    snapshotSchema: str
    parserVersion: str
    rootModelId: str | None
    document: dict[str, Any]
    bom: dict[str, int]
    parseIssues: list[dict[str, Any]]
    createdAt: str


class ComponentCandidateResponse(BaseModel):
    id: str
    importId: str
    sceneSnapshotId: str
    status: str
    summary: dict[str, Any]
    reviewDecisions: dict[str, Any]
    createdAt: str
    updatedAt: str | None


class ComponentImportCreateResponse(BaseModel):
    importJob: ComponentImportResponse
    sourceArtifact: ComponentArtifactResponse
    exchangeArtifact: ComponentArtifactResponse | None


class ComponentImportParseResponse(BaseModel):
    importJob: ComponentImportResponse
    sceneSnapshot: ComponentSceneSnapshotResponse
    candidate: ComponentCandidateResponse


class ComponentRelationCandidateResponse(BaseModel):
    id: str
    componentCandidateId: str
    partLibraryVersionId: str
    endpointA: dict[str, Any]
    endpointB: dict[str, Any]
    connectionType: str
    jointType: str
    positionResidual: float
    rotationResidual: float
    verifiedByTolerance: bool
    confidence: float
    status: str
    detectionMethod: str
    metadata: dict[str, Any]
    createdAt: str
    updatedAt: str | None


class ComponentAssemblyRelationResponse(BaseModel):
    id: str
    componentCandidateId: str
    relationCandidateId: str
    endpointA: dict[str, Any]
    endpointB: dict[str, Any]
    connectionType: str
    jointType: str
    placement: dict[str, Any]
    confirmedBy: str
    confirmedAt: str


class ComponentFreeConnectorResponse(BaseModel):
    worldConnectorId: str
    partInstanceId: str
    instancePath: list[str]
    partRef: str
    connectorId: str
    connectorType: str | None
    connectorGender: str | None
    connectorKind: str
    connectorGroup: str | None
    position: dict[str, float]
    axis: dict[str, float]
    matrix: list[float]
    directionLabel: str | None
    directionGroup: str | None
    metadata: dict[str, Any]


class ComponentInterfaceCreateRequest(BaseModel):
    worldConnectorId: str
    name: str
    exposure: str | None = None
    defaultBehavior: str | None = None
    mechanicalRoles: list[str] = []
    businessRoles: list[str] = []
    requirements: dict[str, Any] = {}


class ComponentInterfaceResponse(BaseModel):
    id: str
    componentCandidateId: str
    worldConnectorId: str
    name: str
    exposure: str
    defaultBehavior: str
    sourceConnector: dict[str, Any]
    mechanicalRoles: list[str]
    businessRoles: list[str]
    requirements: dict[str, Any]
    reviewStatus: str
    createdBy: str
    createdAt: str
    updatedAt: str | None


class ComponentValidationReportResponse(BaseModel):
    id: str
    componentCandidateId: str | None
    componentVersionId: str | None
    validationLevel: str
    passed: bool
    checks: list[dict[str, Any]]
    issues: list[dict[str, Any]]
    validatorVersion: str
    createdAt: str


class ComponentApproveRequest(BaseModel):
    name: str
    category: str | None = None
    componentId: str | None = None
    version: str = "0.1.0"
    revision: int = 1
    description: str | None = None
    tags: list[str] = []


class ComponentResponse(BaseModel):
    id: str
    name: str
    category: str | None
    status: str
    currentVersionId: str | None
    description: str | None
    tags: list[str]
    metadata: dict[str, Any]
    createdBy: str
    createdAt: str
    updatedAt: str | None


class ComponentVersionResponse(BaseModel):
    id: str
    componentId: str
    componentCandidateId: str
    version: str
    revision: int
    status: str
    sourceArtifactId: str
    exchangeArtifactId: str | None
    sceneSnapshotId: str
    parserVersion: str
    partLibraryVersionId: str | None
    validationReportId: str | None
    interfaceSignature: str
    structureHash: str
    geometryHash: str
    metadata: dict[str, Any]
    createdBy: str
    createdAt: str
    publishedAt: str | None


class ComponentApproveResponse(BaseModel):
    component: ComponentResponse
    version: ComponentVersionResponse
    validationReport: ComponentValidationReportResponse


class ComponentVersionPublishRequest(BaseModel):
    releaseNote: str | None = None
