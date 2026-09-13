import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { GroupMembershipCandidateList } from '../ComponentGroupControls';
import type { ComponentResponse } from '../componentRepoApi';

function component(index: number): ComponentResponse {
  return {
    id: `component-${index}`,
    name: `Component ${index}`,
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
    createdAt: '2026-09-13T00:00:00Z',
    updatedAt: null,
  };
}

describe('GroupMembershipCandidateList', () => {
  it('renders more than 100 candidates and keeps continuation visible', () => {
    const markup = renderToStaticMarkup(
      <GroupMembershipCandidateList
        components={Array.from({ length: 101 }, (_, index) => component(index + 1))}
        hasMore
        loadMoreLabel="Load More"
        loadingMore={false}
        onLoadMore={() => undefined}
        onToggle={() => undefined}
        selectedIds={new Set(['component-101'])}
      />,
    );

    expect(markup.match(/type="checkbox"/g)).toHaveLength(101);
    expect(markup).toContain('Component 101');
    expect(markup).toContain('Load More');
    expect(markup).toContain('checked=""');
  });
});
