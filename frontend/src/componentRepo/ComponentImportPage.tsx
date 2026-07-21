import React from 'react';
import { ArrowRight, FileArchive, Upload } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import appConfig from '../app/appConfig';
import { useAppTranslation } from '../i18n';
import {
  createComponentImport,
  createComponentImportWithUploadSession,
  parseComponentImport,
  type ComponentImportCreateResponse,
  type ComponentImportParseResponse,
} from './componentRepoApi';
import { routeFor } from './ComponentRepoPage';

export function ComponentImportPage() {
  const tr = useAppTranslation();
  const navigate = useNavigate();
  const [sourceFile, setSourceFile] = React.useState<File | null>(null);
  const [exchangeFile, setExchangeFile] = React.useState<File | null>(null);
  const [createdImport, setCreatedImport] = React.useState<ComponentImportCreateResponse | null>(null);
  const [parseResult, setParseResult] = React.useState<ComponentImportParseResponse | null>(null);
  const [isWorking, setIsWorking] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const submitImport = async () => {
    if (!sourceFile) {
      return;
    }
    setIsWorking(true);
    setError(null);
    setParseResult(null);
    try {
      setCreatedImport(await createComponentImportWithFallback(sourceFile, exchangeFile));
    } catch (importError) {
      setError(importError instanceof Error ? importError.message : appConfig.texts.loadFailed);
    } finally {
      setIsWorking(false);
    }
  };

  const parseImport = async () => {
    if (!createdImport) {
      return;
    }
    setIsWorking(true);
    setError(null);
    try {
      setParseResult(await parseComponentImport(createdImport.importJob.id));
    } catch (parseError) {
      setError(parseError instanceof Error ? parseError.message : appConfig.texts.loadFailed);
    } finally {
      setIsWorking(false);
    }
  };

  const openCandidate = () => {
    if (!parseResult) {
      return;
    }
    navigate(routeFor('componentRepoCandidate').replace(':candidateId', encodeURIComponent(parseResult.candidate.id)));
  };

  return (
    <section className="component-repo-page">
      <header className="component-repo-header">
        <div>
          <h1>{appConfig.texts.componentRepoImportTitle}</h1>
          <p>{appConfig.texts.componentRepoImportSubtitle}</p>
        </div>
        <div className="component-repo-actions">
          <button onClick={() => navigate(routeFor('componentRepo'))} type="button">
            {appConfig.texts.componentRepoBackToList}
          </button>
        </div>
      </header>

      <section className="component-repo-layout">
        <form
          className="component-repo-panel"
          onSubmit={(event) => {
            event.preventDefault();
            void submitImport();
          }}
        >
          <div className="component-repo-panel-title">
            <Upload aria-hidden="true" />
            <span>{tr('componentRepo:upload')}</span>
          </div>

          <FileInput
            accept=".io,.ldr,.mpd"
            file={sourceFile}
            inputId="component-source-file"
            label={appConfig.texts.componentRepoSourceFile}
            onChange={setSourceFile}
          />
          <FileInput
            accept=".ldr,.mpd"
            file={exchangeFile}
            inputId="component-exchange-file"
            label={appConfig.texts.componentRepoExchangeFile}
            onChange={setExchangeFile}
          />

          <button className="component-repo-primary-button" disabled={!sourceFile || isWorking} type="submit">
            {isWorking ? appConfig.texts.loading : appConfig.texts.componentRepoCreateImport}
          </button>

          {createdImport ? (
            <button
              className="component-repo-secondary-button"
              disabled={!createdImport.exchangeArtifact || isWorking}
              onClick={() => void parseImport()}
              type="button"
            >
              <FileArchive aria-hidden="true" />
              {appConfig.texts.componentRepoParse}
            </button>
          ) : null}

          {error ? <div className="asset-error">{error}</div> : null}
        </form>

        <aside className="component-repo-panel">
          <div className="component-repo-panel-title">
            <FileArchive aria-hidden="true" />
            <span>{tr('componentRepo:importResult')}</span>
          </div>

          {!createdImport ? <div className="asset-empty">{appConfig.texts.componentRepoNoCandidate}</div> : null}

          {createdImport ? (
            <div className="component-repo-card-list">
              <InfoCard label={tr('componentRepo:importId')} value={createdImport.importJob.id} />
              <InfoCard label={tr('componentRepo:source')} value={createdImport.sourceArtifact.originalFilename} />
              <InfoCard label={tr('componentRepo:exchange')} value={createdImport.exchangeArtifact?.originalFilename ?? '-'} />
              <InfoCard label={tr('componentRepo:status')} value={createdImport.importJob.status} />
            </div>
          ) : null}

          {parseResult ? (
            <div className="component-repo-candidate-ready">
              <strong>{appConfig.texts.componentRepoCandidateReady}</strong>
              <span>{parseResult.candidate.id}</span>
              <div className="component-repo-metadata">
                {Object.entries(parseResult.candidate.summary).map(([key, value]) => (
                  <InfoCard key={key} label={key} value={formatValue(value)} />
                ))}
              </div>
              <button className="component-repo-primary-button" onClick={openCandidate} type="button">
                {tr('componentRepo:openWorkbench')}
                <ArrowRight aria-hidden="true" />
              </button>
            </div>
          ) : null}
        </aside>
      </section>
    </section>
  );
}

async function createComponentImportWithFallback(
  sourceFile: File,
  exchangeFile: File | null,
): Promise<ComponentImportCreateResponse> {
  try {
    return await createComponentImportWithUploadSession(sourceFile, exchangeFile);
  } catch (directUploadError) {
    console.warn('Component Repo direct upload failed, falling back to multipart upload.', directUploadError);
    return createComponentImport(sourceFile, exchangeFile);
  }
}

function FileInput({
  accept,
  file,
  inputId,
  label,
  onChange,
}: {
  accept: string;
  file: File | null;
  inputId: string;
  label: string;
  onChange: (file: File | null) => void;
}) {
  return (
    <div className="component-repo-file-field">
      <span>{label}</span>
      <label className="terrain-file-button" htmlFor={inputId}>
        <Upload aria-hidden="true" />
        {file ? file.name : label}
      </label>
      <input
        accept={accept}
        className="terrain-file-input"
        id={inputId}
        onChange={(event) => {
          onChange(event.target.files?.item(0) ?? null);
        }}
        type="file"
      />
    </div>
  );
}

function InfoCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="component-repo-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function formatValue(value: unknown): string {
  if (typeof value === 'string') {
    return value;
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return JSON.stringify(value);
}
