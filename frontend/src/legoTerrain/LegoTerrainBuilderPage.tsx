import React from 'react';
import { BarChart3, FileJson, Grid3X3, Layers3, Mountain, RefreshCw, Save } from 'lucide-react';
import { localizeStructuredMessage } from '../api/client';
import { formatNumber as formatLocalizedNumber } from '../i18n/formatters';
import legoTerrainConfig from './legoTerrainConfig';
import {
  createLegoHeightmapAsset,
  saveLegoHeightmapModel,
  type LegoHeightmapModelMetadata,
} from './legoHeightmapAsset';
import {
  createLegoHeightmap,
  type LegoHeightCell,
  type LegoHeightmap,
  type LegoHeightmapScale,
} from './legoHeightmap';
import {
  combineGeojsonFeatureCollections,
  createTerrainJob,
  createTerrainUploadPayload,
  loadTerrainJob,
  routeWithParam,
} from '../terrain/terrainApi';
import terrainConfig from '../terrain/terrainConfig';
import type { TerrainAsset, TerrainJob } from '../terrain/terrainTypes';

type LegoTerrainState =
  | { status: 'loading'; asset: null; error: null; progress: number }
  | { status: 'importing'; asset: TerrainAsset | null; error: null; progress: number }
  | { status: 'ready'; asset: TerrainAsset; error: null; progress: number }
  | { status: 'error'; asset: TerrainAsset | null; error: string; progress: number };

export function LegoTerrainBuilderPage() {
  const [terrainState, setTerrainState] = React.useState<LegoTerrainState>({
    status: 'loading',
    asset: null,
    error: null,
    progress: legoTerrainConfig.initialProgress,
  });
  const [scale, setScale] = React.useState<LegoHeightmapScale>({
    horizontalKmPerStud: legoTerrainConfig.scale.defaultHorizontalKmPerStud,
    verticalMetersPerPlate: legoTerrainConfig.scale.defaultVerticalMetersPerPlate,
    aggregation: legoTerrainConfig.heightmap.defaultAggregation,
    minCoverageRatio: legoTerrainConfig.scale.defaultMinCoverageRatio,
  });
  const [modelName, setModelName] = React.useState(legoTerrainConfig.texts.title);
  const [saveMessage, setSaveMessage] = React.useState<string | null>(null);
  const [progressMessage, setProgressMessage] = React.useState('');

  const loadDefaultAsset = React.useCallback(async () => {
    setTerrainState({
      status: 'loading',
      asset: null,
      error: null,
      progress: legoTerrainConfig.initialProgress,
    });
    try {
      const response = await fetch(legoTerrainConfig.assetUrl);
      if (!response.ok) {
        throw new Error(legoTerrainConfig.texts.loadFailed);
      }
      const asset = (await response.json()) as TerrainAsset;
      if (asset.schema !== terrainConfig.expectedSchema) {
        throw new Error(terrainConfig.texts.invalidAsset);
      }
      setTerrainState({
        status: 'ready',
        asset,
        error: null,
        progress: legoTerrainConfig.completeProgress,
      });
      setModelName(asset.name ?? asset.source);
      setSaveMessage(null);
    } catch (error) {
      setTerrainState({
        status: 'error',
        asset: null,
        error: error instanceof Error ? error.message : legoTerrainConfig.texts.loadFailed,
        progress: legoTerrainConfig.initialProgress,
      });
    }
  }, []);

  React.useEffect(() => {
    void loadDefaultAsset();
  }, [loadDefaultAsset]);

  const heightmap = React.useMemo(() => {
    if (!terrainState.asset) {
      return null;
    }
    return createLegoHeightmap(terrainState.asset, scale, legoTerrainConfig.heightmap);
  }, [terrainState.asset, scale]);

  const importGeojson = async (selectedFiles: File[]) => {
    if (selectedFiles.length === legoTerrainConfig.emptyFileCount) {
      return;
    }
    const previousAsset = terrainState.asset;
    setTerrainState({
      status: 'importing',
      asset: previousAsset,
      error: null,
      progress: legoTerrainConfig.initialProgress,
    });
    try {
      const sourceName = selectedFiles
        .map((file) => file.name)
        .join(terrainConfig.texts.sourceNameSeparator);
      const geojsonDocuments: unknown[] = [];
      for (const file of selectedFiles) {
        let geojson: unknown;
        try {
          geojson = JSON.parse(await file.text()) as unknown;
        } catch {
          throw new Error(legoTerrainConfig.texts.invalidGeojson);
        }
        geojsonDocuments.push(geojson);
      }
      const payload = createTerrainUploadPayload(
        sourceName,
        combineGeojsonFeatureCollections(
          geojsonDocuments,
          terrainConfig.geojson,
          legoTerrainConfig.texts.invalidGeojson,
        ),
        terrainConfig.demDatasets.defaultKey,
        legoTerrainConfig.texts.invalidGeojson,
      );
      const createdJob = await createTerrainJob(terrainConfig.jobApiUrl, payload);
      const completedJob = await pollTerrainJob(createdJob.jobId, (job) => {
        setTerrainState((currentState) => ({
          status: 'importing',
          asset: currentState.asset,
          error: null,
          progress: job.progress.percent,
        }));
        setProgressMessage(localizeStructuredMessage(job.progress, 'tasks'));
      });
      if (!completedJob.asset) {
        throw new Error(legoTerrainConfig.texts.loadFailed);
      }
      setTerrainState({
        status: 'ready',
        asset: completedJob.asset,
        error: null,
        progress: legoTerrainConfig.completeProgress,
      });
      setModelName(completedJob.asset.name ?? completedJob.asset.source);
      setSaveMessage(null);
    } catch (error) {
      setTerrainState({
        status: 'error',
        asset: previousAsset,
        error: error instanceof Error ? error.message : legoTerrainConfig.texts.loadFailed,
        progress: legoTerrainConfig.initialProgress,
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
          : legoTerrainConfig.texts.loadFailed,
      );
    }
    return currentJob;
  };

  const saveCurrentHeightmap = async () => {
    if (!heightmap || !terrainState.asset || !modelName.trim()) {
      return;
    }
    try {
      const savedModel: LegoHeightmapModelMetadata = await saveLegoHeightmapModel(
        legoTerrainConfig.modelsApiUrl,
        modelName.trim(),
        createLegoHeightmapAsset(
          heightmap,
          terrainState.asset.source,
          legoTerrainConfig.assetSchema,
        ),
      );
      setSaveMessage(`${legoTerrainConfig.texts.saved}: ${savedModel.name}`);
    } catch (error) {
      setSaveMessage(error instanceof Error ? error.message : legoTerrainConfig.texts.saveFailed);
    }
  };

  return (
    <main className="lego-terrain-page">
      <header className="lego-terrain-header">
        <div>
          <h1>{legoTerrainConfig.texts.title}</h1>
          <p>{legoTerrainConfig.texts.subtitle}</p>
        </div>
        <div className="lego-terrain-actions">
          <button onClick={() => void loadDefaultAsset()} type="button">
            <RefreshCw aria-hidden="true" />
            {legoTerrainConfig.texts.loadDefault}
          </button>
          <label htmlFor={legoTerrainConfig.geojsonFileInputId}>
            <FileJson aria-hidden="true" />
            {legoTerrainConfig.texts.importGeojson}
          </label>
          <input
            accept={terrainConfig.geojsonFileAccept}
            id={legoTerrainConfig.geojsonFileInputId}
            multiple
            onChange={(event) => {
              const files = Array.from(event.target.files ?? []);
              event.target.value = '';
              if (files.length > legoTerrainConfig.emptyFileCount) {
                void importGeojson(files);
              }
            }}
            type="file"
          />
        </div>
      </header>

      <section className="lego-terrain-layout">
        <aside className="lego-terrain-panel">
          <h2>{legoTerrainConfig.texts.scale}</h2>
          <ScaleInput
            label={legoTerrainConfig.texts.horizontalKmPerStud}
            max={legoTerrainConfig.scale.maxHorizontalKmPerStud}
            min={legoTerrainConfig.scale.minHorizontalKmPerStud}
            onChange={(value) =>
              setScale((currentScale) => ({ ...currentScale, horizontalKmPerStud: value }))
            }
            step={legoTerrainConfig.scale.horizontalKmStep}
            value={scale.horizontalKmPerStud}
          />
          <ScaleInput
            label={legoTerrainConfig.texts.verticalMetersPerPlate}
            max={legoTerrainConfig.scale.maxVerticalMetersPerPlate}
            min={legoTerrainConfig.scale.minVerticalMetersPerPlate}
            onChange={(value) =>
              setScale((currentScale) => ({ ...currentScale, verticalMetersPerPlate: value }))
            }
            step={legoTerrainConfig.scale.verticalMetersStep}
            value={scale.verticalMetersPerPlate}
          />
          <label className="lego-terrain-control">
            <span>{legoTerrainConfig.texts.aggregation}</span>
            <select
              onChange={(event) =>
                setScale((currentScale) => ({ ...currentScale, aggregation: event.target.value }))
              }
              value={scale.aggregation}
            >
              <option value={legoTerrainConfig.heightmap.aggregation.percentile}>
                {legoTerrainConfig.texts.percentile}
              </option>
              <option value={legoTerrainConfig.heightmap.aggregation.mean}>
                {legoTerrainConfig.texts.mean}
              </option>
              <option value={legoTerrainConfig.heightmap.aggregation.max}>
                {legoTerrainConfig.texts.max}
              </option>
            </select>
          </label>
          <ScaleInput
            label={legoTerrainConfig.texts.coverage}
            max={legoTerrainConfig.scale.maxCoverageRatio}
            min={legoTerrainConfig.scale.minCoverageRatio}
            onChange={(value) =>
              setScale((currentScale) => ({ ...currentScale, minCoverageRatio: value }))
            }
            step={legoTerrainConfig.scale.coverageStep}
            value={scale.minCoverageRatio}
          />
        </aside>

        <section className="lego-heightmap-workspace">
          <div className="lego-heightmap-title">
            <Grid3X3 aria-hidden="true" />
            <span>{legoTerrainConfig.texts.heightmap}</span>
          </div>
          {heightmap ? (
            <>
              <HeightmapLegend heightmap={heightmap} />
              <HeightmapCanvas heightmap={heightmap} />
            </>
          ) : (
            <div className="lego-heightmap-empty">{legoTerrainConfig.texts.emptyHeightmap}</div>
          )}
          {terrainState.status === 'loading' || terrainState.status === 'importing' ? (
            <div className="lego-terrain-progress">
              <Mountain aria-hidden="true" />
              <span>
                {terrainState.status === 'loading'
                  ? legoTerrainConfig.texts.loading
                  : progressMessage || legoTerrainConfig.texts.importing}
              </span>
              <div>
                <div style={{ width: `${terrainState.progress}${legoTerrainConfig.units.percent}` }} />
              </div>
            </div>
          ) : null}
          {terrainState.status === 'error' ? (
            <div className="lego-terrain-error">{terrainState.error}</div>
          ) : null}
        </section>

        <aside className="lego-terrain-panel">
          <h2>{legoTerrainConfig.texts.source}</h2>
          {terrainState.asset ? (
            <div className="lego-terrain-source">
              <strong>{terrainState.asset.source}</strong>
              <span>{terrainState.asset.columns} x {terrainState.asset.rows}</span>
            </div>
          ) : (
            <div className="lego-terrain-source">
              <span>{legoTerrainConfig.texts.emptyHeightmap}</span>
            </div>
          )}
          {heightmap ? <HeightmapMetrics heightmap={heightmap} /> : null}
          {heightmap ? (
            <div className="lego-terrain-save-panel">
              <label className="lego-terrain-control">
                <span>{legoTerrainConfig.texts.modelName}</span>
                <input
                  onChange={(event) => setModelName(event.target.value)}
                  placeholder={legoTerrainConfig.texts.modelNamePlaceholder}
                  type="text"
                  value={modelName}
                />
              </label>
              <button
                disabled={!modelName.trim()}
                onClick={() => void saveCurrentHeightmap()}
                type="button"
              >
                <Save aria-hidden="true" />
                {legoTerrainConfig.texts.saveHeightmap}
              </button>
              {saveMessage ? <div className="lego-terrain-source">{saveMessage}</div> : null}
            </div>
          ) : null}
        </aside>
      </section>
    </main>
  );
}

function ScaleInput({
  label,
  max,
  min,
  onChange,
  step,
  value,
}: {
  label: string;
  max: number;
  min: number;
  onChange: (value: number) => void;
  step: number;
  value: number;
}) {
  return (
    <label className="lego-terrain-control">
      <span>{label}</span>
      <input
        max={max}
        min={min}
        onChange={(event) => onChange(Number(event.target.value))}
        step={step}
        type="number"
        value={value}
      />
    </label>
  );
}

export function HeightmapMetrics({ heightmap }: { heightmap: LegoHeightmap }) {
  const expression = terrainExpressionLabel(heightmap.metrics.maxHeightPlate);
  return (
    <div className="lego-terrain-metrics">
      <Metric
        icon={<Grid3X3 aria-hidden="true" />}
        label={legoTerrainConfig.texts.dimensions}
        value={`${heightmap.metrics.widthStud} x ${heightmap.metrics.depthStud} ${legoTerrainConfig.units.studs}`}
      />
      <Metric
        icon={<BarChart3 aria-hidden="true" />}
        label={legoTerrainConfig.texts.physicalSize}
        value={`${formatNumber(heightmap.metrics.widthStud * legoTerrainConfig.physical.studCentimeters)} x ${formatNumber(
          heightmap.metrics.depthStud * legoTerrainConfig.physical.studCentimeters,
        )} ${legoTerrainConfig.units.centimeters}`}
      />
      <Metric
        icon={<Layers3 aria-hidden="true" />}
        label={legoTerrainConfig.texts.heightRange}
        value={`${heightmap.metrics.maxHeightPlate} ${legoTerrainConfig.units.plates}`}
      />
      <Metric
        icon={<Grid3X3 aria-hidden="true" />}
        label={legoTerrainConfig.texts.validCells}
        value={`${heightmap.metrics.validCellCount} / ${heightmap.metrics.totalCellCount}`}
      />
      <Metric
        icon={<BarChart3 aria-hidden="true" />}
        label={legoTerrainConfig.texts.coverageSummary}
        value={`${formatNumber(heightmap.metrics.averageCoverageRatio * legoTerrainConfig.heightmap.coveragePrecision)}${legoTerrainConfig.units.percent}`}
      />
      <Metric
        icon={<Mountain aria-hidden="true" />}
        label={legoTerrainConfig.texts.terrainExpression}
        value={expression}
      />
    </div>
  );
}

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="lego-terrain-metric">
      <div>{icon}</div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function HeightmapCanvas({ heightmap }: { heightmap: LegoHeightmap }) {
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }
    const context = canvas.getContext('2d');
    if (!context) {
      return;
    }
    const drawHeightmap = () => {
      drawHeightmapCanvas(canvas, context, heightmap);
    };
    drawHeightmap();
    const resizeObserver = new ResizeObserver(drawHeightmap);
    resizeObserver.observe(canvas);
    return () => resizeObserver.disconnect();
  }, [heightmap]);

  return <canvas className="lego-heightmap-canvas" ref={canvasRef} />;
}

export function HeightmapLegend({ heightmap }: { heightmap: LegoHeightmap }) {
  return (
    <div className="lego-heightmap-legend" aria-label={legoTerrainConfig.texts.heightmapLegend}>
      <LegendItem color={legoTerrainConfig.preview.emptyColor} label={legoTerrainConfig.texts.emptyCell} />
      <LegendItem color={legoTerrainConfig.preview.lowColor} label={legoTerrainConfig.texts.lowPlate} />
      <LegendItem color={legoTerrainConfig.preview.midColor} label={legoTerrainConfig.texts.midPlate} />
      <LegendItem color={legoTerrainConfig.preview.highColor} label={legoTerrainConfig.texts.highPlate} />
      <span>{`${legoTerrainConfig.texts.cellNumberHelp} ${heightmap.metrics.maxHeightPlate} ${legoTerrainConfig.units.plates} ${legoTerrainConfig.texts.maximumHeightSuffix}.`}</span>
    </div>
  );
}

function LegendItem({ color, label }: { color: string; label: string }) {
  return (
    <span className="lego-heightmap-legend-item">
      <span style={{ background: color }} />
      {label}
    </span>
  );
}

function drawHeightmapCanvas(
  canvas: HTMLCanvasElement,
  context: CanvasRenderingContext2D,
  heightmap: LegoHeightmap,
): void {
  const pixelRatio = Math.min(window.devicePixelRatio, legoTerrainConfig.preview.pixelRatioLimit);
  const cssWidth = Math.max(
    legoTerrainConfig.preview.minimumCanvasPixels,
    canvas.clientWidth || legoTerrainConfig.preview.canvasFallbackWidth,
  );
  const cssHeight = Math.max(
    legoTerrainConfig.preview.minimumCanvasPixels,
    canvas.clientHeight || legoTerrainConfig.preview.canvasFallbackHeight,
  );
  canvas.width = cssWidth * pixelRatio;
  canvas.height = cssHeight * pixelRatio;
  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  context.clearRect(0, 0, cssWidth, cssHeight);

  const cellSize = Math.min(
    cssWidth / heightmap.metrics.widthStud,
    cssHeight / heightmap.metrics.depthStud,
  );
  const gridWidth = cellSize * heightmap.metrics.widthStud;
  const gridHeight = cellSize * heightmap.metrics.depthStud;
  const offsetX = (cssWidth - gridWidth) / legoTerrainConfig.heightmap.coordinateAverageDivisor;
  const offsetY = (cssHeight - gridHeight) / legoTerrainConfig.heightmap.coordinateAverageDivisor;

  for (const cell of heightmap.cells) {
    context.fillStyle = cellColor(cell, heightmap.metrics.maxHeightPlate);
    context.fillRect(offsetX + cell.x * cellSize, offsetY + cell.z * cellSize, cellSize, cellSize);
  }

  if (cellSize >= legoTerrainConfig.preview.gridLineMinCellPixels) {
    drawHeightmapGrid(context, heightmap, offsetX, offsetY, cellSize);
  }
  if (cellSize >= legoTerrainConfig.preview.labelMinCellPixels) {
    drawHeightmapLabels(context, heightmap, offsetX, offsetY, cellSize);
  }
}

function drawHeightmapGrid(
  context: CanvasRenderingContext2D,
  heightmap: LegoHeightmap,
  offsetX: number,
  offsetY: number,
  cellSize: number,
): void {
  context.strokeStyle = legoTerrainConfig.preview.gridColor;
  context.lineWidth = legoTerrainConfig.preview.gridLineWidth;
  for (let x = 0; x <= heightmap.metrics.widthStud; x += 1) {
    const lineX = offsetX + x * cellSize;
    context.beginPath();
    context.moveTo(lineX, offsetY);
    context.lineTo(lineX, offsetY + heightmap.metrics.depthStud * cellSize);
    context.stroke();
  }
  for (let z = 0; z <= heightmap.metrics.depthStud; z += 1) {
    const lineY = offsetY + z * cellSize;
    context.beginPath();
    context.moveTo(offsetX, lineY);
    context.lineTo(offsetX + heightmap.metrics.widthStud * cellSize, lineY);
    context.stroke();
  }
}

function drawHeightmapLabels(
  context: CanvasRenderingContext2D,
  heightmap: LegoHeightmap,
  offsetX: number,
  offsetY: number,
  cellSize: number,
): void {
  context.font = `${legoTerrainConfig.preview.labelFontSizePixels}px ${legoTerrainConfig.preview.labelFontFamily}`;
  context.textAlign = legoTerrainConfig.preview.labelAlign as CanvasTextAlign;
  context.textBaseline = legoTerrainConfig.preview.labelBaseline as CanvasTextBaseline;
  for (const cell of heightmap.cells) {
    if (cell.elevationMeters === null) {
      continue;
    }
    context.fillStyle = legoTerrainConfig.preview.labelColor;
    context.fillText(
      String(cell.heightPlate),
      offsetX + cell.x * cellSize + cellSize / legoTerrainConfig.heightmap.coordinateAverageDivisor,
      offsetY + cell.z * cellSize + cellSize / legoTerrainConfig.heightmap.coordinateAverageDivisor,
    );
  }
}

function cellColor(cell: LegoHeightCell, maxHeightPlate: number): string {
  if (cell.elevationMeters === null) {
    return legoTerrainConfig.preview.emptyColor;
  }
  const ratio = cell.heightPlate / Math.max(legoTerrainConfig.heightmap.minimumStudCount, maxHeightPlate);
  if (ratio <= legoTerrainConfig.heightmap.percentileRatio) {
    return mixColor(
      legoTerrainConfig.preview.lowColor,
      legoTerrainConfig.preview.midColor,
      ratio / legoTerrainConfig.heightmap.percentileRatio,
    );
  }
  return mixColor(
    legoTerrainConfig.preview.midColor,
    legoTerrainConfig.preview.highColor,
    (ratio - legoTerrainConfig.heightmap.percentileRatio) /
      (legoTerrainConfig.scale.maxCoverageRatio - legoTerrainConfig.heightmap.percentileRatio),
  );
}

function mixColor(startHex: string, endHex: string, ratio: number): string {
  const start = hexToRgb(startHex);
  const end = hexToRgb(endHex);
  return `rgb(${Math.round(start.red + (end.red - start.red) * ratio)}, ${Math.round(
    start.green + (end.green - start.green) * ratio,
  )}, ${Math.round(start.blue + (end.blue - start.blue) * ratio)})`;
}

function hexToRgb(hex: string): { red: number; green: number; blue: number } {
  const value = Number.parseInt(hex.slice(legoTerrainConfig.heightmap.minimumStudCount), 16);
  return {
    red: (value >> 16) & 255,
    green: (value >> 8) & 255,
    blue: value & 255,
  };
}

function terrainExpressionLabel(maxHeightPlate: number): string {
  if (maxHeightPlate < legoTerrainConfig.terrainExpression.weakMaxPlate) {
    return legoTerrainConfig.texts.weakTerrain;
  }
  if (maxHeightPlate < legoTerrainConfig.terrainExpression.acceptableMaxPlate) {
    return legoTerrainConfig.texts.acceptableTerrain;
  }
  if (maxHeightPlate < legoTerrainConfig.terrainExpression.strongMaxPlate) {
    return legoTerrainConfig.texts.strongTerrain;
  }
  return legoTerrainConfig.texts.complexTerrain;
}

function formatNumber(value: number): string {
  return formatLocalizedNumber(value, { maximumFractionDigits: 1 });
}

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, milliseconds);
  });
}
