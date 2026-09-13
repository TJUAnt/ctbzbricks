import appConfig from '../app/appConfig';
import { authenticatedApiFetch, authenticatedRequestJson } from '../api/authenticatedClient';

type ComponentRepoApiConfig = typeof appConfig.componentRepoApi;

/** 根据集中配置生成 Component Repo 路径，机器标识符始终按 URL 规则编码。 */
export function componentRepoPath(
  key: keyof ComponentRepoApiConfig,
  params: Record<string, string> = {},
): string {
  let path = appConfig.componentRepoApi[key];
  Object.entries(params).forEach(([paramKey, value]) => {
    path = path.replace(`{${paramKey}}`, encodeURIComponent(value));
  });
  return path;
}

/** 通过统一鉴权客户端读取 JSON，保留稳定的 code + params 错误语义。 */
export async function componentRepoRequestJson<T>(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<T> {
  return authenticatedRequestJson<T>(input, init);
}

/** 执行没有响应体的 Component Repo 写操作。 */
export async function componentRepoRequestVoid(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<void> {
  await authenticatedApiFetch(input, init);
}

/** 为仍返回裸 items 的页码接口读取完整集合，避免固定首屏上限静默截断。 */
export async function collectComponentRepoPages<T>(
  loadPage: (page: number, pageSize: number) => Promise<{ items: T[] }>,
  pageSize = 100,
): Promise<T[]> {
  const items: T[] = [];
  for (let page = 1; ; page += 1) {
    const response = await loadPage(page, pageSize);
    items.push(...response.items);
    if (response.items.length < pageSize) return items;
  }
}
