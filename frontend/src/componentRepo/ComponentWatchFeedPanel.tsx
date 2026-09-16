import React from 'react';
import { AlertCircle, Bell, CheckCircle2, LoaderCircle, RefreshCw, Settings2 } from 'lucide-react';
import { Link } from 'react-router-dom';

import appConfig from '../app/appConfig';
import { resolvedLocale, useAppTranslation } from '../i18n';
import {
  listComponentWatchFeed,
  starComponent,
  unstarComponent,
  type ComponentResponse,
  type ComponentWatchFeedItemResponse,
} from './componentRepoApi';
import { ComponentPublicFeedCard } from './ComponentPublicFeedCard';
import { projectPublicFeedItems } from './componentPublicFeed';

const feedPageSize = 20;

type WatchFeedState = {
  status: 'loading' | 'loading-more' | 'ready' | 'error';
  items: ComponentWatchFeedItemResponse[];
  nextCursor: string | null;
  error: string | null;
};

/** ComponentWatchFeedPanel 是组件广场“个人订阅”页签，只读取当前用户订阅产生的发布动态。 */
export function ComponentWatchFeedPanel() {
  const tr = useAppTranslation();
  const contentLocale = resolvedLocale();
  const requestIDRef = React.useRef(0);
  const sentinelRef = React.useRef<HTMLDivElement | null>(null);
  const [windowDays, setWindowDays] = React.useState(30);
  const [starMutations, setStarMutations] = React.useState<Set<string>>(new Set());
  const [notice, setNotice] = React.useState<string | null>(null);
  const [state, setState] = React.useState<WatchFeedState>({
    status: 'loading',
    items: [],
    nextCursor: null,
    error: null,
  });

  const load = React.useCallback(async (cursor?: string) => {
    const requestID = ++requestIDRef.current;
    setState((current) => ({
      ...current,
      status: cursor ? 'loading-more' : 'loading',
      items: cursor ? current.items : [],
      error: null,
    }));
    try {
      const result = await listComponentWatchFeed({
        limit: feedPageSize,
        cursor,
        // 后续页必须沿用 cursor 内冻结的窗口，只有首屏使用当前选择计算时间下界。
        since: cursor ? undefined : watchFeedSince(windowDays),
      });
      if (requestID !== requestIDRef.current) return;
      setState((current) => ({
        status: 'ready',
        items: cursor ? mergeFeedItems(current.items, result.items) : result.items,
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
  }, [windowDays]);

  React.useEffect(() => {
    // 错误响应在 API 边界按请求语言渲染；切换语言或时间窗口后重新读取首屏。
    void load();
    return () => {
      requestIDRef.current += 1;
    };
  }, [contentLocale, load]);

  React.useEffect(() => {
    const target = sentinelRef.current;
    if (!target || !state.nextCursor || state.status !== 'ready' || typeof IntersectionObserver === 'undefined') return undefined;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) void load(state.nextCursor ?? undefined);
    }, { rootMargin: '240px 0px' });
    observer.observe(target);
    return () => observer.disconnect();
  }, [load, state.nextCursor, state.status]);

  /** 订阅 Feed 与公共 Feed 共用 Star 交互；同一 Component 的多条事件必须同步显示关系状态。 */
  const toggleStar = async (component: ComponentResponse) => {
    if (component.ownedByActor || starMutations.has(component.id)) return;
    const starred = !component.starredByActor;
    setNotice(null);
    setStarMutations((current) => new Set(current).add(component.id));
    setState((current) => ({
      ...current,
      error: null,
      items: current.items.map((item) => item.component.id === component.id ? {
        ...item,
        component: {
          ...item.component,
          starredByActor: starred,
          starCount: Math.max(0, item.component.starCount + (starred ? 1 : -1)),
        },
      } : item),
    }));
    try {
      if (starred) await starComponent(component.id);
      else await unstarComponent(component.id);
      setNotice(tr(starred ? 'componentRepo:componentStarred' : 'componentRepo:componentUnstarred'));
    } catch (error) {
      setState((current) => ({
        ...current,
        status: 'error',
        error: error instanceof Error ? error.message : appConfig.texts.loadFailed,
      }));
      void load();
    } finally {
      setStarMutations((current) => {
        const next = new Set(current);
        next.delete(component.id);
        return next;
      });
    }
  };

  const cards = React.useMemo(() => projectPublicFeedItems(state.items), [state.items]);

  return (
    <section className="component-library-panel component-watch-feed-panel component-plaza-watch-feed">
      <header className="component-library-panel-header component-watch-feed-header">
        <div>
          <div className="component-library-title-row">
            <h2>{tr('componentRepo:subscriptionUpdates')}</h2>
          </div>
          <p>{tr('componentRepo:subscriptionUpdatesDescription')}</p>
        </div>
        <div className="component-watch-feed-controls">
          <label>
            <span>{tr('componentRepo:feedWindow')}</span>
            <select
              aria-label={tr('componentRepo:feedWindow')}
              onChange={(event) => setWindowDays(Number(event.target.value))}
              value={windowDays}
            >
              <option value={7}>{tr('componentRepo:last7Days')}</option>
              <option value={30}>{tr('componentRepo:last30Days')}</option>
              <option value={90}>{tr('componentRepo:last90Days')}</option>
            </select>
          </label>
          <button
            aria-label={tr('componentRepo:refreshWatchFeed')}
            className="component-library-refresh"
            onClick={() => void load()}
            type="button"
          >
            <RefreshCw aria-hidden="true" className={state.status === 'loading' ? 'component-library-spin' : undefined} />
          </button>
          <Link className="component-watch-manage-link" to={appConfig.routePaths.componentRepoWatches}>
            <Settings2 aria-hidden="true" />{tr('componentRepo:manageSubscriptions')}
          </Link>
        </div>
      </header>

      {state.error ? <div className="component-library-alert"><AlertCircle aria-hidden="true" />{state.error}</div> : null}
      {notice ? <div className="component-library-notice"><CheckCircle2 aria-hidden="true" />{notice}</div> : null}
      <div aria-busy={state.status === 'loading-more'} className="component-public-feed" aria-label={tr('componentRepo:watchFeedList')} role="feed">
        {cards.map((item) => (
          <ComponentPublicFeedCard
            detailPath={appConfig.routePaths.componentRepoDetail.replace(':componentId', encodeURIComponent(item.id))}
            item={item}
            key={item.feedEventId}
            onToggleStar={(component) => void toggleStar(component)}
            starPending={starMutations.has(item.id)}
          />
        ))}
      </div>
      {state.status === 'loading' && state.items.length === 0 ? (
        <div className="component-library-empty"><LoaderCircle className="component-library-spin" /><strong>{tr('componentRepo:loadingWatchFeed')}</strong></div>
      ) : null}
      {state.status !== 'loading' && state.items.length === 0 ? (
        <div className="component-library-empty">
          <span><Bell aria-hidden="true" /></span>
          <strong>{tr('componentRepo:noWatchUpdates')}</strong>
          <p>{tr('componentRepo:noWatchUpdatesDescription')}</p>
        </div>
      ) : null}
      {state.nextCursor ? (
        <div className="component-library-pagination" ref={sentinelRef}>
          <button disabled={state.status === 'loading-more'} onClick={() => void load(state.nextCursor ?? undefined)} type="button">
            {tr(state.status === 'loading-more' ? 'componentRepo:loadingMore' : 'componentRepo:loadMore')}
          </button>
        </div>
      ) : null}
    </section>
  );
}

/** mergeFeedItems 按事件键去重追加 cursor 页；服务端顺序包含微秒精度，前端不得重新排序降精度。 */
export function mergeFeedItems(
  existing: ComponentWatchFeedItemResponse[],
  incoming: ComponentWatchFeedItemResponse[],
): ComponentWatchFeedItemResponse[] {
  const known = new Set(existing.map((item) => item.eventId));
  return [...existing, ...incoming.filter((item) => !known.has(item.eventId))];
}

/** watchFeedSince 把页签的 7/30/90 天选择转换成首屏 RFC 3339 下界。 */
export function watchFeedSince(days: number, nowMilliseconds = Date.now()): string {
  return new Date(nowMilliseconds - days * 24 * 60 * 60 * 1000).toISOString();
}
