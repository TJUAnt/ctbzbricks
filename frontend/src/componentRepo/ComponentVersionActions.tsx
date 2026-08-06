import React from 'react';
import {
  AlertTriangle,
  Download,
  LoaderCircle,
  MoreHorizontal,
  Trash2,
  X,
} from 'lucide-react';
import { useAppTranslation } from '../i18n';
import {
  deleteComponentVersion,
  downloadComponentVersionSource,
  type ComponentVersionDeleteResponse,
  type ComponentVersionResponse,
} from './componentRepoApi';

export function ComponentVersionActions({
  componentName,
  isOnlyVersion,
  onDeleted,
  version,
}: {
  componentName: string;
  isOnlyVersion: boolean;
  onDeleted: (
    result: ComponentVersionDeleteResponse,
    version: ComponentVersionResponse,
  ) => void;
  version: ComponentVersionResponse;
}) {
  const tr = useAppTranslation();
  const detailsRef = React.useRef<HTMLDetailsElement | null>(null);
  const [confirming, setConfirming] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const deletion = version.deletion;
  const showDelete = Boolean(
    deletion?.allowed || deletion?.reason === 'current',
  );

  const closeMenu = () => {
    if (detailsRef.current) detailsRef.current.open = false;
  };

  const download = async () => {
    setError(null);
    try {
      await downloadComponentVersionSource(version.id);
      closeMenu();
    } catch (downloadError) {
      setError(
        downloadError instanceof Error
          ? downloadError.message
          : tr('componentRepo:downloadFailed'),
      );
    }
  };

  const requestDelete = () => {
    if (!deletion?.allowed) return;
    setError(null);
    setConfirming(true);
    closeMenu();
  };

  const confirmDelete = async () => {
    setDeleting(true);
    setError(null);
    try {
      const result = await deleteComponentVersion(version.id);
      setConfirming(false);
      onDeleted(result, version);
    } catch (deleteError) {
      setError(
        deleteError instanceof Error
          ? deleteError.message
          : tr('errors:common.unknown'),
      );
    } finally {
      setDeleting(false);
    }
  };

  return (
    <>
      <details className="component-version-actions" ref={detailsRef}>
        <summary aria-label={tr('componentRepo:versionActions')}>
          <MoreHorizontal aria-hidden="true" />
        </summary>
        <div className="component-version-action-menu" role="menu">
          <button onClick={() => void download()} role="menuitem" type="button">
            <Download aria-hidden="true" />
            {tr('componentRepo:downloadSource')}
          </button>
          {showDelete ? <span aria-hidden="true" /> : null}
          {showDelete ? (
            <button
              className="component-version-delete-action"
              disabled={!deletion?.allowed}
              onClick={requestDelete}
              role="menuitem"
              type="button"
            >
              <Trash2 aria-hidden="true" />
              {tr('componentRepo:deleteVersion')}
            </button>
          ) : null}
          {deletion?.reason === 'current' ? (
            <small>{tr('componentRepo:currentVersionCannotDelete')}</small>
          ) : null}
          {error && !confirming ? (
            <div className="component-version-action-error">
              <AlertTriangle aria-hidden="true" />
              {error}
            </div>
          ) : null}
        </div>
      </details>

      {confirming ? (
        <div className="component-version-delete-backdrop">
          <section
            aria-labelledby={`delete-version-title-${version.id}`}
            aria-modal="true"
            className="component-version-delete-dialog"
            role="dialog"
          >
            <header>
              <div>
                <span><Trash2 aria-hidden="true" /></span>
                <h2 id={`delete-version-title-${version.id}`}>
                  {tr(
                    isOnlyVersion
                      ? 'componentRepo:deleteOnlyVersionTitle'
                      : 'componentRepo:deleteVersionTitle',
                  )}
                </h2>
              </div>
              <button
                aria-label={tr('componentRepo:close')}
                disabled={deleting}
                onClick={() => {
                  setConfirming(false);
                  setError(null);
                }}
                type="button"
              >
                <X aria-hidden="true" />
              </button>
            </header>
            <div className="component-version-delete-body">
              <p>
                {tr(
                  isOnlyVersion
                    ? 'componentRepo:deleteOnlyVersionDescription'
                    : 'componentRepo:deleteVersionDescription',
                  {
                    componentName,
                    revision: version.revision,
                    version: version.version,
                  },
                )}
              </p>
              <div>
                <AlertTriangle aria-hidden="true" />
                {tr('componentRepo:sharedArtifactsRetained')}
              </div>
              {error ? (
                <div className="component-version-delete-error">
                  <AlertTriangle aria-hidden="true" />
                  {error}
                </div>
              ) : null}
            </div>
            <footer>
              <button
                disabled={deleting}
                onClick={() => {
                  setConfirming(false);
                  setError(null);
                }}
                type="button"
              >
                {tr('componentRepo:cancel')}
              </button>
              <button
                className="component-version-delete-confirm"
                disabled={deleting}
                onClick={() => void confirmDelete()}
                type="button"
              >
                {deleting ? <LoaderCircle aria-hidden="true" /> : <Trash2 aria-hidden="true" />}
                {tr(
                  deleting
                    ? 'componentRepo:deletingVersion'
                    : 'componentRepo:deleteVersion',
                )}
              </button>
            </footer>
          </section>
        </div>
      ) : null}
    </>
  );
}
