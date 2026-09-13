import React from 'react';
import { Box, ChevronRight, LoaderCircle, Star, UserRound } from 'lucide-react';
import { Link } from 'react-router-dom';

import { useAppTranslation } from '../i18n';
import { formatDateTime, formatNumber } from '../i18n/formatters';
import { type ComponentPublicFeedItemResponse, type ComponentResponse } from './componentRepoApi';
import type { PublicFeedComponentResponse } from './componentPublicFeed';

type ComponentPublicFeedCardProps = {
  item: PublicFeedComponentResponse;
  starPending: boolean;
  onToggleStar: (component: ComponentResponse) => void;
  detailPath: string;
};

/** ComponentPublicFeedCard 以一次发布事件为边界展示发布人、事件版本、Worker 派生图片和用户原文。 */
export function ComponentPublicFeedCard({
  item,
  starPending,
  onToggleStar,
  detailPath,
}: ComponentPublicFeedCardProps) {
  const tr = useAppTranslation();
  const publisher = shortPublisherId(item.feedPublisherId);

  return (
    <article className="component-public-feed-card">
      <header className="component-public-feed-author">
        <span aria-hidden="true" className="component-public-feed-avatar">
          <UserRound />
        </span>
        <div>
          <strong>{tr('componentRepo:publishedBy', { publisher })}</strong>
          <span>{item.feedOccurredAt ? formatDateTime(item.feedOccurredAt) : ''}</span>
        </div>
      </header>

      <div className="component-public-feed-heading">
        <div>
          <Link to={detailPath}>{item.name}</Link>
          <span>{tr('componentRepo:publishedVersionUpdate', {
            version: item.feedVersion ?? '',
            revision: item.feedRevision ?? 0,
          })}</span>
        </div>
        <span className="component-public-feed-category">{item.category ?? tr('componentRepo:uncategorized')}</span>
      </div>

      <ComponentFeedPreview
        alt={tr('componentRepo:componentPreviewAlt', { componentName: item.name })}
        image={item.feedRender?.image}
      />

      <div className="component-public-feed-copy">
        <p lang={item.contentLocale}>{item.description?.trim() || tr('componentRepo:noComponentDescription')}</p>
        {item.feedReleaseNote?.trim() ? (
          <div className="component-public-feed-release-note">
            <strong>{tr('componentRepo:releaseNotes')}</strong>
            <p lang={item.feedReleaseNoteLocale ?? item.contentLocale}>{item.feedReleaseNote}</p>
          </div>
        ) : null}
      </div>

      <footer className="component-public-feed-actions">
        {!item.ownedByActor ? (
          <button
            aria-label={tr(item.starredByActor ? 'componentRepo:unstarComponent' : 'componentRepo:starComponent')}
            aria-pressed={item.starredByActor}
            disabled={starPending}
            onClick={() => onToggleStar(item)}
            type="button"
          >
            {starPending ? <LoaderCircle className="component-library-spin" /> : (
              <Star aria-hidden="true" fill={item.starredByActor ? 'currentColor' : 'none'} />
            )}
            {formatNumber(item.starCount)}
          </button>
        ) : (
          <span title={tr('componentRepo:starCount')}><Star aria-hidden="true" />{formatNumber(item.starCount)}</span>
        )}
        <Link to={detailPath}>{tr('componentRepo:details')}<ChevronRight aria-hidden="true" /></Link>
      </footer>
    </article>
  );
}

/** ComponentFeedPreview 只展示 Worker 的终态派生图；失败终态使用统一占位，不再在浏览器下载 GLB 即时截图。 */
function ComponentFeedPreview({
  alt,
  image,
}: {
  alt: string;
  image?: ComponentPublicFeedItemResponse['render']['image'];
}) {
  const tr = useAppTranslation();
  return (
    <div className="component-public-feed-preview">
      {image ? <img alt={alt} decoding="async" height={image.height} loading="lazy" src={image.url} width={image.width} /> : (
        <div>
          <Box aria-hidden="true" />
          <span>{tr('componentRepo:previewUnavailable')}</span>
        </div>
      )}
    </div>
  );
}

function shortPublisherId(id?: string): string {
  if (!id) return '—';
  return id.length > 12 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id;
}
