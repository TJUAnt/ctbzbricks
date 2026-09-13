import { ApiError } from '../../api/client';
import { componentRepoPath as pathFor, componentRepoRequestJson as requestJson } from '../componentRepoTransport';
import type { ComponentTaskResponse } from '../componentRepoTypes';

const taskPollIntervalMs = 1_000;
const taskPollTimeoutMs = 10 * 60 * 1_000;

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
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
