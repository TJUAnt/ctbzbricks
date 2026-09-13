import React from 'react';
import { LoaderCircle } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { localizeStructuredMessage } from '../api/client';
import appConfig from '../app/appConfig';
import { useAppTranslation } from '../i18n';
import { getComponentImport } from './componentRepoApi';
import { routeFor, StatusPill } from './ComponentRepoPresenters';

type ImportStatusState = {
  status: 'processing' | 'failed';
  error: string | null;
};

const importPollIntervalMs = 2_000;

export function ComponentImportStatusPage() {
  const tr = useAppTranslation();
  const navigate = useNavigate();
  const { importId = '' } = useParams();
  const [state, setState] = React.useState<ImportStatusState>({
    status: 'processing',
    error: null,
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
            setState({ status: 'failed', error: appConfig.texts.loadFailed });
            return;
          }
          navigate(routeFor('componentRepoCandidate').replace(
            ':candidateId',
            encodeURIComponent(componentImport.candidateId),
          ), { replace: true });
          return;
        }
        if (componentImport.processingStatus === 'failed') {
          setState({
            status: 'failed',
            error: componentImport.failure
              ? localizeStructuredMessage(componentImport.failure)
              : tr('componentRepo:componentUploadFailed'),
          });
          return;
        }
        timer = window.setTimeout(() => void poll(), importPollIntervalMs);
      } catch (error) {
        if (!active) return;
        setState({
          status: 'failed',
          error: error instanceof Error ? error.message : appConfig.texts.loadFailed,
        });
      }
    };

    if (importId) {
      void poll();
    } else {
      setState({ status: 'failed', error: appConfig.texts.loadFailed });
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
          <LoaderCircle aria-hidden="true" className="component-library-spin" />
          <strong>{tr('componentRepo:parsing')}</strong>
          <span>{tr('componentRepo:filesUploadedProcessingComponent')}</span>
          <StatusPill status="processing" />
        </section>
      ) : (
        <div className="asset-error">{state.error}</div>
      )}
    </section>
  );
}
