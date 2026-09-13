import { describe, expect, it } from 'vitest';

import type { ComponentPublicFeedItemResponse, ComponentResponse } from '../componentRepoApi';
import { appendPublicFeedItems, projectPublicFeedItems } from '../componentPublicFeed';

function component(id: string): ComponentResponse {
  return {
    id,
    name: id,
    contentKind: 'user',
    contentLocale: 'en-US',
    category: null,
    status: 'active',
    currentVersionId: null,
    description: null,
    tags: [],
    metadata: {},
    starredByActor: false,
    starCount: 0,
    createdAt: '2026-09-01T00:00:00Z',
    updatedAt: '2026-09-01T00:00:00Z',
  };
}

function event(eventId: string, componentId: string, occurredAt: string): ComponentPublicFeedItemResponse {
  return {
    eventId,
    occurredAt,
    componentVersionId: `version-${eventId}`,
    version: eventId,
    revision: 1,
    publishedAt: occurredAt,
    releaseNote: null,
    releaseNoteLocale: null,
    publisher: { id: `publisher-${eventId}` },
    render: {
      status: 'ready',
      availableAt: occurredAt,
      image: {
        artifactId: `image-${eventId}`,
        url: `/assets/${eventId}.png`,
        format: 'png',
        sha256: 'a'.repeat(64),
        byteLength: 128,
        width: 1200,
        height: 800,
      },
    },
    component: component(componentId),
  };
}

describe('component public Feed projection', () => {
  it('keeps repeated Component releases as separate ordered events', () => {
    const projected = projectPublicFeedItems([
      event('event-2', 'component-1', '2026-09-12T02:00:00Z'),
      event('event-1', 'component-1', '2026-09-12T01:00:00Z'),
    ]);
    expect(projected.map((item) => item.feedEventId)).toEqual(['event-2', 'event-1']);
    expect(projected.map((item) => item.id)).toEqual(['component-1', 'component-1']);
    expect(projected[0]).toMatchObject({
      feedComponentVersionId: 'version-event-2',
      feedPublisherId: 'publisher-event-2',
      feedVersion: 'event-2',
      feedRevision: 1,
      feedRender: {
        status: 'ready',
        image: { width: 1200, height: 800 },
      },
    });
  });

  it('appends a cursor page once without reordering existing events', () => {
    const current = projectPublicFeedItems([
      event('event-3', 'component-2', '2026-09-12T03:00:00Z'),
      event('event-2', 'component-1', '2026-09-12T02:00:00Z'),
    ]);
    const merged = appendPublicFeedItems(current, [
      event('event-2', 'component-1', '2026-09-12T02:00:00Z'),
      event('event-1', 'component-1', '2026-09-12T01:00:00Z'),
    ]);
    expect(merged.map((item) => item.feedEventId)).toEqual(['event-3', 'event-2', 'event-1']);
  });
});
