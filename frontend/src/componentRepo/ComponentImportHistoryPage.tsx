import React from 'react';
import {
  ExternalLink,
  FileClock,
  FileText,
  LoaderCircle,
  RefreshCw,
  Search,
  Upload,
} from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { localizeStructuredMessage } from '../api/client';
import appConfig from '../app/appConfig';
import { formatDateTime, formatNumber } from '../i18n/formatters';
import { useAppTranslation, useDynamicTranslation, type TranslationKey } from '../i18n';
import {
  listComponentImports,
  type ComponentImportRecordResponse,
  type ComponentImportHistoryResponse,
} from './componentRepoApi';
import { routeFor, StatusPill } from './ComponentRepoPage';

type ImportFilter = 'all' | ComponentImportRecordResponse['processingStatus'];

const importPageSize = 20;
const importPollIntervalMs = 5_000;

// ComponentImportHistoryPage 是全局导入记录入口；上传和 Worker 状态变更仍由既有 API/Worker 边界负责。
export function ComponentImportHistoryPage() {
  const tr = useAppTranslation();
  const navigate = useNavigate();
  return (
    <section className="component-repo-page component-import-history-page">
      <header className="component-repo-header">
        <div>
          <h1>{tr('componentRepo:importHistory')}</h1>
          <p>{tr('componentRepo:importHistoryDescription')}</p>
        </div>
        <div className="component-repo-actions">
          <button onClick={() => navigate(routeFor('componentRepo'))} type="button">
            {appConfig.texts.componentRepoBackToList}
          </button>
          <button
            className="component-repo-primary-button"
            onClick={() => navigate(routeFor('componentRepoImport'))}
            type="button"
          >
            <Upload aria-hidden="true" />
            {tr('componentRepo:uploadComponent')}
          </button>
        </div>
      </header>
      <section className="component-repo-panel">
        <ComponentImportHistoryList />
      </section>
    </section>
  );
}

// ComponentImportHistoryList 可在全局页面和组件详情 Tab 复用；componentId 只收窄服务端 owner-scoped 查询。
export function ComponentImportHistoryList({ componentId }: { componentId?: string }) {
  const tr = useAppTranslation();
  const trDynamic = useDynamicTranslation();
  const [filter, setFilter] = React.useState<ImportFilter>('all');
  const [query, setQuery] = React.useState('');
  const [page, setPage] = React.useState(1);
  const [refreshToken, setRefreshToken] = React.useState(0);
  const [state, setState] = React.useState<{
    data: ComponentImportHistoryResponse | null;
    loading: boolean;
    error: string | null;
  }>({ data: null, loading: true, error: null });

  React.useEffect(() => {
    let active = true;
    setState((current) => ({ ...current, loading: true, error: null }));
    void listComponentImports({
      page,
      pageSize: importPageSize,
      processingStatus: filter === 'all' ? null : filter,
      query: query.trim(),
      componentId,
    }).then((data) => {
      if (active) setState({ data, loading: false, error: null });
    }).catch((error: unknown) => {
      if (!active) return;
      setState((current) => ({
        ...current,
        loading: false,
        error: error instanceof Error ? error.message : tr('componentRepo:importRecordsLoadFailed'),
      }));
    });
    return () => {
      active = false;
    };
  }, [componentId, filter, page, query, refreshToken, tr]);

  const hasProcessing = (state.data?.items ?? []).some(
    (item) => item.processingStatus === 'processing',
  );
  React.useEffect(() => {
    if (!hasProcessing) return undefined;
    // 只在可见页面存在处理中记录时刷新列表，避免对每条 Import 建立独立轮询。
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') setRefreshToken((current) => current + 1);
    }, importPollIntervalMs);
    return () => window.clearInterval(timer);
  }, [hasProcessing]);

  const data = state.data;
  const counts = data?.statusCounts ?? { processing: 0, ready: 0, failed: 0 };
  const totalCount = counts.processing + counts.ready + counts.failed;
  const filterOptions: Array<[ImportFilter, TranslationKey, number]> = [
    ['all', 'componentRepo:all', totalCount],
    ['processing', 'componentRepo:processing', counts.processing],
    ['ready', 'componentRepo:ready', counts.ready],
    ['failed', 'componentRepo:failed', counts.failed],
  ];

  return (
    <div className="component-import-history">
      <div className="component-import-history-toolbar">
        <label className="component-library-search">
          <Search aria-hidden="true" />
          <input
            aria-label={tr('componentRepo:searchImportRecords')}
            onChange={(event) => {
              setQuery(event.target.value);
              setPage(1);
            }}
            placeholder={tr('componentRepo:searchImportFileOrId')}
            value={query}
          />
        </label>
        <div className="component-library-filters" role="group" aria-label={tr('componentRepo:filterImportsByStatus')}>
          {filterOptions.map(([value, label, count]) => (
            <button
              className={filter === value ? 'component-library-filter-active' : undefined}
              key={value}
              onClick={() => {
                setFilter(value);
                setPage(1);
              }}
              type="button"
            >
              {trDynamic(label)} <span>{formatNumber(count)}</span>
            </button>
          ))}
        </div>
        <button
          aria-label={tr('componentRepo:refreshImportRecords')}
          className="component-library-refresh"
          onClick={() => setRefreshToken((current) => current + 1)}
          type="button"
        >
          <RefreshCw aria-hidden="true" />
        </button>
      </div>

      {state.error ? <div className="component-library-alert">{state.error}</div> : null}
      {state.loading && !data ? (
        <div className="component-library-empty">
          <LoaderCircle className="component-library-spin" />
          <strong>{tr('componentRepo:loadingImportRecords')}</strong>
        </div>
      ) : null}
      {!state.loading && data?.items.length === 0 ? (
        <div className="component-library-empty">
          <span><FileClock aria-hidden="true" /></span>
          <strong>{tr(totalCount === 0 ? 'componentRepo:noImportRecords' : 'componentRepo:noMatchingImportRecords')}</strong>
        </div>
      ) : null}
      {data && data.items.length > 0 ? (
        <div aria-busy={state.loading} className="component-import-history-table" role="table">
          <div className="component-import-history-row component-import-history-head" role="row">
            <span role="columnheader">{tr('componentRepo:sourceFile')}</span>
            <span role="columnheader">{tr('componentRepo:importType')}</span>
            <span role="columnheader">{tr('componentRepo:status')}</span>
            <span role="columnheader">{tr('componentRepo:createdTime')}</span>
            <span role="columnheader">{tr('componentRepo:duration')}</span>
            <span role="columnheader">{tr('componentRepo:actions')}</span>
          </div>
          {data.items.map((item) => (
            <ImportHistoryRow item={item} key={item.id} />
          ))}
        </div>
      ) : null}
      {data && data.totalPages > 1 ? (
        <nav aria-label={tr('componentRepo:importRecordsPagination')} className="component-library-pagination">
          <button disabled={state.loading || page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))} type="button">
            {tr('componentRepo:previousPage')}
          </button>
          <span>{tr('componentRepo:pageOf', { page, totalPages: data.totalPages })}</span>
          <button disabled={state.loading || page >= data.totalPages} onClick={() => setPage((current) => current + 1)} type="button">
            {tr('componentRepo:nextPage')}
          </button>
        </nav>
      ) : null}
    </div>
  );
}

function ImportHistoryRow({ item }: { item: ComponentImportRecordResponse }) {
  const tr = useAppTranslation();
  const resultRoute = item.componentId
    ? routeFor('componentRepoDetail').replace(':componentId', encodeURIComponent(item.componentId))
    : item.candidateId
      ? routeFor('componentRepoCandidate').replace(':candidateId', encodeURIComponent(item.candidateId))
      : routeFor('componentRepoImportStatus').replace(':importId', encodeURIComponent(item.id));
  const detailRoute = routeFor('componentRepoImportStatus').replace(':importId', encodeURIComponent(item.id));
  const failure = item.failure ? localizeStructuredMessage(item.failure) : null;
  return (
    <div className="component-import-history-row" role="row">
      <span className="component-import-history-file" role="cell">
        <FileText aria-hidden="true" />
        <span>
          <strong>{item.originalFilename}</strong>
          <small>{formatFileSize(item.fileSize)} · {item.id}</small>
          {failure ? <em title={failure}>{failure}</em> : null}
        </span>
      </span>
      <span role="cell">{tr(item.importKind === 'update' ? 'componentRepo:updateComponentImport' : 'componentRepo:createComponentImport')}</span>
      <span role="cell"><StatusPill status={item.processingStatus} /></span>
      <span role="cell">{formatDateTime(item.createdAt, { dateStyle: 'short', timeStyle: 'short' })}</span>
      <span role="cell">{formatImportDuration(item)}</span>
      <span className="component-import-history-actions" role="cell">
        <Link to={item.processingStatus === 'ready' ? resultRoute : detailRoute}>
          <ExternalLink aria-hidden="true" />
          {tr(item.processingStatus === 'ready' ? 'componentRepo:viewResult' : 'componentRepo:viewProgress')}
        </Link>
      </span>
    </div>
  );
}

function formatImportDuration(item: ComponentImportRecordResponse): string {
  const start = new Date(item.startedAt ?? item.createdAt).getTime();
  const end = item.completedAt ? new Date(item.completedAt).getTime() : Date.now();
  if (!Number.isFinite(start) || !Number.isFinite(end)) return '—';
  const totalSeconds = Math.max(0, Math.floor((end - start) / 1_000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${formatNumber(minutes, { minimumIntegerDigits: 2 })}:${formatNumber(seconds, { minimumIntegerDigits: 2 })}`;
}

function formatFileSize(value: number): string {
  if (value >= 1024 * 1024) return `${formatNumber(value / (1024 * 1024), { maximumFractionDigits: 1 })} MB`;
  if (value >= 1024) return `${formatNumber(value / 1024, { maximumFractionDigits: 1 })} KB`;
  return `${formatNumber(value)} B`;
}
