import React from 'react';
import { localizeStructuredMessage } from '../api/client';
import {
  Boxes,
  CheckCircle2,
  GitBranch,
  Plug,
  RefreshCw,
  Rocket,
  ShieldCheck,
  Upload,
  XCircle,
} from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import appConfig from '../app/appConfig';
import { useAppTranslation } from '../i18n';
import {
  confirmRelation,
  detectRelations,
  getConnectorAnalysis,
  getCandidate,
  getComponent,
  getComponentVersion,
  listComponentVersions,
  listRelations,
  loadCandidatePreview,
  loadComponentVersionPreview,
  publishVersion,
  rejectRelation,
  validateCandidate,
  type ComponentCandidateResponse,
  type ComponentPreviewResponse,
  type ComponentResponse,
  type ComponentConnectorResponse,
  type ComponentInterfaceResponse,
  type ComponentRelationCandidateResponse,
  type ComponentValidationReportResponse,
  type ComponentVersionPreviewModelResponse,
  type ComponentVersionResponse,
} from './componentRepoApi';
import { ComponentUploadDialog, routeFor, StatusPill } from './ComponentRepoPage';
import { ComponentScene } from '../parts/PartViewerPage';

type CandidateWorkbenchState = {
  relations: ComponentRelationCandidateResponse[];
  freeConnectors: ComponentConnectorResponse[];
  interfaces: ComponentInterfaceResponse[];
  candidate: ComponentCandidateResponse | null;
  component: ComponentResponse | null;
  currentVersion: ComponentVersionResponse | null;
  preview: ComponentPreviewResponse | ComponentVersionPreviewModelResponse | null;
  previewStatus: 'idle' | 'loading' | 'error';
  validationReport: ComponentValidationReportResponse | null;
  publishedVersion: ComponentVersionResponse | null;
  loading: boolean;
  error: string | null;
  message: string | null;
};

export function ComponentCandidateWorkbenchPage() {
  const tr = useAppTranslation();
  const params = useParams();
  const navigate = useNavigate();
  const routeCandidateId = params.candidateId ?? '';
  const componentId = params.componentId ?? '';
  const [candidateId, setCandidateId] = React.useState(routeCandidateId);
  const resetViewRef = React.useRef<(() => void) | null>(null);
  const registerPreviewReset = React.useCallback((reset: (() => void) | null) => {
    resetViewRef.current = reset;
  }, []);
  const [isUploadOpen, setIsUploadOpen] = React.useState(false);
  const [state, setState] = React.useState<CandidateWorkbenchState>({
    relations: [],
    freeConnectors: [],
    interfaces: [],
    candidate: null,
    component: null,
    currentVersion: null,
    preview: null,
    previewStatus: 'idle',
    validationReport: null,
    publishedVersion: null,
    loading: false,
    error: null,
    message: null,
  });
  const [componentName, setComponentName] = React.useState('');
  const [componentCategory, setComponentCategory] = React.useState('');
  const [version, setVersion] = React.useState('0.1.0');
  const [releaseNote, setReleaseNote] = React.useState('');

  const runTask = React.useCallback(
    async (task: () => Promise<void>, successMessage?: string) => {
      setState((current) => ({ ...current, loading: true, error: null, message: null }));
      try {
        await task();
        setState((current) => ({
          ...current,
          loading: false,
          error: null,
          message: successMessage ?? null,
        }));
      } catch (error) {
        setState((current) => ({
          ...current,
          loading: false,
          error: error instanceof Error ? error.message : appConfig.texts.loadFailed,
          message: null,
        }));
      }
    },
    [],
  );

  const refreshReviewData = React.useCallback(async () => {
    const [candidate, relations, connectorAnalysis] = await Promise.all([
      getCandidate(candidateId),
      listRelations(candidateId),
      getConnectorAnalysis(candidateId),
    ]);
    const freeConnectors = connectorAnalysis.connectors.filter(
      (connector) => connector.state === 'external',
    );
    setState((current) => ({
      ...current,
      candidate,
      relations,
      freeConnectors,
      interfaces: connectorAnalysis.externalInterfaces,
    }));
  }, [candidateId]);

  React.useEffect(() => {
    let active = true;
    const loadContext = async () => {
      setState((current) => ({ ...current, loading: true, error: null }));
      try {
        let component: ComponentResponse | null = null;
        let currentVersion: ComponentVersionResponse | null = null;
        let candidate: ComponentCandidateResponse;
        let preview: ComponentPreviewResponse | ComponentVersionPreviewModelResponse;
        if (componentId) {
          const [loadedComponent, versions] = await Promise.all([
            getComponent(componentId),
            listComponentVersions(componentId),
          ]);
          const selectedVersion = versions.find((item) => item.id === loadedComponent.currentVersionId) ?? versions[0];
          if (!selectedVersion) throw new Error(tr('componentRepo:noComponentVersions'));
          component = loadedComponent;
          currentVersion = selectedVersion;
          candidate = await getCandidate(selectedVersion.componentCandidateId);
          preview = await loadComponentVersionPreview(currentVersion.id);
        } else {
          if (!routeCandidateId) throw new Error(tr('componentRepo:candidateIdIsMissing'));
          candidate = await getCandidate(routeCandidateId);
          const componentRecordId = String(candidate.reviewDecisions.componentId ?? '');
          const draftVersionId = String(candidate.reviewDecisions.draftVersionId ?? '');
          if (componentRecordId && draftVersionId) {
            [component, currentVersion] = await Promise.all([
              getComponent(componentRecordId),
              getComponentVersion(draftVersionId),
            ]);
            preview = await loadComponentVersionPreview(currentVersion.id);
          } else {
            // Parsed candidates can be previewed directly before a draft version exists.
            preview = await loadCandidatePreview(candidate.id);
          }
        }
        if (!active) return;
        setCandidateId(candidate.id);
        setComponentName(component?.name ?? '');
        setComponentCategory(component?.category ?? '');
        if (currentVersion) setVersion(currentVersion.version);
        setState((current) => ({
          ...current,
          candidate,
          component,
          currentVersion,
          preview,
          previewStatus: 'idle',
          publishedVersion: (
            currentVersion && currentVersion.id === component?.currentVersionId
              ? currentVersion
              : null
          ),
          loading: false,
        }));
      } catch (error) {
        if (active) {
          setState((current) => ({
            ...current,
            loading: false,
            previewStatus: 'error',
            error: error instanceof Error ? error.message : appConfig.texts.loadFailed,
          }));
        }
      }
    };
    void loadContext();
    return () => { active = false; };
  }, [componentId, routeCandidateId, tr]);

  React.useEffect(() => {
    if (candidateId) void runTask(refreshReviewData);
  }, [candidateId, refreshReviewData, runTask]);

  const detect = () =>
    runTask(async () => {
      const relations = await detectRelations(candidateId);
      const candidate = await getCandidate(candidateId);
      const connectorAnalysis = await getConnectorAnalysis(candidateId);
      setState((current) => ({
        ...current,
        candidate,
        relations,
        freeConnectors: connectorAnalysis.connectors.filter(
          (connector) => connector.state === 'external',
        ),
        interfaces: connectorAnalysis.externalInterfaces,
      }));
    }, tr('componentRepo:connectionDetectionComplete'));

  const confirm = (relationId: string) =>
    runTask(async () => {
      await confirmRelation(candidateId, relationId);
      await refreshReviewData();
    }, tr('componentRepo:connectionConfirmed'));

  const reject = (relationId: string) =>
    runTask(async () => {
      await rejectRelation(candidateId, relationId);
      await refreshReviewData();
    }, tr('componentRepo:connectionRejected'));

  const validate = () =>
    runTask(async () => {
      const validationReport = await validateCandidate(candidateId);
      setState((current) => ({ ...current, validationReport }));
    }, tr('componentRepo:validationComplete'));

  const publish = () =>
    runTask(async () => {
      const draftVersionId = state.currentVersion?.id;
      if (!draftVersionId) {
        throw new Error(tr('componentRepo:draftVersionUnavailable'));
      }
      if (!componentName.trim()) throw new Error(tr('componentRepo:enterAComponentName'));
      const publishedVersion = await publishVersion(draftVersionId, {
        releaseNote: releaseNote.trim(),
        name: componentName.trim(),
        category: componentCategory.trim() || null,
        version: version.trim() || '0.1.0',
      });
      const component = await getComponent(publishedVersion.componentId);
      setState((current) => ({ ...current, component, currentVersion: publishedVersion, publishedVersion }));
    }, tr('componentRepo:componentVersionPublished'));

  if (!candidateId && !componentId && !routeCandidateId) {
    return (
      <section className="component-repo-page">
        <div className="asset-error">{tr('componentRepo:candidateIdIsMissing')}</div>
      </section>
    );
  }

  const isEditable = state.currentVersion?.status === 'draft';

  return (
    <section className="component-repo-page">
      <header className="component-repo-header">
        <div>
          <h1>{appConfig.texts.componentRepoCandidateTitle}</h1>
          <p>
            {appConfig.texts.componentRepoCandidateSubtitle} · {candidateId}
          </p>
        </div>
        <div className="component-repo-actions">
          {state.component ? (
            <button onClick={() => setIsUploadOpen(true)} type="button">
              <Upload aria-hidden="true" />
              {tr('componentRepo:uploadNewDrawing')}
            </button>
          ) : null}
          <button onClick={() => navigate(routeFor('componentRepoImport'))} type="button">
            {appConfig.texts.componentRepoNewImport}
          </button>
          <button onClick={() => navigate(routeFor('componentRepo'))} type="button">
            {appConfig.texts.componentRepoBackToList}
          </button>
        </div>
      </header>

      {state.error ? <div className="asset-error">{state.error}</div> : null}
      {state.message ? <div className="component-repo-message">{state.message}</div> : null}
      {state.loading ? <div className="asset-loading">{appConfig.texts.loading}</div> : null}

      <section className="component-detail-preview">
        <div className="component-detail-preview-stage">
          {state.preview?.model ? (
            <ComponentScene
              preview={{ model: state.preview.model }}
              registerReset={registerPreviewReset}
            />
          ) : null}
          {!state.preview?.model && state.previewStatus !== 'error' ? (
            <div className="asset-loading">{tr('componentRepo:loadingPreview')}</div>
          ) : null}
          {state.previewStatus === 'error' ? (
            <div className="asset-error">{tr('componentRepo:previewUnavailable')}</div>
          ) : null}
          {state.preview?.model ? (
            <button className="component-detail-preview-reset" onClick={() => resetViewRef.current?.()} type="button">
              <RefreshCw aria-hidden="true" />{tr('componentRepo:resetPreview')}
            </button>
          ) : null}
        </div>
        <div className="component-detail-preview-meta">
          <strong>{state.component?.name ?? tr('componentRepo:component')}</strong>
          <span>{state.currentVersion ? `v${state.currentVersion.version} · ${state.currentVersion.id}` : '—'}</span>
          <StatusPill
            status={state.currentVersion
              ? (state.currentVersion.id === state.component?.currentVersionId ? 'published' : 'draft')
              : (state.candidate?.status ?? 'pending_review')}
          />
        </div>
      </section>

      <section className="component-repo-workbench">
        <aside className="component-repo-panel">
          <div className="component-repo-panel-title">
            <Boxes aria-hidden="true" />
            <span>{tr('componentRepo:candidate')}</span>
          </div>
          <div className="component-repo-card-list">
            <Metric label={tr('componentRepo:candidateId')} value={candidateId} />
            <Metric label={tr('componentRepo:relations')} value={String(state.relations.length)} />
            <Metric label={tr('componentRepo:freeConnectors')} value={String(state.freeConnectors.length)} />
            <Metric label={tr('componentRepo:interfaces')} value={String(state.interfaces.length)} />
          </div>

          <div className="component-repo-stepper">
            <Step done={state.relations.length > 0} label={tr('componentRepo:detect')} />
            <Step done={state.interfaces.length > 0} label={tr('componentRepo:interface')} />
            <Step done={Boolean(state.validationReport?.passed)} label={tr('componentRepo:validate')} />
            <Step done={Boolean(state.currentVersion)} label={tr('componentRepo:draft')} />
            <Step done={Boolean(state.publishedVersion)} label={tr('componentRepo:publish')} />
          </div>

          {state.validationReport ? <ValidationReport report={state.validationReport} /> : null}
        </aside>

        <main className="component-repo-panel component-repo-workspace">
          <div className="component-repo-toolbar">
            <div className="component-repo-panel-title">
              <GitBranch aria-hidden="true" />
              <span>{tr('componentRepo:relationReview')}</span>
            </div>
            <button disabled={!isEditable || state.loading} onClick={() => void detect()} type="button">
              <RefreshCw aria-hidden="true" />
              {appConfig.texts.componentRepoDetectRelations}
            </button>
          </div>

          {state.relations.length > 0 ? (
            <div className="component-repo-relation-list">
              {state.relations.map((relation) => (
                <article className="component-repo-relation-card" key={relation.id}>
                  <div>
                    <strong>{relation.connectionType}</strong>
                    <StatusPill status={relation.status} />
                  </div>
                  <span>
                    {endpointLabel(relation.endpointA)} ↔ {endpointLabel(relation.endpointB)}
                  </span>
                  <div className="component-repo-relation-metrics">
                    <Metric label={tr('componentRepo:position')} value={relation.positionResidual.toFixed(3)} />
                    <Metric label={tr('componentRepo:rotation')} value={`${relation.rotationResidual.toFixed(2)}°`} />
                    <Metric label={tr('componentRepo:confidence')} value={relation.confidence.toFixed(2)} />
                  </div>
                  <div className="component-repo-inline-actions">
                    <button disabled={!isEditable || state.loading || relation.status === 'confirmed'} onClick={() => void confirm(relation.id)} type="button">
                      <CheckCircle2 aria-hidden="true" />
                      {tr('componentRepo:confirm')}
                    </button>
                    <button disabled={!isEditable || state.loading || relation.status === 'rejected' || relation.status === 'confirmed'} onClick={() => void reject(relation.id)} type="button">
                      <XCircle aria-hidden="true" />
                      {tr('componentRepo:reject')}
                    </button>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="asset-empty">{appConfig.texts.componentRepoNoRelations}</div>
          )}
        </main>

        <aside className="component-repo-panel">
          <div className="component-repo-panel-title">
            <Plug aria-hidden="true" />
            <span>{tr('componentRepo:externalInterface')}</span>
          </div>
          <p>{tr('componentRepo:automaticInterfaceDescription')}</p>

          {state.interfaces.length > 0 ? (
            <div className="component-repo-card-list">
              {state.interfaces.map((componentInterface) => (
                <article className="component-repo-card" key={componentInterface.id}>
                  <div>
                    <strong>{String(componentInterface.sourceConnector.connectorType ?? componentInterface.sourceConnector.connectorKind)}</strong>
                    <StatusPill status={componentInterface.reviewStatus} />
                  </div>
                  <span>{String(componentInterface.sourceConnector.partRef)} · {componentInterface.worldConnectorId}</span>
                </article>
              ))}
            </div>
          ) : (
            <div className="asset-empty">{appConfig.texts.componentRepoNoInterfaces}</div>
          )}

          <div className="component-repo-panel-title">
            <Rocket aria-hidden="true" />
            <span>{tr('componentRepo:draftPublish')}</span>
          </div>
          <label className="component-repo-control-field">
            <span>{appConfig.texts.componentRepoComponentName}</span>
            <input
              disabled={!isEditable}
              onChange={(event) => setComponentName(event.target.value)}
              placeholder={appConfig.texts.componentRepoComponentNamePlaceholder}
              value={componentName}
            />
          </label>
          <label className="component-repo-control-field">
            <span>{appConfig.texts.componentRepoCategory}</span>
            <input
              disabled={!isEditable}
              onChange={(event) => setComponentCategory(event.target.value)}
              placeholder={appConfig.texts.componentRepoCategoryPlaceholder}
              value={componentCategory}
            />
          </label>
          <label className="component-repo-control-field">
            <span>{appConfig.texts.componentRepoVersion}</span>
            <input disabled={!isEditable} onChange={(event) => setVersion(event.target.value)} value={version} />
          </label>
          <label className="component-repo-control-field">
            <span>{appConfig.texts.componentRepoReleaseNote}</span>
            <input disabled={!isEditable} onChange={(event) => setReleaseNote(event.target.value)} value={releaseNote} />
          </label>
          <div className="component-repo-inline-actions component-repo-publish-actions">
            <button disabled={!isEditable || state.loading} onClick={() => void validate()} type="button">
              <ShieldCheck aria-hidden="true" />
              {appConfig.texts.componentRepoValidate}
            </button>
            <button disabled={!isEditable || state.loading} onClick={() => void publish()} type="button">
              {appConfig.texts.componentRepoPublish}
            </button>
          </div>
          {state.currentVersion ? (
            <div className="component-repo-summary-card">
              <strong>{state.currentVersion.id === state.component?.currentVersionId ? tr('componentRepo:publishedVersion') : tr('componentRepo:editingVersion')}: {state.currentVersion.id}</strong>
              <span>
                {state.component?.name} · v{state.currentVersion.version}
              </span>
            </div>
          ) : null}
          {state.publishedVersion ? (
            <div className="component-repo-message">
              {tr('componentRepo:published')}: {state.publishedVersion.id}
            </div>
          ) : null}
        </aside>
      </section>
      {isUploadOpen && state.component ? (
        <ComponentUploadDialog
          baseVersionId={state.component.currentVersionId ?? state.currentVersion?.id}
          onClose={() => setIsUploadOpen(false)}
          onUploaded={(result) => {
            setIsUploadOpen(false);
            navigate(routeFor('componentRepoCandidate').replace(
              ':candidateId',
              encodeURIComponent(result.id),
            ));
          }}
          targetComponentId={state.component.id}
        />
      ) : null}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="component-repo-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Step({ done, label }: { done: boolean; label: string }) {
  return (
    <div className={done ? 'component-repo-step component-repo-step-done' : 'component-repo-step'}>
      {done ? <CheckCircle2 aria-hidden="true" /> : <span />}
      {label}
    </div>
  );
}

function ValidationReport({ report }: { report: ComponentValidationReportResponse }) {
  const tr = useAppTranslation();
  return (
    <section className="component-repo-validation">
      <div>
        <strong>{tr('componentRepo:validation')}</strong>
        <StatusPill status={report.passed ? 'passed' : 'blocked'} />
      </div>
      {report.checks.map((check) => (
        <div className="component-repo-check" key={check.code}>
          <span>{localizeStructuredMessage(check)}</span>
          <StatusPill status={check.status} />
        </div>
      ))}
    </section>
  );
}

function endpointLabel(endpoint: Record<string, unknown>): string {
  const partRef = typeof endpoint.partRef === 'string' ? endpoint.partRef : 'part';
  const connectorType = typeof endpoint.connectorType === 'string' ? endpoint.connectorType : 'connector';
  return `${partRef}/${connectorType}`;
}
