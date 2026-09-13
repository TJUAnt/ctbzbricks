import appConfig from '../../app/appConfig';
import { ApiError } from '../../api/client';
import { currentTaskContext } from '../../api/taskContext';
import {
  collectComponentRepoPages as collectPagedItems,
  componentRepoPath as pathFor,
  componentRepoRequestJson as requestJson,
  componentRepoRequestVoid as requestVoid,
} from '../componentRepoTransport';
import type {
  ComponentGroupMembershipCandidatePage,
  ComponentGroupResponse,
  ComponentGroupSearchResponse,
  ComponentGroupTreeResponse,
  ComponentPageResponse,
  ComponentPublicFeedPageResponse,
  ComponentResponse,
  ComponentStarPageResponse,
  ComponentStarResponse,
  ComponentWatchFeedPageResponse,
  ComponentWatchPageResponse,
  ComponentWatchResponse,
} from '../componentRepoTypes';

/** 按事件倒序读取组件库广场；当前 actor 的 Watch 关系不参与 Feed 成员筛选。 */
export async function listComponentPublicFeed(payload: {
  limit?: number;
  cursor?: string;
  query?: string;
} = {}): Promise<ComponentPublicFeedPageResponse> {
  const url = new URL(appConfig.componentRepoApi.componentPublicFeed, window.location.origin);
  url.searchParams.set('locale', currentTaskContext().locale);
  if (payload.limit) url.searchParams.set('limit', String(payload.limit));
  if (payload.cursor) url.searchParams.set('cursor', payload.cursor);
  if (payload.query) url.searchParams.set('query', payload.query);
  return requestJson<ComponentPublicFeedPageResponse>(url.toString());
}

/** 使用冻结窗口和不透明游标读取当前 actor 的订阅发布事件。 */
export async function listComponentWatchFeed(payload: {
  since?: string;
  limit?: number;
  cursor?: string;
} = {}): Promise<ComponentWatchFeedPageResponse> {
  const url = new URL(appConfig.componentRepoApi.componentWatchFeed, window.location.origin);
  url.searchParams.set('locale', currentTaskContext().locale);
  if (payload.since) url.searchParams.set('since', payload.since);
  if (payload.limit) url.searchParams.set('limit', String(payload.limit));
  if (payload.cursor) url.searchParams.set('cursor', payload.cursor);
  return requestJson<ComponentWatchFeedPageResponse>(url.toString());
}

/** 读取完整分组成员，防止裸 items 接口的固定首屏上限静默漏掉后续关系。 */
export async function listComponentGroupComponents(groupId: string): Promise<ComponentResponse[]> {
  return collectPagedItems(async (page, pageSize) => {
    const url = new URL(pathFor('componentGroupComponents', { groupId }), window.location.origin);
    url.searchParams.set('locale', currentTaskContext().locale);
    url.searchParams.set('page', String(page));
    url.searchParams.set('pageSize', String(pageSize));
    return requestJson<{ items: ComponentResponse[] }>(url.toString());
  });
}

/** 从自有、收藏和现有成员三个服务端分页来源汇总一页可管理候选。 */
export async function listComponentGroupMembershipCandidates(payload: {
  rootGroupId: string;
  groupId: string;
  query?: string;
  page: number;
  pageSize: number;
}): Promise<ComponentGroupMembershipCandidatePage> {
  const queries = payload.query?.trim() ? [payload.query.trim()] : [];
  const [owned, starred, existing] = await Promise.all([
    searchComponentGroupComponents(payload.rootGroupId, {
      queries, statuses: null, page: payload.page, pageSize: payload.pageSize,
    }),
    listComponentStars({
      page: payload.page,
      pageSize: payload.pageSize,
      query: payload.query?.trim() || undefined,
      sort: 'starred_at_desc',
    }),
    searchComponentGroupComponents(payload.groupId, {
      queries, statuses: null, page: payload.page, pageSize: payload.pageSize,
    }),
  ]);
  const byId = new Map<string, ComponentResponse>();
  [...owned.items, ...starred.items, ...existing.items]
    .forEach((component) => byId.set(component.id, component));
  return {
    items: [...byId.values()],
    page: payload.page,
    hasMore: [owned, starred, existing].some((source) => source.page < source.totalPages),
  };
}

export async function listComponents(payload: {
  page: number;
  pageSize: number;
  query?: string;
  status?: string;
}): Promise<ComponentPageResponse> {
  const url = new URL(appConfig.componentRepoApi.components, window.location.origin);
  url.searchParams.set('locale', currentTaskContext().locale);
  url.searchParams.set('page', String(payload.page));
  url.searchParams.set('pageSize', String(payload.pageSize));
  if (payload.query) url.searchParams.set('query', payload.query);
  if (payload.status) url.searchParams.set('status', payload.status);
  return requestJson<ComponentPageResponse>(url.toString());
}

/** 读取当前用户仍公开可见的收藏，按收藏时间倒序稳定分页。 */

export async function listComponentStars(payload: {
  page: number;
  pageSize: number;
  query?: string;
  category?: string;
  sort?: 'starred_at_desc';
}): Promise<ComponentStarPageResponse> {
  const url = new URL(appConfig.componentRepoApi.componentStars, window.location.origin);
  url.searchParams.set('locale', currentTaskContext().locale);
  url.searchParams.set('page', String(payload.page));
  url.searchParams.set('pageSize', String(payload.pageSize));
  if (payload.query) url.searchParams.set('query', payload.query);
  if (payload.category) url.searchParams.set('category', payload.category);
  if (payload.sort) url.searchParams.set('sort', payload.sort);
  return requestJson<ComponentStarPageResponse>(url.toString());
}

/** 幂等收藏一个公开的非本人 Component。 */

export async function starComponent(componentId: string): Promise<ComponentStarResponse> {
  return requestJson<ComponentStarResponse>(pathFor('componentStar', { componentId }), {
    method: 'PUT',
  });
}

/** 幂等取消当前用户与 Component 的收藏关系。 */

export async function unstarComponent(componentId: string): Promise<void> {
  await requestVoid(pathFor('componentStar', { componentId }), { method: 'DELETE' });
}

/** 显式订阅 Component 的新版本发布；Watch 与 Star 使用独立关系和 API。 */

export async function watchComponent(componentId: string): Promise<ComponentWatchResponse> {
  return requestJson<ComponentWatchResponse>(pathFor('componentWatch', { componentId }), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ level: 'releases_only' }),
  });
}

/** 幂等取消当前 actor 的更新订阅，不改变 Star 或 Component 权限。 */

export async function unwatchComponent(componentId: string): Promise<void> {
  await requestVoid(pathFor('componentWatch', { componentId }), { method: 'DELETE' });
}

/** 使用服务端不透明 keyset cursor 读取当前 actor 的 active Watch。 */

export async function listComponentWatches(payload: {
  limit?: number;
  cursor?: string;
  query?: string;
  category?: string;
} = {}): Promise<ComponentWatchPageResponse> {
  const url = new URL(appConfig.componentRepoApi.componentWatches, window.location.origin);
  url.searchParams.set('locale', currentTaskContext().locale);
  if (payload.limit) url.searchParams.set('limit', String(payload.limit));
  if (payload.cursor) url.searchParams.set('cursor', payload.cursor);
  if (payload.query) url.searchParams.set('query', payload.query);
  if (payload.category) url.searchParams.set('category', payload.category);
  return requestJson<ComponentWatchPageResponse>(url.toString());
}

export async function listComponentGroups(): Promise<ComponentGroupTreeResponse> {
  let response = await requestJson<{ items: ComponentGroupResponse[] }>(appConfig.componentRepoApi.componentGroups);
  if (!response.items.some((group) => group.groupType === 'root')) {
    await requestVoid(appConfig.componentRepoApi.componentGroupsBootstrap, { method: 'POST' });
    response = await requestJson<{ items: ComponentGroupResponse[] }>(appConfig.componentRepoApi.componentGroups);
  }
  const root = response.items.find((group) => group.groupType === 'root');
  if (!root) throw new ApiError('component_repo.group_not_found');
  return { root, groups: response.items.filter((group) => group.groupType === 'custom') };
}

export async function createComponentGroup(payload: {
  parentGroupId: string;
  name: string;
  contentLocale: string;
}): Promise<ComponentGroupResponse> {
  return requestJson<ComponentGroupResponse>(appConfig.componentRepoApi.componentGroups, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function updateComponentGroup(
  groupId: string,
  payload: {
    name?: string;
    contentLocale?: string;
    parentGroupId?: string;
    sortOrder?: number;
  },
): Promise<ComponentGroupResponse> {
  return requestJson<ComponentGroupResponse>(pathFor('componentGroup', { groupId }), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function moveComponentGroup(
  groupId: string,
  parentGroupId: string,
  position: number,
): Promise<ComponentGroupResponse> {
  return requestJson<ComponentGroupResponse>(pathFor('componentGroupMove', { groupId }), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ parentGroupId, sortOrder: position }),
  });
}

export async function deleteComponentGroup(groupId: string): Promise<void> {
  await requestVoid(pathFor('componentGroup', { groupId }), { method: 'DELETE' });
}

export async function searchComponentGroupComponents(
  groupId: string,
  payload: {
    queries: string[];
    statuses: string[] | null;
    page: number;
    pageSize: number;
  },
): Promise<ComponentGroupSearchResponse> {
  const url = new URL(pathFor('componentGroupComponentSearch', { groupId }), window.location.origin);
  url.searchParams.set('locale', currentTaskContext().locale);
  payload.queries.forEach((query) => url.searchParams.append('query', query));
  url.searchParams.set('page', String(payload.page));
  url.searchParams.set('pageSize', String(payload.pageSize));
  payload.statuses?.forEach((status) => url.searchParams.append('status', status));
  return requestJson<ComponentGroupSearchResponse>(url.toString());
}

export async function listComponentGroupIds(componentId: string): Promise<string[]> {
  const response = await requestJson<{ componentId: string; groupIds: string[] }>(
    pathFor('componentGroupsForComponent', { componentId }),
  );
  return response.groupIds;
}

export async function addComponentToGroup(
  groupId: string,
  componentId: string,
): Promise<void> {
  await requestVoid(
    pathFor('componentGroupComponents', { groupId }),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ componentId }),
    },
  );
}

export async function removeComponentFromGroup(
  groupId: string,
  componentId: string,
): Promise<void> {
  await requestVoid(
    pathFor('componentGroupComponent', { groupId, componentId }),
    { method: 'DELETE' },
  );
}
