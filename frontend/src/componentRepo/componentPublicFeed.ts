import type { ComponentPublicFeedItemResponse, ComponentResponse } from './componentRepoApi';

/** PublicFeedComponentResponse 保留事件版本和发布人，卡片不得用当前版本替代事件发生时的版本。 */
export type PublicFeedComponentResponse = ComponentResponse & {
  feedEventId?: string;
  feedOccurredAt?: string;
  feedComponentVersionId?: string;
  feedVersion?: string;
  feedRevision?: number;
  feedReleaseNote?: string | null;
  feedReleaseNoteLocale?: 'zh-CN' | 'en-US' | null;
  feedPublisherId?: string;
  feedRender?: ComponentPublicFeedItemResponse['render'];
};

/** projectPublicFeedItems 把接口事件转换为现有组件行可消费的投影，事件顺序保持服务端结果顺序。 */
export function projectPublicFeedItems(items: ComponentPublicFeedItemResponse[]): PublicFeedComponentResponse[] {
  return items.map((item) => ({
    ...item.component,
    feedEventId: item.eventId,
    feedOccurredAt: item.occurredAt,
    feedComponentVersionId: item.componentVersionId,
    feedVersion: item.version,
    feedRevision: item.revision,
    feedReleaseNote: item.releaseNote,
    feedReleaseNoteLocale: item.releaseNoteLocale,
    feedPublisherId: item.publisher.id,
    feedRender: item.render,
  }));
}

/** appendPublicFeedItems 按事件 ID 去重追加游标页，不按 Component ID 合并历史发布事件。 */
export function appendPublicFeedItems(
  current: PublicFeedComponentResponse[],
  items: ComponentPublicFeedItemResponse[],
): PublicFeedComponentResponse[] {
  const knownEvents = new Set(current.map((item) => item.feedEventId).filter(Boolean));
  return [
    ...current,
    ...projectPublicFeedItems(items).filter((item) => !knownEvents.has(item.feedEventId)),
  ];
}
