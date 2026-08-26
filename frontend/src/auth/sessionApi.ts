import { requestJson } from '../api/client';

/** Go 系统后端完成会话确认后返回的最小用户身份。 */
export type VerifiedSessionUser = {
  id: string;
  email?: string;
};

type VerifySessionResponse = {
  authenticated: true;
  user: VerifiedSessionUser;
};

/** 页面刷新时通过 Go 系统后端确认浏览器缓存的 Supabase session 仍然有效。 */
export async function verifyAuthSession(accessToken: string): Promise<VerifiedSessionUser> {
  const response = await requestJson<VerifySessionResponse>('/api/v1/auth/session', {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  return response.user;
}
