import React from 'react';
import { localizeStructuredMessage } from '../api/client';
import {
  AlertTriangle,
  Bell,
  Boxes,
  Braces,
  Crosshair,
  FileClock,
  FolderTree,
  GitCompareArrows,
  GitBranch,
  Layers3,
  LoaderCircle,
  Plug,
  RefreshCw,
  Rocket,
  ShieldCheck,
  Star,
  Trash2,
  X,
} from 'lucide-react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import appConfig from '../app/appConfig';
import { useAuth } from '../auth/AuthContext';
import { resolvedLocale, useAppTranslation, useDynamicTranslation, type TranslationKey } from '../i18n';
import { ComponentScene, type ComponentSceneConnector } from '../parts/PartViewerPage';
import {
  deleteComponent,
  getComponent,
  getConnectorAnalysis,
  getValidationReport,
  listComponentGroupIds,
  listComponentGroups,
  listComponentVersions,
  listRelations,
  loadComponentVersionDiff,
  loadComponentVersionParts,
  loadComponentVersionPreview,
  publishVersion,
  starComponent,
  unstarComponent,
  unwatchComponent,
  validateCandidate,
  watchComponent,
  type ComponentConnectorAnalysisResponse,
  type ComponentConnectorResponse,
  type ComponentGroupTreeResponse,
  type ComponentRelationCandidateResponse,
  type ComponentValidationReportResponse,
  type ComponentResponse,
  type ComponentVersionPartsResponse,
  type ComponentVersionDiffChangeKind,
  type ComponentVersionDiffResponse,
  type ComponentVersionPreviewModelResponse,
  type ComponentVersionResponse,
} from './componentRepoApi';
import { ComponentVersionActions } from './ComponentVersionActions';
import { ComponentDiffScene, type ComponentDiffFocus } from './ComponentDiffScene';
import { ComponentImportHistoryList } from './ComponentImportHistoryPage';
import { routeFor, StatusPill } from './ComponentRepoPage';

type ComponentDetailState = {
  component: ComponentResponse | null;
  version: ComponentVersionResponse | null;
  versions: ComponentVersionResponse[];
  preview: ComponentVersionPreviewModelResponse | null;
  partDetails: ComponentVersionPartsResponse | null;
  connectorAnalysis: ComponentConnectorAnalysisResponse | null;
  relations: ComponentRelationCandidateResponse[];
  validationReport: ComponentValidationReportResponse | null;
  groupTree: ComponentGroupTreeResponse | null;
  groupIds: string[];
  loading: boolean;
  previewLoading: boolean;
  connectorLoading: boolean;
  partsLoading: boolean;
  validationLoading: boolean;
  error: string | null;
  previewError: string | null;
  connectorError: string | null;
};

type PartSummary = {
  key: string;
  partRef: string;
  name: string;
  quantity: number;
  partLibraryVersionId: string | null;
  geometryStatus: 'ready' | 'failed' | 'missing';
};

type ConnectorPartGroup = {
  partInstanceId: string;
  partRef: string;
  connectors: ComponentConnectorResponse[];
};

type ComponentDiffViewState = {
  afterPreview: ComponentVersionPreviewModelResponse | null;
  beforePreview: ComponentVersionPreviewModelResponse | null;
  diff: ComponentVersionDiffResponse | null;
  error: string | null;
  loading: boolean;
  targetVersion: ComponentVersionResponse | null;
};

const connectorGroupLabelKeys: Record<ComponentConnectorResponse['state'], TranslationKey> = {
  internal: 'componentRepo:connectorGroupInternal',
  external: 'componentRepo:connectorGroupExternal',
  blocked: 'componentRepo:connectorGroupBlocked',
  unsupported: 'componentRepo:connectorGroupUnsupported',
  unresolved: 'componentRepo:connectorGroupUnresolved',
};
const connectorStateOrder: ComponentConnectorResponse['state'][] = [
  'external',
  'internal',
  'blocked',
  'unsupported',
  'unresolved',
];
const connectorStateRank = new Map(
  connectorStateOrder.map((state, index) => [state, index]),
);

const diffChangeLabelKeys: Record<ComponentVersionDiffChangeKind, TranslationKey> = {
  part_added: 'componentRepo:diffAdded',
  part_removed: 'componentRepo:diffRemoved',
  transform_changed: 'componentRepo:diffMoved',
  color_changed: 'componentRepo:diffColorChanged',
  part_replaced: 'componentRepo:diffReplaced',
};

/** ComponentDetailPage 聚合不可变版本详情，并为 owner 提供相邻版本的只读三维对比入口。 */
export function ComponentDetailPage() {
  const tr = useAppTranslation();
  const trDynamic = useDynamicTranslation();
  const contentLocale = resolvedLocale();
  const { isConfigured: isAuthConfigured, isLoading: isAuthLoading, user } = useAuth();
  const navigate = useNavigate();
  const params = useParams();
  const componentId = params.componentId ?? '';
  const resetViewRef = React.useRef<(() => void) | null>(null);
  const [refreshToken, setRefreshToken] = React.useState(0);
  const [actionNotice, setActionNotice] = React.useState<string | null>(null);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [publishing, setPublishing] = React.useState(false);
  const [validating, setValidating] = React.useState(false);
  const [starring, setStarring] = React.useState(false);
  const [watchMutating, setWatchMutating] = React.useState(false);
  const [confirmingDeleteComponent, setConfirmingDeleteComponent] = React.useState(false);
  const [deletingComponent, setDeletingComponent] = React.useState(false);
  const [activeConnectorPartId, setActiveConnectorPartId] = React.useState<string | null>(null);
  const [selectedConnectorId, setSelectedConnectorId] = React.useState<string | null>(null);
  const [historyTab, setHistoryTab] = React.useState<'versions' | 'imports'>('versions');
  const diffRequestRef = React.useRef(0);
  const diffResetRef = React.useRef<(() => void) | null>(null);
  const [diffFocus, setDiffFocus] = React.useState<ComponentDiffFocus | null>(null);
  const [diffView, setDiffView] = React.useState<ComponentDiffViewState>({
    afterPreview: null,
    beforePreview: null,
    diff: null,
    error: null,
    loading: false,
    targetVersion: null,
  });
  const trRef = React.useRef(tr);
  trRef.current = tr;
  const [state, setState] = React.useState<ComponentDetailState>({
    component: null,
    version: null,
    versions: [],
    preview: null,
    partDetails: null,
    connectorAnalysis: null,
    relations: [],
    validationReport: null,
    groupTree: null,
    groupIds: [],
    loading: true,
    previewLoading: true,
    connectorLoading: true,
    partsLoading: true,
    validationLoading: true,
    error: null,
    previewError: null,
    connectorError: null,
  });

  React.useEffect(() => {
    // 同一路由切换 Component 时必须丢弃旧版本的异步响应，避免把上一组件的 Diff 投影到新详情页。
    diffRequestRef.current += 1;
    diffResetRef.current = null;
    setDiffFocus(null);
    setDiffView({
      afterPreview: null,
      beforePreview: null,
      diff: null,
      error: null,
      loading: false,
      targetVersion: null,
    });
  }, [componentId]);

  React.useEffect(() => {
    // 详情错误由 API 在请求时按 locale 翻译；语言切换后必须重取，避免跨 owner 404 等旧译文滞留。
    let active = true;
    const load = async () => {
      setState((current) => ({
        ...current,
        loading: true,
        previewLoading: true,
        connectorLoading: true,
        partsLoading: true,
        validationLoading: true,
        error: null,
        previewError: null,
        connectorError: null,
      }));
      try {
        const [component, versions] = await Promise.all([
          getComponent(componentId),
          listComponentVersions(componentId),
        ]);
        // 分组关系属于 owner 私有数据；公开详情只读取 Component 和版本，不探测他人的分组。
        const [groupTree, groupIds] = component.ownedByActor
          ? await Promise.all([listComponentGroups(), listComponentGroupIds(componentId)])
          : [null, [] as string[]];
        const version = preferredDetailVersion(component, versions);
        if (!version) throw new Error(trRef.current('componentRepo:noComponentVersions'));
        // Relation/Connector 是 Candidate owner 的审核数据；公开详情只读取 Version 级公开投影。
        const connectorAnalysisPromise = component.ownedByActor && version.componentCandidateId
          ? getConnectorAnalysis(version.componentCandidateId)
          .then((connectorAnalysis) => ({
            connectorAnalysis,
            connectorError: null as string | null,
          }))
          .catch((analysisError: unknown) => ({
            connectorAnalysis: null,
            connectorError: analysisError instanceof Error
              ? analysisError.message
              : appConfig.texts.loadFailed,
          }))
          : Promise.resolve({ connectorAnalysis: null, connectorError: null });
        const partDetailsPromise = loadComponentVersionParts(version.id)
          .then((partDetails) => ({ partDetails, failed: false }))
          .catch(() => ({ partDetails: null, failed: true }));
        const validationReportPromise = version.validationReportId
          ? getValidationReport(version.validationReportId)
            .then((validationReport) => ({ validationReport }))
            .catch(() => ({ validationReport: null }))
          : Promise.resolve({ validationReport: null });
        if (!active) return;
        setState((current) => ({
          ...current,
          component,
          version,
          versions,
          groupTree,
          groupIds,
          loading: false,
        }));
        // Preview 是可重建派生数据。历史 generator stale 或几何暂不可用时只降级预览区域，
        // 不能清空已加载的 Component，也不能阻断 owner 的发布、验证和删除操作。
        const [previewResult, relations] = await Promise.all([
          loadComponentVersionPreview(version.id)
            .then((preview) => ({ preview, previewError: null as string | null }))
            .catch((previewError: unknown) => ({
              preview: null,
              previewError: previewError instanceof Error
                ? previewError.message
                : trRef.current('errors:common.unknown'),
            })),
          component.ownedByActor && version.componentCandidateId
            ? listRelations(version.componentCandidateId)
            : Promise.resolve([]),
        ]);
        if (!active) return;
        setState({
          component,
          version,
          versions,
          preview: previewResult.preview,
          partDetails: null,
          connectorAnalysis: null,
          relations,
          validationReport: null,
          groupTree,
          groupIds,
          loading: false,
          previewLoading: false,
          connectorLoading: true,
          partsLoading: true,
          validationLoading: true,
          error: null,
          previewError: previewResult.previewError,
          connectorError: null,
        });

        const { connectorAnalysis, connectorError } = await connectorAnalysisPromise;
        if (!active) return;
        setState((current) => ({
          ...current,
          connectorAnalysis,
          connectorLoading: false,
          connectorError,
        }));

        const { partDetails } = await partDetailsPromise;
        if (!active) return;
        setState((current) => ({
          ...current,
          partDetails,
          partsLoading: false,
        }));

        const { validationReport } = await validationReportPromise;
        if (!active) return;
        setState((current) => ({
          ...current,
          validationReport,
          validationLoading: false,
        }));
      } catch (error) {
        if (!active) return;
        setState((current) => ({
          ...current,
          loading: false,
          previewLoading: false,
          connectorLoading: false,
          partsLoading: false,
          validationLoading: false,
          error: error instanceof Error ? error.message : appConfig.texts.loadFailed,
        }));
      }
    };
    if (componentId) void load();
    return () => {
      active = false;
    };
  }, [componentId, contentLocale, refreshToken]);

  const partSummaries = React.useMemo(
    () => (state.partDetails?.parts ?? []).map((part) => ({
      ...part,
      key: part.partRef,
      name: part.name ?? part.partRef,
      partLibraryVersionId: state.partDetails?.partLibraryVersionId ?? null,
    })),
    [state.partDetails?.parts],
  );
  const selectedGroups = React.useMemo(() => {
    if (!state.groupTree) return [];
    const selected = new Set(state.groupIds);
    return state.groupTree.groups.filter((group) => selected.has(group.id));
  }, [state.groupIds, state.groupTree]);
  const connectors = state.connectorAnalysis?.connectors ?? [];
  const externalInterfaces = state.connectorAnalysis?.externalInterfaces ?? [];
  const connectorPartGroups = React.useMemo(
    () => groupConnectorsByPart(connectors),
    [connectors],
  );
  const activeConnectorPart = connectorPartGroups.find(
    (group) => group.partInstanceId === activeConnectorPartId,
  ) ?? connectorPartGroups[0] ?? null;
  const selectedConnector = React.useMemo(
    () => connectors.find((connector) => connector.worldConnectorId === selectedConnectorId) ?? null,
    [connectors, selectedConnectorId],
  );
  const selectedSceneConnector = React.useMemo<ComponentSceneConnector | null>(
    () => selectedConnector
      ? {
          accessAxis: selectedConnector.accessAxis,
          id: selectedConnector.worldConnectorId,
          position: selectedConnector.position,
        }
      : null,
    [selectedConnector],
  );
  const registerPreviewReset = React.useCallback((reset: (() => void) | null) => {
    resetViewRef.current = reset;
  }, []);
  // 所有权由已鉴权的 Go API 投影，避免浏览器 auth 对象尚未同步或格式漂移时误隐藏管理操作。
  // ownedByActor 缺失时仅为兼容尚未重启的旧开发 API，回退到原 ownerId 判断。
  const componentOwnedByActor = Boolean(
    state.component
      && (
        state.component.ownedByActor
        ?? (!isAuthConfigured || state.component.ownerId === user?.id)
      ),
  );
  const componentOwnershipResolved = Boolean(
    state.component
      && (typeof state.component.ownedByActor === 'boolean' || !isAuthLoading),
  );
  const canPublish = Boolean(
    state.component
      && state.version?.status === 'draft'
      && state.component.contentKind === 'user'
      && componentOwnershipResolved
      && componentOwnedByActor,
  );
  const canValidate = Boolean(
    state.component
      && state.version?.componentCandidateId
      && (state.version.status === 'draft' || state.version.status === 'published')
      && state.component.contentKind === 'user'
      && componentOwnershipResolved
      && componentOwnedByActor,
  );
  const canDeleteComponent = Boolean(
    state.component
      && state.component.contentKind === 'user'
      && componentOwnershipResolved
      && componentOwnedByActor,
  );
  const canStarComponent = Boolean(
    state.component
      && componentOwnershipResolved
      && !componentOwnedByActor,
  );
  const canWatchComponent = canStarComponent;
  // Version Diff 是 owner-only 只读能力；前端只并行读取两个已有 GLB，不触发 Preview 物化。
  const compareVersion = async (version: ComponentVersionResponse) => {
    const requestID = diffRequestRef.current + 1;
    diffRequestRef.current = requestID;
    setDiffFocus(null);
    setDiffView({
      afterPreview: null,
      beforePreview: null,
      diff: null,
      error: null,
      loading: true,
      targetVersion: version,
    });
    try {
      const diff = await loadComponentVersionDiff(version.id);
      const afterPromise = state.version?.id === version.id && state.preview?.model
        ? Promise.resolve(state.preview)
        : loadComponentVersionPreview(version.id);
      const beforePromise = diff.baseVersionId
        ? loadComponentVersionPreview(diff.baseVersionId)
        : Promise.resolve(null);
      const [afterPreview, beforePreview] = await Promise.all([afterPromise, beforePromise]);
      if (!afterPreview.model || (diff.baseVersionId && !beforePreview?.model)) {
        throw new Error(trRef.current('componentRepo:diffPreviewUnavailable'));
      }
      if (diffRequestRef.current !== requestID) return;
      setDiffView({
        afterPreview,
        beforePreview,
        diff,
        error: null,
        loading: false,
        targetVersion: version,
      });
    } catch (error) {
      if (diffRequestRef.current !== requestID) return;
      setDiffView({
        afterPreview: null,
        beforePreview: null,
        diff: null,
        error: error instanceof Error ? error.message : trRef.current('errors:common.unknown'),
        loading: false,
        targetVersion: version,
      });
    }
  };
  const closeVersionDiff = () => {
    diffRequestRef.current += 1;
    diffResetRef.current = null;
    setDiffFocus(null);
    setDiffView({
      afterPreview: null,
      beforePreview: null,
      diff: null,
      error: null,
      loading: false,
      targetVersion: null,
    });
  };
  const publish = async () => {
    if (!state.version || !canPublish) return;
    setPublishing(true);
    setActionError(null);
    setActionNotice(null);
    try {
      await publishVersion(state.version.id);
      setActionNotice(tr('componentRepo:componentVersionPublished'));
      setRefreshToken((current) => current + 1);
    } catch (publishError) {
      setActionError(
        publishError instanceof Error
          ? publishError.message
          : tr('errors:common.unknown'),
      );
    } finally {
      setPublishing(false);
    }
  };
  // 详情页只触发持久化异步验证；发布按钮与验证任务保持两个独立动作。
  const validate = async () => {
    if (!state.version?.componentCandidateId || !canValidate) return;
    setValidating(true);
    setActionError(null);
    setActionNotice(null);
    try {
      const validationReport = await validateCandidate(state.version.componentCandidateId);
      setState((current) => ({ ...current, validationReport, validationLoading: false }));
      setActionNotice(tr('componentRepo:validationComplete'));
    } catch (validationError) {
      setActionError(
        validationError instanceof Error
          ? validationError.message
          : tr('errors:common.unknown'),
      );
    } finally {
      setValidating(false);
    }
  };
  const confirmDeleteComponent = async () => {
    if (!state.component || !canDeleteComponent) return;
    setDeletingComponent(true);
    setActionError(null);
    setActionNotice(null);
    try {
      await deleteComponent(state.component.id);
      navigate(routeFor('componentRepo'));
    } catch (deleteError) {
      setActionError(
        deleteError instanceof Error
          ? deleteError.message
          : tr('errors:common.unknown'),
      );
      setConfirmingDeleteComponent(false);
    } finally {
      setDeletingComponent(false);
    }
  };
  const toggleStar = async () => {
    if (!state.component || !canStarComponent || starring) return;
    const componentID = state.component.id;
    const wasStarred = state.component.starredByActor;
    setStarring(true);
    setActionError(null);
    setActionNotice(null);
    setState((current) => current.component ? {
      ...current,
      component: {
        ...current.component,
        starredByActor: !wasStarred,
        starCount: Math.max(0, current.component.starCount + (wasStarred ? -1 : 1)),
      },
    } : current);
    try {
      if (wasStarred) await unstarComponent(componentID);
      else await starComponent(componentID);
      setActionNotice(tr(wasStarred ? 'componentRepo:componentUnstarred' : 'componentRepo:componentStarred'));
    } catch (starError) {
      setActionError(starError instanceof Error ? starError.message : tr('errors:common.unknown'));
      setRefreshToken((current) => current + 1);
    } finally {
      setStarring(false);
    }
  };
  // Watch 是独立偏好：乐观更新只改变 watch 投影，失败时重新读取服务端权威状态。
  const toggleWatch = async () => {
    if (!state.component || !canWatchComponent || watchMutating) return;
    const componentID = state.component.id;
    const wasWatching = Boolean(state.component.watch?.watching);
    setWatchMutating(true);
    setActionError(null);
    setActionNotice(null);
    setState((current) => current.component ? {
      ...current,
      component: {
        ...current.component,
        watch: wasWatching
          ? { watching: false, level: null, watchedAt: null }
          : { watching: true, level: 'releases_only', watchedAt: null },
      },
    } : current);
    try {
      if (wasWatching) {
        await unwatchComponent(componentID);
        setActionNotice(tr('componentRepo:componentUnwatched'));
      } else {
        const watch = await watchComponent(componentID);
        setState((current) => current.component ? {
          ...current,
          component: {
            ...current.component,
            watch: { watching: true, level: watch.level, watchedAt: watch.watchedAt },
          },
        } : current);
        setActionNotice(tr('componentRepo:componentWatched'));
      }
    } catch (watchError) {
      setActionError(watchError instanceof Error ? watchError.message : tr('errors:common.unknown'));
      setRefreshToken((current) => current + 1);
    } finally {
      setWatchMutating(false);
    }
  };
  const diffBaseVersion = diffView.diff?.baseVersionId
    ? state.versions.find((version) => version.id === diffView.diff?.baseVersionId) ?? null
    : null;
  const visibleDiffChanges = diffView.diff?.instanceChanges.slice(0, 100) ?? [];
  const hiddenDiffChangeCount = Math.max(
    0,
    (diffView.diff?.instanceChanges.length ?? 0) - visibleDiffChanges.length,
  );
  return (
    <section className="component-repo-page component-detail-page">
      <header className="component-repo-header">
        <div>
          <h1>{tr('componentRepo:componentDetails')}</h1>
          <p>{tr('componentRepo:componentDetailsDescription')}</p>
        </div>
        <div className="component-repo-actions">
          <button onClick={() => navigate(routeFor('componentRepo'))} type="button">
            {appConfig.texts.componentRepoBackToList}
          </button>
          {canStarComponent && state.component ? (
            <button
              aria-pressed={state.component.starredByActor}
              className="component-detail-star-button"
              disabled={starring}
              onClick={() => void toggleStar()}
              title={tr(state.component.starredByActor ? 'componentRepo:unstarComponent' : 'componentRepo:starComponent')}
              type="button"
            >
              {starring
                ? <LoaderCircle aria-hidden="true" className="component-library-spin" />
                : <Star aria-hidden="true" fill={state.component.starredByActor ? 'currentColor' : 'none'} />}
              {tr(state.component.starredByActor ? 'componentRepo:starred' : 'componentRepo:star')}
              <span>{state.component.starCount}</span>
            </button>
          ) : state.component ? (
            <span className="component-detail-star-count" title={tr('componentRepo:starCount')}>
              <Star aria-hidden="true" />{state.component.starCount}
            </span>
          ) : null}
          {canWatchComponent && state.component ? (
            <button
              aria-label={tr(state.component.watch?.watching ? 'componentRepo:unwatchComponent' : 'componentRepo:watchComponent')}
              aria-pressed={Boolean(state.component.watch?.watching)}
              className="component-detail-star-button"
              disabled={watchMutating}
              onClick={() => void toggleWatch()}
              title={tr(state.component.watch?.watching ? 'componentRepo:unwatchComponent' : 'componentRepo:watchComponent')}
              type="button"
            >
              {watchMutating
                ? <LoaderCircle aria-hidden="true" className="component-library-spin" />
                : <Bell aria-hidden="true" fill={state.component.watch?.watching ? 'currentColor' : 'none'} />}
              {tr(state.component.watch?.watching ? 'componentRepo:watching' : 'componentRepo:watch')}
            </button>
          ) : null}
          {canDeleteComponent ? (
            <button
              className="component-repo-danger-button"
              disabled={deletingComponent}
              onClick={() => {
                setActionError(null);
                setActionNotice(null);
                setConfirmingDeleteComponent(true);
              }}
              type="button"
            >
              <Trash2 aria-hidden="true" />
              {tr('componentRepo:deleteComponent')}
            </button>
          ) : null}
          {canValidate ? (
            <button
              disabled={validating}
              onClick={() => void validate()}
              type="button"
            >
              {validating
                ? <LoaderCircle aria-hidden="true" className="component-library-spin" />
                : <ShieldCheck aria-hidden="true" />}
              {tr('componentRepo:validate')}
            </button>
          ) : null}
          {canPublish ? (
            <button
              className="component-repo-primary-button"
              disabled={publishing}
              onClick={() => void publish()}
              type="button"
            >
              {publishing
                ? <LoaderCircle aria-hidden="true" className="component-library-spin" />
                : <Rocket aria-hidden="true" />}
              {tr('componentRepo:publish')}
            </button>
          ) : null}
        </div>
      </header>

      {confirmingDeleteComponent && state.component ? (
        <div className="component-version-delete-backdrop">
          <section
            aria-labelledby={`delete-component-title-${state.component.id}`}
            aria-modal="true"
            className="component-version-delete-dialog"
            role="dialog"
          >
            <header>
              <div>
                <span><Trash2 aria-hidden="true" /></span>
                <h2 id={`delete-component-title-${state.component.id}`}>
                  {tr('componentRepo:deleteComponentTitle')}
                </h2>
              </div>
              <button
                aria-label={tr('componentRepo:close')}
                disabled={deletingComponent}
                onClick={() => {
                  setConfirmingDeleteComponent(false);
                  setActionError(null);
                }}
                type="button"
              >
                <X aria-hidden="true" />
              </button>
            </header>
            <div className="component-version-delete-body">
              <p>
                {tr('componentRepo:deleteComponentDescription', {
                  componentName: state.component.name,
                })}
              </p>
              <div>
                <AlertTriangle aria-hidden="true" />
                {tr('componentRepo:deleteComponentArtifactsRetained')}
              </div>
              {actionError ? (
                <div className="component-version-delete-error">
                  <AlertTriangle aria-hidden="true" />
                  {actionError}
                </div>
              ) : null}
            </div>
            <footer>
              <button
                disabled={deletingComponent}
                onClick={() => {
                  setConfirmingDeleteComponent(false);
                  setActionError(null);
                }}
                type="button"
              >
                {tr('componentRepo:cancel')}
              </button>
              <button
                className="component-version-delete-confirm"
                disabled={deletingComponent}
                onClick={() => void confirmDeleteComponent()}
                type="button"
              >
                {deletingComponent ? <LoaderCircle aria-hidden="true" /> : <Trash2 aria-hidden="true" />}
                {tr(
                  deletingComponent
                    ? 'componentRepo:deletingComponent'
                    : 'componentRepo:deleteComponent',
                )}
              </button>
            </footer>
          </section>
        </div>
      ) : null}

      {state.error ? <div className="asset-error">{state.error}</div> : null}
      {actionError ? <div className="asset-error">{actionError}</div> : null}
      {actionNotice ? <div className="component-library-notice">{actionNotice}</div> : null}
      {state.loading ? <div className="asset-loading">{appConfig.texts.loading}</div> : null}

      <section className="component-detail-preview">
        <div className="component-detail-preview-stage">
          {state.preview?.model ? (
            <ComponentScene
              preview={{ model: state.preview.model }}
              registerReset={registerPreviewReset}
              selectedConnector={selectedSceneConnector}
            />
          ) : null}
          {state.previewError ? (
            <div className="asset-error">{state.previewError}</div>
          ) : null}
          {!state.preview?.model && state.previewLoading && !state.previewError ? (
            <div className="asset-loading">{tr('componentRepo:loadingPreview')}</div>
          ) : null}
          {state.preview?.model ? (
            <button
              className="component-detail-preview-reset"
              onClick={() => resetViewRef.current?.()}
              type="button"
            >
              <RefreshCw aria-hidden="true" />
              {tr('componentRepo:resetPreview')}
            </button>
          ) : null}
          {selectedConnector ? (
            <div className="component-detail-selected-connector">
              <Crosshair aria-hidden="true" />
              <span>
                {tr('componentRepo:selectedConnectionPoint')}: {selectedConnector.connectorType
                  ?? selectedConnector.connectorKind}
              </span>
              <button
                onClick={() => setSelectedConnectorId(null)}
                type="button"
              >
                {tr('componentRepo:clearConnectionPointSelection')}
              </button>
            </div>
          ) : null}
        </div>
        <div className="component-detail-preview-meta">
          <strong>{state.component?.name ?? tr('componentRepo:component')}</strong>
          <span>{state.version ? `v${state.version.version} · ${state.version.id}` : '—'}</span>
          {state.version ? <StatusPill status={state.version.status} /> : null}
          {state.validationReport?.passed ? <StatusPill status="passed" /> : null}
          {componentOwnedByActor && state.version ? (
            <button
              className="component-diff-open-button"
              onClick={() => {
                if (state.version) void compareVersion(state.version);
              }}
              type="button"
            >
              <GitCompareArrows aria-hidden="true" />
              {tr('componentRepo:compareWithPreviousVersion')}
            </button>
          ) : null}
          <div className="component-detail-groups">
            <span><FolderTree aria-hidden="true" />{tr('componentRepo:groups')}</span>
            <div>
              {selectedGroups.length > 0 ? selectedGroups.map((group) => (
                <em key={group.id}>{group.name}</em>
              )) : <small>{tr('componentRepo:notInCustomGroup')}</small>}
            </div>
          </div>
        </div>
      </section>

      {diffView.targetVersion ? (
        <section className="component-version-diff-panel" aria-live="polite">
          <header className="component-version-diff-header">
            <div>
              <span><GitCompareArrows aria-hidden="true" /></span>
              <div>
                <h2>{tr('componentRepo:versionComparison')}</h2>
                <p>{tr('componentRepo:versionComparisonDescription')}</p>
              </div>
            </div>
            <div>
              {diffView.diff ? (
                <button onClick={() => diffResetRef.current?.()} type="button">
                  <RefreshCw aria-hidden="true" />
                  {tr('componentRepo:resetPreview')}
                </button>
              ) : null}
              <button onClick={closeVersionDiff} type="button">
                <X aria-hidden="true" />
                {tr('componentRepo:closeComparison')}
              </button>
            </div>
          </header>

          {diffView.loading ? (
            <div className="component-version-diff-status">
              <LoaderCircle aria-hidden="true" className="component-library-spin" />
              {tr('componentRepo:loadingVersionComparison')}
            </div>
          ) : null}
          {diffView.error ? <div className="asset-error">{diffView.error}</div> : null}

          {diffView.diff && diffView.afterPreview?.model ? (
            <>
              <ComponentDiffScene
                afterLabel={tr('componentRepo:diffAfterVersion', {
                  version: diffView.targetVersion.version,
                })}
                afterModel={diffView.afterPreview.model}
                beforeLabel={diffBaseVersion
                  ? tr('componentRepo:diffBeforeVersion', { version: diffBaseVersion.version })
                  : tr('componentRepo:diffEmptyBaseline')}
                beforeModel={diffView.beforePreview?.model ?? null}
                diff={diffView.diff}
                emptyBeforeLabel={tr('componentRepo:diffNoPreviousModel')}
                focus={diffFocus}
                loadFailedLabel={tr('componentRepo:diffPreviewUnavailable')}
                registerReset={(reset) => { diffResetRef.current = reset; }}
              />

              <div className="component-version-diff-summary">
                <DiffMetric label={tr('componentRepo:diffAdded')} value={diffView.diff.summary.addedInstances} />
                <DiffMetric label={tr('componentRepo:diffRemoved')} value={diffView.diff.summary.removedInstances} />
                <DiffMetric label={tr('componentRepo:diffMoved')} value={diffView.diff.summary.transformChangedInstances} />
                <DiffMetric label={tr('componentRepo:diffColorChanged')} value={diffView.diff.summary.colorChangedInstances} />
                <DiffMetric label={tr('componentRepo:diffReplaced')} value={diffView.diff.summary.replacedInstances} />
                <DiffMetric label={tr('componentRepo:diffAmbiguous')} value={diffView.diff.summary.ambiguousGroups} />
              </div>

              <div className="component-version-diff-legend" aria-label={tr('componentRepo:diffLegend')}>
                {Object.entries(diffChangeLabelKeys).map(([kind, key]) => (
                  <span key={kind}>
                    <i className={`component-diff-color component-diff-color-${kind}`} />
                    {trDynamic(key)}
                  </span>
                ))}
                <span>
                  <i className="component-diff-color component-diff-color-ambiguous" />
                  {tr('componentRepo:diffAmbiguous')}
                </span>
              </div>

              {diffView.diff.truncated ? (
                <div className="component-version-diff-warning">
                  <AlertTriangle aria-hidden="true" />
                  {tr('componentRepo:diffDetailsTruncated')}
                </div>
              ) : null}

              <div className="component-version-diff-change-list">
                {visibleDiffChanges.map((change, index) => {
                  const beforeInstanceId = change.before?.instanceId;
                  const afterInstanceId = change.after?.instanceId;
                  const selected = diffFocus?.beforeInstanceId === beforeInstanceId
                    && diffFocus?.afterInstanceId === afterInstanceId;
                  return (
                    <button
                      aria-pressed={selected}
                      className={selected ? 'is-selected' : undefined}
                      key={`${change.kind}-${beforeInstanceId ?? ''}-${afterInstanceId ?? ''}-${index}`}
                      onClick={() => setDiffFocus(selected ? null : { beforeInstanceId, afterInstanceId })}
                      type="button"
                    >
                      <i className={`component-diff-color component-diff-color-${change.kind}`} />
                      <strong>{trDynamic(diffChangeLabelKeys[change.kind])}</strong>
                      <span>{change.after?.partRef ?? change.before?.partRef}</span>
                      <small>{change.after?.instanceId ?? change.before?.instanceId}</small>
                    </button>
                  );
                })}
                {hiddenDiffChangeCount > 0 ? (
                  <div>{tr('componentRepo:moreDiffChangesNotShown', { count: hiddenDiffChangeCount })}</div>
                ) : null}
                {visibleDiffChanges.length === 0 && diffView.diff.summary.ambiguousGroups === 0 ? (
                  <div>{tr('componentRepo:noVersionChanges')}</div>
                ) : null}
              </div>
            </>
          ) : null}
        </section>
      ) : null}

      {state.validationLoading && state.version?.validationReportId ? (
        <section className="component-repo-panel">
          <div className="asset-loading">{appConfig.texts.loading}</div>
        </section>
      ) : null}
      {state.validationReport ? (
        <section className="component-repo-panel component-repo-validation">
          <div>
            <strong>{tr('componentRepo:validation')}</strong>
            <StatusPill status={state.validationReport.passed ? 'passed' : 'blocked'} />
          </div>
          {state.validationReport.checks.map((check) => (
            <div className="component-repo-check" key={check.code}>
              <span>{localizeStructuredMessage(check)}</span>
              <StatusPill status={check.status} />
            </div>
          ))}
        </section>
      ) : null}

      <section className="component-detail-metrics" aria-label={tr('componentRepo:componentOverview')}>
        <DetailMetric icon={<Boxes />} label={tr('componentRepo:partCount')} value={state.partDetails?.partCount ?? 0} />
        <DetailMetric icon={<GitBranch />} label={tr('componentRepo:relations')} value={state.relations.length} />
        <DetailMetric icon={<Braces />} label={tr('componentRepo:connectionPointCount')} value={connectors.length} />
        <DetailMetric icon={<Plug />} label={tr('componentRepo:externalInterfaceCount')} value={externalInterfaces.length} />
      </section>

      <section className="component-detail-grid">
        <article className="component-repo-panel component-detail-wide-panel">
          <div className="component-repo-panel-title">
            <Braces aria-hidden="true" />
            <span>{tr('componentRepo:connectionPoints')}</span>
          </div>
          {state.connectorError ? <div className="asset-error">{state.connectorError}</div> : null}
          {state.connectorLoading ? (
            <div className="asset-loading">{appConfig.texts.loading}</div>
          ) : connectorPartGroups.length > 0 ? (
            <div className="component-detail-connectors-by-part">
              <div
                aria-label={tr('componentRepo:partsList')}
                className="component-detail-connector-part-tabs"
                role="tablist"
              >
                {connectorPartGroups.map((group) => {
                  const active = group.partInstanceId === activeConnectorPart?.partInstanceId;
                  return (
                    <button
                      aria-selected={active}
                      className={active ? 'is-active' : undefined}
                      key={group.partInstanceId}
                      onClick={() => {
                        setActiveConnectorPartId(group.partInstanceId);
                        setSelectedConnectorId(null);
                      }}
                      role="tab"
                      type="button"
                    >
                      <strong>{group.partRef}</strong>
                      <small>{group.partInstanceId}</small>
                      <span>{group.connectors.length}</span>
                    </button>
                  );
                })}
              </div>
              {activeConnectorPart ? (
                <div className="component-detail-connector-list" role="tabpanel">
                  {activeConnectorPart.connectors.map((connector) => (
                    <button
                      aria-label={tr('componentRepo:selectConnectionPoint', {
                        id: connector.worldConnectorId,
                      })}
                      aria-pressed={connector.worldConnectorId === selectedConnectorId}
                      className={`component-detail-connector${
                        connector.worldConnectorId === selectedConnectorId ? ' is-selected' : ''
                      }`}
                      key={connector.worldConnectorId}
                      onClick={() => setSelectedConnectorId((current) => (
                        current === connector.worldConnectorId
                          ? null
                          : connector.worldConnectorId
                      ))}
                      type="button"
                    >
                      <div>
                        <strong>{connector.connectorType ?? connector.connectorKind}</strong>
                        <Crosshair aria-hidden="true" />
                      </div>
                      <span>{trDynamic(connectorGroupLabelKeys[connector.state])}</span>
                      <small>{connector.connectorId}</small>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          ) : <div className="asset-empty">{tr('componentRepo:noConnectionPoints')}</div>}
        </article>

        <article className="component-repo-panel component-detail-wide-panel">
          <div className="component-repo-panel-title">
            <Layers3 aria-hidden="true" />
            <span>{tr('componentRepo:partsList')}</span>
          </div>
          {state.partsLoading ? (
            <div className="asset-loading">{appConfig.texts.loading}</div>
          ) : partSummaries.length > 0 ? (
            <div className="component-detail-part-card-grid">
              {partSummaries.map((part) => (
                <PartSummaryCard
                  key={part.key}
                  missingGeometryLabel={tr('componentRepo:previewGeometryMissing')}
                  part={part}
                />
              ))}
            </div>
          ) : <div className="asset-empty">{tr('componentRepo:noParts')}</div>}
        </article>

        <article className="component-repo-panel component-detail-wide-panel">
          <div aria-label={tr('componentRepo:importHistoryForComponent')} className="component-detail-history-tabs" role="tablist">
            <button
              aria-selected={historyTab === 'versions'}
              className={historyTab === 'versions' ? 'component-detail-history-tab-active' : undefined}
              onClick={() => setHistoryTab('versions')}
              role="tab"
              type="button"
            >
              <GitBranch aria-hidden="true" />
              {tr('componentRepo:versionHistory')}
            </button>
            <button
              aria-selected={historyTab === 'imports'}
              className={historyTab === 'imports' ? 'component-detail-history-tab-active' : undefined}
              onClick={() => setHistoryTab('imports')}
              role="tab"
              type="button"
            >
              <FileClock aria-hidden="true" />
              {tr('componentRepo:importHistory')}
            </button>
          </div>
          {historyTab === 'versions' ? (
            <div className="component-detail-version-list" role="tabpanel">
              {state.versions.map((version) => (
                <div key={version.id}>
                  <strong>v{version.version}</strong>
                  <span>{version.id}</span>
                  <StatusPill status={version.status} />
                  {componentOwnedByActor ? (
                    <button
                      className="component-version-diff-list-button"
                      onClick={() => void compareVersion(version)}
                      type="button"
                    >
                      <GitCompareArrows aria-hidden="true" />
                      {tr('componentRepo:compareWithPreviousVersion')}
                    </button>
                  ) : null}
                  {state.component ? (
                    <ComponentVersionActions
                      componentName={state.component.name}
                      isOnlyVersion={state.versions.length === 1}
                      onDeleted={(deletedVersion) => {
                        setActionNotice(tr('componentRepo:versionDeleted', {
                          version: deletedVersion.version,
                        }));
                        setRefreshToken((current) => current + 1);
                      }}
                      version={version}
                    />
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <div role="tabpanel">
              <ComponentImportHistoryList componentId={componentId} />
            </div>
          )}
        </article>
      </section>
    </section>
  );
}

function preferredDetailVersion(
  component: ComponentResponse,
  versions: ComponentVersionResponse[],
): ComponentVersionResponse | undefined {
  const current = versions.find((item) => item.id === component.currentVersionId);
  const currentCreatedAt = current ? Date.parse(current.createdAt) : Number.NEGATIVE_INFINITY;
  const newerDraft = versions.find(
    (item) => item.status === 'draft' && Date.parse(item.createdAt) > currentCreatedAt,
  );
  return newerDraft ?? current ?? versions[0];
}

function DiffMetric({ label, value }: { label: string; value: number }) {
  return (
    <article>
      <strong>{value}</strong>
      <span>{label}</span>
    </article>
  );
}

function DetailMetric({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
}) {
  return (
    <article>
      <span>{icon}</span>
      <div><strong>{value}</strong><small>{label}</small></div>
    </article>
  );
}

function PartSummaryCard({
  part,
  missingGeometryLabel,
}: {
  part: PartSummary;
  missingGeometryLabel: string;
}) {
  const geometryAvailable = part.geometryStatus === 'ready';
  const content = (
    <>
      <PartCardImage src={null} />
      <span className="component-detail-part-card-copy">
        <strong>{part.name}</strong>
        <small>{part.partRef}</small>
        {!geometryAvailable ? (
          <span className="component-detail-part-card-availability">{missingGeometryLabel}</span>
        ) : null}
        <em>×{part.quantity}</em>
      </span>
    </>
  );
  if (!part.partLibraryVersionId) {
    return (
      <article className={`component-detail-part-card${geometryAvailable ? '' : ' is-unavailable'}`}>
        {content}
      </article>
    );
  }
  return (
    <Link
      className={`component-detail-part-card${geometryAvailable ? '' : ' is-unavailable'}`}
      to={`/parts/${encodeURIComponent(part.partLibraryVersionId)}/${encodeURIComponent(part.partRef)}`}
    >
      {content}
    </Link>
  );
}

function groupConnectorsByPart(
  connectors: ComponentConnectorResponse[],
): ConnectorPartGroup[] {
  const groups = new Map<string, ConnectorPartGroup>();
  for (const connector of connectors) {
    const group = groups.get(connector.partInstanceId) ?? {
      partInstanceId: connector.partInstanceId,
      partRef: connector.partRef,
      connectors: [],
    };
    group.connectors.push(connector);
    groups.set(connector.partInstanceId, group);
  }
  return [...groups.values()]
    .filter((group) => group.connectors.length > 0)
    .map((group) => ({
      ...group,
      connectors: [...group.connectors].sort(
        (left, right) => (
          (connectorStateRank.get(left.state) ?? Number.MAX_SAFE_INTEGER)
          - (connectorStateRank.get(right.state) ?? Number.MAX_SAFE_INTEGER)
        ) || left.connectorId.localeCompare(right.connectorId),
      ),
    }));
}

function PartCardImage({ src }: { src: string | null }) {
  const [failed, setFailed] = React.useState(false);
  React.useEffect(() => setFailed(false), [src]);
  return (
    <span className="component-detail-part-card-image">
      {src && !failed ? (
        <img
          alt=""
          decoding="async"
          loading="lazy"
          onError={() => setFailed(true)}
          src={src}
        />
      ) : <Boxes aria-hidden="true" />}
    </span>
  );
}
