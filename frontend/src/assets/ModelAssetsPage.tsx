import React from 'react';
import { Database, ChevronLeft, ChevronRight } from 'lucide-react';
import appConfig from '../app/appConfig.json';
import {
  deleteModelAsset,
  loadModelAssetPage,
  type ModelAsset,
  type ModelAssetPage,
} from './modelAssetApi';

type ModelAssetState =
  | { status: 'loading'; page: ModelAssetPage | null; error: null }
  | { status: 'ready'; page: ModelAssetPage; error: null }
  | { status: 'error'; page: ModelAssetPage | null; error: string };

export function ModelAssetsPage({ onOpenAsset }: { onOpenAsset: (asset: ModelAsset) => void }) {
  const [pageNumber, setPageNumber] = React.useState(1);
  const [state, setState] = React.useState<ModelAssetState>({
    status: 'loading',
    page: null,
    error: null,
  });

  React.useEffect(() => {
    let active = true;
    setState((currentState) => ({ status: 'loading', page: currentState.page, error: null }));
    loadModelAssetPage(appConfig.modelAssetsApiUrl, pageNumber, appConfig.modelAssetPageSize)
      .then((page) => {
        if (active) {
          setState({ status: 'ready', page, error: null });
        }
      })
      .catch((error: Error) => {
        if (active) {
          setState((currentState) => ({
            status: 'error',
            page: currentState.page,
            error: error.message || appConfig.texts.loadFailed,
          }));
        }
      });
    return () => {
      active = false;
    };
  }, [pageNumber]);

  const refreshPage = React.useCallback(() => {
    setState((currentState) => ({ status: 'loading', page: currentState.page, error: null }));
    loadModelAssetPage(appConfig.modelAssetsApiUrl, pageNumber, appConfig.modelAssetPageSize)
      .then((page) => setState({ status: 'ready', page, error: null }))
      .catch((error: Error) =>
        setState((currentState) => ({
          status: 'error',
          page: currentState.page,
          error: error.message || appConfig.texts.loadFailed,
        })),
      );
  }, [pageNumber]);

  const deleteAsset = async (assetId: string) => {
    await deleteModelAsset(appConfig.modelAssetsApiUrl, assetId);
    refreshPage();
  };

  const currentPage = state.page;
  const totalPages = currentPage
    ? Math.max(1, Math.ceil(currentPage.total / currentPage.pageSize))
    : 1;

  return (
    <section className="asset-page">
      <div className="asset-header">
        <div>
          <h1>{appConfig.texts.modelListTitle}</h1>
          <p>{appConfig.texts.modelListSubtitle}</p>
        </div>
        <Database aria-hidden="true" />
      </div>

      {state.status === 'error' ? <div className="asset-error">{state.error}</div> : null}
      {state.status === 'loading' ? <div className="asset-loading">{appConfig.texts.loading}</div> : null}

      {currentPage && currentPage.items.length > 0 ? (
        <div className="asset-table">
          {currentPage.items.map((asset) => (
            <div className="asset-row" key={asset.id}>
              <div>
                <strong>{asset.name}</strong>
                <span>{asset.id}</span>
              </div>
              <div>{asset.modelType}</div>
              <div>{asset.status}</div>
              <div>
                {asset.columns && asset.rows ? `${asset.columns} x ${asset.rows}` : '-'}
              </div>
              <div>{asset.validSampleCount?.toLocaleString() ?? '-'}</div>
              <div>{new Date(asset.createdAt).toLocaleString()}</div>
              <div className="asset-row-actions">
                <button onClick={() => onOpenAsset(asset)} type="button">
                  {appConfig.texts.viewAsset}
                </button>
                <button onClick={() => void deleteAsset(asset.id)} type="button">
                  {appConfig.texts.deleteAsset}
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {currentPage && currentPage.items.length === 0 ? (
        <div className="asset-empty">{appConfig.texts.emptyModels}</div>
      ) : null}

      <div className="asset-pagination">
        <button
          disabled={pageNumber <= 1}
          onClick={() => setPageNumber((value) => value - 1)}
          type="button"
        >
          <ChevronLeft aria-hidden="true" />
          {appConfig.texts.previousPage}
        </button>
        <span>
          {pageNumber} / {totalPages}
        </span>
        <button
          disabled={pageNumber >= totalPages}
          onClick={() => setPageNumber((value) => value + 1)}
          type="button"
        >
          {appConfig.texts.nextPage}
          <ChevronRight aria-hidden="true" />
        </button>
      </div>
    </section>
  );
}
