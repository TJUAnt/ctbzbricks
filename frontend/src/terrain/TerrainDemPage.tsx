import React from 'react';
import { ArrowUp, Compass, Grid3X3, Layers3, Mountain, RotateCcw } from 'lucide-react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { localizeStructuredMessage } from '../api/client';
import { formatNumber } from '../i18n/formatters';
import {
  combineGeojsonFeatureCollections,
  createTerrainJob,
  createTerrainUploadPayload,
  geojsonModelName,
  loadTerrainJob,
  loadTerrainModel,
  loadTerrainModels,
  routeWithParam,
  saveTerrainModel,
  summarizeGeojsonDocuments,
  type TerrainGeojsonFileInfo,
} from './terrainApi';
import terrainConfig from './terrainConfig';
import {
  combinedTerrainBounds,
  createBoundaryLines,
  createTerrainMeshData,
  createTerrainSceneFrame,
} from './terrainMesh';
import type { TerrainAsset, TerrainJob, TerrainModelMetadata } from './terrainTypes';

type TerrainConfig = typeof terrainConfig;

type TerrainState =
  | { status: 'loading'; assets: null; error: null; progress: number }
  | { status: 'importing'; assets: TerrainAsset[] | null; error: null; progress: number }
  | { status: 'ready'; assets: TerrainAsset[]; error: null; progress: number }
  | { status: 'error'; assets: TerrainAsset[] | null; error: string; progress: number };

export function TerrainDemPage() {
  const [terrainState, setTerrainState] = React.useState<TerrainState>({
    status: 'loading',
    assets: null,
    error: null,
    progress: terrainConfig.initialProgress,
  });
  const [models, setModels] = React.useState<TerrainModelMetadata[]>([]);
  const [previewVerticalExaggeration, setPreviewVerticalExaggeration] = React.useState(
    terrainConfig.renderOptions.defaultVerticalExaggeration,
  );
  const [demDatasetKey, setDemDatasetKey] = React.useState(terrainConfig.demDatasets.defaultKey);
  const [modelName, setModelName] = React.useState('');
  const [terrainName, setTerrainName] = React.useState<string | null>(null);
  const [saveMessage, setSaveMessage] = React.useState<string | null>(null);
  const [geojsonInfo, setGeojsonInfo] = React.useState<TerrainGeojsonFileInfo[] | null>(null);
  const [progressMessage, setProgressMessage] = React.useState('');

  React.useEffect(() => {
    let active = true;
    fetch(terrainConfig.assetUrl)
      .then((response) => {
        if (!response.ok) {
          throw new Error(terrainConfig.texts.loadFailed);
        }
        return response.json() as Promise<TerrainAsset>;
      })
      .then((asset) => {
        if (asset.schema !== terrainConfig.expectedSchema) {
          throw new Error(terrainConfig.texts.invalidAsset);
        }
        if (active) {
          setTerrainState({
            status: 'ready',
            assets: [asset],
            error: null,
            progress: terrainConfig.initialProgress,
          });
          setPreviewVerticalExaggeration(
            asset.renderOptions?.verticalExaggeration ??
              terrainConfig.renderOptions.defaultVerticalExaggeration,
          );
          setModelName(asset.name ?? asset.source);
        }
      })
      .catch((error: Error) => {
        if (active) {
          setTerrainState({
            status: 'error',
            assets: null,
            error: error.message,
            progress: terrainConfig.initialProgress,
          });
        }
      });
    return () => {
      active = false;
    };
  }, []);

  const refreshModels = React.useCallback(async () => {
    setModels(await loadTerrainModels(terrainConfig.modelsApiUrl));
  }, []);

  React.useEffect(() => {
    void refreshModels();
  }, [refreshModels]);

  const importGeojson = async (selectedFiles: File[]) => {
    if (selectedFiles.length === terrainConfig.emptyFileCount) {
      return;
    }
    const previousAssets = terrainState.assets;
    setTerrainState((currentState) => ({
      status: 'importing',
      assets: currentState.assets,
      error: null,
      progress: terrainConfig.initialProgress,
    }));
    try {
      const sourceName = selectedFiles
        .map((file) => file.name)
        .join(terrainConfig.texts.sourceNameSeparator);
      const sourceNames = selectedFiles.map((file) => file.name);
      const geojsonDocuments: unknown[] = [];
      for (const file of selectedFiles) {
        let geojson: unknown;
        try {
          geojson = JSON.parse(await file.text()) as unknown;
        } catch {
          throw new Error(terrainConfig.texts.invalidGeojson);
        }
        geojsonDocuments.push(geojson);
      }
      const importedGeojsonInfo = summarizeGeojsonDocuments(
        geojsonDocuments,
        sourceNames,
        terrainConfig.geojson,
        terrainConfig.texts.invalidGeojson,
      );
      const importedModelName = geojsonModelName(
        geojsonDocuments,
        terrainConfig.geojson,
        terrainConfig.texts.invalidGeojson,
      );
      setGeojsonInfo(importedGeojsonInfo);
      setTerrainName(importedModelName);
      setModelName(importedModelName);
      const payload = createTerrainUploadPayload(
        sourceName,
        combineGeojsonFeatureCollections(
          geojsonDocuments,
          terrainConfig.geojson,
          terrainConfig.texts.invalidGeojson,
        ),
        demDatasetKey,
        terrainConfig.texts.invalidGeojson,
      );
      const createdJob = await createTerrainJob(terrainConfig.jobApiUrl, payload);
      const completedJob = await pollTerrainJob(createdJob.jobId, (job) => {
        setTerrainState((currentState) => ({
          status: 'importing',
          assets: currentState.assets,
          error: null,
          progress: job.progress.percent,
        }));
        setProgressMessage(localizeStructuredMessage(job.progress, 'tasks'));
      });
      if (!completedJob.asset) {
        throw new Error(terrainConfig.texts.loadFailed);
      }
      setTerrainState({
        status: 'ready',
        assets: [completedJob.asset],
        error: null,
        progress: terrainConfig.completeProgress,
      });
      setPreviewVerticalExaggeration(
        completedJob.asset.renderOptions?.verticalExaggeration ??
          terrainConfig.renderOptions.defaultVerticalExaggeration,
      );
      setSaveMessage(null);
    } catch (error) {
      setTerrainState({
        status: 'error',
        assets: previousAssets,
        error: error instanceof Error ? error.message : terrainConfig.texts.loadFailed,
        progress: terrainConfig.initialProgress,
      });
    }
  };

  const pollTerrainJob = async (
    jobId: string,
    onProgress: (job: TerrainJob) => void,
  ): Promise<TerrainJob> => {
    const jobUrl = routeWithParam(
      terrainConfig.jobStatusApiUrl,
      terrainConfig.routePlaceholders.jobId,
      jobId,
    );
    let currentJob = await loadTerrainJob(jobUrl);
    onProgress(currentJob);
    while (
      currentJob.status !== terrainConfig.jobStatus.complete &&
      currentJob.status !== terrainConfig.jobStatus.failed
    ) {
      await wait(terrainConfig.pollIntervalMs);
      currentJob = await loadTerrainJob(jobUrl);
      onProgress(currentJob);
    }
    if (currentJob.status === terrainConfig.jobStatus.failed) {
      throw new Error(
        currentJob.error
          ? localizeStructuredMessage(currentJob.error)
          : terrainConfig.texts.loadFailed,
      );
    }
    return currentJob;
  };

  const openSavedModel = async (modelId: string) => {
    try {
      const modelUrl = routeWithParam(
        terrainConfig.modelApiUrl,
        terrainConfig.routePlaceholders.modelId,
        modelId,
      );
      const asset = await loadTerrainModel(
        modelUrl,
        terrainConfig.expectedSchema,
        terrainConfig.texts.invalidAsset,
      );
      setTerrainState({
        status: 'ready',
        assets: [asset],
        error: null,
        progress: terrainConfig.initialProgress,
      });
      setPreviewVerticalExaggeration(
        asset.renderOptions?.verticalExaggeration ??
          terrainConfig.renderOptions.defaultVerticalExaggeration,
      );
      setModelName(asset.name ?? asset.source);
      setTerrainName(asset.name ?? asset.source);
      setGeojsonInfo(null);
      setSaveMessage(null);
    } catch (error) {
      setTerrainState((currentState) => ({
        status: 'error',
        assets: currentState.assets,
        error: error instanceof Error ? error.message : terrainConfig.texts.loadFailed,
        progress: terrainConfig.initialProgress,
      }));
    }
  };

  const confirmRerender = () => {
    setTerrainState((currentState) => {
      if (!currentState.assets) {
        return currentState;
      }
      return {
        status: 'ready',
        assets: currentState.assets.map((asset) => ({
          ...asset,
          renderOptions: {
            verticalExaggeration: previewVerticalExaggeration,
          },
        })),
        error: null,
        progress: terrainConfig.initialProgress,
      };
    });
    setSaveMessage(null);
  };

  const saveCurrentModel = async () => {
    if (!terrainState.assets || terrainState.assets.length !== terrainConfig.singleAssetCount || !modelName.trim()) {
      return;
    }
    const [asset] = terrainState.assets;
    const savedModel = await saveTerrainModel(
      terrainConfig.modelsApiUrl,
      modelName.trim(),
      {
        ...asset,
        name: modelName.trim(),
        renderOptions: {
          verticalExaggeration: previewVerticalExaggeration,
        },
      },
    );
    setTerrainState((currentState) => {
      if (!currentState.assets) {
        return currentState;
      }
      return {
        status: 'ready',
        assets: currentState.assets.map((currentAsset) => ({
          ...currentAsset,
          modelId: savedModel.modelId,
          createdAt: savedModel.createdAt,
          name: savedModel.name,
          renderOptions: savedModel.renderOptions,
        })),
        error: null,
        progress: terrainConfig.initialProgress,
      };
    });
    setSaveMessage(terrainConfig.texts.saved);
    await refreshModels();
  };

  return (
    <main className="terrain-app">
      <section className="terrain-viewer" aria-label={terrainConfig.texts.title}>
        {terrainState.assets ? (
          <TerrainScene assets={terrainState.assets} config={terrainConfig} />
        ) : (
          <div className="terrain-message">
            <Mountain aria-hidden="true" />
            <span>
              {terrainState.status === 'loading' ? terrainConfig.texts.loading : terrainState.error}
            </span>
          </div>
        )}
        {terrainState.status === 'importing' ? (
          <div className="terrain-overlay">
            <Mountain aria-hidden="true" />
            <div>
              <span>{terrainConfig.texts.importing}</span>
              <small>{progressMessage}</small>
              <div className="terrain-progress" aria-valuenow={terrainState.progress}>
                <div style={{ width: `${terrainState.progress}%` }} />
              </div>
            </div>
          </div>
        ) : null}
      </section>

      <aside className="terrain-panel">
        <div>
          <h1>{terrainName || terrainConfig.texts.title}</h1>
          <p>{terrainConfig.texts.subtitle}</p>
        </div>
        <label className="terrain-file-button" htmlFor={terrainConfig.geojsonFileInputId}>
          <Mountain aria-hidden="true" />
          {terrainConfig.texts.importGeojson}
        </label>
        <label className="terrain-scale-control" htmlFor={terrainConfig.demDatasetInputId}>
          <span>{terrainConfig.texts.demDataset}</span>
          <select
            disabled={terrainState.status === 'importing'}
            id={terrainConfig.demDatasetInputId}
            onChange={(event) => setDemDatasetKey(event.target.value)}
            value={demDatasetKey}
          >
            {terrainConfig.demDatasets.options.map((demDataset) => (
              <option key={demDataset.key} value={demDataset.key}>
                {demDataset.label}
              </option>
            ))}
          </select>
        </label>
        {terrainState.assets ? (
          <div className="terrain-save-panel">
            <label className="terrain-scale-control">
              <span>{terrainConfig.texts.previewScale}</span>
              <div className="terrain-scale-stepper">
                <button
                  onClick={() =>
                    setPreviewVerticalExaggeration((value) =>
                      Math.max(
                        terrainConfig.renderOptions.minVerticalExaggeration,
                        value - terrainConfig.renderOptions.verticalExaggerationStep,
                      ),
                    )
                  }
                  type="button"
                >
                  -
                </button>
                <input
                  max={terrainConfig.renderOptions.maxVerticalExaggeration}
                  min={terrainConfig.renderOptions.minVerticalExaggeration}
                  onChange={(event) => setPreviewVerticalExaggeration(Number(event.target.value))}
                  step={terrainConfig.renderOptions.verticalExaggerationStep}
                  type="number"
                  value={previewVerticalExaggeration}
                />
                <button
                  onClick={() =>
                    setPreviewVerticalExaggeration((value) =>
                      Math.min(
                        terrainConfig.renderOptions.maxVerticalExaggeration,
                        value + terrainConfig.renderOptions.verticalExaggerationStep,
                      ),
                    )
                  }
                  type="button"
                >
                  +
                </button>
              </div>
            </label>
            <button className="terrain-page-switch" onClick={confirmRerender} type="button">
              {terrainConfig.texts.confirmRerender}
            </button>
            <label className="terrain-scale-control">
              <span>{terrainConfig.texts.modelName}</span>
              <input
                onChange={(event) => setModelName(event.target.value)}
                placeholder={terrainConfig.texts.modelNamePlaceholder}
                type="text"
                value={modelName}
              />
            </label>
            <button
              className="terrain-file-button"
              disabled={!modelName.trim()}
              onClick={() => void saveCurrentModel()}
              type="button"
            >
              {terrainConfig.texts.saveModel}
            </button>
            {saveMessage ? <div className="terrain-empty">{saveMessage}</div> : null}
          </div>
        ) : null}
        <input
          accept={terrainConfig.geojsonFileAccept}
          className="terrain-file-input"
          disabled={terrainState.status === 'importing'}
          id={terrainConfig.geojsonFileInputId}
          multiple
          onChange={(event) => {
            const files = Array.from(event.target.files ?? []);
            event.target.value = '';
            if (files.length > terrainConfig.emptyFileCount) {
              void importGeojson(files);
            }
          }}
          type="file"
        />
        {terrainState.assets ? (
          <TerrainStats assets={terrainState.assets} config={terrainConfig} />
        ) : null}
        {geojsonInfo ? <GeojsonInfoPanel geojsonInfo={geojsonInfo} config={terrainConfig} /> : null}
        {terrainState.status === 'error' ? (
          <div className="terrain-error">{terrainState.error}</div>
        ) : null}
        <TerrainModelList models={models} onOpenModel={openSavedModel} onRefresh={refreshModels} />
      </aside>
    </main>
  );
}

function GeojsonInfoPanel({
  geojsonInfo,
  config,
}: {
  geojsonInfo: TerrainGeojsonFileInfo[];
  config: TerrainConfig;
}) {
  return (
    <div className="terrain-geojson-info">
      <h2>{config.texts.geojsonInfo}</h2>
      {geojsonInfo.map((fileInfo) => (
        <div className="terrain-geojson-file" key={fileInfo.sourceName}>
          <div className="terrain-geojson-properties">
            {fileInfo.properties.length > config.emptyFileCount ? (
              fileInfo.properties.map((property) => (
                <div key={`${fileInfo.sourceName}-${property.key}-${property.value}`}>
                  <em>{property.key}</em>
                  <strong>{property.value}</strong>
                </div>
              ))
            ) : (
              <strong>{config.texts.geojsonNoProperties}</strong>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

export function TerrainScene({ assets, config }: { assets: TerrainAsset[]; config: TerrainConfig }) {
  const mountRef = React.useRef<HTMLDivElement | null>(null);
  const compassDialRef = React.useRef<HTMLDivElement | null>(null);
  const controlsRef = React.useRef<OrbitControls | null>(null);
  const cameraRef = React.useRef<THREE.PerspectiveCamera | null>(null);

  React.useEffect(() => {
    const mount = mountRef.current;
    if (!mount) {
      return undefined;
    }

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(config.scene.backgroundColor);

    const camera = new THREE.PerspectiveCamera(
      config.scene.fieldOfView,
      mount.clientWidth / mount.clientHeight,
      config.scene.nearPlane,
      config.scene.farPlane,
    );
    setVector3(camera.position, config.scene.cameraPosition);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    setVector3(controls.target, config.scene.cameraTarget);
    controls.enableDamping = true;
    controlsRef.current = controls;

    scene.add(
      new THREE.AmbientLight(config.scene.ambientLightColor, config.scene.ambientLightIntensity),
    );

    const directionalLight = new THREE.DirectionalLight(
      config.scene.directionalLightColor,
      config.scene.directionalLightIntensity,
    );
    setVector3(directionalLight.position, config.scene.directionalLightPosition);
    scene.add(directionalLight);

    const material = new THREE.MeshStandardMaterial({
      roughness: config.scene.terrainRoughness,
      metalness: config.scene.terrainMetalness,
      vertexColors: true,
      side: THREE.DoubleSide,
    });
    const frame = createTerrainSceneFrame(
      combinedTerrainBounds(assets),
      assets[0].renderOptions?.verticalExaggeration ?? config.scene.defaultVerticalExaggeration,
      config.scene,
    );
    const terrainGeometries: THREE.BufferGeometry[] = [];
    assets.forEach((asset) => {
      const meshData = createTerrainMeshData(asset, config.scene, frame);
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.BufferAttribute(meshData.positions, 3));
      geometry.setAttribute('color', new THREE.BufferAttribute(meshData.colors, 3));
      geometry.computeVertexNormals();
      terrainGeometries.push(geometry);
      scene.add(new THREE.Mesh(geometry, material));
    });

    const boundaryMaterial = new THREE.LineBasicMaterial({
      color: config.scene.boundaryColor,
      linewidth: config.scene.boundaryLineWidth,
    });
    const boundaryGroup = new THREE.Group();
    const boundaryGeometries: THREE.BufferGeometry[] = [];
    assets.forEach((asset) => {
      createBoundaryLines(asset, config.scene, frame).forEach((linePositions) => {
        const boundaryGeometry = new THREE.BufferGeometry();
        boundaryGeometry.setAttribute('position', new THREE.BufferAttribute(linePositions, 3));
        boundaryGeometries.push(boundaryGeometry);
        boundaryGroup.add(new THREE.Line(boundaryGeometry, boundaryMaterial));
      });
    });
    scene.add(boundaryGroup);

    const resizeObserver = new ResizeObserver(() => {
      camera.aspect = mount.clientWidth / mount.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(mount.clientWidth, mount.clientHeight);
    });
    resizeObserver.observe(mount);

    let animationFrame = 0;
    const animate = () => {
      animationFrame = window.requestAnimationFrame(animate);
      controls.update();
      compassDialRef.current?.style.setProperty(
        config.scene.compassRotationCssProperty,
        String(-controls.getAzimuthalAngle()),
      );
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      window.cancelAnimationFrame(animationFrame);
      resizeObserver.disconnect();
      controls.dispose();
      terrainGeometries.forEach((geometry) => geometry.dispose());
      material.dispose();
      boundaryGeometries.forEach((boundaryGeometry) => boundaryGeometry.dispose());
      boundaryMaterial.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [assets, config]);

  const resetView = () => {
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    if (!camera || !controls) {
      return;
    }
    setVector3(camera.position, config.scene.cameraPosition);
    setVector3(controls.target, config.scene.cameraTarget);
    controls.update();
  };

  return (
    <>
      <div className="terrain-canvas" ref={mountRef} />
      <div className="terrain-guide" aria-label={config.texts.guideLabel}>
        <div className="terrain-compass">
          <Compass aria-hidden="true" />
          <div className="terrain-compass-dial" ref={compassDialRef}>
            <span className="terrain-compass-north">{config.texts.compassNorth}</span>
            <span className="terrain-compass-east">{config.texts.compassEast}</span>
            <span className="terrain-compass-south">{config.texts.compassSouth}</span>
            <span className="terrain-compass-west">{config.texts.compassWest}</span>
            <div className="terrain-compass-needle" />
          </div>
        </div>
        <div className="terrain-normal-guide">
          <ArrowUp aria-hidden="true" />
          <span>{config.texts.normalVectorLabel}</span>
          <strong>{config.texts.normalVectorDirection}</strong>
        </div>
      </div>
      <button
        aria-label={config.texts.resetView}
        className="terrain-reset"
        onClick={resetView}
        title={config.texts.resetView}
        type="button"
      >
        <RotateCcw aria-hidden="true" />
      </button>
    </>
  );
}

export function TerrainStats({ assets, config }: { assets: TerrainAsset[]; config: TerrainConfig }) {
  const validSampleCount = assets.reduce(
    (total, asset) => total + asset.elevations.filter((elevation) => elevation !== null).length,
    config.initialProgress,
  );
  const minElevation = Math.min(...assets.map((asset) => asset.minElevation));
  const maxElevation = Math.max(...assets.map((asset) => asset.maxElevation));
  return (
    <div className="terrain-stats">
      <Metric icon={<Layers3 aria-hidden="true" />} label={config.texts.source} value={sourceNames(assets, config)} />
      <Metric
        icon={<Layers3 aria-hidden="true" />}
        label={config.texts.assetCount}
        value={formatNumber(assets.length)}
      />
      <Metric
        icon={<Grid3X3 aria-hidden="true" />}
        label={config.texts.grid}
        value={gridSummary(assets, config)}
      />
      <Metric
        icon={<Mountain aria-hidden="true" />}
        label={config.texts.elevation}
        value={`${minElevation}m - ${maxElevation}m`}
      />
      <Metric
        icon={<Grid3X3 aria-hidden="true" />}
        label={config.texts.validSamples}
        value={formatNumber(validSampleCount)}
      />
    </div>
  );
}

function sourceNames(assets: TerrainAsset[], config: TerrainConfig): string {
  return assets.map((asset) => asset.source).join(config.texts.sourceNameSeparator);
}

function gridSummary(assets: TerrainAsset[], config: TerrainConfig): string {
  const gridValues = new Set(assets.map((asset) => `${asset.columns} x ${asset.rows}`));
  if (gridValues.size === config.singleAssetCount) {
    return Array.from(gridValues)[0];
  }
  return Array.from(gridValues).join(config.texts.sourceNameSeparator);
}

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="terrain-metric">
      <div className="terrain-metric-icon">{icon}</div>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
    </div>
  );
}

function TerrainModelList({
  models,
  onOpenModel,
  onRefresh,
}: {
  models: TerrainModelMetadata[];
  onOpenModel: (modelId: string) => void;
  onRefresh: () => Promise<void>;
}) {
  return (
    <div className="terrain-models">
      <div className="terrain-models-header">
        <h2>{terrainConfig.texts.modelList}</h2>
        <button onClick={() => void onRefresh()} type="button">
          {terrainConfig.texts.refreshModels}
        </button>
      </div>
      {models.length === 0 ? (
        <div className="terrain-empty">{terrainConfig.texts.noModels}</div>
      ) : (
        <div className="terrain-model-list">
          {models.map((model) => (
            <button
              className="terrain-model-item"
              key={model.modelId}
              onClick={() => onOpenModel(model.modelId)}
              type="button"
            >
              <span>{model.source}</span>
              <strong>
                {model.columns} x {model.rows} / {formatNumber(model.validSampleCount)}
              </strong>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function setVector3(vector: THREE.Vector3, values: number[]): void {
  vector.set(values[0], values[1], values[2]);
}

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, milliseconds);
  });
}
