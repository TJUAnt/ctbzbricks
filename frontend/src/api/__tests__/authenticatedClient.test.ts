import { afterEach, describe, expect, it, vi } from 'vitest';
import { currentAccessToken } from '../../auth/supabaseClient';
import { authenticatedRequestJson } from '../authenticatedClient';

vi.mock('../../auth/supabaseClient', () => ({
  currentAccessToken: vi.fn(),
}));

describe('authenticatedRequestJson', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetAllMocks();
  });

  it('在保留业务 headers 的同时注入当前 Bearer token', async () => {
    vi.mocked(currentAccessToken).mockResolvedValue('access-token');
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await authenticatedRequestJson<{ ok: boolean }>('/api/v1/parts/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: 'brick' }),
    });

    const requestInit = fetchMock.mock.calls[0]?.[1] as RequestInit;
    const headers = new Headers(requestInit.headers);
    expect(headers.get('Authorization')).toBe('Bearer access-token');
    expect(headers.get('Content-Type')).toBe('application/json');
  });
});
