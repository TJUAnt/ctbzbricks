import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import i18n from '../../i18n';
import { ApiError, apiFetch, errorMessage, requestJson } from '../client';

describe('API error client', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  afterEach(async () => {
    vi.unstubAllGlobals();
    await i18n.changeLanguage('zh-CN');
  });

  it('parses the stable error contract and resolves the current language lazily', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: {
        code: 'terrain.job_not_found',
        params: { jobId: 'job-42' },
        traceId: 'req_test',
      },
    }), {
      status: 404,
      headers: { 'Content-Type': 'application/json' },
    })));

    const error = await apiFetch('/api/terrain/jobs/job-42').catch((caught) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ code: 'terrain.job_not_found', traceId: 'req_test', status: 404 });
    expect(errorMessage(error)).toContain('job-42');
    expect(errorMessage(error)).toContain('未找到');

    await i18n.changeLanguage('en-US');
    expect(error.message).toBe('DEM job job-42 was not found.');
  });

  it('never exposes a raw non-contract response body', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('secret stack trace', { status: 500 })));

    const error = await requestJson('/api/failure').catch((caught) => caught);
    expect(error).toBeInstanceOf(ApiError);
    if (!(error instanceof ApiError)) throw new Error('Expected ApiError');
    expect(error.message).not.toContain('secret stack trace');
    expect(error.code).toBe('request.failed');
  });

  it('normalizes network failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('socket details')));

    const error = await apiFetch('/api/offline').catch((caught) => caught);
    expect(error).toBeInstanceOf(ApiError);
    if (!(error instanceof ApiError)) throw new Error('Expected ApiError');
    expect(error.code).toBe('common.network_error');
    expect(error.message).not.toContain('socket details');
  });
});
