import React from 'react';
import { Upload } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import appConfig from '../app/appConfig';
import { useAppTranslation } from '../i18n';
import {
  createComponentImportWithUploadSession,
} from './componentRepoApi';
import { routeFor } from './ComponentRepoPresenters';

export function ComponentImportPage() {
  const tr = useAppTranslation();
  const navigate = useNavigate();
  const [sourceFile, setSourceFile] = React.useState<File | null>(null);
  const [exchangeFile, setExchangeFile] = React.useState<File | null>(null);
  const [isWorking, setIsWorking] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const submitImport = async () => {
    if (!sourceFile) {
      return;
    }
    setIsWorking(true);
    setError(null);
    try {
      const result = await createComponentImportWithUploadSession(sourceFile, exchangeFile);
      navigate(routeFor('componentRepoImportStatus').replace(
        ':importId',
        encodeURIComponent(result.importId),
      ));
    } catch (importError) {
      setError(importError instanceof Error ? importError.message : appConfig.texts.loadFailed);
    } finally {
      setIsWorking(false);
    }
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

          {error ? <div className="asset-error">{error}</div> : null}
        </form>
      </section>
    </section>
  );
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
