import appConfig from '../app/appConfig';
import { ApiError, apiFetch } from '../api/client';
import type { StructuredMessage } from '../api/client';
import { authenticatedApiFetch, authenticatedRequestJson } from '../api/authenticatedClient';
import { supabase } from '../auth/supabaseClient';
import { currentTaskContext } from '../api/taskContext';
import { translate as tr } from '../i18n';

type ComponentRepoApiConfig = typeof appConfig.componentRepoApi;

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
  translationMissing?: boolean;
  createdAt: string;
  updatedAt: string | null;
  starredAt?: string;
};

export type ComponentStarResponse = {
  componentId: string;
  starredAt: string;
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

type AcceptedTask = { taskId: string; status: string };

type GoComponentVersionResponse = Omit<
  ComponentVersionResponse,
  'deletion' | 'previewFailure'
> & {
  previewFailureCode: string | null;
  previewFailureParams: Record<string, unknown>;
};

type GoComponentPreview = {
  versionId: string;
  status: ComponentVersionPreviewModelResponse['status'];
  generatorVersion: string | null;
  artifactId: string | null;
  sha256: string | null;
  fileSize: number | null;
  url: string | null;
  failure: StructuredMessage | null;
};

type GoComponentVersionParts = {
  versionId: string;
  partLibraryVersionId: string | null;
  partCount: number;
  items: Array<{
    ldrawPartNum: string;
    quantity: number;
    name: string | null;
    contentLocale: 'zh-CN' | 'en-US' | null;
    translationStatus: ComponentVersionPartSummary['translationStatus'];
    geometryStatus: ComponentVersionPartSummary['geometryStatus'];
  }>;
};

type GoConnector = Omit<
  ComponentConnectorResponse,
  'accessAxis' | 'connectorId' | 'connectorKind' | 'position'
> & {
  id: string;
  connectorKind: string | null;
  position: number[];
  axis: number[];
  matrix: number[];
  accessAxis: number[];
};

/** 读取公开目录和 actor 自有 Component 的稳定分页投影。 */
export async function listComponents(payload: {
  page: number;
  pageSize: number;
  query?: string;
  status?: string;
}): Promise<ComponentPageResponse> {
  const url = new URL(appConfig.componentRepoApi.components, window.location.origin);
  url.searchParams.set('locale', currentTaskContext().locale);
  url.searchParams.set('page', String(payload.page));
  url.searchParams.set('pageSize', String(payload.pageSize));
  if (payload.query) url.searchParams.set('query', payload.query);
  if (payload.status) url.searchParams.set('status', payload.status);
  return requestJson<ComponentPageResponse>(url.toString());
}

/** 读取当前用户仍公开可见的收藏，按收藏时间倒序稳定分页。 */
export async function listComponentStars(payload: {
  page: number;
  pageSize: number;
  query?: string;
  category?: string;
  sort?: 'starred_at_desc';
}): Promise<ComponentStarPageResponse> {
  const url = new URL(appConfig.componentRepoApi.componentStars, window.location.origin);
  url.searchParams.set('locale', currentTaskContext().locale);
  url.searchParams.set('page', String(payload.page));
  url.searchParams.set('pageSize', String(payload.pageSize));
  if (payload.query) url.searchParams.set('query', payload.query);
  if (payload.category) url.searchParams.set('category', payload.category);
  if (payload.sort) url.searchParams.set('sort', payload.sort);
  return requestJson<ComponentStarPageResponse>(url.toString());
}

/** 幂等收藏一个公开的非本人 Component。 */
export async function starComponent(componentId: string): Promise<ComponentStarResponse> {
  return requestJson<ComponentStarResponse>(pathFor('componentStar', { componentId }), {
    method: 'PUT',
  });
}

/** 幂等取消当前用户与 Component 的收藏关系。 */
export async function unstarComponent(componentId: string): Promise<void> {
  await requestVoid(pathFor('componentStar', { componentId }), { method: 'DELETE' });
}

export async function listComponentGroups(): Promise<ComponentGroupTreeResponse> {
  let response = await requestJson<{ items: ComponentGroupResponse[] }>(appConfig.componentRepoApi.componentGroups);
  if (!response.items.some((group) => group.groupType === 'root')) {
    await requestVoid(appConfig.componentRepoApi.componentGroupsBootstrap, { method: 'POST' });
    response = await requestJson<{ items: ComponentGroupResponse[] }>(appConfig.componentRepoApi.componentGroups);
  }
  const root = response.items.find((group) => group.groupType === 'root');
  if (!root) throw new ApiError('component_repo.group_not_found');
  return { root, groups: response.items.filter((group) => group.groupType === 'custom') };
}

export async function createComponentGroup(payload: {
  parentGroupId: string;
  name: string;
  contentLocale: string;
}): Promise<ComponentGroupResponse> {
  return requestJson<ComponentGroupResponse>(appConfig.componentRepoApi.componentGroups, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function updateComponentGroup(
  groupId: string,
  payload: {
    name?: string;
    contentLocale?: string;
    parentGroupId?: string;
    sortOrder?: number;
  },
): Promise<ComponentGroupResponse> {
  return requestJson<ComponentGroupResponse>(pathFor('componentGroup', { groupId }), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function moveComponentGroup(
  groupId: string,
  parentGroupId: string,
  position: number,
): Promise<ComponentGroupResponse> {
  return requestJson<ComponentGroupResponse>(pathFor('componentGroupMove', { groupId }), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ parentGroupId, sortOrder: position }),
  });
}

export async function deleteComponentGroup(groupId: string): Promise<void> {
  await requestVoid(pathFor('componentGroup', { groupId }), { method: 'DELETE' });
}

export async function listComponentGroupComponents(
  groupId: string,
): Promise<ComponentResponse[]> {
  const url = new URL(
    pathFor('componentGroupComponents', { groupId }),
    window.location.origin,
  );
  url.searchParams.set('locale', currentTaskContext().locale);
  url.searchParams.set('pageSize', '100');
  const response = await requestJson<{ items: ComponentResponse[] }>(url.toString());
  return response.items;
}

export async function searchComponentGroupComponents(
  groupId: string,
  payload: {
    queries: string[];
    statuses: string[] | null;
    page: number;
    pageSize: number;
  },
): Promise<ComponentGroupSearchResponse> {
  const url = new URL(pathFor('componentGroupComponentSearch', { groupId }), window.location.origin);
  url.searchParams.set('locale', currentTaskContext().locale);
  payload.queries.forEach((query) => url.searchParams.append('query', query));
  url.searchParams.set('page', String(payload.page));
  url.searchParams.set('pageSize', String(payload.pageSize));
  payload.statuses?.forEach((status) => url.searchParams.append('status', status));
  return requestJson<ComponentGroupSearchResponse>(url.toString());
}

export async function listComponentGroupIds(componentId: string): Promise<string[]> {
  const response = await requestJson<{ componentId: string; groupIds: string[] }>(
    pathFor('componentGroupsForComponent', { componentId }),
  );
  return response.groupIds;
}

export async function addComponentToGroup(
  groupId: string,
  componentId: string,
): Promise<void> {
  await requestVoid(
    pathFor('componentGroupComponents', { groupId }),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ componentId }),
    },
  );
}

export async function removeComponentFromGroup(
  groupId: string,
  componentId: string,
): Promise<void> {
  await requestVoid(
    pathFor('componentGroupComponent', { groupId, componentId }),
    { method: 'DELETE' },
  );
}

export async function getActivePartLibraryVersion(): Promise<PartLibraryVersionResponse> {
  return requestJson<PartLibraryVersionResponse>(appConfig.componentRepoApi.activePartLibraryVersion);
}

/** Load one immutable Part resource and materialize its GLB through the durable task system. */
export async function loadPartPreview(
  partLibraryVersionId: string,
  ldrawPartNum: string,
): Promise<ReadyPartPreviewResponse> {
  const previewPath = pathFor('partPreview', { partLibraryVersionId, ldrawPartNum });
  const previewUrl = new URL(previewPath, window.location.origin);
  previewUrl.searchParams.set('locale', currentTaskContext().locale);
  let preview = await requestJson<PartPreviewResponse>(previewUrl.toString());
  if (preview.status !== 'ready') {
    const context = currentTaskContext();
    const accepted = await requestJson<AcceptedTask>(
      pathFor('partPreviewMaterialize', { partLibraryVersionId, ldrawPartNum }),
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(context),
      },
    );
    await waitForTask(accepted.taskId);
    preview = await requestJson<PartPreviewResponse>(previewUrl.toString());
  }
  if (preview.status === 'failed' || !preview.model) {
    throw new ApiError(
      preview.failure?.code ?? 'component_repo.part_preview_unavailable',
      preview.failure?.params ?? { partLibraryVersionId, ldrawPartNum },
      null,
      409,
    );
  }
  if (!preview.geometry) {
    throw new ApiError(
      'component_repo.part_preview_unavailable',
      { partLibraryVersionId, ldrawPartNum },
      null,
      409,
    );
  }
  return preview as ReadyPartPreviewResponse;
}

export async function getComponent(componentId: string): Promise<ComponentResponse> {
  const url = new URL(pathFor('componentDetail', { componentId }), window.location.origin);
  url.searchParams.set('locale', currentTaskContext().locale);
  return requestJson<ComponentResponse>(url.toString());
}

export async function updateComponent(
  componentId: string,
  payload: {
    name?: string;
    category?: string | null;
    contentLocale?: string;
  },
): Promise<ComponentResponse> {
  return requestJson<ComponentResponse>(pathFor('componentDetail', { componentId }), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function deleteComponent(componentId: string): Promise<void> {
  await requestVoid(pathFor('componentDetail', { componentId }), { method: 'DELETE' });
}

export async function getComponentVersion(versionId: string): Promise<ComponentVersionResponse> {
  const version = await requestJson<GoComponentVersionResponse>(pathFor('componentVersion', { versionId }));
  return componentVersionFromGo(version);
}

/** 读取由 Go componentdiff 即时计算的只读结果；本调用不创建 Task 或派生 Artifact。 */
export async function loadComponentVersionDiff(versionId: string): Promise<ComponentVersionDiffResponse> {
  return requestJson<ComponentVersionDiffResponse>(pathFor('componentVersionDiff', { versionId }));
}

export async function updateComponentVersion(
  versionId: string,
  payload: { version?: string; revision?: number; releaseNote?: string | null; releaseNoteLocale?: string | null },
): Promise<ComponentVersionResponse> {
  const version = await requestJson<GoComponentVersionResponse>(pathFor('componentVersion', { versionId }), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return componentVersionFromGo(version);
}

export async function deleteComponentVersion(
  version: ComponentVersionResponse,
): Promise<void> {
  await requestVoid(pathFor('componentVersionDelete', { versionId: version.id }), { method: 'DELETE' });
}

/** 只读取 Worker 已生成并验证的 ComponentVersion GLB；首次生成不由前端触发。 */
export async function loadComponentVersionPreview(versionId: string): Promise<ComponentVersionPreviewModelResponse> {
  const preview = await requestJson<GoComponentPreview>(pathFor('componentVersionPreview', { versionId }));
  if (preview.status === 'failed') {
    throw new ApiError(
      preview.failure?.code ?? 'common.internal_error',
      preview.failure?.params ?? {},
      null,
      400,
    );
  }
  if (preview.status !== 'ready' || !preview.artifactId || !preview.url) {
    throw new ApiError('component_repo.preview_unavailable', { versionId }, null, 409);
  }
  return componentPreviewFromGo(preview);
}

export async function loadComponentVersionParts(versionId: string): Promise<ComponentVersionPartsResponse> {
  const url = new URL(pathFor('componentVersionParts', { versionId }), window.location.origin);
  url.searchParams.set('locale', currentTaskContext().locale);
  const response = await requestJson<GoComponentVersionParts>(url.toString());
  return {
    versionId: response.versionId,
    partLibraryVersionId: response.partLibraryVersionId,
    partCount: response.partCount,
    parts: response.items.map((item) => ({
      partRef: item.ldrawPartNum,
      quantity: item.quantity,
      name: item.name,
      contentLocale: item.contentLocale,
      translationStatus: item.translationStatus,
      geometryStatus: item.geometryStatus,
    })),
  };
}

export async function listComponentVersions(componentId: string, status?: string): Promise<ComponentVersionResponse[]> {
  const url = new URL(pathFor('componentVersions', { componentId }), window.location.origin);
  url.searchParams.set('pageSize', '100');
  const response = await requestJson<{ items: GoComponentVersionResponse[] }>(url.toString());
  const versions = response.items.map(componentVersionFromGo);
  return status ? versions.filter((version) => version.status === status) : versions;
}

export async function createComponentImportWithUploadSession(
  sourceFile: File,
  exchangeFile: File | null,
  target: ComponentImportTarget = {},
): Promise<ComponentImportUploadCompleteResponse> {
  return createComponentImportWithProgress(sourceFile, exchangeFile, undefined, target);
}

export async function createComponentImportWithProgress(
  sourceFile: File,
  exchangeFile: File | null,
  onProgress?: (progress: ComponentUploadProgress) => void,
  target: ComponentImportTarget = {},
): Promise<ComponentImportUploadCompleteResponse> {
  if (!supabase) {
    throw new ApiError('component_repo.missing_supabase_config');
  }
  onProgress?.({ percent: 4, message: tr('componentRepo:creatingASecureUploadChannel') });
  const uploadSession = await createComponentUploadSession(sourceFile, exchangeFile, target);
  onProgress?.({ percent: 12, message: tr('componentRepo:uploadChannelReadyUploadingFiles') });
  await uploadComponentSessionFiles(uploadSession, sourceFile, exchangeFile, onProgress);
  onProgress?.({ percent: 92, message: tr('componentRepo:filesUploadedVerifyingIntegrity') });
  const completion = await completeComponentUploadSession(uploadSession.id);
  // complete 返回 202 后上传交互立即结束；解析、BOM 和 GLB 由持久 Worker 异步推进。
  onProgress?.({ percent: 100, message: tr('componentRepo:uploadComplete') });
  return completion;
}

export async function createComponentUploadSession(
  sourceFile: File,
  exchangeFile: File | null,
  target: ComponentImportTarget = {},
): Promise<ComponentUploadSessionResponse> {
  const [sourceSpec, exchangeSpec] = await Promise.all([
    fileSpec(sourceFile),
    exchangeFile ? fileSpec(exchangeFile) : Promise.resolve(null),
  ]);
  return requestJson<ComponentUploadSessionResponse>(appConfig.componentRepoApi.componentImportUploadSession, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      sourceFile: sourceSpec,
      exchangeFile: exchangeSpec,
      targetComponentId: target.targetComponentId ?? null,
      baseVersionId: target.baseVersionId ?? null,
      contentLocale: currentTaskContext().locale,
      timezone: currentTaskContext().timezone,
    }),
  });
}

export async function uploadComponentSessionFiles(
  uploadSession: ComponentUploadSessionResponse,
  sourceFile: File,
  exchangeFile: File | null,
  onProgress?: (progress: ComponentUploadProgress) => void,
): Promise<void> {
  if (!supabase) {
    throw new ApiError('component_repo.missing_supabase_config');
  }
  const fileByRole = new Map<string, File>([['source', sourceFile]]);
  if (exchangeFile) {
    fileByRole.set('exchange', exchangeFile);
  }
  for (const [index, upload] of uploadSession.uploads.entries()) {
    const file = fileByRole.get(upload.role);
    if (!file) {
      throw new ApiError('request.validation_failed', { field: upload.role });
    }
    const { error } = await supabase.storage.from(upload.bucket).upload(upload.objectPath, file, {
      contentType: upload.contentType,
      upsert: false,
    });
    if (error) {
      throw new ApiError('component_repo.storage_unavailable');
    }
    const percent = 12 + Math.round(((index + 1) / uploadSession.uploads.length) * 74);
    onProgress?.({
      percent,
      message: tr(upload.role === 'source' ? 'componentRepo:componentSourceUploaded' : 'componentRepo:exchangeFileUploaded'),
    });
  }
}

export async function completeComponentUploadSession(uploadSessionId: string): Promise<ComponentImportUploadCompleteResponse> {
  return requestJson<ComponentImportUploadCompleteResponse>(
    pathFor('componentImportUploadComplete', { uploadSessionId }),
    {
      method: 'POST',
    },
  );
}

export async function getComponentImport(importId: string): Promise<ComponentImportResponse> {
  return requestJson<ComponentImportResponse>(
    pathFor('componentImport', { importId }),
  );
}

/** 读取持久化导入历史；该请求只观察 API/Worker 已提交的状态，不触发后台处理。 */
export async function listComponentImports(options: {
  page: number;
  pageSize: number;
  processingStatus?: ComponentImportRecordResponse['processingStatus'] | null;
  query?: string;
  componentId?: string | null;
}): Promise<ComponentImportHistoryResponse> {
  const url = new URL(appConfig.componentRepoApi.componentImports, window.location.origin);
  url.searchParams.set('page', String(options.page));
  url.searchParams.set('pageSize', String(options.pageSize));
  if (options.processingStatus) url.searchParams.set('processingStatus', options.processingStatus);
  if (options.query) url.searchParams.set('query', options.query);
  if (options.componentId) url.searchParams.set('componentId', options.componentId);
  return requestJson<ComponentImportHistoryResponse>(url.toString());
}

const taskPollIntervalMs = 1_000;
const taskPollTimeoutMs = 10 * 60 * 1_000;

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

export async function getCandidate(candidateId: string): Promise<ComponentCandidateResponse> {
  return requestJson<ComponentCandidateResponse>(pathFor('candidateDetail', { candidateId }));
}

export async function listRelations(candidateId: string): Promise<ComponentRelationCandidateResponse[]> {
  const response = await requestJson<{ items: ComponentRelationCandidateResponse[] }>(
    pathFor('candidateRelations', { candidateId }),
  );
  return response.items;
}

export async function detectRelations(candidateId: string): Promise<ComponentRelationCandidateResponse[]> {
  const accepted = await requestJson<AcceptedTask>(pathFor('candidateRelationsDetect', { candidateId }), {
    method: 'POST',
  });
  await waitForTask(accepted.taskId);
  return listRelations(candidateId);
}

export async function confirmRelation(
  candidateId: string,
  relationId: string,
): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>(pathFor('candidateRelationConfirm', { candidateId, relationId }), {
    method: 'POST',
  });
}

export async function rejectRelation(
  candidateId: string,
  relationId: string,
): Promise<ComponentRelationCandidateResponse> {
  return requestJson<ComponentRelationCandidateResponse>(pathFor('candidateRelationReject', { candidateId, relationId }), {
    method: 'POST',
  });
}

export async function getConnectorAnalysis(candidateId: string): Promise<ComponentConnectorAnalysisResponse> {
  const [connectors, externalInterfaces] = await Promise.all([
    listConnectors(candidateId),
    listInterfaces(candidateId),
  ]);
  return { componentCandidateId: candidateId, connectors, externalInterfaces };
}

export async function listInterfaces(candidateId: string): Promise<ComponentInterfaceResponse[]> {
  const response = await requestJson<{ items: ComponentInterfaceResponse[] }>(
    pathFor('candidateInterfaces', { candidateId }),
  );
  return response.items;
}

export async function validateCandidate(candidateId: string): Promise<ComponentValidationReportResponse> {
  const accepted = await requestJson<AcceptedTask>(pathFor('candidateValidate', { candidateId }), {
    method: 'POST',
  });
  const task = await waitForTask(accepted.taskId);
  const reportId = String(task.result.validationReportId ?? '');
  if (!reportId) throw new ApiError('common.invalid_response');
  return getValidationReport(reportId);
}

// 读取持久化验证报告；可见性由 Go Backend 按 Draft/Published Version 边界判定。
export async function getValidationReport(reportId: string): Promise<ComponentValidationReportResponse> {
  return requestJson<ComponentValidationReportResponse>(pathFor('validationReport', { reportId }));
}

export async function publishVersion(
  versionId: string,
): Promise<ComponentVersionResponse> {
  const version = await requestJson<GoComponentVersionResponse>(pathFor('componentVersionPublish', { versionId }), {
    method: 'POST',
  });
  return componentVersionFromGo(version);
}

export function componentVersionSourceUrl(versionId: string): string {
  return pathFor('componentVersionSource', { versionId });
}

export async function downloadComponentVersionSource(versionId: string): Promise<void> {
  const download = await requestJson<{ artifactId: string; url: string; expiresAt: string }>(
    componentVersionSourceUrl(versionId),
  );
  const response = await apiFetch(download.url);
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = responseFilename(response) ?? `${versionId}.io`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}

async function listConnectors(candidateId: string): Promise<ComponentConnectorResponse[]> {
  const response = await requestJson<{ items: GoConnector[] }>(
    pathFor('candidateConnectors', { candidateId }),
  );
  return response.items.map((connector) => ({
    ...connector,
    connectorId: connector.id,
    connectorKind: connector.connectorKind ?? '',
    position: vectorFromGo(connector.position),
    accessAxis: vectorFromGo(connector.accessAxis),
  }));
}

function componentVersionFromGo(version: GoComponentVersionResponse): ComponentVersionResponse {
  const { previewFailureCode, previewFailureParams, ...rest } = version;
  return {
    ...rest,
    previewFailure: previewFailureCode
      ? { code: previewFailureCode, params: previewFailureParams ?? {} }
      : null,
    deletion: {
      allowed: version.status === 'draft',
      reason: null,
    },
  };
}

function componentPreviewFromGo(preview: GoComponentPreview): ComponentVersionPreviewModelResponse {
  const model = preview.status === 'ready'
    && preview.artifactId
    && preview.sha256
    && preview.fileSize !== null
    && preview.url
    ? {
        artifactId: preview.artifactId,
        format: 'glb' as const,
        url: preview.url,
        sha256: preview.sha256,
        byteLength: preview.fileSize,
      }
    : null;
  return {
    versionId: preview.versionId,
    status: preview.status,
    model,
    failure: preview.failure,
  };
}

function vectorFromGo(value: number[]): Record<string, number> {
  return { x: value[0] ?? 0, y: value[1] ?? 0, z: value[2] ?? 0 };
}

export async function getTask(taskId: string): Promise<ComponentTaskResponse> {
  return requestJson<ComponentTaskResponse>(pathFor('taskDetail', { taskId }));
}

export async function waitForTask(taskId: string): Promise<ComponentTaskResponse> {
  const deadline = Date.now() + taskPollTimeoutMs;
  while (Date.now() < deadline) {
    const task = await getTask(taskId);
    if (task.status === 'succeeded') return task;
    if (task.status === 'failed') {
      throw new ApiError(task.error?.code ?? 'common.internal_error', task.error?.params ?? {}, null, 400);
    }
    if (task.status === 'cancelled') {
      throw new ApiError('request.failed', {}, null, 409);
    }
    await delay(taskPollIntervalMs);
  }
  throw new ApiError('request.failed', { taskId }, null, 408);
}

function pathFor(key: keyof ComponentRepoApiConfig, params: Record<string, string>): string {
  let path = appConfig.componentRepoApi[key];
  Object.entries(params).forEach(([paramKey, value]) => {
    path = path.replace(`{${paramKey}}`, encodeURIComponent(value));
  });
  return path;
}

async function fileSpec(file: File): Promise<{
  filename: string;
  contentType: string | null;
  fileSize: number;
  sha256: string;
}> {
  return {
    filename: file.name,
    contentType: file.type || null,
    fileSize: file.size,
    sha256: await fileSha256(file),
  };
}

async function fileSha256(file: File): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

function responseFilename(response: Response): string | null {
  const disposition = response.headers.get('Content-Disposition');
  if (!disposition) {
    return null;
  }
  const match = disposition.match(/filename="?([^";]+)"?/i);
  return match?.[1] ?? null;
}

async function requestJson<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  return authenticatedRequestJson<T>(input, init);
}

async function requestVoid(input: RequestInfo | URL, init?: RequestInit): Promise<void> {
  await authenticatedApiFetch(input, init);
}
