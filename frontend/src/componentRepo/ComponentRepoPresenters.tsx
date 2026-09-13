import React from 'react';
import { AlertCircle, LoaderCircle } from 'lucide-react';
import appConfig from '../app/appConfig';
import { useAppTranslation, useDynamicTranslation, type TranslationKey } from '../i18n';
import { formatDateTime, formatNumber } from '../i18n/formatters';
import { ComponentVersionActions } from './ComponentVersionActions';
import type { ComponentResponse, ComponentVersionResponse } from './componentRepoApi';
import type { PublicFeedComponentResponse } from './componentPublicFeed';

export type LibraryFilter = 'all' | 'draft' | 'published';
export type LibraryItem = {
  key: string;
  id: string;
  name: string;
  status: string;
  createdAt: string;
  starredAt?: string;
  data: ComponentResponse;
};

export function VersionDropdown({ component, onDeleted, state, versions }: {
  component: ComponentResponse;
  onDeleted: (version: ComponentVersionResponse) => void;
  state: 'idle' | 'loading' | 'error';
  versions: ComponentVersionResponse[];
}) {
  const tr = useAppTranslation();
  return (
    <section className="component-version-dropdown" role="menu">
        <div className="component-version-list">
          {state === 'loading' ? <div className="component-library-empty"><LoaderCircle className="component-library-spin" /><strong>{tr('componentRepo:loadingVersions')}</strong></div> : null}
          {state === 'error' ? <div className="component-library-alert"><AlertCircle />{tr('componentRepo:failedToLoadVersions')}</div> : null}
          {state === 'idle' && versions.length === 0 ? <div className="component-library-empty"><strong>{tr('componentRepo:noComponentVersions')}</strong></div> : null}
          {versions.map((version) => (
            <article key={version.id}>
              <div><strong>v{version.version}</strong><span>{tr('componentRepo:revision')} {version.revision}</span></div>
              <StatusPill status={version.id === component.currentVersionId ? 'published' : 'draft'} />
              <ComponentVersionActions
                componentName={component.name}
                isOnlyVersion={versions.length === 1}
                onDeleted={onDeleted}
                version={version}
              />
            </article>
          ))}
        </div>
    </section>
  );
}

export function SummaryCard({ icon, label, tone, value }: { icon: React.ReactNode; label: string; tone: string; value: number }) {
  return <article className={`component-library-summary-card component-library-summary-card-${tone}`}><span>{icon}</span><div><strong>{value}</strong><p>{label}</p></div></article>;
}

export function ComponentLogicalSize({ size }: { size: ComponentResponse['logicalSize'] }) {
  const tr = useAppTranslation();
  if (!size) {
    return <span aria-label={tr('componentRepo:sizeUnavailable')} className="component-library-size-unavailable" role="cell">—</span>;
  }
  const width = formatDimension(size.widthStud);
  const depth = formatDimension(size.depthStud);
  const height = formatDimension(size.heightPlate);
  return (
    <div
      aria-label={tr('componentRepo:sizeAccessibleLabel', { width, depth, height })}
      className="component-library-size"
      role="cell"
    >
      <strong aria-hidden="true">{width} × {depth} × {height}</strong>
      <small aria-hidden="true">{tr('componentRepo:sizeUnits')}</small>
    </div>
  );
}

export function buildLibraryItems(components: PublicFeedComponentResponse[]): LibraryItem[] {
  return components.map((item) => ({
    key: item.feedEventId ?? item.id,
    id: item.id,
    name: item.name,
    status: item.status,
    createdAt: item.feedOccurredAt ?? item.createdAt,
    starredAt: item.starredAt,
    data: item,
  }));
}

export function statusesForFilter(filter: LibraryFilter): string[] | null {
  if (filter === 'all') return null;
  if (filter === 'draft') return ['draft'];
  if (filter === 'published') return ['active'];
  return null;
}

export function sumStatuses(counts: Record<string, number>, statuses: string[]): number {
  return statuses.reduce((total, status) => total + (counts[status] ?? 0), 0);
}

export function shortId(id: string): string { return id.length > 16 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id; }
function formatDimension(value: number): string { return formatNumber(value, { maximumFractionDigits: 2 }); }
export function formatDate(value: string): string { return formatDateTime(value, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }); }

const statusLabels: Partial<Record<string, TranslationKey>> = {
  uploaded: 'componentRepo:uploaded', parsing: 'componentRepo:parsing', parsed: 'componentRepo:pendingReview', pending_review: 'componentRepo:pendingReview', in_review: 'componentRepo:inReview',
  draft: 'componentRepo:draft', active: 'componentRepo:published', published: 'componentRepo:published', failed: 'componentRepo:failed', blocked: 'componentRepo:blocked', rejected: 'componentRepo:rejected', archived: 'componentRepo:archived',
  confirmed: 'componentRepo:confirmed', passed: 'componentRepo:passed', pass: 'componentRepo:passed', pending: 'componentRepo:pending', ready: 'componentRepo:ready', processing: 'componentRepo:processing',
};

export function StatusPill({ status }: { status: string }) {
  const trDynamic = useDynamicTranslation();
  const translationKey = statusLabels[status];
  return <span className={`component-repo-status component-repo-status-${status}`}>{translationKey ? trDynamic(translationKey) : status}</span>;
}

export function routeFor(page: keyof typeof appConfig.routePaths): string {
  return appConfig.routePaths[page];
}
