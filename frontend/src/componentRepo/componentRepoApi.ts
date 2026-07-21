import appConfig from '../app/appConfig';
import {
  ApiError,
  apiErrorFromPayload,
  apiFetch,
  requestJson as apiRequestJson,
} from '../api/client';
import type { StructuredMessage } from '../api/client';
import { currentAccessToken, supabase } from '../auth/supabaseClient';
import { currentTaskContext } from '../api/taskContext';
import { translate as tr } from '../i18n';

type ComponentRepoApiConfig = typeof appConfig.componentRepoApi;

export type ComponentResponse = {
  id: string;
  name: string;
  contentKind: 'official' | 'user';
  contentLocale: 'zh-CN' | 'en-US';
  translationStatus: 'source' | 'draft' | 'reviewed' | 'rejected' | 'fallback';
  category: string | null;
  status: string;
  currentVersionId: string | null;
  description: string | null;
  tags: string[];
  metadata: Record<string, unknown>;
  createdBy: string;
  createdAt: string;
  updatedAt: string | null;
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

/** Indexed local-space Part geometry shared by every instance with the same partRef. */
export type ComponentPreviewMesh = {
  partRef: string;
  /** Flat xyz vertex coordinates in LDraw units (LDU). */
  positions: number[];
  /** Zero-based vertex indices, with each consecutive three defining a triangle. */
  indices: number[];
  triangleCount: number;
};

/**
 * Render contract: `parts` defines how the Component is assembled and `meshes`
 * supplies one reusable surface mesh for each unique Part reference.
 */
export type ComponentPreviewResponse = {
  source: {
    kind: 'component' | 'import';
    id: string;
    name: string;
    status: string;
  };
  component: ComponentResponse | null;
  versionId: string | null;
  partCount: number;
  logicalSize: {
    widthStud: number;
    depthStud: number;
    heightPlate: number;
  };
  parts: ComponentPreviewPart[];
  meshes: ComponentPreviewMesh[];
};

export type ComponentVersionResponse = {
  id: string;
  componentId: string;
  componentCandidateId: string;
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
  metadata: Record<string, unknown>;
  createdBy: string;
  createdAt: string;
  publishedAt: string | null;
};

export type ComponentArtifactResponse = {
  id: string;
  artifactType: string;
  originalFilename: string;
  storageProvider: string;
  storageBucket: string;
  storageKey: string;
  storageUri: string;
  sha256: string;
  fileSize: number;
  mimeType: string;
  immutable: boolean;
  uploadedBy: string;
  uploadedAt: string;
  metadata: Record<string, unknown>;
};

export type ComponentImportResponse = {
  id: string;
  sourceArtifactId: string;
  exchangeArtifactId: string | null;
  targetComponentId: string | null;
  baseVersionId: string | null;
  status: string;
  parserVersion: string | null;
  partLibraryVersion: string | null;
  createdBy: string;
  createdAt: string;
  completedAt: string | null;
  failure: StructuredMessage | null;
  metadata: Record<string, unknown>;
  sourceFilename?: string | null;
  sourceFileSize?: number | null;
};

export type ComponentUploadProgress = {
  percent: number;
  message: string;
};

export type ComponentCandidateResponse = {
  id: string;
  importId: string;
  sceneSnapshotId: string;
  status: string;
  summary: Record<string, unknown>;
  reviewDecisions: Record<string, unknown>;
  createdAt: string;
  updatedAt: string | null;
};

export type ComponentImportCreateResponse = {
  importJob: ComponentImportResponse;
  sourceArtifact: ComponentArtifactResponse;
  exchangeArtifact: ComponentArtifactResponse | null;
};

export type ComponentUploadTargetResponse = {
  role: string;
  artifactId: string;
  artifactType: string;
  originalFilename: string;
  bucket: string;
  objectPath: string;
  contentType: string;
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

export type ComponentImportParseResponse = {
  importJob: ComponentImportResponse;
  sceneSnapshot: {
    id: string;
    importId: string;
    snapshotSchema: string;
    parserVersion: string;
    rootModelId: string | null;
    document: Record<string, unknown>;
    bom: Record<string, number>;
    parseIssues: StructuredIssue[];
    createdAt: string;
  };
  candidate: ComponentCandidateResponse;
  component: ComponentResponse;
  version: ComponentVersionResponse;
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

export type ComponentFreeConnectorResponse = {
  worldConnectorId: string;
  partInstanceId: string;
  instancePath: string[];
  partRef: string;
  connectorId: string;
  connectorType: string | null;
  connectorGender: string | null;
  connectorKind: string;
  connectorGroup: string | null;
  position: Record<string, number>;
  axis: Record<string, number>;
  matrix: number[];
  directionLabel: string | null;
  directionGroup: string | null;
  metadata: Record<string, unknown>;
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
  createdBy: string;
  createdAt: string;
  updatedAt: string | null;
};

export type ComponentValidationReportResponse = {
  id: string;
  componentCandidateId: string | null;
  componentVersionId: string | null;
  validationLevel: string;
  passed: boolean;
  checks: StructuredCheck[];
  issues: StructuredIssue[];
  validatorVersion: string;
  createdAt: string;
};

export type ComponentImportTarget = {
  targetComponentId?: string | null;
  baseVersionId?: string | null;
};

export async function listComponents(status?: string): Promise<ComponentResponse[]> {
  const url = new URL(appConfig.componentRepoApi.components, window.location.origin);
  url.searchParams.set('contentLocale', currentTaskContext().locale);
  if (status) {
    url.searchParams.set('status', status);
  }
  return requestJson<ComponentResponse[]>(url.toString());
}

/** Load the first renderable repository item; locale affects domain content, not geometry. */
export async function loadFirstComponentPreview(): Promise<ComponentPreviewResponse> {
  const url = new URL(appConfig.componentRepoApi.componentPreviewFirst, window.location.origin);
  url.searchParams.set('contentLocale', currentTaskContext().locale);
  return requestJson<ComponentPreviewResponse>(url.toString());
}

export async function listComponentImports(): Promise<ComponentImportResponse[]> {
  return requestJson<ComponentImportResponse[]>(appConfig.componentRepoApi.componentImports);
}

export async function getComponent(componentId: string): Promise<ComponentResponse> {
  const url = new URL(pathFor('componentDetail', { componentId }), window.location.origin);
  url.searchParams.set('contentLocale', currentTaskContext().locale);
  return requestJson<ComponentResponse>(url.toString());
}

export async function getComponentVersion(versionId: string): Promise<ComponentVersionResponse> {
  return requestJson<ComponentVersionResponse>(pathFor('componentVersion', { versionId }));
}

/** Load one explicit ComponentVersion using the same real Part mesh contract as the viewer. */
export async function loadComponentVersionPreview(versionId: string): Promise<ComponentPreviewResponse> {
  const url = new URL(pathFor('componentVersionPreview', { versionId }), window.location.origin);
  url.searchParams.set('contentLocale', currentTaskContext().locale);
  return requestJson<ComponentPreviewResponse>(url.toString());
}

export async function listComponentVersions(componentId: string, status?: string): Promise<ComponentVersionResponse[]> {
  const url = new URL(pathFor('componentVersions', { componentId }), window.location.origin);
  if (status) {
    url.searchParams.set('status', status);
  }
  return requestJson<ComponentVersionResponse[]>(url.toString());
}

export async function createComponentImport(
  sourceFile: File,
  exchangeFile: File | null,
  target: ComponentImportTarget = {},
): Promise<ComponentImportCreateResponse> {
  const body = new FormData();
  body.append('source_file', sourceFile);
  if (exchangeFile) {
    body.append('exchange_file', exchangeFile);
  }
  appendImportContext(body, target);
  return requestJson<ComponentImportCreateResponse>(appConfig.componentRepoApi.componentImports, {
    method: 'POST',
    body,
  });
}

export async function createComponentImportWithUploadSession(
  sourceFile: File,
  exchangeFile: File | null,
  target: ComponentImportTarget = {},
): Promise<ComponentImportCreateResponse> {
  return createComponentImportWithProgress(sourceFile, exchangeFile, undefined, target);
}

export async function createComponentImportWithProgress(
  sourceFile: File,
  exchangeFile: File | null,
  onProgress?: (progress: ComponentUploadProgress) => void,
  target: ComponentImportTarget = {},
): Promise<ComponentImportCreateResponse> {
  try {
    onProgress?.({ percent: 4, message: tr('componentRepo:creatingASecureUploadChannel') });
    const uploadSession = await createComponentUploadSession(sourceFile, exchangeFile, target);
    onProgress?.({ percent: 12, message: tr('componentRepo:uploadChannelReadyUploadingFiles') });
    await uploadComponentSessionFiles(uploadSession, sourceFile, exchangeFile, onProgress);
    onProgress?.({ percent: 92, message: tr('componentRepo:filesUploadedVerifyingIntegrity') });
    const result = await completeComponentUploadSession(uploadSession.id);
    onProgress?.({ percent: 100, message: tr('componentRepo:uploadComplete') });
    return result;
  } catch (directUploadError) {
    console.warn('Component Repo direct upload failed, falling back to multipart upload.', directUploadError);
    onProgress?.({ percent: 2, message: tr('componentRepo:switchingToACompatibleUploadMethod') });
    return uploadComponentImportWithXhr(sourceFile, exchangeFile, onProgress, target);
  }
}

export async function createComponentUploadSession(
  sourceFile: File,
  exchangeFile: File | null,
  target: ComponentImportTarget = {},
): Promise<ComponentUploadSessionResponse> {
  return requestJson<ComponentUploadSessionResponse>(appConfig.componentRepoApi.componentImportUploadSession, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      sourceFile: fileSpec(sourceFile),
      exchangeFile: exchangeFile ? fileSpec(exchangeFile) : null,
      targetComponentId: target.targetComponentId ?? null,
      baseVersionId: target.baseVersionId ?? null,
      contentLocale: currentTaskContext().locale,
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
    throw new Error(tr('componentRepo:supabaseSignInIsNotConfigured'));
  }
  const fileByRole = new Map<string, File>([['source', sourceFile]]);
  if (exchangeFile) {
    fileByRole.set('exchange', exchangeFile);
  }
  for (const [index, upload] of uploadSession.uploads.entries()) {
    const file = fileByRole.get(upload.role);
    if (!file) {
      throw new Error(`Missing upload file for role: ${upload.role}`);
    }
    const { error } = await supabase.storage.from(upload.bucket).upload(upload.objectPath, file, {
      contentType: upload.contentType,
      upsert: false,
    });
    if (error) {
      throw new Error(error.message);
    }
    const percent = 12 + Math.round(((index + 1) / uploadSession.uploads.length) * 74);
    onProgress?.({
      percent,
      message: tr(upload.role === 'source' ? 'componentRepo:componentSourceUploaded' : 'componentRepo:exchangeFileUploaded'),
    });
  }
}

export async function completeComponentUploadSession(uploadSessionId: string): Promise<ComponentImportCreateResponse> {
  return requestJson<ComponentImportCreateResponse>(
    pathFor('componentImportUploadComplete', { uploadSessionId }),
    {
      method: 'POST',
    },
  );
}

export async function parseComponentImport(importId: string): Promise<ComponentImportParseResponse> {
  return requestJson<ComponentImportParseResponse>(pathFor('componentImportParse', { importId }), {
    method: 'POST',
  });
}

export async function getImportCandidate(importId: string): Promise<ComponentCandidateResponse> {
  return requestJson<ComponentCandidateResponse>(pathFor('componentImportCandidate', { importId }));
}

export async function getCandidate(candidateId: string): Promise<ComponentCandidateResponse> {
  return requestJson<ComponentCandidateResponse>(pathFor('candidateDetail', { candidateId }));
}

/** Load a parsed candidate snapshot without requiring a draft ComponentVersion. */
export async function loadCandidatePreview(candidateId: string): Promise<ComponentPreviewResponse> {
  const url = new URL(pathFor('candidatePreview', { candidateId }), window.location.origin);
  url.searchParams.set('contentLocale', currentTaskContext().locale);
  return requestJson<ComponentPreviewResponse>(url.toString());
}

export async function listRelations(candidateId: string): Promise<ComponentRelationCandidateResponse[]> {
  return requestJson<ComponentRelationCandidateResponse[]>(pathFor('candidateRelations', { candidateId }));
}

export async function detectRelations(candidateId: string): Promise<ComponentRelationCandidateResponse[]> {
  return requestJson<ComponentRelationCandidateResponse[]>(pathFor('candidateRelationsDetect', { candidateId }), {
    method: 'POST',
  });
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

export async function listFreeConnectors(candidateId: string): Promise<ComponentFreeConnectorResponse[]> {
  return requestJson<ComponentFreeConnectorResponse[]>(pathFor('candidateFreeConnectors', { candidateId }));
}

export async function listInterfaces(candidateId: string): Promise<ComponentInterfaceResponse[]> {
  return requestJson<ComponentInterfaceResponse[]>(pathFor('candidateInterfaces', { candidateId }));
}

export async function createInterface(
  candidateId: string,
  worldConnectorId: string,
  name: string,
): Promise<ComponentInterfaceResponse> {
  return requestJson<ComponentInterfaceResponse>(pathFor('candidateInterfaces', { candidateId }), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      worldConnectorId,
      name,
      mechanicalRoles: ['mount'],
      businessRoles: ['external_mount'],
    }),
  });
}

export async function validateCandidate(candidateId: string): Promise<ComponentValidationReportResponse> {
  return requestJson<ComponentValidationReportResponse>(pathFor('candidateValidate', { candidateId }), {
    method: 'POST',
  });
}

export async function publishVersion(
  versionId: string,
  payload: {
    releaseNote: string;
    name: string;
    category: string | null;
    version: string;
  },
): Promise<ComponentVersionResponse> {
  return requestJson<ComponentVersionResponse>(pathFor('componentVersionPublish', { versionId }), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      ...payload,
      contentLocale: currentTaskContext().locale,
    }),
  });
}

export function componentVersionSourceUrl(versionId: string): string {
  return pathFor('componentVersionSource', { versionId });
}

export async function downloadComponentVersionSource(versionId: string): Promise<void> {
  const response = await apiFetch(componentVersionSourceUrl(versionId), await withAuth());
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

function pathFor(key: keyof ComponentRepoApiConfig, params: Record<string, string>): string {
  let path = appConfig.componentRepoApi[key];
  Object.entries(params).forEach(([paramKey, value]) => {
    path = path.replace(`{${paramKey}}`, encodeURIComponent(value));
  });
  return path;
}

function fileSpec(file: File): { filename: string; contentType: string | null; fileSize: number } {
  return {
    filename: file.name,
    contentType: file.type || null,
    fileSize: file.size,
  };
}

async function uploadComponentImportWithXhr(
  sourceFile: File,
  exchangeFile: File | null,
  onProgress?: (progress: ComponentUploadProgress) => void,
  target: ComponentImportTarget = {},
): Promise<ComponentImportCreateResponse> {
  const accessToken = await currentAccessToken();
  const body = new FormData();
  body.append('source_file', sourceFile);
  if (exchangeFile) {
    body.append('exchange_file', exchangeFile);
  }
  appendImportContext(body, target);

  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open('POST', appConfig.componentRepoApi.componentImports);
    if (accessToken) {
      request.setRequestHeader('Authorization', `Bearer ${accessToken}`);
    }
    request.upload.addEventListener('progress', (event) => {
      if (!event.lengthComputable) {
        return;
      }
      const percent = Math.max(3, Math.min(95, Math.round((event.loaded / event.total) * 92)));
      onProgress?.({ percent, message: tr('componentRepo:uploadingComponentFiles') });
    });
    request.addEventListener('load', () => {
      if (request.status < 200 || request.status >= 300) {
        reject(xhrApiError(request));
        return;
      }
      try {
        const result = JSON.parse(request.responseText) as ComponentImportCreateResponse;
        onProgress?.({ percent: 100, message: tr('componentRepo:uploadComplete') });
        resolve(result);
      } catch {
        reject(new ApiError('common.invalid_response', {}, request.getResponseHeader('X-Trace-Id'), request.status));
      }
    });
    request.addEventListener('error', () => reject(new ApiError('common.network_error')));
    request.addEventListener('abort', () => reject(new Error(tr('componentRepo:componentUploadCanceled'))));
    request.send(body);
  });
}

function appendImportContext(body: FormData, target: ComponentImportTarget): void {
  body.append('content_locale', currentTaskContext().locale);
  if (target.targetComponentId) body.append('target_component_id', target.targetComponentId);
  if (target.baseVersionId) body.append('base_version_id', target.baseVersionId);
}

function xhrApiError(request: XMLHttpRequest): ApiError {
  let payload: unknown = null;
  try {
    payload = JSON.parse(request.responseText) as unknown;
  } catch {
    payload = null;
  }
  return apiErrorFromPayload(
    payload,
    request.status,
    request.getResponseHeader('X-Trace-Id'),
  );
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
  return apiRequestJson<T>(input, await withAuth(init));
}

async function withAuth(init?: RequestInit): Promise<RequestInit | undefined> {
  const accessToken = await currentAccessToken();
  if (!accessToken) {
    return init;
  }
  const headers = new Headers(init?.headers);
  headers.set('Authorization', `Bearer ${accessToken}`);
  return {
    ...init,
    headers,
  };
}
