import type { StructuredMessage } from '../api/client';

export type ComponentResponse = {
  id: string;
  ownerId?: string | null;
  name: string;
  contentKind: 'official' | 'user';
  contentLocale: 'zh-CN' | 'en-US';
  translationStatus?: 'source' | 'draft' | 'reviewed' | 'rejected' | 'fallback';
  category: string | null;
  status: string;
  currentVersionId: string | null;
  logicalSize?: {
    widthStud: number;
    depthStud: number;
    heightPlate: number;
  } | null;
  ownedByActor?: boolean;
  description: string | null;
  tags: string[];
  metadata: Record<string, unknown>;
  createdBy?: string;
  starredByActor: boolean;
  starCount: number;
  watch?: {
    watching: boolean;
    level: 'releases_only' | null;
    watchedAt: string | null;
  };
  translationMissing?: boolean;
  createdAt: string;
  updatedAt: string | null;
  starredAt?: string;
};

export type ComponentStarResponse = {
  componentId: string;
  starredAt: string;
};

export type ComponentWatchResponse = {
  componentId: string;
  watching: true;
  level: 'releases_only';
  watchedAt: string;
};

export type ComponentWatchListItemResponse = {
  componentId: string;
  contentKind: 'official' | 'user';
  contentLocale: 'zh-CN' | 'en-US';
  name: string;
  category: string | null;
  currentVersionId: string | null;
  version: string | null;
  revision: number | null;
  publishedAt: string | null;
  level: 'releases_only';
  watchedAt: string;
  translationMissing: boolean;
};

export type ComponentWatchPageResponse = {
  items: ComponentWatchListItemResponse[];
  nextCursor: string | null;
};

/** ComponentWatchFeedItemResponse 是当前 active Watch 动态聚合出的单条发布更新投影。 */
export type ComponentWatchFeedItemResponse = {
  eventId: string;
  eventType: 'component.version.published.v1';
  occurredAt: string;
  componentId: string;
  contentKind: 'official' | 'user';
  contentLocale: 'zh-CN' | 'en-US';
  componentName: string;
  category: string | null;
  componentVersionId: string;
  version: string;
  revision: number;
  publishedAt: string | null;
  releaseNote: string | null;
  releaseNoteLocale: 'zh-CN' | 'en-US' | null;
  translationMissing: boolean;
};

/** ComponentWatchFeedPageResponse 使用冻结时间窗口和不透明 keyset cursor 继续读取。 */
export type ComponentWatchFeedPageResponse = {
  items: ComponentWatchFeedItemResponse[];
  nextCursor: string | null;
  windowStart: string;
};

export type StarredComponentResponse = ComponentResponse & {
  starredAt: string;
};

export type ComponentStarPageResponse = {
  items: StarredComponentResponse[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
  relationshipTotal: number;
};

export type ComponentPageResponse = {
  items: ComponentResponse[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
};

/** ComponentPublicFeedItemResponse 保留发布事件身份，并提供当前 Component 与发布版本投影。 */
export type ComponentPublicFeedItemResponse = {
  eventId: string;
  occurredAt: string;
  componentVersionId: string;
  version: string;
  revision: number;
  publishedAt: string | null;
  releaseNote: string | null;
  releaseNoteLocale: 'zh-CN' | 'en-US' | null;
  publisher: {
    id: string;
  };
  render: {
    status: 'ready' | 'fallback';
    availableAt: string;
    image: {
      artifactId: string;
      url: string;
      format: 'png';
      sha256: string;
      byteLength: number;
      width: number;
      height: number;
    } | null;
  };
  component: ComponentResponse;
};

/** ComponentPublicFeedPageResponse 使用不透明游标继续公共发布事件流。 */
export type ComponentPublicFeedPageResponse = {
  items: ComponentPublicFeedItemResponse[];
  nextCursor: string | null;
};

export type ComponentGroupResponse = {
  id: string;
  parentGroupId: string | null;
  groupType: 'root' | 'custom';
  name: string | null;
  contentLocale: 'zh-CN' | 'en-US' | null;
  sortOrder: number;
  directComponentCount: number;
  createdAt: string;
  updatedAt: string;
};

export type ComponentGroupTreeResponse = {
  root: ComponentGroupResponse;
  groups: ComponentGroupResponse[];
};

export type ComponentGroupSearchResponse = {
  items: ComponentResponse[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
  statusCounts: Record<string, number>;
};

/** 分组成员编辑器的一页候选；候选来自自有、收藏和现有成员三个服务端分页集合。 */
export type ComponentGroupMembershipCandidatePage = {
  items: ComponentResponse[];
  page: number;
  hasMore: boolean;
};

/** One Component assembly instance; all transform values use LDraw coordinates. */
export type ComponentPreviewPart = {
  instanceId: string;
  partRef: string;
  colorCode: string;
  transform: {
    position: { x: number; y: number; z: number };
    matrix: number[];
  };
  bbox: {
    minX: number;
    minY: number;
    minZ: number;
    maxX: number;
    maxY: number;
    maxZ: number;
  };
};

export type ComponentPreviewPartAvailability =
  | 'ready'
  | 'missing_geometry'
  | 'missing_mesh';

export type ComponentPreviewInventoryPart = {
  instanceId: string;
  partRef: string;
  colorCode: string;
  availability: ComponentPreviewPartAvailability;
};

export type ComponentPreviewPartCatalog = {
  partRef: string;
  name: string;
  contentLocale: 'zh-CN' | 'en-US' | null;
  translationStatus: 'source' | 'draft' | 'reviewed' | 'rejected' | 'fallback' | 'missing' | null;
  imageUrl: string | null;
  availability: ComponentPreviewPartAvailability;
};

export type ComponentPreviewResponse = {
  source: {
    kind: 'component' | 'part' | 'import';
    id: string;
    name: string;
    status: string;
  };
  component: ComponentResponse | null;
  versionId: string | null;
  partCount: number;
  renderablePartCount: number;
  logicalSize: {
    widthStud: number;
    depthStud: number;
    heightPlate: number;
  };
  parts: ComponentPreviewPart[];
  partInventory: ComponentPreviewInventoryPart[];
  partCatalog: ComponentPreviewPartCatalog[];
  model: {
    artifactId: string;
    format: 'glb';
    compression?: 'meshopt';
    url: string;
    sha256: string;
    byteLength: number;
    cacheKey?: string;
  };
};

export type ComponentVersionPreviewModelResponse = {
  versionId: string;
  status: 'pending' | 'ready' | 'failed' | 'stale';
  model: ComponentPreviewResponse['model'] | null;
  failure: StructuredMessage | null;
};

/** Component Version Diff 对外稳定的实例变化枚举；值是机器数据，不参与本地化。 */
export type ComponentVersionDiffChangeKind =
  | 'part_added'
  | 'part_removed'
  | 'transform_changed'
  | 'color_changed'
  | 'part_replaced';

/** Diff 实例状态使用 LDraw 世界坐标；前端渲染时必须复用 Component GLB 根坐标转换。 */
export type ComponentVersionDiffPartState = {
  instanceId: string;
  partRef: string;
  colorCode: string;
  worldMatrix: number[];
};

/** Go componentdiff 的只读响应契约，包含完整统计和可能截断的实例明细。 */
export type ComponentVersionDiffResponse = {
  versionId: string;
  baseVersionId: string | null;
  comparisonBasis: 'empty' | 'import_base_version';
  algorithmVersion: string;
  structureHash: string;
  geometryHash: string;
  baseStructureHash: string | null;
  baseGeometryHash: string | null;
  summary: {
    beforeInstances: number;
    afterInstances: number;
    unchangedInstances: number;
    addedInstances: number;
    removedInstances: number;
    transformChangedInstances: number;
    colorChangedInstances: number;
    replacedInstances: number;
    ambiguousBeforeInstances: number;
    ambiguousAfterInstances: number;
    ambiguousGroups: number;
    bomChangedPartTypes: number;
  };
  bomChanges: Array<{
    partRef: string;
    beforeQuantity: number;
    afterQuantity: number;
    delta: number;
  }>;
  instanceChanges: Array<{
    kind: ComponentVersionDiffChangeKind;
    before?: ComponentVersionDiffPartState;
    after?: ComponentVersionDiffPartState;
    transformDelta?: {
      translationChanged: boolean;
      linearTransformChanged: boolean;
    };
  }>;
  ambiguousGroups: Array<{
    partRef: string;
    colorCode: string;
    beforeInstanceIds: string[];
    afterInstanceIds: string[];
  }>;
  truncated: boolean;
};

export type ComponentVersionPartSummary = {
  partRef: string;
  name: string | null;
  contentLocale: 'zh-CN' | 'en-US' | null;
  translationStatus: 'source' | 'draft' | 'reviewed' | 'rejected' | 'fallback' | null;
  geometryStatus: 'ready' | 'failed' | 'missing';
  quantity: number;
};

export type ComponentVersionPartsResponse = {
  versionId: string;
  partLibraryVersionId: string | null;
  partCount: number;
  parts: ComponentVersionPartSummary[];
};

export type PartLibraryVersionResponse = {
  id: string;
  sourceName: string;
  sourceHash: string;
  status: 'active';
  createdAt: string;
};

export type PartPreviewResponse = {
  partLibraryVersionId: string;
  ldrawPartNum: string;
  name: string;
  contentLocale: 'zh-CN' | 'en-US';
  translationStatus: 'reviewed' | 'fallback';
  status: 'pending' | 'running' | 'ready' | 'failed';
  generatorVersion: string | null;
  taskId: string | null;
  geometry: {
    bbox: { minX: number; minY: number; minZ: number; maxX: number; maxY: number; maxZ: number };
    logicalWidthStud: number | null;
    logicalDepthStud: number | null;
    logicalHeightPlate: number | null;
    logicalSizeDerivationStatus: 'legacy_imported' | 'derived_exact' | 'derived_approximate' | 'not_applicable' | 'failed';
    vertexCount: number;
    faceCount: number;
  } | null;
  model: ComponentPreviewResponse['model'] | null;
  failure: StructuredMessage | null;
};

export type ReadyPartPreviewResponse = PartPreviewResponse & {
  status: 'ready';
  geometry: NonNullable<PartPreviewResponse['geometry']>;
  model: NonNullable<PartPreviewResponse['model']>;
};

export type ComponentVersionResponse = {
  id: string;
  componentId: string;
  componentCandidateId: string | null;
  version: string;
  revision: number;
  status: string;
  sourceArtifactId: string;
  exchangeArtifactId: string | null;
  sceneSnapshotId: string;
  parserVersion: string;
  partLibraryVersionId: string | null;
  validationReportId: string | null;
  interfaceSignature: string;
  structureHash: string;
  geometryHash: string;
  previewArtifactId: string | null;
  previewStatus: 'pending' | 'ready' | 'failed' | 'stale';
  previewGeneratorVersion: string | null;
  previewFailure: StructuredMessage | null;
  releaseNote: string | null;
  releaseNoteLocale: string | null;
  metadata: Record<string, unknown>;
  createdBy?: string;
  createdAt: string;
  publishedAt: string | null;
  deletion?: {
    allowed: boolean;
    reason: 'current' | 'forbidden' | null;
  } | null;
};

export type ComponentImportResponse = {
  id: string;
  sourceArtifactId: string;
  exchangeArtifactId: string | null;
  targetComponentId: string | null;
  baseVersionId: string | null;
  status: string;
  parserVersion: string | null;
  partLibraryVersionId: string | null;
  taskId: string;
  candidateId: string | null;
  draftVersionId: string | null;
  processingStatus: 'processing' | 'ready' | 'failed';
  previewTaskId: string | null;
  locale: string;
  timezone: string;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
  failure: StructuredMessage | null;
  metadata: Record<string, unknown>;
};

export type ComponentImportRecordResponse = {
  id: string;
  sourceArtifactId: string;
  originalFilename: string;
  fileSize: number;
  mimeType: string;
  importKind: 'create' | 'update';
  targetComponentId: string | null;
  componentId: string | null;
  baseVersionId: string | null;
  status: string;
  processingStatus: 'processing' | 'ready' | 'failed';
  parserVersion: string;
  partLibraryVersionId: string | null;
  taskId: string;
  candidateId: string | null;
  draftVersionId: string | null;
  previewTaskId: string | null;
  failure: StructuredMessage | null;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
};

export type ComponentImportHistoryResponse = {
  items: ComponentImportRecordResponse[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
  statusCounts: Record<ComponentImportRecordResponse['processingStatus'], number>;
};

export type ComponentUploadProgress = {
  percent: number;
  message: string;
};

export type ComponentCandidateResponse = {
  id: string;
  importId: string;
  status: string;
  summary: Record<string, unknown>;
  reviewDecisions: Record<string, unknown>;
  interfaceSignature: string;
  structureHash: string;
  geometryHash: string;
  componentId: string | null;
  draftVersionId: string | null;
  sceneSnapshot: {
    id: string;
    schemaVersion: string;
    parserVersion: string;
    rootModelId: string | null;
    document: Record<string, unknown>;
    bom: Record<string, number>;
    parseIssues: StructuredIssue[];
    createdAt: string;
  };
  createdAt: string;
  updatedAt: string | null;
};

export type ComponentUploadTargetResponse = {
  role: string;
  artifactId: string;
  artifactType: string;
  originalFilename: string;
  bucket: string;
  objectPath: string;
  contentType: string;
  fileSize: number;
  expectedSha256: string;
  uploadSessionId: string;
};

export type ComponentUploadSessionResponse = {
  id: string;
  ownerId: string;
  status: string;
  bucket: string;
  uploads: ComponentUploadTargetResponse[];
  createdBy: string;
  createdAt: string;
  completedAt: string | null;
  failure: StructuredMessage | null;
  metadata: Record<string, unknown>;
};

export type ComponentImportUploadCompleteResponse = {
  importId: string;
  taskId: string;
  status: string;
};

export type ComponentTaskResponse = {
  id: string;
  taskJobId: string;
  executionNumber: number;
  taskType: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
  result: Record<string, unknown>;
  resultArtifactId: string | null;
  locale: string;
  timezone: string;
  attempts: number;
  maxAttempts: number;
  progress: StructuredMessage & { percent: number | null } | null;
  error: StructuredMessage | null;
  cancelRequestedAt: string | null;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  updatedAt: string;
};

export type StructuredIssue = StructuredMessage & {
  severity: string;
  path: Array<string | number>;
};

export type StructuredCheck = StructuredMessage & {
  status: string;
  path: Array<string | number>;
};

export type ComponentRelationCandidateResponse = {
  id: string;
  componentCandidateId: string;
  partLibraryVersionId: string;
  endpointA: Record<string, unknown>;
  endpointB: Record<string, unknown>;
  connectionType: string;
  jointType: string;
  positionResidual: number;
  rotationResidual: number;
  verifiedByTolerance: boolean;
  confidence: number;
  status: string;
  detectionMethod: string;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string | null;
};

export type ComponentConnectorResponse = {
  worldConnectorId: string;
  partInstanceId: string;
  partRef: string;
  connectorId: string;
  connectorType: string | null;
  connectorKind: string;
  connectorGender: string | null;
  state: 'internal' | 'external' | 'blocked' | 'unsupported' | 'unresolved';
  position: Record<string, number>;
  accessAxis: Record<string, number>;
  externalInterfaceId: string | null;
  capacity: number;
  occupiedSlots: number;
  availableCapacity: number;
  eligibility: Record<string, unknown>;
};

export type ComponentInterfaceResponse = {
  id: string;
  componentCandidateId: string;
  worldConnectorId: string;
  name: string;
  exposure: string;
  defaultBehavior: string;
  sourceConnector: Record<string, unknown>;
  mechanicalRoles: string[];
  businessRoles: string[];
  requirements: Record<string, unknown>;
  reviewStatus: string;
  createdAt: string;
  updatedAt: string | null;
};

export type ComponentConnectorAnalysisResponse = {
  componentCandidateId: string;
  connectors: ComponentConnectorResponse[];
  externalInterfaces: ComponentInterfaceResponse[];
};

export type ComponentValidationReportResponse = {
  id: string;
  componentCandidateId: string | null;
  componentVersionId: string | null;
  validationLevel?: string;
  passed: boolean;
  checks: StructuredCheck[];
  issues: StructuredIssue[];
  validatorVersion?: string;
  createdAt: string | null;
};

export type ComponentImportTarget = {
  targetComponentId?: string | null;
  baseVersionId?: string | null;
};
