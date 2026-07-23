import { afterAll, describe, expect, it } from 'vitest';

import i18n from '../../i18n';
import { localizeStructuredMessage, type StructuredMessage } from '../client';

describe('structured task messages', () => {
  afterAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  it('keeps task data locale-independent while localizing presentation', async () => {
    const progress: StructuredMessage = {
      code: 'terrain.progress.processing',
      params: { percent: 42 },
    };
    const serialized = JSON.stringify(progress);

    await i18n.changeLanguage('en-US');
    const english = localizeStructuredMessage(progress, 'tasks');
    await i18n.changeLanguage('zh-CN');
    const chinese = localizeStructuredMessage(progress, 'tasks');

    expect(english).toBe('Processing terrain (42%).');
    expect(chinese).toBe('正在处理地形（42%）。');
    expect(chinese).not.toBe(english);
    expect(JSON.stringify(progress)).toBe(serialized);
  });

  it('localizes the same structured failure without storing exception text', async () => {
    const failure: StructuredMessage = {
      code: 'terrain.generation_failed',
      params: { jobId: 'job-42' },
    };

    await i18n.changeLanguage('en-US');
    const english = localizeStructuredMessage(failure);
    await i18n.changeLanguage('zh-CN');
    const chinese = localizeStructuredMessage(failure);

    expect(english).toBe('The terrain generation task failed.');
    expect(chinese).toBe('地形生成任务执行失败。');
    expect(failure).toEqual({
      code: 'terrain.generation_failed',
      params: { jobId: 'job-42' },
    });
  });
});
