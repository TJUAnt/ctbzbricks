import React from 'react';
import {
  AlertCircle,
  Boxes,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  Download,
  FileArchive,
  FileUp,
  FolderOpen,
  LoaderCircle,
  PackageCheck,
  RefreshCw,
  Search,
  Sparkles,
  Upload,
  X,
} from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import appConfig from '../app/appConfig';
import { resolvedLocale, useAppTranslation, useDynamicTranslation, type AppTranslator, type TranslationKey } from '../i18n';
import { formatDateTime } from '../i18n/formatters';
import {
  createComponentImportWithProgress,
  downloadComponentVersionSource,
  getImportCandidate,
  listComponentImports,
  listComponents,
  listComponentVersions,
  parseComponentImport,
  type ComponentImportCreateResponse,
  type ComponentImportResponse,
  type ComponentResponse,
  type ComponentVersionResponse,
} from './componentRepoApi';

type ComponentRepoListState =
  | { status: 'loading'; components: ComponentResponse[]; imports: ComponentImportResponse[]; error: null }
  | { status: 'ready'; components: ComponentResponse[]; imports: ComponentImportResponse[]; error: null }
  | { status: 'error'; components: ComponentResponse[]; imports: ComponentImportResponse[]; error: string };

type UploadState = 'idle' | 'uploading' | 'success' | 'error';
type LibraryFilter = 'all' | 'processing' | 'review' | 'published' | 'failed';

type LibraryItem =
  | { kind: 'import'; id: string; name: string; status: string; createdAt: string; fileSize: number | null; data: ComponentImportResponse }
  | { kind: 'component'; id: string; name: string; status: string; createdAt: string; fileSize: null; data: ComponentResponse };

export function ComponentRepoPage() {
  const navigate = useNavigate();
  const tr = useAppTranslation();
  const trDynamic = useDynamicTranslation();
  const locale = resolvedLocale();
  const [state, setState] = React.useState<ComponentRepoListState>({
    status: 'loading',
    components: [],
    imports: [],
    error: null,
  });
  const [query, setQuery] = React.useState('');
  const [filter, setFilter] = React.useState<LibraryFilter>('all');
  const [isUploadOpen, setIsUploadOpen] = React.useState(false);
  const [reviewingId, setReviewingId] = React.useState<string | null>(null);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [selectedComponent, setSelectedComponent] = React.useState<ComponentResponse | null>(null);
  const [versions, setVersions] = React.useState<ComponentVersionResponse[]>([]);
  const [versionState, setVersionState] = React.useState<'idle' | 'loading' | 'error'>('idle');

  const refreshLibrary = React.useCallback(() => {
    setState((current) => ({
      status: 'loading',
      components: current.components,
      imports: current.imports,
      error: null,
    }));
    Promise.all([listComponentImports(), listComponents()])
      .then(([imports, components]) => setState({ status: 'ready', components, imports, error: null }))
      .catch((error: Error) =>
        setState((current) => ({
          status: 'error',
          components: current.components,
          imports: current.imports,
          error: error.message,
        })),
      );
  }, []);

  React.useEffect(() => {
    refreshLibrary();
  }, [refreshLibrary]);

  const items = React.useMemo(
    () => buildLibraryItems(state.imports, state.components, tr),
    [locale, state.components, state.imports, tr],
  );
  const visibleItems = React.useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    return items.filter((item) => {
      const matchesQuery = !normalizedQuery || `${item.name} ${item.id}`.toLocaleLowerCase().includes(normalizedQuery);
      return matchesQuery && matchesFilter(item.status, filter);
    });
  }, [filter, items, query]);

  const stats = React.useMemo(() => ({
    total: items.length,
    processing: items.filter((item) => ['uploaded', 'parsing'].includes(item.status)).length,
    review: items.filter((item) => ['parsed', 'pending_review', 'draft'].includes(item.status)).length,
    published: items.filter((item) => ['active', 'published'].includes(item.status)).length,
  }), [items]);

  const continueImport = async (item: Extract<LibraryItem, { kind: 'import' }>) => {
    setReviewingId(item.id);
    setActionError(null);
    try {
      const candidate = item.status === 'uploaded'
        ? (await parseComponentImport(item.id)).candidate
        : await getImportCandidate(item.id);
      navigate(routeFor('componentRepoCandidate').replace(':candidateId', encodeURIComponent(candidate.id)));
    } catch (error) {
      setActionError(error instanceof Error ? error.message : appConfig.texts.loadFailed);
      refreshLibrary();
    } finally {
      setReviewingId(null);
    }
  };

  const toggleVersions = async (component: ComponentResponse) => {
    if (selectedComponent?.id === component.id) {
      setSelectedComponent(null);
      return;
    }
    setSelectedComponent(component);
    setVersions([]);
    setVersionState('loading');
    try {
      setVersions(await listComponentVersions(component.id));
      setVersionState('idle');
    } catch {
      setVersionState('error');
    }
  };

  return (
    <section className="component-library-page">
      <header className="component-library-hero">
        <div className="component-library-heading">
          <span className="component-library-heading-icon"><Boxes aria-hidden="true" /></span>
          <div>
            <h1>{tr('componentRepo:componentLibrary')}</h1>
            <p>{tr('componentRepo:manageReviewAndPublishReusableLegoComponents')}</p>
          </div>
        </div>
        <nav aria-label={tr('componentRepo:componentLibrarySections')} className="component-library-tabs">
          <button className="component-library-tab component-library-tab-active" type="button">
            <FolderOpen aria-hidden="true" />
            {tr('componentRepo:myComponentLibrary')}
          </button>
          <button aria-disabled="true" className="component-library-tab component-library-tab-disabled" type="button">
            <Sparkles aria-hidden="true" />
            {tr('componentRepo:communityLibrary')}
            <span>{tr('componentRepo:comingSoon')}</span>
          </button>
        </nav>
      </header>

      <section className="component-library-summary" aria-label={tr('componentRepo:componentStatusOverview')}>
        <SummaryCard icon={<Boxes />} label={tr('componentRepo:allComponents')} tone="blue" value={stats.total} />
        <SummaryCard icon={<Clock3 />} label={tr('componentRepo:processing')} tone="amber" value={stats.processing} />
        <SummaryCard icon={<FileArchive />} label={tr('componentRepo:pendingReview')} tone="purple" value={stats.review} />
        <SummaryCard icon={<PackageCheck />} label={tr('componentRepo:published')} tone="green" value={stats.published} />
      </section>

      <section className="component-library-panel">
        <header className="component-library-panel-header">
          <div>
            <div className="component-library-title-row">
              <h2>{tr('componentRepo:myComponentLibrary')}</h2>
              <span>{stats.total}</span>
            </div>
            <p>{tr('componentRepo:allUploadedComponentsAndTheirCurrentStatus')}</p>
          </div>
          <button className="component-library-upload-button" onClick={() => setIsUploadOpen(true)} type="button">
            <Upload aria-hidden="true" />
            {tr('componentRepo:uploadComponent')}
          </button>
        </header>

        <div className="component-library-toolbar">
          <label className="component-library-search">
            <Search aria-hidden="true" />
            <input
              aria-label={tr('componentRepo:searchComponents')}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={tr('componentRepo:searchComponentNameOrId')}
              value={query}
            />
          </label>
          <div className="component-library-filters" role="group" aria-label={tr('componentRepo:filterByStatus')}>
            {([
              ['all', 'componentRepo:all'],
              ['processing', 'componentRepo:processing'],
              ['review', 'componentRepo:pendingReview'],
              ['published', 'componentRepo:published'],
              ['failed', 'componentRepo:failed'],
            ] as Array<[LibraryFilter, TranslationKey]>).map(([value, label]) => (
              <button
                className={filter === value ? 'component-library-filter-active' : undefined}
                key={value}
                onClick={() => setFilter(value)}
                type="button"
              >
                {trDynamic(label)}
              </button>
            ))}
          </div>
          <button aria-label={tr('componentRepo:refreshComponentList')} className="component-library-refresh" onClick={refreshLibrary} type="button">
            <RefreshCw aria-hidden="true" className={state.status === 'loading' ? 'component-library-spin' : undefined} />
          </button>
        </div>

        {state.status === 'error' ? <div className="component-library-alert"><AlertCircle />{state.error}</div> : null}
        {actionError ? <div className="component-library-alert"><AlertCircle />{actionError}</div> : null}

        <div className="component-library-table" role="table" aria-label={tr('componentRepo:myComponentList')}>
          <div className="component-library-table-head" role="row">
            <span role="columnheader">{tr('componentRepo:component')}</span>
            <span role="columnheader">{tr('componentRepo:status')}</span>
            <span role="columnheader">{tr('componentRepo:type')}</span>
            <span role="columnheader">{tr('componentRepo:uploadedAt')}</span>
            <span role="columnheader">{tr('componentRepo:actions')}</span>
          </div>
          {visibleItems.map((item) => (
            <article className="component-library-row" key={`${item.kind}-${item.id}`} role="row">
              <div className="component-library-item-main" role="cell">
                <span className={`component-library-file-icon component-library-file-icon-${fileTone(item.name)}`}>
                  <PackageIcon name={item.name} />
                </span>
                <div>
                  <strong>{displayName(item.name)}</strong>
                  <span>{shortId(item.id)}{item.fileSize ? ` · ${formatFileSize(item.fileSize)}` : ''}</span>
                </div>
              </div>
              <div role="cell"><StatusPill status={item.status} /></div>
              <span className="component-library-type" role="cell">{item.kind === 'component' ? tr('componentRepo:component') : fileType(item.name)}</span>
              <span className="component-library-date" role="cell">{formatDate(item.createdAt)}</span>
              <div className="component-library-row-action" role="cell">
                {item.kind === 'import' && ['uploaded', 'parsed'].includes(item.status) ? (
                  <button disabled={reviewingId === item.id} onClick={() => void continueImport(item)} type="button">
                    {reviewingId === item.id ? <LoaderCircle className="component-library-spin" /> : null}
                    {tr(item.status === 'uploaded' ? 'componentRepo:parseAndReview' : 'componentRepo:continueReview')}
                    <ChevronRight aria-hidden="true" />
                  </button>
                ) : item.kind === 'component' ? (
                  <div className="component-library-component-actions">
                    <Link to={routeFor('componentRepoDetail').replace(':componentId', encodeURIComponent(item.id))}>
                      {tr('componentRepo:details')}<ChevronRight aria-hidden="true" />
                    </Link>
                    <button aria-expanded={selectedComponent?.id === item.id} onClick={() => void toggleVersions(item.data)} type="button">
                      {tr('componentRepo:viewVersions')}<ChevronDown aria-hidden="true" />
                    </button>
                    {selectedComponent?.id === item.id ? (
                      <VersionDropdown component={item.data} state={versionState} versions={versions} />
                    ) : null}
                  </div>
                ) : (
                  <span>—</span>
                )}
              </div>
            </article>
          ))}
        </div>

        {state.status === 'loading' && items.length === 0 ? (
          <div className="component-library-empty"><LoaderCircle className="component-library-spin" /><strong>{tr('componentRepo:loadingComponents')}</strong></div>
        ) : null}
        {state.status !== 'loading' && visibleItems.length === 0 ? (
          <div className="component-library-empty">
            <span><Search aria-hidden="true" /></span>
            <strong>{tr(items.length === 0 ? 'componentRepo:noComponentsUploaded' : 'componentRepo:noMatchingComponents')}</strong>
            <p>{tr(items.length === 0 ? 'componentRepo:uploadYourFirstComponentToStartBuildingYourLibrary' : 'componentRepo:tryChangingTheSearchTermOrStatusFilter')}</p>
            {items.length === 0 ? <button onClick={() => setIsUploadOpen(true)} type="button">{tr('componentRepo:uploadComponent')}</button> : null}
          </div>
        ) : null}
      </section>

      {isUploadOpen ? (
        <ComponentUploadDialog
          onClose={() => setIsUploadOpen(false)}
          onUploaded={() => {
            setIsUploadOpen(false);
            refreshLibrary();
          }}
        />
      ) : null}
    </section>
  );
}

export function ComponentUploadDialog({
  baseVersionId,
  onClose,
  onUploaded,
  targetComponentId,
}: {
  baseVersionId?: string | null;
  onClose: () => void;
  onUploaded: (result: ComponentImportCreateResponse) => void;
  targetComponentId?: string | null;
}) {
  const tr = useAppTranslation();
  const [sourceFile, setSourceFile] = React.useState<File | null>(null);
  const [exchangeFile, setExchangeFile] = React.useState<File | null>(null);
  const [state, setState] = React.useState<UploadState>('idle');
  const [progress, setProgress] = React.useState(0);
  const [progressMessage, setProgressMessage] = React.useState(tr('componentRepo:readyToUpload'));
  const [error, setError] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<ComponentImportCreateResponse | null>(null);
  const sourceInputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && state !== 'uploading') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose, state]);

  const submit = async () => {
    if (!sourceFile) return;
    setState('uploading');
    setProgress(0);
    setError(null);
    try {
      const uploaded = await createComponentImportWithProgress(
        sourceFile,
        exchangeFile,
        ({ percent, message }) => {
          setProgress(percent);
          setProgressMessage(message);
        },
        { targetComponentId, baseVersionId },
      );
      setResult(uploaded);
      setState('success');
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : tr('componentRepo:componentUploadFailed'));
      setState('error');
    }
  };

  const reset = () => {
    setState('idle');
    setProgress(0);
    setProgressMessage(tr('componentRepo:readyToUpload'));
    setError(null);
    setResult(null);
  };

  return (
    <div className="component-upload-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget && state !== 'uploading') onClose();
    }}>
      <section aria-labelledby="component-upload-title" aria-modal="true" className="component-upload-dialog" role="dialog">
        <header className="component-upload-header">
          <div>
            <span><Upload aria-hidden="true" /></span>
            <div><h2 id="component-upload-title">{tr('componentRepo:uploadComponent')}</h2><p>{tr('componentRepo:uploadAStudioOrLDrawFileToYourComponentLibrary')}</p></div>
          </div>
          <button aria-label={tr('componentRepo:closeUploadDialog')} disabled={state === 'uploading'} onClick={onClose} type="button"><X /></button>
        </header>

        <div className="component-upload-body">
          {state === 'idle' ? (
            <>
              <input
                accept=".io,.ldr,.mpd"
                className="component-upload-hidden-input"
                onChange={(event) => setSourceFile(event.target.files?.item(0) ?? null)}
                ref={sourceInputRef}
                type="file"
              />
              <button
                className={sourceFile ? 'component-upload-dropzone component-upload-dropzone-selected' : 'component-upload-dropzone'}
                onClick={() => sourceInputRef.current?.click()}
                onDragOver={(event) => event.preventDefault()}
                onDrop={(event) => {
                  event.preventDefault();
                  const file = event.dataTransfer.files.item(0);
                  if (file && isComponentFile(file.name)) setSourceFile(file);
                }}
                type="button"
              >
                {sourceFile ? <CheckCircle2 aria-hidden="true" /> : <FileUp aria-hidden="true" />}
                <strong>{sourceFile ? sourceFile.name : tr('componentRepo:dropAComponentFileHereOrClickToSelect')}</strong>
                <span>{sourceFile ? formatFileSize(sourceFile.size) : tr('componentRepo:supportsIoLdrAndMpdFilesUpTo100Mb')}</span>
              </button>
              <label className="component-upload-secondary-file">
                <span><strong>{tr('componentRepo:exchangeFile')}</strong><em>{tr('componentRepo:optionalOnlyNeededForIoSourceFiles')}</em></span>
                <span className="component-upload-secondary-picker">{exchangeFile ? exchangeFile.name : tr('componentRepo:selectLdrMpd')}</span>
                <input accept=".ldr,.mpd" onChange={(event) => setExchangeFile(event.target.files?.item(0) ?? null)} type="file" />
              </label>
              <div className="component-upload-tip"><CheckCircle2 /><span><strong>{tr('componentRepo:whatHappensAfterUpload')}</strong>{tr('componentRepo:theFileWillBeStoredSecurelyAndEnterTheParsingAndReviewWorkflow')}</span></div>
            </>
          ) : null}

          {state === 'uploading' ? (
            <div className="component-upload-progress-state">
              <span className="component-upload-progress-icon"><Upload /></span>
              <h3>{tr('componentRepo:uploadingComponent')}</h3>
              <p>{sourceFile?.name}</p>
              <div className="component-upload-progress-meta"><span>{progressMessage}</span><strong>{progress}%</strong></div>
              <div aria-label={tr('componentRepo:uploadProgressValue', { percent: progress })} aria-valuemax={100} aria-valuemin={0} aria-valuenow={progress} className="component-upload-progress" role="progressbar">
                <span style={{ width: `${progress}%` }} />
              </div>
              <small>{tr('componentRepo:keepThisPageOpenUntilTheUploadIsComplete')}</small>
            </div>
          ) : null}

          {state === 'success' ? (
            <div className="component-upload-result component-upload-result-success">
              <span><CheckCircle2 /></span>
              <h3>{tr('componentRepo:componentUploaded')}</h3>
              <p>{tr('componentRepo:theFileWasAddedToMyComponentLibraryAndIsReadyForParsingAndReview')}</p>
              <div><strong>{result?.sourceArtifact.originalFilename ?? sourceFile?.name}</strong><span>{sourceFile ? formatFileSize(sourceFile.size) : ''}</span></div>
            </div>
          ) : null}

          {state === 'error' ? (
            <div className="component-upload-result component-upload-result-error">
              <span><AlertCircle /></span>
              <h3>{tr('componentRepo:uploadNotCompleted')}</h3>
              <p>{error}</p>
              <div><strong>{sourceFile?.name}</strong><span>{tr('componentRepo:checkTheNetworkOrFileAndTryAgain')}</span></div>
            </div>
          ) : null}
        </div>

        <footer className="component-upload-footer">
          {state === 'idle' ? <><button onClick={onClose} type="button">{tr('componentRepo:cancel')}</button><button disabled={!sourceFile} onClick={() => void submit()} type="button"><Upload />{tr('componentRepo:startUpload')}</button></> : null}
          {state === 'uploading' ? <span>{tr('componentRepo:processingPleaseWait')}</span> : null}
          {state === 'success' ? <><button onClick={() => { reset(); setSourceFile(null); setExchangeFile(null); }} type="button">{tr('componentRepo:uploadAnother')}</button><button onClick={() => { if (result) onUploaded(result); }} type="button"><CheckCircle2 />{tr('componentRepo:done')}</button></> : null}
          {state === 'error' ? <><button onClick={onClose} type="button">{tr('componentRepo:close')}</button><button onClick={reset} type="button"><RefreshCw />{tr('componentRepo:retryUpload')}</button></> : null}
        </footer>
      </section>
    </div>
  );
}

function VersionDropdown({ component, state, versions }: {
  component: ComponentResponse;
  state: 'idle' | 'loading' | 'error';
  versions: ComponentVersionResponse[];
}) {
  const tr = useAppTranslation();
  const [downloadError, setDownloadError] = React.useState<string | null>(null);
  return (
    <section className="component-version-dropdown" role="menu">
        <div className="component-version-list">
          {state === 'loading' ? <div className="component-library-empty"><LoaderCircle className="component-library-spin" /><strong>{tr('componentRepo:loadingVersions')}</strong></div> : null}
          {state === 'error' ? <div className="component-library-alert"><AlertCircle />{tr('componentRepo:failedToLoadVersions')}</div> : null}
          {downloadError ? <div className="component-library-alert"><AlertCircle />{downloadError}</div> : null}
          {state === 'idle' && versions.length === 0 ? <div className="component-library-empty"><strong>{tr('componentRepo:noComponentVersions')}</strong></div> : null}
          {versions.map((version) => (
            <article key={version.id}>
              <div><strong>v{version.version}</strong><span>{tr('componentRepo:revision')} {version.revision}</span></div>
              <StatusPill status={version.id === component.currentVersionId ? 'published' : 'draft'} />
              <button onClick={async () => {
                setDownloadError(null);
                try { await downloadComponentVersionSource(version.id); }
                catch (error) { setDownloadError(error instanceof Error ? error.message : tr('componentRepo:downloadFailed')); }
              }} type="button"><Download />{tr('componentRepo:downloadSource')}</button>
            </article>
          ))}
        </div>
    </section>
  );
}

function SummaryCard({ icon, label, tone, value }: { icon: React.ReactNode; label: string; tone: string; value: number }) {
  return <article className={`component-library-summary-card component-library-summary-card-${tone}`}><span>{icon}</span><div><strong>{value}</strong><p>{label}</p></div></article>;
}

function PackageIcon({ name }: { name: string }) {
  return fileType(name) === 'IO' ? <Boxes /> : <FileArchive />;
}

function buildLibraryItems(
  imports: ComponentImportResponse[],
  components: ComponentResponse[],
  tr: AppTranslator,
): LibraryItem[] {
  const importItems: LibraryItem[] = imports.filter((item) => !item.targetComponentId).map((item) => ({
    kind: 'import', id: item.id, name: item.sourceFilename || `${tr('componentRepo:componentImport')} ${shortId(item.id)}`,
    status: item.status, createdAt: item.createdAt, fileSize: item.sourceFileSize ?? null, data: item,
  }));
  const componentItems: LibraryItem[] = components
    .map((item) => ({ kind: 'component', id: item.id, name: item.name, status: item.status, createdAt: item.createdAt, fileSize: null, data: item }));
  return [...importItems, ...componentItems].sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt));
}

function matchesFilter(status: string, filter: LibraryFilter): boolean {
  if (filter === 'all') return true;
  if (filter === 'processing') return ['uploaded', 'parsing'].includes(status);
  if (filter === 'review') return ['parsed', 'pending_review', 'draft'].includes(status);
  if (filter === 'published') return ['active', 'published'].includes(status);
  return ['failed', 'blocked', 'rejected'].includes(status);
}

function displayName(name: string): string { return name.replace(/\.(io|ldr|mpd)$/i, ''); }
function fileType(name: string): string { return name.match(/\.([^.]+)$/)?.[1]?.toUpperCase() ?? ''; }
function fileTone(name: string): string { const type = fileType(name); return type === 'IO' ? 'blue' : type === 'LDR' ? 'amber' : 'purple'; }
function isComponentFile(name: string): boolean { return /\.(io|ldr|mpd)$/i.test(name); }
function shortId(id: string): string { return id.length > 16 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id; }
function formatFileSize(bytes: number): string { return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`; }
function formatDate(value: string): string { return formatDateTime(value, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }); }

const statusLabels: Partial<Record<string, TranslationKey>> = {
  uploaded: 'componentRepo:uploaded', parsing: 'componentRepo:parsing', parsed: 'componentRepo:pendingReview', pending_review: 'componentRepo:pendingReview', in_review: 'componentRepo:inReview',
  draft: 'componentRepo:draft', active: 'componentRepo:published', published: 'componentRepo:published', failed: 'componentRepo:failed', blocked: 'componentRepo:blocked', rejected: 'componentRepo:rejected', archived: 'componentRepo:archived',
  confirmed: 'componentRepo:confirmed', passed: 'componentRepo:passed', pass: 'componentRepo:passed', pending: 'componentRepo:pending',
};

export function StatusPill({ status }: { status: string }) {
  const trDynamic = useDynamicTranslation();
  const translationKey = statusLabels[status];
  return <span className={`component-repo-status component-repo-status-${status}`}>{translationKey ? trDynamic(translationKey) : status}</span>;
}

export function routeFor(page: keyof typeof appConfig.routePaths): string {
  return appConfig.routePaths[page];
}
