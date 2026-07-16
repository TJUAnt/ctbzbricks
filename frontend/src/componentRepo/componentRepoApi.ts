import appConfig from '../app/appConfig.json';
import { currentAccessToken } from '../auth/supabaseClient';

type ComponentRepoApiConfig = typeof appConfig.componentRepoApi;

export type ComponentResponse = {
  id: string;
  name: string;
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
  failureReason: string | null;
  metadata: Record<string, unknown>;
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
    parseIssues: Array<Record<string, unknown>>;
    createdAt: string;
  };
  candidate: ComponentCandidateResponse;
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
  checks: Array<{ code: string; status: string; message: string }>;
  issues: Array<{ code: string; severity: string; message: string }>;
  validatorVersion: string;
  createdAt: string;
};

export type ComponentApproveResponse = {
  component: ComponentResponse;
  version: ComponentVersionResponse;
  validationReport: ComponentValidationReportResponse;
};

export async function listComponents(status?: string): Promise<ComponentResponse[]> {
  const url = new URL(appConfig.componentRepoApi.components, window.location.origin);
  if (status) {
    url.searchParams.set('status', status);
  }
  return requestJson<ComponentResponse[]>(url.toString());
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
): Promise<ComponentImportCreateResponse> {
  const body = new FormData();
  body.append('source_file', sourceFile);
  if (exchangeFile) {
    body.append('exchange_file', exchangeFile);
  }
  return requestJson<ComponentImportCreateResponse>(appConfig.componentRepoApi.componentImports, {
    method: 'POST',
    body,
  });
}

export async function parseComponentImport(importId: string): Promise<ComponentImportParseResponse> {
  return requestJson<ComponentImportParseResponse>(pathFor('componentImportParse', { importId }), {
    method: 'POST',
  });
}

export async function getImportCandidate(importId: string): Promise<ComponentCandidateResponse> {
  return requestJson<ComponentCandidateResponse>(pathFor('componentImportCandidate', { importId }));
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

export async function approveCandidate(
  candidateId: string,
  payload: {
    name: string;
    category: string | null;
    version: string;
  },
): Promise<ComponentApproveResponse> {
  return requestJson<ComponentApproveResponse>(pathFor('candidateApprove', { candidateId }), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: payload.name,
      category: payload.category || null,
      version: payload.version,
      tags: payload.category ? [payload.category] : [],
    }),
  });
}

export async function publishVersion(
  versionId: string,
  releaseNote: string,
): Promise<ComponentVersionResponse> {
  return requestJson<ComponentVersionResponse>(pathFor('componentVersionPublish', { versionId }), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ releaseNote }),
  });
}

export function componentVersionSourceUrl(versionId: string): string {
  return pathFor('componentVersionSource', { versionId });
}

export async function downloadComponentVersionSource(versionId: string): Promise<void> {
  const response = await fetch(componentVersionSourceUrl(versionId), await withAuth());
  if (!response.ok) {
    throw new Error(await responseError(response));
  }
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

function responseFilename(response: Response): string | null {
  const disposition = response.headers.get('Content-Disposition');
  if (!disposition) {
    return null;
  }
  const match = disposition.match(/filename="?([^";]+)"?/i);
  return match?.[1] ?? null;
}

async function requestJson<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, await withAuth(init));
  if (!response.ok) {
    throw new Error(await responseError(response));
  }
  return (await response.json()) as T;
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

async function responseError(response: Response): Promise<string> {
  const text = await response.text();
  if (!text) {
    return `HTTP ${response.status}`;
  }
  try {
    const payload = JSON.parse(text) as { detail?: unknown };
    if (typeof payload.detail === 'string') {
      return payload.detail;
    }
  } catch {
    // Fall through to raw response text.
  }
  return text;
}
