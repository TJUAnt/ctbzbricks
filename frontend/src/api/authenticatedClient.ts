import { currentAccessToken } from '../auth/supabaseClient';
import { apiFetch, requestJson } from './client';

/** 向需要登录态的 Go API 发起原始请求，供无 JSON 响应等边界复用同一认证注入规则。 */
export async function authenticatedApiFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
  fallbackCode?: string,
): Promise<Response> {
  return apiFetch(input, await withCurrentAccessToken(init), fallbackCode);
}

/**
 * 向需要登录态的 Go API 发起 JSON 请求。
 *
 * 该入口统一从当前 Supabase session 读取 access token，并在请求发出前写入 Bearer header；
 * 页面和领域 API 不应各自复制认证注入逻辑，以免新增路由遗漏登录态。
 */
export async function authenticatedRequestJson<T>(
  input: RequestInfo | URL,
  init?: RequestInit,
  fallbackCode?: string,
): Promise<T> {
  return requestJson<T>(input, await withCurrentAccessToken(init), fallbackCode);
}

/** 保留调用方已有 headers，只覆盖 Authorization 为当前有效 session token。 */
async function withCurrentAccessToken(init?: RequestInit): Promise<RequestInit | undefined> {
  const accessToken = await currentAccessToken();
  if (!accessToken) return init;
  const headers = new Headers(init?.headers);
  headers.set('Authorization', `Bearer ${accessToken}`);
  return { ...init, headers };
}
