"""API schemas for Component Repo."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.api.schemas.task import (
    StructuredCheckResponse,
    StructuredIssueResponse,
    StructuredMessageResponse,
)
from src.i18n.domain_content import normalize_content_locale


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
    verificationStatus: str


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


class ComponentUploadFileSpec(BaseModel):
    filename: str
    contentType: str | None = None
    fileSize: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class ComponentUploadSessionCreateRequest(BaseModel):
    sourceFile: ComponentUploadFileSpec
    exchangeFile: ComponentUploadFileSpec | None = None
    targetComponentId: str | None = None
    baseVersionId: str | None = None
    contentLocale: str
    timezone: str


class ComponentUploadTargetResponse(BaseModel):
    role: str
    artifactId: str
    artifactType: str
    originalFilename: str
    bucket: str
    objectPath: str
    contentType: str
    fileSize: int
    expectedSha256: str
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


class ComponentImportParseRequest(BaseModel):
    importId: str


class ComponentImportUploadCompleteResponse(BaseModel):
    importJob: ComponentImportResponse
    sourceArtifact: ComponentArtifactResponse
    exchangeArtifact: ComponentArtifactResponse | None


class ComponentImportParseResponse(BaseModel):
    importJob: ComponentImportResponse
    sourceArtifact: ComponentArtifactResponse
    exchangeArtifact: ComponentArtifactResponse | None
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


class ComponentConnectorResponse(ComponentFreeConnectorResponse):
    state: str
    occupiedByRelationIds: list[str]
    accessAxis: dict[str, float]
    externalInterfaceId: str | None
    recognition: dict[str, Any]


class ComponentConnectorSummaryResponse(BaseModel):
    worldConnectorId: str
    partInstanceId: str
    partRef: str
    connectorId: str
    connectorType: str | None
    connectorKind: str
    state: str
    position: dict[str, float]
    accessAxis: dict[str, float]
    externalInterfaceId: str | None


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
    recognitionMethod: str
    recognitionVersion: str
    interfaceGroupId: str


class ComponentConnectorAnalysisResponse(BaseModel):
    componentCandidateId: str
    partLibraryVersionId: str
    recognitionMethod: str
    recognitionVersion: str
    connectors: list[ComponentConnectorResponse]
    externalInterfaces: list[ComponentInterfaceResponse]


class ComponentConnectorSummaryAnalysisResponse(BaseModel):
    componentCandidateId: str
    partLibraryVersionId: str
    recognitionMethod: str
    recognitionVersion: str
    connectors: list[ComponentConnectorSummaryResponse]
    externalInterfaces: list[ComponentInterfaceResponse]


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


class ComponentLogicalSizeResponse(BaseModel):
    widthStud: float
    depthStud: float
    heightPlate: float


class ComponentResponse(BaseModel):
    id: str
    name: str
    contentKind: str
    contentLocale: str
    translationStatus: str
    category: str | None
    status: str
    currentVersionId: str | None
    logicalSize: ComponentLogicalSizeResponse | None
    description: str | None
    tags: list[str]
    metadata: dict[str, Any]
    createdBy: str
    createdAt: str
    updatedAt: str | None


class ComponentGroupResponse(BaseModel):
    id: str
    parentGroupId: str | None
    groupType: str
    name: str | None
    contentLocale: str | None
    sortOrder: int
    directComponentCount: int
    createdAt: str
    updatedAt: str


class ComponentGroupTreeResponse(BaseModel):
    root: ComponentGroupResponse
    groups: list[ComponentGroupResponse]


class ComponentGroupCreateRequest(BaseModel):
    parentGroupId: str
    name: str = Field(min_length=1, max_length=100)
    contentLocale: str


class ComponentGroupUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    contentLocale: str | None = None
    parentGroupId: str | None = None
    sortOrder: int | None = Field(default=None, ge=0)


class ComponentGroupMoveRequest(BaseModel):
    parentGroupId: str
    position: int = Field(ge=0)


class ComponentGroupMembershipsResponse(BaseModel):
    componentId: str
    groupIds: list[str]


class ComponentGroupSearchRequest(BaseModel):
    contentLocale: str
    query: str = Field(default="", max_length=200)
    statuses: list[str] | None = Field(default=None, max_length=20)
    allowPlanarRotation: bool = True
    sizeTolerance: float = Field(default=0, ge=0)
    page: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)

    @field_validator("contentLocale")
    @classmethod
    def validate_content_locale(cls, value: str) -> str:
        return normalize_content_locale(value)


class ComponentGroupSearchResponse(BaseModel):
    items: list[ComponentResponse]
    total: int
    page: int
    pageSize: int
    totalPages: int
    statusCounts: dict[str, int]


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


class ComponentPreviewInventoryPartResponse(BaseModel):
    """One assembly instance, including Parts excluded from preview calculations."""

    instanceId: str
    partRef: str
    colorCode: str
    availability: str = Field(
        description="Machine status: ready, missing_geometry, or missing_mesh."
    )


class ComponentPreviewSourceResponse(BaseModel):
    """Repository record from which the preview geometry was selected."""

    kind: str = Field(description="Source kind: component, part, or import.")
    id: str = Field(description="Stable Component UUID, LDraw Part number, or import ID.")
    name: str = Field(description="Localized official name or imported artifact filename.")
    status: str = Field(description="Machine-readable workflow status of the source record.")


class ComponentPreviewPartCatalogResponse(BaseModel):
    """Localized display metadata for one unique Part used by the assembly."""

    partRef: str
    name: str
    contentLocale: str | None
    translationStatus: str | None
    imageUrl: str | None
    availability: str = Field(
        description="Machine status: ready, missing_geometry, or missing_mesh."
    )


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


class ComponentPreviewModelResponse(BaseModel):
    """Immutable binary model cached in artifact storage."""

    artifactId: str
    format: str = Field(description="Binary model format; currently glb.")
    compression: str = Field(description="Geometry compression; currently meshopt.")
    url: str = Field(description="Direct signed URL or local API fallback URL.")
    sha256: str
    byteLength: int
    cacheKey: str


class ComponentVersionPreviewArtifactResponse(BaseModel):
    artifactId: str
    format: str
    compression: str
    url: str
    sha256: str
    byteLength: int


class ComponentVersionPreviewModelResponse(BaseModel):
    """Version-addressed GLB state without scene or mesh JSON."""

    versionId: str
    status: str
    model: ComponentVersionPreviewArtifactResponse | None
    failure: StructuredMessageResponse | None


class ComponentVersionPartSummaryResponse(BaseModel):
    partRef: str
    name: str
    contentLocale: str | None
    translationStatus: str | None
    imageUrl: str | None
    quantity: int
    availability: str


class ComponentVersionPartsResponse(BaseModel):
    versionId: str
    partCount: int
    renderablePartCount: int
    logicalSize: dict[str, float]
    parts: list[ComponentVersionPartSummaryResponse]


class ComponentPreviewResponse(BaseModel):
    """Render contract for a Component assembly or one standalone Part."""

    source: ComponentPreviewSourceResponse = Field(
        description="Repository record selected for this preview."
    )
    component: ComponentResponse | None = Field(
        description="Component metadata, or null for a standalone Part or unbound import."
    )
    versionId: str | None = Field(
        description="Component version ID, or null before an import becomes a version."
    )
    partCount: int = Field(description="Number of Part instances in the assembly.")
    renderablePartCount: int = Field(
        description="Number of Part instances included in geometry and GLB calculations."
    )
    logicalSize: dict[str, float] = Field(
        description="Item size in studs for width/depth and plates for height."
    )
    parts: list[ComponentPreviewPartResponse] = Field(
        description="Renderable assembly instances and their world transforms."
    )
    partInventory: list[ComponentPreviewInventoryPartResponse] = Field(
        description="All assembly instances with their preview availability status."
    )
    partCatalog: list[ComponentPreviewPartCatalogResponse] = Field(
        default_factory=list,
        description="Unique Part display metadata selected for the requested locale.",
    )
    model: ComponentPreviewModelResponse = Field(
        description="Cached meshopt-compressed GLB loaded directly by the renderer."
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
    previewArtifactId: str | None
    previewStatus: str
    previewGeneratorVersion: str | None
    previewFailure: StructuredMessageResponse | None
    metadata: dict[str, Any]
    createdBy: str
    createdAt: str
    publishedAt: str | None
    deletion: "ComponentVersionDeletionCapabilityResponse | None" = None


class ComponentVersionDeletionCapabilityResponse(BaseModel):
    allowed: bool
    reason: str | None = None


class ComponentVersionDeleteResponse(BaseModel):
    versionId: str
    componentId: str
    componentDeleted: bool
    nextVersionId: str | None


class ComponentVersionPublishRequest(BaseModel):
    releaseNote: str | None = None
    name: str | None = None
    category: str | None = None
    version: str | None = None
    contentLocale: str | None = None
