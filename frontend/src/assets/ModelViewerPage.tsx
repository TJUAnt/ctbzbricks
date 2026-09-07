import React from 'react';
import { ArrowLeft, Box } from 'lucide-react';
import appConfig from '../app/appConfig';
import {
  HeightmapCanvas,
  HeightmapLegend,
  HeightmapMetrics,
} from '../archive/dem/LegoTerrainBuilderPage';
import {
  loadLegoHeightmapModel,
  type LegoHeightmapAsset,
} from '../legoTerrain/legoHeightmapAsset';
import { MeshModelViewer } from '../modelImport/MeshModelViewer';
import legoTerrainConfig from '../legoTerrain/legoTerrainConfig';
import { loadTerrainModel, routeWithParam } from '../terrain/terrainApi';
import terrainConfig from '../terrain/terrainConfig';
import { TerrainScene, TerrainStats } from '../archive/dem/TerrainDemPage';
import type { TerrainAsset } from '../terrain/terrainTypes';
import type { ModelAsset } from './modelAssetApi';

type ViewerState =
  | { status: 'loading'; asset: null; error: null }
  | { status: 'ready'; asset: TerrainAsset | LegoHeightmapAsset | null; error: null }
  | { status: 'error'; asset: null; error: string };

export function ModelViewerPage({
  modelAsset,
  onBack,
}: {
  modelAsset: ModelAsset;
  onBack: () => void;
}) {
  const [state, setState] = React.useState<ViewerState>({
    status: 'loading',
    asset: null,
    error: null,
  });

  React.useEffect(() => {
    let active = true;
    if (modelAsset.modelType === appConfig.modelTypes.mesh) {
      setState({ status: 'ready', asset: null, error: null });
      return () => {
        active = false;
      };
    }
    setState({ status: 'loading', asset: null, error: null });
    loadViewerAsset(modelAsset)
      .then((asset) => {
        if (active) {
          setState({ status: 'ready', asset, error: null });
        }
      })
      .catch((error: Error) => {
        if (active) {
          setState({ status: 'error', asset: null, error: error.message });
        }
      });
    return () => {
      active = false;
    };
  }, [modelAsset]);

  return (
    <main className="model-viewer-page">
      <header className="model-viewer-header">
        <button onClick={onBack} type="button">
          <ArrowLeft aria-hidden="true" />
          {appConfig.texts.backToModelList}
        </button>
        <div>
          <h1>{appConfig.texts.modelViewerTitle}</h1>
          <p>{modelAsset.name}</p>
        </div>
        <Box aria-hidden="true" />
      </header>

      {state.status === 'ready' && modelAsset.modelType === appConfig.modelTypes.dem ? (
        <section className="model-viewer-layout">
          <div className="model-viewer-canvas">
            <TerrainScene assets={[state.asset as TerrainAsset]} config={terrainConfig} />
          </div>
          <aside className="model-viewer-panel">
            <TerrainStats assets={[state.asset as TerrainAsset]} config={terrainConfig} />
          </aside>
        </section>
      ) : null}

      {state.status === 'ready' && modelAsset.modelType === appConfig.modelTypes.legoHeightmap ? (
        <section className="model-viewer-layout">
          <div className="model-viewer-heightmap">
            <HeightmapLegend heightmap={state.asset as LegoHeightmapAsset} />
            <HeightmapCanvas heightmap={state.asset as LegoHeightmapAsset} />
          </div>
          <aside className="model-viewer-panel">
            <HeightmapMetrics heightmap={state.asset as LegoHeightmapAsset} />
          </aside>
        </section>
      ) : null}

      {state.status === 'ready' && modelAsset.modelType === appConfig.modelTypes.mesh ? (
        <MeshModelViewer modelAsset={modelAsset} />
      ) : null}

      {state.status === 'loading' ? <div className="asset-loading">{appConfig.texts.loading}</div> : null}
      {state.status === 'error' ? <div className="asset-error">{state.error}</div> : null}
    </main>
  );
}

function loadViewerAsset(modelAsset: ModelAsset): Promise<TerrainAsset | LegoHeightmapAsset> {
  if (modelAsset.modelType === appConfig.modelTypes.dem) {
    return loadTerrainModel(
      routeWithParam(
        terrainConfig.modelApiUrl,
        terrainConfig.routePlaceholders.modelId,
        modelAsset.id,
      ),
      terrainConfig.expectedSchema,
      terrainConfig.texts.invalidAsset,
    );
  }
  if (modelAsset.modelType === appConfig.modelTypes.legoHeightmap) {
    return loadLegoHeightmapModel(
      routeWithParam(
        legoTerrainConfig.modelApiUrl,
        legoTerrainConfig.routePlaceholders.modelId,
        modelAsset.id,
      ),
      legoTerrainConfig.assetSchema,
      appConfig.texts.unsupportedModelType,
    );
  }
  return Promise.reject(new Error(appConfig.texts.unsupportedModelType));
}
