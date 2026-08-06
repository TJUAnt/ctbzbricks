import React from 'react';
import {
  Boxes,
  Braces,
  Crosshair,
  FolderTree,
  GitBranch,
  Layers3,
  LoaderCircle,
  Plug,
  RefreshCw,
  Rocket,
} from 'lucide-react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import appConfig from '../app/appConfig';
import { useAuth } from '../auth/AuthContext';
import { useAppTranslation, useDynamicTranslation, type TranslationKey } from '../i18n';
import { ComponentScene, type ComponentSceneConnector } from '../parts/PartViewerPage';
import {
  getComponent,
  getConnectorAnalysis,
  listComponentGroupIds,
  listComponentGroups,
  listComponentVersions,
  listRelations,
  loadComponentVersionParts,
  loadComponentVersionPreview,
  publishVersion,
  type ComponentConnectorAnalysisResponse,
  type ComponentConnectorResponse,
  type ComponentGroupTreeResponse,
  type ComponentPreviewPartAvailability,
  type ComponentRelationCandidateResponse,
  type ComponentResponse,
  type ComponentVersionPartsResponse,
  type ComponentVersionPreviewModelResponse,
  type ComponentVersionResponse,
} from './componentRepoApi';
import { ComponentVersionActions } from './ComponentVersionActions';
import { routeFor, StatusPill } from './ComponentRepoPage';

type ComponentDetailState = {
  component: ComponentResponse | null;
  version: ComponentVersionResponse | null;
  versions: ComponentVersionResponse[];
  preview: ComponentVersionPreviewModelResponse | null;
  partDetails: ComponentVersionPartsResponse | null;
  connectorAnalysis: ComponentConnectorAnalysisResponse | null;
  relations: ComponentRelationCandidateResponse[];
  groupTree: ComponentGroupTreeResponse | null;
  groupIds: string[];
  loading: boolean;
  connectorLoading: boolean;
  partsLoading: boolean;
  error: string | null;
  connectorError: string | null;
};

type PartSummary = {
  key: string;
  partRef: string;
  imageUrl: string | null;
  name: string;
  quantity: number;
  availability: ComponentPreviewPartAvailability;
};

type ConnectorPartGroup = {
  partInstanceId: string;
  partRef: string;
  connectors: ComponentConnectorResponse[];
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

export function ComponentDetailPage() {
  const tr = useAppTranslation();
  const trDynamic = useDynamicTranslation();
  const { isConfigured: isAuthConfigured, isLoading: isAuthLoading, user } = useAuth();
  const navigate = useNavigate();
  const params = useParams();
  const componentId = params.componentId ?? '';
  const resetViewRef = React.useRef<(() => void) | null>(null);
  const [refreshToken, setRefreshToken] = React.useState(0);
  const [actionNotice, setActionNotice] = React.useState<string | null>(null);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [publishing, setPublishing] = React.useState(false);
  const [activeConnectorPartId, setActiveConnectorPartId] = React.useState<string | null>(null);
  const [selectedConnectorId, setSelectedConnectorId] = React.useState<string | null>(null);
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
    groupTree: null,
    groupIds: [],
    loading: true,
    connectorLoading: true,
    partsLoading: true,
    error: null,
    connectorError: null,
  });

  React.useEffect(() => {
    let active = true;
    const load = async () => {
      setState((current) => ({
        ...current,
        loading: true,
        connectorLoading: true,
        partsLoading: true,
        error: null,
        connectorError: null,
      }));
      try {
        const [component, versions, groupTree, groupIds] = await Promise.all([
          getComponent(componentId),
          listComponentVersions(componentId),
          listComponentGroups(),
          listComponentGroupIds(componentId),
        ]);
        const version = preferredDetailVersion(component, versions);
        if (!version) throw new Error(trRef.current('componentRepo:noComponentVersions'));
        const connectorAnalysisPromise = getConnectorAnalysis(version.componentCandidateId)
          .then((connectorAnalysis) => ({
            connectorAnalysis,
            connectorError: null as string | null,
          }))
          .catch((analysisError: unknown) => ({
            connectorAnalysis: null,
            connectorError: analysisError instanceof Error
              ? analysisError.message
              : appConfig.texts.loadFailed,
          }));
        const partDetailsPromise = loadComponentVersionParts(version.id)
          .then((partDetails) => ({ partDetails, failed: false }))
          .catch(() => ({ partDetails: null, failed: true }));
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
        const [preview, relations] = await Promise.all([
          loadComponentVersionPreview(version.id),
          listRelations(version.componentCandidateId),
        ]);
        if (!active) return;
        setState({
          component,
          version,
          versions,
          preview,
          partDetails: null,
          connectorAnalysis: null,
          relations,
          groupTree,
          groupIds,
          loading: false,
          connectorLoading: true,
          partsLoading: true,
          error: null,
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
      } catch (error) {
        if (!active) return;
        setState((current) => ({
          ...current,
          loading: false,
          connectorLoading: false,
          partsLoading: false,
          error: error instanceof Error ? error.message : appConfig.texts.loadFailed,
        }));
      }
    };
    if (componentId) void load();
    return () => {
      active = false;
    };
  }, [componentId, refreshToken]);

  const partSummaries = React.useMemo(
    () => (state.partDetails?.parts ?? []).map((part) => ({
      ...part,
      key: part.partRef,
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
  const canPublish = Boolean(
    state.component
      && state.version?.status === 'draft'
      && state.component.contentKind === 'user'
      && !isAuthLoading
      && (
        !isAuthConfigured
        || state.component.createdBy === `auth:${user?.id}`
      ),
  );
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
          {!state.preview?.model && !state.error ? (
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
                <PartSummaryCard key={part.key} part={part} />
              ))}
            </div>
          ) : <div className="asset-empty">{tr('componentRepo:noParts')}</div>}
        </article>

        <article className="component-repo-panel component-detail-wide-panel">
          <div className="component-repo-panel-title">
            <GitBranch aria-hidden="true" />
            <span>{tr('componentRepo:versionHistory')}</span>
          </div>
          <div className="component-detail-version-list">
            {state.versions.map((version) => (
              <div key={version.id}>
                <strong>v{version.version}</strong>
                <span>{version.id}</span>
                <StatusPill status={version.status} />
                {state.component ? (
                  <ComponentVersionActions
                    componentName={state.component.name}
                    isOnlyVersion={state.versions.length === 1}
                    onDeleted={(result, deletedVersion) => {
                      setActionNotice(tr('componentRepo:versionDeleted', {
                        version: deletedVersion.version,
                      }));
                      if (result.componentDeleted) {
                        navigate(routeFor('componentRepo'));
                        return;
                      }
                      setRefreshToken((current) => current + 1);
                    }}
                    version={version}
                  />
                ) : null}
              </div>
            ))}
          </div>
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

function PartSummaryCard({ part }: { part: PartSummary }) {
  const tr = useAppTranslation();
  const cardContent = (
    <>
      <PartCardImage src={part.imageUrl} />
      <span className="component-detail-part-card-copy">
        <strong>{part.name}</strong>
        <small>{part.partRef}</small>
        {part.availability !== 'ready' ? (
          <span className="component-detail-part-card-availability">
            {tr('componentRepo:partExcludedFromCalculation')}
          </span>
        ) : null}
        <em>×{part.quantity}</em>
      </span>
    </>
  );
  if (part.availability !== 'ready') {
    return (
      <article className="component-detail-part-card is-unavailable">
        {cardContent}
      </article>
    );
  }
  return (
    <Link
      className="component-detail-part-card"
      to={`/library/part/${encodeURIComponent(part.partRef)}`}
    >
      {cardContent}
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
