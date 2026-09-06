import React from 'react';
import {
  AlertCircle,
  Bell,
  Boxes,
  ChevronRight,
  LoaderCircle,
  RefreshCw,
  Search,
  X,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import appConfig from '../app/appConfig';
import { resolvedLocale, useAppTranslation } from '../i18n';
import { formatDateTime } from '../i18n/formatters';
import {
  listComponentWatches,
  unwatchComponent,
  type ComponentWatchListItemResponse,
} from './componentRepoApi';

const watchPageSize = 20;

type WatchListState = {
  status: 'loading' | 'loading-more' | 'ready' | 'error';
  items: ComponentWatchListItemResponse[];
  nextCursor: string | null;
  error: string | null;
};

type WatchFilters = {
  query: string;
  category: string;
};

const emptyFilters: WatchFilters = { query: '', category: '' };

/** ComponentWatchListPage 展示当前用户的 active Watch，并始终通过服务端 cursor 继续分页。 */
export function ComponentWatchListPage() {
  const tr = useAppTranslation();
  const contentLocale = resolvedLocale();
  const requestIDRef = React.useRef(0);
  const [state, setState] = React.useState<WatchListState>({
    status: 'loading',
    items: [],
    nextCursor: null,
    error: null,
  });
  const [draftFilters, setDraftFilters] = React.useState<WatchFilters>(emptyFilters);
  const [filters, setFilters] = React.useState<WatchFilters>(emptyFilters);
  const [mutatingIDs, setMutatingIDs] = React.useState<Set<string>>(new Set());

  const load = React.useCallback(async (cursor?: string) => {
    const requestID = ++requestIDRef.current;
    setState((current) => ({
      ...current,
      status: cursor ? 'loading-more' : 'loading',
      items: cursor ? current.items : [],
      error: null,
    }));
    try {
      const result = await listComponentWatches({
        limit: watchPageSize,
        cursor,
        query: filters.query,
        category: filters.category,
      });
      if (requestID !== requestIDRef.current) return;
      setState((current) => ({
        status: 'ready',
        items: cursor ? mergeWatchItems(current.items, result.items) : result.items,
        nextCursor: result.nextCursor,
        error: null,
      }));
    } catch (error) {
      if (requestID !== requestIDRef.current) return;
      setState((current) => ({
        ...current,
        status: 'error',
        error: error instanceof Error ? error.message : appConfig.texts.loadFailed,
      }));
    }
  }, [filters.category, filters.query]);

  React.useEffect(() => {
    // 错误响应在 API 边界按当时语言渲染；切换语言后重新读取，避免页面继续保留旧语言句子。
    void load();
    return () => {
      requestIDRef.current += 1;
    };
  }, [contentLocale, load]);

  /** 取消订阅采用乐观移除；请求失败时恢复原位置，避免短暂网络错误造成错误的本地状态。 */
  const removeWatch = async (componentID: string) => {
    if (mutatingIDs.has(componentID)) return;
    const index = state.items.findIndex((item) => item.componentId === componentID);
    if (index < 0) return;
    const removed = state.items[index];
    setMutatingIDs((current) => new Set(current).add(componentID));
    setState((current) => ({
      ...current,
      items: current.items.filter((item) => item.componentId !== componentID),
      error: null,
    }));
    try {
      await unwatchComponent(componentID);
    } catch (error) {
      setState((current) => {
        const items = [...current.items];
        items.splice(Math.min(index, items.length), 0, removed);
        return {
          ...current,
          items: mergeWatchItems([], items),
          status: 'error',
          error: error instanceof Error ? error.message : appConfig.texts.loadFailed,
        };
      });
    } finally {
      setMutatingIDs((current) => {
        const next = new Set(current);
        next.delete(componentID);
        return next;
      });
    }
  };

  const hasFilters = filters.query !== '' || filters.category !== '';

  return (
    <section className="component-library-page component-watch-page">
      <header className="component-library-hero">
        <div className="component-library-heading">
          <span className="component-library-heading-icon"><Bell aria-hidden="true" /></span>
          <div>
            <h1>{tr('componentRepo:mySubscriptions')}</h1>
            <p>{tr('componentRepo:mySubscriptionsDescription')}</p>
          </div>
        </div>
        <nav aria-label={tr('componentRepo:componentLibrarySections')} className="component-library-tabs">
          <Link className="component-library-tab" to={appConfig.routePaths.componentRepo}>
            <Boxes aria-hidden="true" />
            {tr('componentRepo:componentLibrary')}
          </Link>
          <span aria-current="page" className="component-library-tab component-library-tab-active">
            <Bell aria-hidden="true" />
            {tr('componentRepo:mySubscriptions')}
          </span>
        </nav>
      </header>

      <section className="component-library-panel">
        <header className="component-library-panel-header">
          <div>
            <div className="component-library-title-row">
              <h2>{tr('componentRepo:watchedComponents')}</h2>
              <span>{state.items.length}</span>
            </div>
            <p>{tr('componentRepo:watchListCountDescription')}</p>
          </div>
        </header>

        <form
          className="component-library-toolbar component-watch-toolbar"
          onSubmit={(event) => {
            event.preventDefault();
            setFilters({
              query: draftFilters.query.trim(),
              category: draftFilters.category.trim(),
            });
          }}
        >
          <label className="component-library-search">
            <Search aria-hidden="true" />
            <input
              aria-label={tr('componentRepo:searchSubscriptions')}
              maxLength={200}
              onChange={(event) => setDraftFilters((current) => ({ ...current, query: event.target.value }))}
              placeholder={tr('componentRepo:searchComponentNameOrId')}
              value={draftFilters.query}
            />
          </label>
          <label className="component-library-category-filter">
            <span>{tr('componentRepo:categoryFilter')}</span>
            <input
              aria-label={tr('componentRepo:categoryFilter')}
              maxLength={128}
              onChange={(event) => setDraftFilters((current) => ({ ...current, category: event.target.value }))}
              placeholder={tr('componentRepo:allCategories')}
              value={draftFilters.category}
            />
          </label>
          <div className="component-watch-toolbar-actions">
            <button className="component-repo-secondary-button" type="submit">
              <Search aria-hidden="true" />{tr('componentRepo:applyFilters')}
            </button>
            {draftFilters.query !== '' || draftFilters.category !== '' || hasFilters ? (
              <button
                aria-label={tr('componentRepo:clearSubscriptionFilters')}
                className="component-library-refresh"
                onClick={() => {
                  setDraftFilters(emptyFilters);
                  setFilters(emptyFilters);
                }}
                type="button"
              >
                <X aria-hidden="true" />
              </button>
            ) : null}
            <button
              aria-label={tr('componentRepo:refreshSubscriptionList')}
              className="component-library-refresh"
              onClick={() => void load()}
              type="button"
            >
              <RefreshCw aria-hidden="true" className={state.status === 'loading' ? 'component-library-spin' : undefined} />
            </button>
          </div>
        </form>

        {state.error ? <div className="component-library-alert"><AlertCircle aria-hidden="true" />{state.error}</div> : null}

        <div className="component-library-table" role="table" aria-label={tr('componentRepo:subscriptionList')}>
          <div className="component-library-table-head component-watch-table-grid" role="row">
            <span role="columnheader">{tr('componentRepo:component')}</span>
            <span role="columnheader">{tr('componentRepo:subscriptionLevel')}</span>
            <span role="columnheader">{tr('componentRepo:latestPublishedVersion')}</span>
            <span role="columnheader">{tr('componentRepo:watchedAt')}</span>
            <span role="columnheader">{tr('componentRepo:actions')}</span>
          </div>
          {state.items.map((item) => (
            <article className="component-library-row component-watch-table-grid" key={item.componentId} role="row">
              <div className="component-library-item-main" role="cell">
                <span className="component-library-file-icon component-library-file-icon-blue"><Boxes aria-hidden="true" /></span>
                <div>
                  <strong>{item.name}</strong>
                  <span>{item.category ?? tr('componentRepo:uncategorized')} · {shortID(item.componentId)}</span>
                </div>
              </div>
              <span className="component-library-type" role="cell">{tr('componentRepo:watchReleasesOnly')}</span>
              <div className="component-watch-version" role="cell">
                <strong>{item.version && item.revision
                  ? tr('componentRepo:versionAndRevision', { version: item.version, revision: item.revision })
                  : tr('componentRepo:versionUnavailable')}</strong>
                <span>{item.publishedAt ? formatWatchDate(item.publishedAt) : '—'}</span>
              </div>
              <span className="component-library-date" role="cell">{formatWatchDate(item.watchedAt)}</span>
              <div className="component-library-row-action" role="cell">
                <div className="component-watch-actions">
                  <Link to={appConfig.routePaths.componentRepoDetail.replace(':componentId', encodeURIComponent(item.componentId))}>
                    {tr('componentRepo:details')}<ChevronRight aria-hidden="true" />
                  </Link>
                  <button
                    disabled={mutatingIDs.has(item.componentId)}
                    onClick={() => void removeWatch(item.componentId)}
                    type="button"
                  >
                    {mutatingIDs.has(item.componentId) ? <LoaderCircle className="component-library-spin" /> : <Bell aria-hidden="true" />}
                    {tr('componentRepo:unwatchComponent')}
                  </button>
                </div>
              </div>
            </article>
          ))}
        </div>

        {state.status === 'loading' && state.items.length === 0 ? (
          <div className="component-library-empty"><LoaderCircle className="component-library-spin" /><strong>{tr('componentRepo:loadingSubscriptions')}</strong></div>
        ) : null}
        {state.status !== 'loading' && state.items.length === 0 ? (
          <div className="component-library-empty">
            <span><Bell aria-hidden="true" /></span>
            <strong>{tr(hasFilters ? 'componentRepo:noMatchingSubscriptions' : 'componentRepo:noSubscriptions')}</strong>
            <p>{tr(hasFilters ? 'componentRepo:tryChangingSubscriptionFilters' : 'componentRepo:browseComponentsToWatch')}</p>
            {!hasFilters ? <Link className="component-repo-primary-button" to={appConfig.routePaths.componentRepo}>{tr('componentRepo:browseComponents')}</Link> : null}
          </div>
        ) : null}
        {state.nextCursor ? (
          <nav aria-label={tr('componentRepo:subscriptionPagination')} className="component-library-pagination">
            <button
              disabled={state.status === 'loading-more'}
              onClick={() => void load(state.nextCursor ?? undefined)}
              type="button"
            >
              {state.status === 'loading-more' ? tr('componentRepo:loadingMore') : tr('componentRepo:loadMore')}
            </button>
          </nav>
        ) : null}
      </section>
    </section>
  );
}

function mergeWatchItems(
  existing: ComponentWatchListItemResponse[],
  incoming: ComponentWatchListItemResponse[],
): ComponentWatchListItemResponse[] {
  const known = new Set(existing.map((item) => item.componentId));
  return [...existing, ...incoming.filter((item) => !known.has(item.componentId))];
}

function shortID(id: string): string {
  return id.length > 16 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id;
}

function formatWatchDate(value: string): string {
  return formatDateTime(value, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}
