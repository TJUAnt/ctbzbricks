"""API schemas for Component Repo."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.api.schemas.task import (
    StructuredCheckResponse,
    StructuredIssueResponse,
    StructuredMessageResponse,
)


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
    failure: StructuredMessageResponse | None
    metadata: dict[str, Any]
    sourceFilename: str | None = None
    sourceFileSize: int | None = None


class ComponentSceneSnapshotResponse(BaseModel):
    id: str
    importId: str
    snapshotSchema: str
    parserVersion: str
    rootModelId: str | None
    document: dict[str, Any]
    bom: dict[str, int]
    parseIssues: list[StructuredIssueResponse]
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


class ComponentUploadFileSpec(BaseModel):
    filename: str
    contentType: str | None = None
    fileSize: int | None = None


class ComponentUploadSessionCreateRequest(BaseModel):
    sourceFile: ComponentUploadFileSpec
    exchangeFile: ComponentUploadFileSpec | None = None
    targetComponentId: str | None = None
    baseVersionId: str | None = None
    contentLocale: str


class ComponentUploadTargetResponse(BaseModel):
    role: str
    artifactId: str
    artifactType: str
    originalFilename: str
    bucket: str
    objectPath: str
    contentType: str
    uploadSessionId: str


class ComponentUploadSessionResponse(BaseModel):
    id: str
    ownerId: str
    status: str
    bucket: str
    uploads: list[ComponentUploadTargetResponse]
    createdBy: str
    createdAt: str
    completedAt: str | None
    failure: StructuredMessageResponse | None
    metadata: dict[str, Any]


class ComponentImportParseResponse(BaseModel):
    importJob: ComponentImportResponse
    sceneSnapshot: ComponentSceneSnapshotResponse
    candidate: ComponentCandidateResponse
    component: "ComponentResponse"
    version: "ComponentVersionResponse"


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
    checks: list[StructuredCheckResponse]
    issues: list[StructuredIssueResponse]
    validatorVersion: str
    createdAt: str


class ComponentResponse(BaseModel):
    id: str
    name: str
    contentKind: str
    contentLocale: str
    translationStatus: str
    category: str | None
    status: str
    currentVersionId: str | None
    description: str | None
    tags: list[str]
    metadata: dict[str, Any]
    createdBy: str
    createdAt: str
    updatedAt: str | None


class ComponentPreviewPartResponse(BaseModel):
    """One Part instance placed by the Component assembly snapshot."""

    instanceId: str = Field(description="Stable ID of this assembly instance.")
    partRef: str = Field(description="Normalized LDraw Part filename, such as 3001.dat.")
    colorCode: str = Field(description="LDraw color code stored by the assembly instance.")
    transform: dict[str, Any] = Field(
        description=(
            "World transform in LDraw coordinates: position in LDU plus a row-major "
            "3 by 3 orientation matrix."
        )
    )
    bbox: dict[str, float] = Field(
        description=(
            "Local Part bounds in LDU, used for logical-size calculations and diagnostics; "
            "the bounds are not the rendered shape."
        )
    )


class ComponentPreviewSourceResponse(BaseModel):
    """Repository record from which the preview assembly was selected."""

    kind: str = Field(description="Source kind: component or import.")
    id: str = Field(description="Stable Component Repo source ID.")
    name: str = Field(description="Localized Component name or imported artifact filename.")
    status: str = Field(description="Machine-readable workflow status of the source record.")


class ComponentPreviewMeshResponse(BaseModel):
    """Indexed local-space triangle mesh shared by all instances of one Part."""

    partRef: str = Field(description="Part reference matched by assembly instances.")
    positions: list[float] = Field(
        description="Flat xyz vertex coordinates in LDU, grouped by three values."
    )
    indices: list[int] = Field(
        description="Zero-based vertex indices grouped by three values per triangle."
    )
    triangleCount: int = Field(description="Number of triangles represented by indices.")


class ComponentPreviewResponse(BaseModel):
    """Render contract combining Component placement data with reusable Part geometry."""

    source: ComponentPreviewSourceResponse = Field(
        description="Repository record selected for this preview."
    )
    component: ComponentResponse | None = Field(
        description="Component metadata, or null when previewing an unbound import."
    )
    versionId: str | None = Field(
        description="Component version ID, or null before an import becomes a version."
    )
    partCount: int = Field(description="Number of Part instances in the assembly.")
    logicalSize: dict[str, float] = Field(
        description="Overall assembly size in studs for width/depth and plates for height."
    )
    parts: list[ComponentPreviewPartResponse] = Field(
        description="Assembly instances and their world transforms."
    )
    meshes: list[ComponentPreviewMeshResponse] = Field(
        description="One reusable local-space mesh for each unique partRef."
    )


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


class ComponentVersionPublishRequest(BaseModel):
    releaseNote: str | None = None
    name: str | None = None
    category: str | None = None
    version: str | None = None
    contentLocale: str | None = None
