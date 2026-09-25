import React from 'react';
import { AlertCircle, Bell, Boxes, CheckCircle2, LoaderCircle, RefreshCw, Search } from 'lucide-react';
import { Link, useSearchParams } from 'react-router-dom';

import appConfig from '../app/appConfig';
import { resolvedLocale, useAppTranslation } from '../i18n';
import {
  listComponentPublicFeed,
  starComponent,
  unstarComponent,
  type ComponentResponse,
} from './componentRepoApi';
import { ComponentPublicFeedCard } from './ComponentPublicFeedCard';
import { routeFor } from './ComponentRepoPresenters';
import { ComponentWatchFeedPanel } from './ComponentWatchFeedPanel';
import {
  componentSearchFilters,
  ComponentSearchForm,
  emptyComponentSearchValues,
  hasComponentSearchFilters,
  type ComponentSearchValues,
} from './ComponentSearchForm';
import {
  appendPublicFeedItems,
  projectPublicFeedItems,
  type PublicFeedComponentResponse,
} from './componentPublicFeed';

const feedPageSize = 20;

type PublicFeedState = {
  status: 'loading' | 'ready' | 'error';
  items: PublicFeedComponentResponse[];
  nextCursor: string | null;
  loadingMore: boolean;
  error: string | null;
};

/** ComponentPlazaPage 独立拥有公共与个人订阅 Feed 壳层，不初始化个人仓库的分组、上传或版本状态。 */
export function ComponentPlazaPage() {
  const [searchParams] = useSearchParams();
  const tab = searchParams.get('tab') === 'subscriptions' ? 'subscriptions' : 'public';
  const tr = useAppTranslation();
  const contentLocale = resolvedLocale();
  const requestIDRef = React.useRef(0);
  const loadingMoreRef = React.useRef(false);
  const sentinelRef = React.useRef<HTMLDivElement | null>(null);
  const [searchDraft, setSearchDraft] = React.useState<ComponentSearchValues>(emptyComponentSearchValues);
  const [searchFilters, setSearchFilters] = React.useState(() => componentSearchFilters(emptyComponentSearchValues));
  const [refreshRevision, setRefreshRevision] = React.useState(0);
  const [starMutations, setStarMutations] = React.useState<Set<string>>(new Set());
  const [notice, setNotice] = React.useState<string | null>(null);
  const [state, setState] = React.useState<PublicFeedState>({
    status: 'loading',
    items: [],
    nextCursor: null,
    loadingMore: false,
    error: null,
  });

  const loadFirstPage = React.useCallback(async () => {
    const requestID = ++requestIDRef.current;
    loadingMoreRef.current = false;
    setState((current) => ({ ...current, status: 'loading', items: [], nextCursor: null, loadingMore: false, error: null }));
    try {
      const result = await listComponentPublicFeed({ limit: feedPageSize, filters: searchFilters });
      if (requestID !== requestIDRef.current) return;
      setState({
        status: 'ready',
        items: projectPublicFeedItems(result.items),
        nextCursor: result.nextCursor,
        loadingMore: false,
        error: null,
      });
    } catch (error) {
      if (requestID !== requestIDRef.current) return;
      setState({
        status: 'error',
        items: [],
        nextCursor: null,
        loadingMore: false,
        error: error instanceof Error ? error.message : appConfig.texts.loadFailed,
      });
    }
  }, [searchFilters]);

  React.useEffect(() => {
    if (tab !== 'public') return undefined;
    void loadFirstPage();
    return () => {
      requestIDRef.current += 1;
    };
  }, [contentLocale, loadFirstPage, refreshRevision, tab]);

  // 公共 Feed 的续页保持单飞，并用请求代次阻止搜索、刷新或切换页签后的旧响应污染当前列表。
  const loadMore = React.useCallback(async () => {
    if (tab !== 'public' || state.status !== 'ready' || !state.nextCursor || loadingMoreRef.current) return;
    const requestID = requestIDRef.current;
    const cursor = state.nextCursor;
    loadingMoreRef.current = true;
    setState((current) => ({ ...current, loadingMore: true }));
    try {
      const result = await listComponentPublicFeed({ limit: feedPageSize, cursor, filters: searchFilters });
      if (requestID !== requestIDRef.current) return;
      setState((current) => ({
        ...current,
        items: current.nextCursor === cursor ? appendPublicFeedItems(current.items, result.items) : current.items,
        nextCursor: current.nextCursor === cursor ? result.nextCursor : current.nextCursor,
        loadingMore: false,
      }));
    } catch (error) {
      if (requestID !== requestIDRef.current) return;
      setState((current) => ({
        ...current,
        loadingMore: false,
        error: error instanceof Error ? error.message : appConfig.texts.loadFailed,
      }));
    } finally {
      loadingMoreRef.current = false;
    }
  }, [searchFilters, state.nextCursor, state.status, tab]);

  React.useEffect(() => {
    const target = sentinelRef.current;
    if (tab !== 'public' || !target || !state.nextCursor || typeof IntersectionObserver === 'undefined') return undefined;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) void loadMore();
    }, { rootMargin: '240px 0px' });
    observer.observe(target);
    return () => observer.disconnect();
  }, [loadMore, state.nextCursor, tab]);

  /** Star 变化同步更新当前页面中同一 Component 的全部发布事件卡片，失败后以首屏重读恢复权威状态。 */
  const toggleStar = async (component: ComponentResponse) => {
    if (component.ownedByActor || starMutations.has(component.id)) return;
    const starred = !component.starredByActor;
    setNotice(null);
    setStarMutations((current) => new Set(current).add(component.id));
    setState((current) => ({
      ...current,
      error: null,
      items: current.items.map((item) => item.id === component.id ? {
        ...item,
        starredByActor: starred,
        starCount: Math.max(0, item.starCount + (starred ? 1 : -1)),
      } : item),
    }));
    try {
      if (starred) await starComponent(component.id);
      else await unstarComponent(component.id);
      setNotice(tr(starred ? 'componentRepo:componentStarred' : 'componentRepo:componentUnstarred'));
    } catch (error) {
      setState((current) => ({
        ...current,
        error: error instanceof Error ? error.message : appConfig.texts.loadFailed,
      }));
      setRefreshRevision((current) => current + 1);
    } finally {
      setStarMutations((current) => {
        const next = new Set(current);
        next.delete(component.id);
        return next;
      });
    }
  };

  return (
    <section className="component-library-page component-plaza-page">
      <header className="component-library-hero">
        <div className="component-library-heading">
          <span className="component-library-heading-icon"><Boxes aria-hidden="true" /></span>
          <div>
            <h1>{tr('app:navigation.modelPlaza')}</h1>
            <p>{tr('app:navigation.modelPlazaDescription')}</p>
          </div>
        </div>
        <nav aria-label={tr('componentRepo:plazaFeedTabs')} className="component-library-tabs">
          <Link
            aria-current={tab === 'public' ? 'page' : undefined}
            className={`component-library-tab ${tab === 'public' ? 'component-library-tab-active' : ''}`}
            to={routeFor('modelPlaza')}
          >
            <Boxes aria-hidden="true" />{tr('componentRepo:publicFeedTab')}
          </Link>
          <Link
            aria-current={tab === 'subscriptions' ? 'page' : undefined}
            className={`component-library-tab ${tab === 'subscriptions' ? 'component-library-tab-active' : ''}`}
            to={`${routeFor('modelPlaza')}?tab=subscriptions`}
          >
            <Bell aria-hidden="true" />{tr('componentRepo:personalSubscriptionsTab')}
          </Link>
        </nav>
      </header>

      {tab === 'subscriptions' ? <ComponentWatchFeedPanel /> : (
        <section className="component-library-panel">
          <header className="component-library-panel-header">
            <div>
              <div className="component-library-title-row"><h2>{tr('componentRepo:communityFeed')}</h2></div>
              <p>{tr('componentRepo:communityLibraryDescription')}</p>
            </div>
          </header>

          <ComponentSearchForm
            loading={state.status === 'loading'}
            onChange={setSearchDraft}
            onSubmit={() => setSearchFilters(componentSearchFilters(searchDraft))}
            values={searchDraft}
          />
          <div className="component-library-toolbar component-library-filter-toolbar">
            <button
              aria-label={tr('componentRepo:refreshComponentList')}
              className="component-library-refresh"
              onClick={() => setRefreshRevision((current) => current + 1)}
              type="button"
            >
              <RefreshCw aria-hidden="true" className={state.status === 'loading' ? 'component-library-spin' : undefined} />
            </button>
          </div>

          {state.error ? <div className="component-library-alert"><AlertCircle aria-hidden="true" />{state.error}</div> : null}
          {notice ? <div className="component-library-notice"><CheckCircle2 aria-hidden="true" />{notice}</div> : null}
          <div aria-busy={state.loadingMore} className="component-public-feed" aria-label={tr('componentRepo:communityFeed')} role="feed">
            {state.items.map((item) => (
              <ComponentPublicFeedCard
                detailPath={routeFor('componentRepoDetail').replace(':componentId', encodeURIComponent(item.id))}
                item={item}
                key={item.feedEventId}
                onToggleStar={(component) => void toggleStar(component)}
                starPending={starMutations.has(item.id)}
              />
            ))}
          </div>
          {state.status === 'loading' && state.items.length === 0 ? (
            <div className="component-library-empty"><LoaderCircle className="component-library-spin" /><strong>{tr('componentRepo:loadingComponents')}</strong></div>
          ) : null}
          {state.status !== 'loading' && state.items.length === 0 ? (
            <div className="component-library-empty">
              <span><Search aria-hidden="true" /></span>
              <strong>{tr(hasComponentSearchFilters(searchFilters) ? 'componentRepo:noMatchingComponents' : 'componentRepo:noCommunityUpdates')}</strong>
              <p>{tr(hasComponentSearchFilters(searchFilters) ? 'componentRepo:tryChangingTheSearchTermOrStatusFilter' : 'componentRepo:noCommunityUpdatesDescription')}</p>
            </div>
          ) : null}
          {state.nextCursor ? (
            <div className="component-library-pagination" ref={sentinelRef}>
              <button disabled={state.loadingMore} onClick={() => void loadMore()} type="button">
                {tr(state.loadingMore ? 'componentRepo:loadingMore' : 'componentRepo:loadMore')}
              </button>
            </div>
          ) : null}
        </section>
      )}
    </section>
  );
}
