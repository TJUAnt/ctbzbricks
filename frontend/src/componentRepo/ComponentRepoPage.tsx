import React from 'react';
import { Boxes, ChevronRight, Download, RefreshCw, Upload } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import appConfig from '../app/appConfig.json';
import {
  downloadComponentVersionSource,
  listComponents,
  listComponentVersions,
  type ComponentResponse,
  type ComponentVersionResponse,
} from './componentRepoApi';

type ComponentRepoListState =
  | { status: 'loading'; components: ComponentResponse[]; error: null }
  | { status: 'ready'; components: ComponentResponse[]; error: null }
  | { status: 'error'; components: ComponentResponse[]; error: string };

export function ComponentRepoPage() {
  const navigate = useNavigate();
  const [state, setState] = React.useState<ComponentRepoListState>({
    status: 'loading',
    components: [],
    error: null,
  });
  const [selectedComponentId, setSelectedComponentId] = React.useState<string | null>(null);
  const [versions, setVersions] = React.useState<ComponentVersionResponse[]>([]);
  const [versionError, setVersionError] = React.useState<string | null>(null);
  const [downloadError, setDownloadError] = React.useState<string | null>(null);

  const refreshComponents = React.useCallback(() => {
    setState((current) => ({ status: 'loading', components: current.components, error: null }));
    listComponents()
      .then((components) => setState({ status: 'ready', components, error: null }))
      .catch((error: Error) =>
        setState((current) => ({
          status: 'error',
          components: current.components,
          error: error.message,
        })),
      );
  }, []);

  React.useEffect(() => {
    refreshComponents();
  }, [refreshComponents]);

  const loadVersions = async (componentId: string) => {
    setSelectedComponentId(componentId);
    setVersionError(null);
    try {
      setVersions(await listComponentVersions(componentId));
    } catch (error) {
      setVersionError(error instanceof Error ? error.message : appConfig.texts.loadFailed);
      setVersions([]);
    }
  };

  const selectedComponent = state.components.find((component) => component.id === selectedComponentId) ?? null;

  const downloadSource = async (versionId: string) => {
    setDownloadError(null);
    try {
      await downloadComponentVersionSource(versionId);
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : appConfig.texts.loadFailed);
    }
  };

  return (
    <section className="component-repo-page">
      <header className="component-repo-header">
        <div>
          <h1>{appConfig.texts.componentRepoTitle}</h1>
          <p>{appConfig.texts.componentRepoSubtitle}</p>
        </div>
        <div className="component-repo-actions">
          <button onClick={refreshComponents} type="button">
            <RefreshCw aria-hidden="true" />
            刷新
          </button>
          <button onClick={() => navigate(routeFor('componentRepoImport'))} type="button">
            <Upload aria-hidden="true" />
            {appConfig.texts.componentRepoNewImport}
          </button>
        </div>
      </header>

      {state.status === 'error' ? <div className="asset-error">{state.error}</div> : null}
      {state.status === 'loading' ? <div className="asset-loading">{appConfig.texts.loading}</div> : null}

      <section className="component-repo-layout component-repo-list-layout">
        <div className="component-repo-panel">
          <div className="component-repo-panel-title">
            <Boxes aria-hidden="true" />
            <span>Published Components</span>
          </div>
          {state.components.length > 0 ? (
            <div className="component-repo-table">
              {state.components.map((component) => (
                <button
                  className={
                    component.id === selectedComponentId
                      ? 'component-repo-row component-repo-row-active'
                      : 'component-repo-row'
                  }
                  key={component.id}
                  onClick={() => void loadVersions(component.id)}
                  type="button"
                >
                  <div>
                    <strong>{component.name}</strong>
                    <span>{component.id}</span>
                  </div>
                  <StatusPill status={component.status} />
                  <span>{component.category ?? '-'}</span>
                  <span>{component.currentVersionId ?? '-'}</span>
                  <ChevronRight aria-hidden="true" />
                </button>
              ))}
            </div>
          ) : state.status !== 'loading' ? (
            <div className="asset-empty">{appConfig.texts.componentRepoEmpty}</div>
          ) : null}
        </div>

        <aside className="component-repo-panel">
          <div className="component-repo-panel-title">
            <Download aria-hidden="true" />
            <span>Versions</span>
          </div>
          {!selectedComponent ? (
            <div className="asset-empty">选择一个组件查看已发布版本。</div>
          ) : null}
          {versionError ? <div className="asset-error">{versionError}</div> : null}
          {selectedComponent ? (
            <div className="component-repo-summary-card">
              <strong>{selectedComponent.name}</strong>
              <span>{selectedComponent.description ?? selectedComponent.category ?? selectedComponent.id}</span>
            </div>
          ) : null}
          {downloadError ? <div className="asset-error">{downloadError}</div> : null}
          {versions.length > 0 ? (
            <div className="component-repo-card-list">
              {versions.map((version) => (
                <article className="component-repo-card" key={version.id}>
                  <div>
                    <strong>
                      v{version.version} r{version.revision}
                    </strong>
                    <StatusPill status={version.status} />
                  </div>
                  <span>{version.id}</span>
                  <button onClick={() => void downloadSource(version.id)} type="button">
                    <Download aria-hidden="true" />
                    {appConfig.texts.componentRepoDownloadSource}
                  </button>
                </article>
              ))}
            </div>
          ) : selectedComponent && !versionError ? (
            <div className="asset-empty">暂无 published version。</div>
          ) : null}
        </aside>
      </section>
    </section>
  );
}

export function StatusPill({ status }: { status: string }) {
  return <span className={`component-repo-status component-repo-status-${status}`}>{status}</span>;
}

export function routeFor(page: keyof typeof appConfig.routePaths): string {
  return appConfig.routePaths[page];
}
