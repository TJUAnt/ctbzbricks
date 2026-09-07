import { afterEach, expect, it, vi } from 'vitest';
import { authenticatedRequestJson } from '../../api/authenticatedClient';
import { waitForPixelProject, updatePixelArtProjectPixels, type PixelArtProject } from '../pixelArtApi';
vi.mock('../../api/authenticatedClient', () => ({ authenticatedRequestJson: vi.fn() }));
vi.mock('../../api/taskContext', () => ({ currentTaskContext: () => ({ locale: 'en-US', timezone: 'UTC' }) }));
vi.mock('../../api/client', () => ({ localizeStructuredMessage: (value: { code: string }) => value.code }));
afterEach(() => { vi.resetAllMocks(); vi.unstubAllGlobals(); });

it('恢复持久任务只轮询 GET，不重新提交生成', async () => {
  vi.stubGlobal('window', { setTimeout: (fn: () => void) => { fn(); return 1; } });
  const ready = { modelId: 'project', pixels: [] };
  const progress: Array<{ status: string; percent: number | null }> = [];
  vi.mocked(authenticatedRequestJson)
    .mockResolvedValueOnce({ modelId: 'project', taskId: 'task-1', status: 'running' })
    .mockResolvedValueOnce({ id: 'task-1', status: 'running', progress: null, error: null })
    .mockResolvedValueOnce({ id: 'task-1', status: 'succeeded', progress: null, error: null })
    .mockResolvedValueOnce(ready);
  expect(await waitForPixelProject('project', undefined, undefined, (value) => progress.push({ status: value.status, percent: value.percent }))).toEqual(ready);
  expect(progress).toEqual([{ status: 'running', percent: null }, { status: 'succeeded', percent: 100 }]);
  expect(vi.mocked(authenticatedRequestJson).mock.calls).toEqual([
    ['/api/v1/pixel-art/projects/project'],
    ['/api/v1/tasks/task-1'],
    ['/api/v1/tasks/task-1'],
    ['/api/v1/pixel-art/projects/project'],
  ]);
});
it('失败任务结束轮询并保留结构化错误码', async () => {
  vi.mocked(authenticatedRequestJson).mockResolvedValue({ status: 'failed', error: { code: 'pixel_art.generation_failed', params: {} } });
  await expect(waitForPixelProject('project')).rejects.toThrow('pixel_art.generation_failed');
  expect(authenticatedRequestJson).toHaveBeenCalledTimes(1);
});
it('保存冻结父修订和任务语言，等待新修订完成', async () => {
  const project = { modelId: 'project', revisionId: 'revision', pixels: [], palette: [] } as unknown as PixelArtProject;
  vi.mocked(authenticatedRequestJson)
    .mockResolvedValueOnce({ modelId: 'project', taskId: 'task-2' })
    .mockResolvedValueOnce({ id: 'task-2', status: 'succeeded', progress: null, error: null })
    .mockResolvedValueOnce({ ...project, revisionId: 'next' });
  expect((await updatePixelArtProjectPixels(project)).revisionId).toBe('next');
  const options = vi.mocked(authenticatedRequestJson).mock.calls[0][1] as RequestInit;
  expect(JSON.parse(options.body as string)).toEqual({ revisionId: 'revision', locale: 'en-US', timezone: 'UTC', pixels: [], palette: [] });
});

it('页面取消后不再请求项目，也不取消持久化任务', async () => {
  const controller = new AbortController();
  controller.abort();
  await expect(waitForPixelProject('project', controller.signal)).rejects.toMatchObject({ name: 'AbortError' });
  expect(authenticatedRequestJson).not.toHaveBeenCalled();
});
