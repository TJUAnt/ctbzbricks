import { ApiError, apiFetch } from '../../api/client';
import type { StructuredMessage } from '../../api/client';
import { currentTaskContext } from '../../api/taskContext';
import {
  collectComponentRepoPages as collectPagedItems,
  componentRepoPath as pathFor,
  componentRepoRequestJson as requestJson,
  componentRepoRequestVoid as requestVoid,
} from '../componentRepoTransport';
import type {
  ComponentVersionDiffResponse,
  ComponentVersionPartSummary,
  ComponentVersionPartsResponse,
  ComponentVersionPreviewModelResponse,
  ComponentResponse,
  ComponentVersionResponse,
} from '../componentRepoTypes';

type GoComponentVersionResponse = Omit<ComponentVersionResponse, 'deletion' | 'previewFailure'> & {
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
    previewModel: ComponentVersionPartSummary['previewModel'];
  }>;
};

/** 分页读取完整版本历史后再应用可选状态筛选，避免第 101 条之后的版本静默消失。 */
export async function listComponentVersions(componentId: string, status?: string): Promise<ComponentVersionResponse[]> {
  const rawVersions = await collectPagedItems(async (page, pageSize) => {
    const url = new URL(pathFor('componentVersions', { componentId }), window.location.origin);
    url.searchParams.set('page', String(page));
    url.searchParams.set('pageSize', String(pageSize));
    return requestJson<{ items: GoComponentVersionResponse[] }>(url.toString());
  });
  const versions = rawVersions.map(componentVersionFromGo);
  return status ? versions.filter((version) => version.status === status) : versions;
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
      previewModel: item.previewModel ?? null,
    })),
  };
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

function responseFilename(response: Response): string | null {
  const disposition = response.headers.get('Content-Disposition');
  if (!disposition) {
    return null;
  }
  const match = disposition.match(/filename="?([^";]+)"?/i);
  return match?.[1] ?? null;
}
