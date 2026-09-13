import appConfig from '../../app/appConfig';
import { ApiError } from '../../api/client';
import { currentTaskContext } from '../../api/taskContext';
import { supabase } from '../../auth/supabaseClient';
import { translate as tr } from '../../i18n';
import { componentRepoPath as pathFor, componentRepoRequestJson as requestJson } from '../componentRepoTransport';
import type {
  ComponentImportHistoryResponse,
  ComponentImportRecordResponse,
  ComponentImportResponse,
  ComponentImportTarget,
  ComponentImportUploadCompleteResponse,
  ComponentUploadProgress,
  ComponentUploadSessionResponse,
} from '../componentRepoTypes';

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
