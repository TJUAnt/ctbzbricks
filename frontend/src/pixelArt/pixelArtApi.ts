import { authenticatedRequestJson as requestJson } from '../api/authenticatedClient';
import { localizeStructuredMessage, type StructuredMessage } from '../api/client';
import pixelArtConfig from './pixelArtConfig';
import { currentTaskContext } from '../api/taskContext';

export type PixelArtCrop = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type PixelArtPreprocessing = {
  brightness: number;
  contrast: number;
  saturation: number;
  sharpness: number;
  localContrast: number;
  preserveLightDetails: boolean;
};

export type PixelArtSettings = {
  algorithm: string;
  gridWidth: number;
  gridHeight: number;
  colorCount: number;
  crop: PixelArtCrop;
  preprocessing: PixelArtPreprocessing;
};

export type PixelCell = {
  x: number;
  y: number;
  colorIndex: number;
  rgb: string;
  sourceColor?: string;
  quantizedColor?: string;
  featureScore?: number;
  edgeStrength?: number;
  localContrast?: number;
  sidePixelWidthPlates?: number;
  sidePixelHeightPlates?: number;
  sidePartWidthPlates?: number;
  sidePartHeightPlates?: number;
  sidePartType?: string;
  sidePartRole?: string;
  modified?: boolean;
  locked?: boolean;
};

export type PixelPaletteColor = {
  colorIndex: number;
  rgb: string;
  count: number;
};

export type PixelArtProject = {
  modelId: string;
  revisionId: string;
  name: string;
  contentLocale: 'zh-CN' | 'en-US';
  source: string;
  createdAt: string;
  schema: string;
  gridWidth: number;
  gridHeight: number;
  colorCount: number;
  palette: PixelPaletteColor[];
  pixels: PixelCell[];
  previewImage: string;
};

export type PixelArtProjectSummary = {
  modelId: string;
  revisionId: string;
  name: string;
  contentLocale: 'zh-CN' | 'en-US';
  source: string;
  createdAt: string;
  gridWidth: number;
  gridHeight: number;
  colorCount: number;
  previewImage: string;
  status: string;
  taskId: string;
};

export type PixelArtProjectList = {
  page: number;
  pageSize: number;
  total: number;
  items: PixelArtProjectSummary[];
};

export async function loadPixelArtProjects(page: number, pageSize: number): Promise<PixelArtProjectList> {
  const url = new URL(pixelArtConfig.projectsApiUrl, window.location.origin);
  url.searchParams.set('page', String(page));
  url.searchParams.set('page_size', String(pageSize));
  return requestJson<PixelArtProjectList>(`${url.pathname}${url.search}`);
}

/** 上传工作图片并持久化生成任务；返回即代表任务可脱离页面继续执行。 */
export async function submitPixelArtProject(
  name: string,
  image: File,
  settings: PixelArtSettings,
  signal?: AbortSignal,
): Promise<PixelWriteAccepted> {
  const formData = new FormData();
  formData.append(pixelArtConfig.request.formKeys.name, name);
  formData.append(pixelArtConfig.request.formKeys.contentLocale, currentTaskContext().locale);
  formData.append(pixelArtConfig.request.formKeys.settings, JSON.stringify(settings));
  formData.append('timezone', currentTaskContext().timezone);
  formData.append(pixelArtConfig.request.formKeys.image, image);

  return requestJson<PixelWriteAccepted>(pixelArtConfig.projectsApiUrl, {
    method: pixelArtConfig.request.method,
    body: formData,
    signal,
  });
}

export async function updatePixelArtProjectPixels(
  project: PixelArtProject,
  signal?: AbortSignal,
): Promise<PixelArtProject> {
  const accepted = await requestJson<PixelWriteAccepted>(
    pixelArtConfig.projectPixelsApiUrl.replace(
      pixelArtConfig.routePlaceholders.projectId,
      project.modelId,
    ),
    {
      signal,
      method: pixelArtConfig.request.updateMethod,
      headers: {
        [pixelArtConfig.request.contentTypeHeader]: pixelArtConfig.request.jsonContentType,
      },
      body: JSON.stringify({
        revisionId: project.revisionId,
        ...currentTaskContext(),
        palette: project.palette,
        pixels: project.pixels,
      }),
    },
  );
  return waitForPixelProject(accepted.modelId, signal, accepted.taskId);
}

/** Go 写请求只返回持久任务标识；页面刷新后同一个项目 ID 仍能恢复结果。 */
export type PixelWriteAccepted = { modelId: string; revisionId: string; taskId: string; status: string; error?: StructuredMessage };
export type PixelTaskStatus = 'uploading' | 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
export type PixelTaskSnapshot = { taskId: string; status: PixelTaskStatus; percent: number | null };
type TaskResponse = {
  id: string;
  status: Exclude<PixelTaskStatus, 'uploading'>;
  progress: (StructuredMessage & { percent: number | null }) | null;
  error: StructuredMessage | null;
};

/**
 * 等待已持久化修订：恢复时先解析 taskId，之后只轮询轻量任务接口，成功后读取一次完整项目。
 * 中止信号只停止当前页面等待，不取消数据库任务。
 */
export async function waitForPixelProject(
  projectId: string,
  signal?: AbortSignal,
  acceptedTaskId?: string,
  onProgress?: (snapshot: PixelTaskSnapshot) => void,
): Promise<PixelArtProject> {
  let taskId = acceptedTaskId;
  if (!taskId) {
    signal?.throwIfAborted();
    const value = await requestJson<PixelArtProject | PixelWriteAccepted>(
      `${pixelArtConfig.projectsApiUrl}/${encodeURIComponent(projectId)}`,
      ...(signal ? [{ signal }] : []),
    );
    if ('pixels' in value) {
      onProgress?.({ taskId: '', status: 'succeeded', percent: 100 });
      return value;
    }
    if (value.status === 'failed' || value.status === 'cancelled') {
      throw new Error(localizeStructuredMessage(value.error ?? { code: 'pixel_art.generation_failed', params: {} }));
    }
    taskId = value.taskId;
  }
  for (;;) {
    signal?.throwIfAborted();
    const task = await requestJson<TaskResponse>(`/api/v1/tasks/${encodeURIComponent(taskId)}`, ...(signal ? [{ signal }] : []));
    onProgress?.(taskSnapshot(task));
    if (task.status === 'succeeded') {
      return requestJson<PixelArtProject>(
        `${pixelArtConfig.projectsApiUrl}/${encodeURIComponent(projectId)}`,
        ...(signal ? [{ signal }] : []),
      );
    }
    if (task.status === 'failed' || task.status === 'cancelled') {
      throw new Error(localizeStructuredMessage(task.error ?? { code: 'pixel_art.generation_failed', params: {} }));
    }
    await new Promise<void>((resolve, reject) => {
      const onAbort = () => { window.clearTimeout(timer); reject(signal?.reason); };
      const timer = window.setTimeout(() => { signal?.removeEventListener('abort', onAbort); resolve(); }, 1000);
      signal?.addEventListener('abort', onAbort, { once: true });
      if (signal?.aborted) onAbort();
    });
  }
}

/** 只展示后端提供的真实百分比；没有百分比时由原生 progress 呈现不确定进度。 */
function taskSnapshot(task: TaskResponse): PixelTaskSnapshot {
  const terminalPercent = task.status === 'succeeded' || task.status === 'failed' || task.status === 'cancelled' ? 100 : null;
  return { taskId: task.id, status: task.status, percent: task.progress?.percent ?? terminalPercent };
}
