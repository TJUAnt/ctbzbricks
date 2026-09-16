import { describe, expect, it } from 'vitest';

import { mergeWatchItems } from '../ComponentWatchListPage';
import { mergeFeedItems, watchFeedSince } from '../ComponentWatchFeedPanel';
import type {
  ComponentWatchFeedItemResponse,
  ComponentWatchListItemResponse,
} from '../componentRepoApi';

const watchItem = (componentId: string): ComponentWatchListItemResponse => ({
  componentId,
  contentKind: 'user',
  contentLocale: 'zh-CN',
  name: `Component ${componentId}`,
  category: 'building',
  currentVersionId: `version-${componentId}`,
  version: '1.0.0',
  revision: 1,
  publishedAt: '2026-09-10T00:00:00.000Z',
  level: 'releases_only',
  watchedAt: '2026-09-10T01:00:00.000Z',
  translationMissing: false,
});

const feedItem = (eventId: string, occurredAt: string): ComponentWatchFeedItemResponse => ({
  eventId,
  eventType: 'component.version.published.v1',
  occurredAt,
  componentVersionId: `version-${eventId}`,
  version: eventId,
  revision: 1,
  publishedAt: occurredAt,
  releaseNote: '发布说明原文',
  releaseNoteLocale: 'zh-CN',
  publisher: { id: 'publisher-1' },
  render: { status: 'fallback', availableAt: occurredAt, image: null },
  component: {
    id: 'component-1',
    ownerId: 'publisher-1',
    contentKind: 'user',
    contentLocale: 'zh-CN',
    name: '用户原文',
    description: '用户描述原文',
    tags: [],
    category: 'building',
    status: 'active',
    currentVersionId: `version-${eventId}`,
    metadata: {},
    ownedByActor: false,
    starredByActor: false,
    starCount: 0,
    translationMissing: false,
    createdAt: occurredAt,
    updatedAt: occurredAt,
  },
});

describe('Component Watch list state helpers', () => {
  it('keeps the first Watch projection when cursor pages overlap', () => {
    const first = watchItem('component-1');
    const duplicate = { ...first, name: 'stale duplicate' };
    expect(mergeWatchItems([first], [duplicate, watchItem('component-2')])).toEqual([
      first,
      watchItem('component-2'),
    ]);
  });

  it('deduplicates Feed cursor overlap without changing the server order', () => {
    const older = feedItem('event-1', '2026-09-10T00:00:00.000Z');
    const sameTimeLower = feedItem('event-2', '2026-09-10T01:00:00.000Z');
    const sameTimeHigher = feedItem('event-3', '2026-09-10T01:00:00.000Z');
    expect(mergeFeedItems([sameTimeLower], [sameTimeLower, sameTimeHigher, older])).toEqual([
      sameTimeLower,
      sameTimeHigher,
      older,
    ]);
  });

  it.each([
    [7, '2026-09-03T12:00:00.000Z'],
    [30, '2026-08-11T12:00:00.000Z'],
    [90, '2026-06-12T12:00:00.000Z'],
  ])('converts the %d-day window to an exact UTC lower bound', (days, expected) => {
    expect(watchFeedSince(days, Date.parse('2026-09-10T12:00:00.000Z'))).toBe(expected);
  });
});
