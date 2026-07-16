import React from 'react';
import {
  Boxes,
  CheckCircle2,
  GitBranch,
  Plug,
  RefreshCw,
  Rocket,
  ShieldCheck,
  XCircle,
} from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import appConfig from '../app/appConfig.json';
import {
  approveCandidate,
  confirmRelation,
  createInterface,
  detectRelations,
  listFreeConnectors,
  listInterfaces,
  listRelations,
  publishVersion,
  rejectRelation,
  validateCandidate,
  type ComponentApproveResponse,
  type ComponentFreeConnectorResponse,
  type ComponentInterfaceResponse,
  type ComponentRelationCandidateResponse,
  type ComponentValidationReportResponse,
  type ComponentVersionResponse,
} from './componentRepoApi';
import { routeFor, StatusPill } from './ComponentRepoPage';

type CandidateWorkbenchState = {
  relations: ComponentRelationCandidateResponse[];
  freeConnectors: ComponentFreeConnectorResponse[];
  interfaces: ComponentInterfaceResponse[];
  validationReport: ComponentValidationReportResponse | null;
  approval: ComponentApproveResponse | null;
  publishedVersion: ComponentVersionResponse | null;
  loading: boolean;
  error: string | null;
  message: string | null;
};

export function ComponentCandidateWorkbenchPage() {
  const params = useParams();
  const navigate = useNavigate();
  const candidateId = params.candidateId ?? '';
  const [state, setState] = React.useState<CandidateWorkbenchState>({
    relations: [],
    freeConnectors: [],
    interfaces: [],
    validationReport: null,
    approval: null,
    publishedVersion: null,
    loading: false,
    error: null,
    message: null,
  });
  const [interfaceName, setInterfaceName] = React.useState('mount_axle');
  const [selectedConnectorId, setSelectedConnectorId] = React.useState('');
  const [componentName, setComponentName] = React.useState('wheel_shell_component2');
  const [componentCategory, setComponentCategory] = React.useState('technic');
  const [version, setVersion] = React.useState('0.1.0');
  const [releaseNote, setReleaseNote] = React.useState('first publish');

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
    const [relations, interfaces] = await Promise.all([
      listRelations(candidateId),
      listInterfaces(candidateId),
    ]);
    let freeConnectors: ComponentFreeConnectorResponse[] = [];
    try {
      freeConnectors = await listFreeConnectors(candidateId);
    } catch {
      freeConnectors = [];
    }
    setState((current) => ({
      ...current,
      relations,
      freeConnectors,
      interfaces,
    }));
    setSelectedConnectorId((current) => current || freeConnectors[0]?.worldConnectorId || '');
  }, [candidateId]);

  React.useEffect(() => {
    if (!candidateId) {
      return;
    }
    void runTask(refreshReviewData);
  }, [candidateId, refreshReviewData, runTask]);

  const detect = () =>
    runTask(async () => {
      const relations = await detectRelations(candidateId);
      const freeConnectors = await listFreeConnectors(candidateId);
      setState((current) => ({ ...current, relations, freeConnectors }));
      setSelectedConnectorId((current) => current || freeConnectors[0]?.worldConnectorId || '');
    }, '连接识别完成');

  const confirm = (relationId: string) =>
    runTask(async () => {
      await confirmRelation(candidateId, relationId);
      await refreshReviewData();
    }, '连接已确认');

  const reject = (relationId: string) =>
    runTask(async () => {
      await rejectRelation(candidateId, relationId);
      await refreshReviewData();
    }, '连接已拒绝');

  const addInterface = () =>
    runTask(async () => {
      if (!selectedConnectorId || !interfaceName.trim()) {
        throw new Error('请选择 connector 并填写接口名称');
      }
      const created = await createInterface(candidateId, selectedConnectorId, interfaceName.trim());
      const interfaces = await listInterfaces(candidateId);
      setState((current) => ({ ...current, interfaces }));
      setInterfaceName(created.name);
    }, '外部接口已标记');

  const validate = () =>
    runTask(async () => {
      const validationReport = await validateCandidate(candidateId);
      setState((current) => ({ ...current, validationReport }));
    }, '验证完成');

  const approve = () =>
    runTask(async () => {
      if (!componentName.trim()) {
        throw new Error('请填写组件名称');
      }
      const approval = await approveCandidate(candidateId, {
        name: componentName.trim(),
        category: componentCategory.trim() || null,
        version: version.trim() || '0.1.0',
      });
      setState((current) => ({
        ...current,
        approval,
        validationReport: approval.validationReport,
      }));
    }, 'Draft version 已生成');

  const publish = () =>
    runTask(async () => {
      const draftVersionId = state.approval?.version.id;
      if (!draftVersionId) {
        throw new Error('请先生成 Draft version');
      }
      const publishedVersion = await publishVersion(draftVersionId, releaseNote.trim());
      setState((current) => ({ ...current, publishedVersion }));
    }, '组件版本已发布');

  if (!candidateId) {
    return (
      <section className="component-repo-page">
        <div className="asset-error">Candidate ID 缺失</div>
      </section>
    );
  }

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

      <section className="component-repo-workbench">
        <aside className="component-repo-panel">
          <div className="component-repo-panel-title">
            <Boxes aria-hidden="true" />
            <span>Candidate</span>
          </div>
          <div className="component-repo-card-list">
            <Metric label="Candidate ID" value={candidateId} />
            <Metric label="Relations" value={String(state.relations.length)} />
            <Metric label="Free connectors" value={String(state.freeConnectors.length)} />
            <Metric label="Interfaces" value={String(state.interfaces.length)} />
          </div>

          <div className="component-repo-stepper">
            <Step done={state.relations.length > 0} label="Detect" />
            <Step done={state.interfaces.length > 0} label="Interface" />
            <Step done={Boolean(state.validationReport?.passed)} label="Validate" />
            <Step done={Boolean(state.approval)} label="Draft" />
            <Step done={Boolean(state.publishedVersion)} label="Publish" />
          </div>

          {state.validationReport ? <ValidationReport report={state.validationReport} /> : null}
        </aside>

        <main className="component-repo-panel component-repo-workspace">
          <div className="component-repo-toolbar">
            <div className="component-repo-panel-title">
              <GitBranch aria-hidden="true" />
              <span>Relation Review</span>
            </div>
            <button disabled={state.loading} onClick={() => void detect()} type="button">
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
                    <Metric label="position" value={relation.positionResidual.toFixed(3)} />
                    <Metric label="rotation" value={`${relation.rotationResidual.toFixed(2)}°`} />
                    <Metric label="confidence" value={relation.confidence.toFixed(2)} />
                  </div>
                  <div className="component-repo-inline-actions">
                    <button disabled={state.loading || relation.status === 'confirmed'} onClick={() => void confirm(relation.id)} type="button">
                      <CheckCircle2 aria-hidden="true" />
                      Confirm
                    </button>
                    <button disabled={state.loading || relation.status === 'rejected'} onClick={() => void reject(relation.id)} type="button">
                      <XCircle aria-hidden="true" />
                      Reject
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
            <span>External Interface</span>
          </div>

          <label className="component-repo-control-field">
            <span>Free connector</span>
            <select value={selectedConnectorId} onChange={(event) => setSelectedConnectorId(event.target.value)}>
              {state.freeConnectors.map((connector) => (
                <option key={connector.worldConnectorId} value={connector.worldConnectorId}>
                  {connector.partRef} · {connector.connectorType ?? connector.connectorKind}
                </option>
              ))}
            </select>
          </label>
          <label className="component-repo-control-field">
            <span>{appConfig.texts.componentRepoInterfaceName}</span>
            <input
              onChange={(event) => setInterfaceName(event.target.value)}
              placeholder={appConfig.texts.componentRepoInterfaceNamePlaceholder}
              value={interfaceName}
            />
          </label>
          <button
            className="component-repo-primary-button"
            disabled={!selectedConnectorId || state.loading}
            onClick={() => void addInterface()}
            type="button"
          >
            {appConfig.texts.componentRepoCreateInterface}
          </button>

          {state.interfaces.length > 0 ? (
            <div className="component-repo-card-list">
              {state.interfaces.map((componentInterface) => (
                <article className="component-repo-card" key={componentInterface.id}>
                  <div>
                    <strong>{componentInterface.name}</strong>
                    <StatusPill status={componentInterface.reviewStatus} />
                  </div>
                  <span>{componentInterface.worldConnectorId}</span>
                </article>
              ))}
            </div>
          ) : (
            <div className="asset-empty">{appConfig.texts.componentRepoNoInterfaces}</div>
          )}

          <div className="component-repo-panel-title">
            <Rocket aria-hidden="true" />
            <span>Draft & Publish</span>
          </div>
          <label className="component-repo-control-field">
            <span>{appConfig.texts.componentRepoComponentName}</span>
            <input
              onChange={(event) => setComponentName(event.target.value)}
              placeholder={appConfig.texts.componentRepoComponentNamePlaceholder}
              value={componentName}
            />
          </label>
          <label className="component-repo-control-field">
            <span>{appConfig.texts.componentRepoCategory}</span>
            <input
              onChange={(event) => setComponentCategory(event.target.value)}
              placeholder={appConfig.texts.componentRepoCategoryPlaceholder}
              value={componentCategory}
            />
          </label>
          <label className="component-repo-control-field">
            <span>{appConfig.texts.componentRepoVersion}</span>
            <input onChange={(event) => setVersion(event.target.value)} value={version} />
          </label>
          <label className="component-repo-control-field">
            <span>{appConfig.texts.componentRepoReleaseNote}</span>
            <input onChange={(event) => setReleaseNote(event.target.value)} value={releaseNote} />
          </label>
          <div className="component-repo-inline-actions component-repo-publish-actions">
            <button onClick={() => void validate()} type="button">
              <ShieldCheck aria-hidden="true" />
              {appConfig.texts.componentRepoValidate}
            </button>
            <button disabled={!state.validationReport?.passed} onClick={() => void approve()} type="button">
              {appConfig.texts.componentRepoApprove}
            </button>
            <button disabled={!state.approval || Boolean(state.publishedVersion)} onClick={() => void publish()} type="button">
              {appConfig.texts.componentRepoPublish}
            </button>
          </div>
          {state.approval ? (
            <div className="component-repo-summary-card">
              <strong>Draft: {state.approval.version.id}</strong>
              <span>
                {state.approval.component.name} · v{state.approval.version.version}
              </span>
            </div>
          ) : null}
          {state.publishedVersion ? (
            <div className="component-repo-message">
              Published: {state.publishedVersion.id}
            </div>
          ) : null}
        </aside>
      </section>
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
  return (
    <section className="component-repo-validation">
      <div>
        <strong>Validation</strong>
        <StatusPill status={report.passed ? 'passed' : 'blocked'} />
      </div>
      {report.checks.map((check) => (
        <div className="component-repo-check" key={check.code}>
          <span>{check.code}</span>
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
