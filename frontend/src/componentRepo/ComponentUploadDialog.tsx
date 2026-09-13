import React from 'react';
import {
  AlertCircle,
  CheckCircle2,
  FileUp,
  RefreshCw,
  Upload,
  X,
} from 'lucide-react';
import { useAppTranslation } from '../i18n';
import {
  createComponentImportWithProgress,
  type ComponentImportUploadCompleteResponse,
} from './componentRepoApi';

type UploadState = 'idle' | 'uploading' | 'error';

function isComponentFile(name: string): boolean {
  return /\.(io|ldr|mpd)$/i.test(name);
}

function formatFileSize(bytes: number): string {
  return bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export function ComponentUploadDialog({
  baseVersionId,
  onClose,
  onUploadCompleted,
  targetComponentId,
}: {
  baseVersionId?: string | null;
  onClose: () => void;
  onUploadCompleted: (result: ComponentImportUploadCompleteResponse) => void;
  targetComponentId?: string | null;
}) {
  const tr = useAppTranslation();
  const [sourceFile, setSourceFile] = React.useState<File | null>(null);
  const [exchangeFile, setExchangeFile] = React.useState<File | null>(null);
  const [state, setState] = React.useState<UploadState>('idle');
  const [progress, setProgress] = React.useState(0);
  const [progressMessage, setProgressMessage] = React.useState(tr('componentRepo:readyToUpload'));
  const [error, setError] = React.useState<string | null>(null);
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
      const completion = await createComponentImportWithProgress(
        sourceFile,
        exchangeFile,
        ({ percent, message }) => {
          setProgress(percent);
          setProgressMessage(message);
        },
        { targetComponentId, baseVersionId },
      );
      onUploadCompleted(completion);
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
          {state === 'uploading' ? <span>{tr('componentRepo:uploadingComponentFiles')}</span> : null}
          {state === 'error' ? <><button onClick={onClose} type="button">{tr('componentRepo:close')}</button><button onClick={reset} type="button"><RefreshCw />{tr('componentRepo:retryUpload')}</button></> : null}
        </footer>
      </section>
    </div>
  );
}
