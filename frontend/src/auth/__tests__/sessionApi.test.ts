import { afterEach, describe, expect, it, vi } from 'vitest';

import { verifyAuthSession } from '../sessionApi';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Go auth session API', () => {
  it('verifies the stored Supabase token through the Go backend', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      authenticated: true,
      user: { id: 'user-1', email: 'user@example.com' },
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(verifyAuthSession('access-token')).resolves.toEqual({
      id: 'user-1',
      email: 'user@example.com',
    });
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/auth/session', {
      headers: { Authorization: 'Bearer access-token' },
    });
  });
});
