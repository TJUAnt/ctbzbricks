import React from 'react';
import { CheckCircle2, Circle, LoaderCircle } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { localizeStructuredMessage } from '../api/client';
import appConfig from '../app/appConfig';
import { useAppTranslation, useDynamicTranslation, type TranslationKey } from '../i18n';
import {
  getComponentImport,
  getTask,
  type ComponentImportResponse,
  type ComponentTaskResponse,
} from './componentRepoApi';
import { routeFor, StatusPill } from './ComponentRepoPresenters';

type ImportStatusState = {
  status: 'processing' | 'failed';
  error: string | null;
  componentImport: ComponentImportResponse | null;
  parseTask: ComponentTaskResponse | null;
  previewTask: ComponentTaskResponse | null;
};

const importPollIntervalMs = 2_000;

export function ComponentImportStatusPage() {
  const tr = useAppTranslation();
  const navigate = useNavigate();
  const { importId = '' } = useParams();
  const [state, setState] = React.useState<ImportStatusState>({
    status: 'processing',
    error: null,
    componentImport: null,
    parseTask: null,
    previewTask: null,
  });

  React.useEffect(() => {
    let active = true;
    let timer: number | null = null;

    // 状态页只读观察持久 Import；它不触发解析、Preview 物化或任何 Worker mutation。
    const poll = async () => {
      try {
        const componentImport = await getComponentImport(importId);
        if (!active) return;
        if (componentImport.processingStatus === 'ready') {
          if (!componentImport.candidateId) {
            setState((current) => ({ ...current, status: 'failed', error: appConfig.texts.loadFailed }));
            return;
          }
          navigate(routeFor('componentRepoCandidate').replace(
            ':candidateId',
            encodeURIComponent(componentImport.candidateId),
          ), { replace: true });
          return;
        }
        if (componentImport.processingStatus === 'failed') {
          setState((current) => ({
            ...current,
            status: 'failed',
            error: componentImport.failure
              ? localizeStructuredMessage(componentImport.failure)
              : tr('componentRepo:componentUploadFailed'),
            componentImport,
          }));
          return;
        }
        const [parseTask, previewTask] = await Promise.all([
          getTask(componentImport.taskId).catch(() => null),
          componentImport.previewTaskId
            ? getTask(componentImport.previewTaskId).catch(() => null)
            : Promise.resolve(null),
        ]);
        if (!active) return;
        setState({
          status: 'processing',
          error: null,
          componentImport,
          parseTask,
          previewTask,
        });
        timer = window.setTimeout(() => void poll(), importPollIntervalMs);
      } catch (error) {
        if (!active) return;
        setState((current) => ({
          ...current,
          status: 'failed',
          error: error instanceof Error ? error.message : appConfig.texts.loadFailed,
        }));
      }
    };

    if (importId) {
      void poll();
    } else {
      setState((current) => ({ ...current, status: 'failed', error: appConfig.texts.loadFailed }));
    }
    return () => {
      active = false;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [importId, navigate, tr]);

  return (
    <section className="component-repo-page">
      <header className="component-repo-header">
        <div>
          <h1>{tr('componentRepo:componentImport')}</h1>
          <p>{tr('componentRepo:importId')}: {importId}</p>
        </div>
        <div className="component-repo-actions">
          <button onClick={() => navigate(routeFor('componentRepo'))} type="button">
            {appConfig.texts.componentRepoBackToList}
          </button>
        </div>
      </header>

      {state.status === 'processing' ? (
        <section className="component-repo-panel component-import-processing-panel">
          <div className="component-import-processing-heading">
            <LoaderCircle aria-hidden="true" className="component-library-spin" />
            <div>
              <strong>{tr('componentRepo:parsing')}</strong>
              <span>{tr('componentRepo:filesUploadedProcessingComponent')}</span>
            </div>
            <StatusPill status="processing" />
          </div>
          <ImportProgress
            componentImport={state.componentImport}
            parseTask={state.parseTask}
            previewTask={state.previewTask}
          />
        </section>
      ) : (
        <div className="asset-error">{state.error}</div>
      )}
    </section>
  );
}

type ImportStageState = 'pending' | 'active' | 'complete';
const parseDescriptionKeys: Record<ImportStageState, TranslationKey> = {
  pending: 'componentRepo:importStageParsePending',
  active: 'componentRepo:importStageParseActive',
  complete: 'componentRepo:importStageParseComplete',
};
const previewDescriptionKeys: Record<ImportStageState, TranslationKey> = {
  pending: 'componentRepo:importStagePreviewPending',
  active: 'componentRepo:importStagePreviewActive',
  complete: 'componentRepo:importStagePreviewComplete',
};

/** ImportProgress 将两个持久任务映射为稳定阶段，不把排队时间伪装成算法内部精确完成度。 */
function ImportProgress({
  componentImport,
  parseTask,
  previewTask,
}: {
  componentImport: ComponentImportResponse | null;
  parseTask: ComponentTaskResponse | null;
  previewTask: ComponentTaskResponse | null;
}) {
  const tr = useAppTranslation();
  const trDynamic = useDynamicTranslation();
  const parseState: ImportStageState = componentImport?.status === 'succeeded' || parseTask?.status === 'succeeded'
    ? 'complete'
    : parseTask?.status === 'queued' || parseTask?.status === 'running'
      ? 'active'
      : 'pending';
  const previewState: ImportStageState = componentImport?.processingStatus === 'ready' || previewTask?.status === 'succeeded'
    ? 'complete'
    : previewTask?.status === 'queued' || previewTask?.status === 'running'
      ? 'active'
      : 'pending';
  const percent = overallProgress(parseTask, previewTask, parseState, previewState);
  const stages: Array<{ key: string; label: string; description: string; state: ImportStageState }> = [
    {
      key: 'upload', label: tr('componentRepo:importStageUpload'),
      description: tr('componentRepo:importStageUploadComplete'), state: 'complete',
    },
    {
      key: 'parse', label: tr('componentRepo:importStageParse'),
      description: trDynamic(parseDescriptionKeys[parseState]), state: parseState,
    },
    {
      key: 'preview', label: tr('componentRepo:importStagePreview'),
      description: trDynamic(previewDescriptionKeys[previewState]), state: previewState,
    },
  ];
  const activeTask = previewState === 'active' ? previewTask : parseState === 'active' ? parseTask : null;
  const progressMessage = activeTask?.progress?.code
    ? localizeStructuredMessage(activeTask.progress as { code: string; params: Record<string, unknown> })
    : null;
  return (
    <div className="component-import-durable-progress">
      <div className="component-import-progress-meta">
        <span>{progressMessage ?? tr('componentRepo:importDurableProgress')}</span>
        <strong>{percent}%</strong>
      </div>
      <div
        aria-label={tr('componentRepo:importProgressValue', { percent })}
        aria-valuemax={100}
        aria-valuemin={0}
        aria-valuenow={percent}
        className="component-upload-progress"
        role="progressbar"
      >
        <span style={{ width: `${percent}%` }} />
      </div>
      <ol className="component-import-stage-list">
        {stages.map((stage) => (
          <li className={`is-${stage.state}`} key={stage.key}>
            {stage.state === 'complete' ? <CheckCircle2 aria-hidden="true" />
              : stage.state === 'active' ? <LoaderCircle aria-hidden="true" className="component-library-spin" />
                : <Circle aria-hidden="true" />}
            <span><strong>{stage.label}</strong><small>{stage.description}</small></span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function overallProgress(
  parseTask: ComponentTaskResponse | null,
  previewTask: ComponentTaskResponse | null,
  parseState: ImportStageState,
  previewState: ImportStageState,
): number {
  if (previewState === 'complete') return 100;
  if (previewState === 'active') return Math.round(65 + (previewTask?.progress?.percent ?? 0) * 0.3);
  if (parseState === 'complete') return 65;
  if (parseState === 'active') return Math.round(20 + (parseTask?.progress?.percent ?? 0) * 0.4);
  return 15;
}
