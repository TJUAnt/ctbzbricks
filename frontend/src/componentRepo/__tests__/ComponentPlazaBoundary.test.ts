import { describe, expect, it } from 'vitest';

import plazaSource from '../ComponentPlazaPage.tsx?raw';
import repoSource from '../ComponentRepoPage.tsx?raw';
import watchFeedSource from '../ComponentWatchFeedPanel.tsx?raw';

describe('Component plaza module boundary', () => {
  it('does not initialize personal repository groups, uploads, or version management', () => {
    expect(plazaSource).not.toContain('listComponentGroups');
    expect(plazaSource).not.toContain('ComponentGroupSidebar');
    expect(plazaSource).not.toContain('ComponentUploadDialog');
    expect(plazaSource).not.toContain('listComponentVersions');
  });

  it('keeps public plaza state out of the personal repository page', () => {
    expect(repoSource).not.toContain('listComponentPublicFeed');
    expect(repoSource).not.toContain('ComponentWatchFeedPanel');
    expect(repoSource).not.toContain("mode?: 'mine' | 'plaza'");
  });

  it('renders personal subscriptions through the same event card as the public Feed', () => {
    expect(watchFeedSource).toContain("import { ComponentPublicFeedCard } from './ComponentPublicFeedCard'");
    expect(watchFeedSource).toContain('<ComponentPublicFeedCard');
    expect(watchFeedSource).not.toContain('component-watch-feed-item');
  });
});
