import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { ComponentPublicFeedCard } from '../ComponentPublicFeedCard';
import type { PublicFeedComponentResponse } from '../componentPublicFeed';

vi.mock('../../i18n', () => ({
  useAppTranslation: () => (key: string, params?: Record<string, string | number>) =>
    `${key}${params ? `:${JSON.stringify(params)}` : ''}`,
}));

vi.mock('../../i18n/formatters', () => ({
  formatDateTime: (value: string) => `date:${value}`,
  formatNumber: (value: number) => String(value),
}));

function feedItem(): PublicFeedComponentResponse {
  return {
    id: 'component-1',
    ownerId: 'publisher-1234567890',
    contentKind: 'user',
    contentLocale: 'zh-CN',
    name: '空间站',
    description: '轨道空间站组件',
    tags: [],
    category: '航天',
    status: 'active',
    currentVersionId: 'version-current',
    logicalSize: { widthStud: 10, depthStud: 8, heightPlate: 12 },
    metadata: {},
    ownedByActor: false,
    starredByActor: false,
    starCount: 3,
    translationMissing: false,
    createdAt: '2026-09-12T01:00:00Z',
    updatedAt: '2026-09-12T02:00:00Z',
    feedEventId: 'event-1',
    feedOccurredAt: '2026-09-12T02:00:00Z',
    feedComponentVersionId: 'version-1',
    feedVersion: '1.2.0',
    feedRevision: 2,
    feedReleaseNote: '新增太阳能板',
    feedReleaseNoteLocale: 'zh-CN',
    feedPublisherId: 'publisher-1234567890',
    feedRender: {
      status: 'ready',
      availableAt: '2026-09-12T02:01:00Z',
      image: {
        artifactId: 'feed-image-1',
        url: '/assets/feed-image-1.png',
        format: 'png',
        sha256: 'a'.repeat(64),
        byteLength: 2048,
        width: 1200,
        height: 800,
      },
    },
  };
}

describe('ComponentPublicFeedCard', () => {
  it('renders publisher, event copy, and the worker-generated 3:2 image', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <ComponentPublicFeedCard
          detailPath="/components/component-1"
          item={feedItem()}
          onToggleStar={() => undefined}
          starPending={false}
        />
      </MemoryRouter>,
    );

    expect(html).toContain('componentRepo:publishedBy');
    expect(html).toContain('publishe…7890');
    expect(html).toContain('componentRepo:publishedVersionUpdate');
    expect(html).toContain('轨道空间站组件');
    expect(html).toContain('新增太阳能板');
    expect(html).toContain('src="/assets/feed-image-1.png"');
    expect(html).toContain('width="1200"');
    expect(html).toContain('height="800"');
  });

  it('renders the stable placeholder after render retries are exhausted', () => {
    const item = feedItem();
    item.feedRender = {
      status: 'fallback',
      availableAt: '2026-09-12T02:01:00Z',
      image: null,
    };
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <ComponentPublicFeedCard
          detailPath="/components/component-1"
          item={item}
          onToggleStar={() => undefined}
          starPending={false}
        />
      </MemoryRouter>,
    );

    expect(html).toContain('componentRepo:previewUnavailable');
    expect(html).not.toContain('<img');
  });
});
