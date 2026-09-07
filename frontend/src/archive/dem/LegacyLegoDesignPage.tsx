import { useSearchParams } from 'react-router-dom';
import React from 'react';
import {
  Boxes,
  ChevronLeft,
  ChevronRight,
  Download,
  FileJson,
  Image as ImageIcon,
  List,
  Maximize2,
  Minimize2,
  RefreshCw,
  Wand2,
  X,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import { localizeStructuredMessage } from '../../api/client';
import type { PixelArtProject, PixelArtProjectList, PixelArtProjectSummary } from '../../pixelArt/pixelArtApi';
import {
  createLegoDesignJob,
  exportLegoDesign,
  exportLegoDesignPlan,
  loadLegoDesignJob,
  loadLegoDesignMetadata,
  loadLegoDesignPixelProject,
  loadLegoDesignPixelProjects,
  type LegoBomItem,
  type LegoDesignJob,
  type LegoDesignMetadata,
  type LegoDesignResult,
  type LegoPlacement,
} from '../../legoDesign/legoDesignApi';
import {
  createDemFinalDesign,
  createDemFinalDesignRequest,
  exportDemFinalDesignLdraw,
  exportDemFinalDesignReport,
  type DemFinalBomItem,
  type DemFinalDesign,
  type DemSurfacePlacement,
} from '../../legoDesign/demFinalDesignApi';
import appConfig from '../../app/appConfig';
import { loadModelAssetPage, type ModelAsset, type ModelAssetPage } from '../../assets/modelAssetApi';
import type { LegoHeightmapScale } from '../../legoTerrain/legoHeightmap';
import legoTerrainConfig from '../../legoTerrain/legoTerrainConfig';
import { loadTerrainModel, routeWithParam } from '../../terrain/terrainApi';
import terrainConfig from '../../terrain/terrainConfig';
import type { TerrainAsset } from '../../terrain/terrainTypes';
import legoDesignConfig from '../../legoDesign/legoDesignConfig';

/** 保留历史 DEM 设计流程；正式 2D 入口禁用 DEM 选择与资产请求。 */
export function LegoDesignPage({ enableDem = false }: { enableDem?: boolean }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeJobId = searchParams.get('job');
  const [page, setPage] = React.useState(legoDesignConfig.pagination.initialPage);
  const [projectList, setProjectList] = React.useState<PixelArtProjectList | null>(null);
  const [demAssetPage, setDemAssetPage] = React.useState<ModelAssetPage | null>(null);
  const [metadata, setMetadata] = React.useState<LegoDesignMetadata | null>(null);
  const [selectedProject, setSelectedProject] = React.useState<PixelArtProject | null>(null);
  const [selectedDemAsset, setSelectedDemAsset] = React.useState<ModelAsset | null>(null);
  const [selectedTerrainAsset, setSelectedTerrainAsset] = React.useState<TerrainAsset | null>(null);
  const [pendingProject, setPendingProject] = React.useState<PixelArtProjectSummary | null>(null);
  const [pendingDemAsset, setPendingDemAsset] = React.useState<ModelAsset | null>(null);
  const [job, setJob] = React.useState<LegoDesignJob | null>(null);
  const [demDesign, setDemDesign] = React.useState<DemFinalDesign | null>(null);
  const [projectModalOpen, setProjectModalOpen] = React.useState(false);
  const [demModalOpen, setDemModalOpen] = React.useState(false);
  const [bomModalOpen, setBomModalOpen] = React.useState(false);
  const [pixelPreviewOpen, setPixelPreviewOpen] = React.useState(false);
  const [showSizeLabels, setShowSizeLabels] = React.useState(legoDesignConfig.preview.sizeLabelsDefaultVisible);
  const [previewFullscreen, setPreviewFullscreen] = React.useState(legoDesignConfig.preview.fullscreenDefault);
  const [previewZoom, setPreviewZoom] = React.useState(legoDesignConfig.preview.zoomDefault);
  const [includeSupportBase, setIncludeSupportBase] = React.useState(legoDesignConfig.supportBase.defaultEnabled);
  const [demGenerationStrategy, setDemGenerationStrategy] = React.useState(legoDesignConfig.demGenerationStrategy.default);
  const [heightmapScale, setHeightmapScale] = React.useState<LegoHeightmapScale>({
    horizontalKmPerStud: legoTerrainConfig.scale.defaultHorizontalKmPerStud,
    verticalMetersPerPlate: legoTerrainConfig.scale.defaultVerticalMetersPerPlate,
    aggregation: legoTerrainConfig.heightmap.defaultAggregation,
    minCoverageRatio: legoTerrainConfig.scale.defaultMinCoverageRatio,
  });
  const [loading, setLoading] = React.useState(false);
  const [generating, setGenerating] = React.useState(false);
  const [exporting, setExporting] = React.useState(false);
  const [exportingPlan, setExportingPlan] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const design = job?.result ?? null;
  const activeBom = demDesign?.bom ?? design?.bom ?? null;
  const hasDesign = design !== null || demDesign !== null;

  const loadData = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextMetadata, nextProjects, nextDemAssets] = await Promise.all([
        loadLegoDesignMetadata(),
        loadLegoDesignPixelProjects(page),
        enableDem ? loadModelAssetPage(appConfig.modelAssetsApiUrl, legoDesignConfig.pagination.initialPage, legoDesignConfig.demAssetPageSize) : Promise.resolve(null),
      ]);
      setMetadata(nextMetadata);
      setProjectList(nextProjects);
      setDemAssetPage(nextDemAssets);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : legoDesignConfig.texts.loadFailed);
    } finally {
      setLoading(false);
    }
  }, [enableDem, page]);

  React.useEffect(() => {
    void loadData();
  }, [loadData]);

  const confirmProject = async () => {
    if (!pendingProject) {
      return;
    }
    setError(null);
    setJob(null);
    setDemDesign(null);
    try {
      setSearchParams({}, { replace: true });
      setGenerating(false);
      setSelectedProject(await loadLegoDesignPixelProject(pendingProject.modelId));
      setSelectedDemAsset(null);
      setSelectedTerrainAsset(null);
      setProjectModalOpen(false);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : legoDesignConfig.texts.projectFailed);
    }
  };

  const confirmDemAsset = async () => {
    if (!pendingDemAsset) {
      return;
    }
    setError(null);
    setJob(null);
    setDemDesign(null);
    try {
      const terrainAsset = await loadTerrainModel(
        routeWithParam(
          terrainConfig.modelApiUrl,
          terrainConfig.routePlaceholders.modelId,
          pendingDemAsset.id,
        ),
        terrainConfig.expectedSchema,
        terrainConfig.texts.invalidAsset,
      );
      setSelectedDemAsset(pendingDemAsset);
      setSelectedTerrainAsset(terrainAsset);
      setSelectedProject(null);
      setDemModalOpen(false);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : legoDesignConfig.texts.loadFailed);
    }
  };

  const generateDesign = async () => {
    if (!selectedProject && !selectedTerrainAsset) {
      setError(legoDesignConfig.texts.noSelection);
      return;
    }
    setGenerating(true);
    setError(null);
    setJob(null);
    setDemDesign(null);
    try {
      if (selectedTerrainAsset) {
        const request = createDemFinalDesignRequest(selectedDemAsset!.id, demGenerationStrategy, heightmapScale);
        setDemDesign(await createDemFinalDesign(request));
        setGenerating(false);
        return;
      }
      const createdJob = await createLegoDesignJob(selectedProject!.modelId);
      setJob(createdJob);
      if (createdJob.status === legoDesignConfig.jobStatus.complete) setGenerating(false);
      setSearchParams({ job: createdJob.jobId }, { replace: true });
    } catch (generationError) {
      setError(generationError instanceof Error ? generationError.message : legoDesignConfig.texts.designFailed);
      setGenerating(false);
    }
  };

  React.useEffect(() => {
    if (!activeJobId) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setGenerating(true);
    const poll = async () => {
      try {
        const nextJob = await loadLegoDesignJob(activeJobId);
        if (!active) return;
        setJob(nextJob);
        if (nextJob.status === legoDesignConfig.jobStatus.complete || nextJob.status === legoDesignConfig.jobStatus.failed) {
          setGenerating(false);
          if (nextJob.error) setError(localizeStructuredMessage(nextJob.error));
          return;
        }
        timer = setTimeout(() => void poll(), legoDesignConfig.polling.intervalMs);
      } catch (error) {
        if (active) {
          setGenerating(false);
          setError(error instanceof Error ? error.message : legoDesignConfig.texts.designFailed);
        }
      }
    };
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [activeJobId]);

  const exportDesign = async () => {
    if (!hasDesign) {
      return;
    }
    setExporting(true);
    setError(null);
    try {
      if (demDesign) {
        const exported = await exportDemFinalDesignLdraw(demDesign);
        downloadBlob(exported.blob, exported.fileName);
      } else if (job && job.status === legoDesignConfig.jobStatus.complete && design) {
        const exported = await exportLegoDesign(job.jobId, includeSupportBase);
        downloadBlob(exported.blob, exported.fileName);
      }
    } catch (exportError) {
      setError(exportError instanceof Error ? exportError.message : legoDesignConfig.texts.exportFailed);
    } finally {
      setExporting(false);
    }
  };

  const exportPlan = async () => {
    setExportingPlan(true);
    setError(null);
    try {
      if (demDesign) {
        const exported = await exportDemFinalDesignReport(demDesign);
        downloadBlob(exported.blob, exported.fileName);
        return;
      }
      if (!job || job.status !== legoDesignConfig.jobStatus.complete || !design) {
        return;
      }
      const exported = await exportLegoDesignPlan(job.jobId, includeSupportBase);
      downloadBlob(exported.blob, exported.fileName);
    } catch (exportError) {
      setError(exportError instanceof Error ? exportError.message : legoDesignConfig.texts.exportPlanFailed);
    } finally {
      setExportingPlan(false);
    }
  };

  const downloadBlob = (blob: Blob, fileName: string) => {
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = objectUrl;
    link.download = fileName;
    link.click();
    URL.revokeObjectURL(objectUrl);
  };

  const totalPages = projectList
    ? Math.max(legoDesignConfig.pagination.initialPage, Math.ceil(projectList.total / projectList.pageSize))
    : legoDesignConfig.pagination.initialPage;

  const clampPreviewZoom = (nextZoom: number) => (
    Math.max(
      legoDesignConfig.preview.zoomMinimum,
      Math.min(
        legoDesignConfig.preview.zoomMaximum,
        Number(nextZoom.toFixed(legoDesignConfig.preview.zoomPrecision)),
      ),
    )
  );

  const updateHeightmapScale: React.Dispatch<React.SetStateAction<LegoHeightmapScale>> = (nextScale) => {
    setHeightmapScale(nextScale);
    setJob(null);
    setDemDesign(null);
  };

  const updateDemGenerationStrategy = (nextStrategy: string) => {
    setDemGenerationStrategy(nextStrategy);
    setJob(null);
    setDemDesign(null);
  };

  return (
    <main className={previewFullscreen ? 'lego-design-page lego-design-page-fullscreen' : 'lego-design-page'}>
      <header className="lego-design-header">
        <div>
          <h1>{legoDesignConfig.texts.title}</h1>
          <p>{legoDesignConfig.texts.subtitle}</p>
        </div>
        <div className="lego-design-actions">
          <button onClick={() => void loadData()} type="button">
            <RefreshCw aria-hidden="true" />
            {legoDesignConfig.texts.refresh}
          </button>
          <button onClick={() => setProjectModalOpen(true)} type="button">
            <ImageIcon aria-hidden="true" />
            {legoDesignConfig.texts.choosePixelArt}
          </button>
          {enableDem ? <button onClick={() => setDemModalOpen(true)} type="button">
            <Boxes aria-hidden="true" />
            {legoDesignConfig.texts.chooseDemModel}
          </button> : null}
          <button disabled={generating} onClick={() => void generateDesign()} type="button">
            <Wand2 aria-hidden="true" />
            {generating
              ? legoDesignConfig.texts.generating
              : selectedTerrainAsset
                ? legoDesignConfig.texts.generateDemDesign
                : legoDesignConfig.texts.generate}
          </button>
          {!selectedTerrainAsset ? <label className="lego-design-action-switch">
            <input
              checked={includeSupportBase}
              onChange={(event) => setIncludeSupportBase(event.target.checked)}
              type="checkbox"
            />
            <span>{legoDesignConfig.texts.addSupportBase}</span>
          </label> : null}
          <button
            disabled={!hasDesign || exporting}
            onClick={() => void exportDesign()}
            type="button"
          >
            <Download aria-hidden="true" />
            {exporting ? legoDesignConfig.texts.exporting : legoDesignConfig.texts.exportDesign}
          </button>
          <button
            disabled={!hasDesign || exportingPlan}
            onClick={() => void exportPlan()}
            type="button"
          >
            <FileJson aria-hidden="true" />
            {exportingPlan ? legoDesignConfig.texts.exportingPlan : legoDesignConfig.texts.exportPlan}
          </button>
        </div>
      </header>

      <section className={previewFullscreen ? 'lego-design-layout lego-design-layout-fullscreen' : 'lego-design-layout'}>
        <aside className="lego-design-panel">
          <h2>{legoDesignConfig.texts.sourceProjects}</h2>
          {metadata ? (
            <div className="lego-design-metadata">
              <Metric label={legoDesignConfig.texts.availableColors} value={String(metadata.colors.length)} />
              <Metric label={legoDesignConfig.texts.availableParts} value={String(metadata.parts.length)} />
            </div>
          ) : null}
          {selectedProject ? <SelectedProject project={selectedProject} /> : null}
          {selectedDemAsset && selectedTerrainAsset ? (
            <>
              <SelectedDemModel asset={selectedDemAsset} />
              <DemGenerationStrategyControl
                strategy={demGenerationStrategy}
                setStrategy={updateDemGenerationStrategy}
              />
              <HeightmapScaleControls scale={heightmapScale} setScale={updateHeightmapScale} />
            </>
          ) : null}
          {!selectedProject && !selectedDemAsset ? <div className="asset-empty">{legoDesignConfig.texts.noSelection}</div> : null}
          <button className="lego-design-full-button" disabled={!selectedProject} onClick={() => setPixelPreviewOpen(true)} type="button">
            <ImageIcon aria-hidden="true" />
            {legoDesignConfig.texts.openPixelPreview}
          </button>
          {job ? <ProgressPanel job={job} /> : null}
          {error ? <div className="asset-error">{error}</div> : null}
          {loading ? <div className="asset-loading">{legoDesignConfig.texts.loading}</div> : null}
          {design ? <DesignMetrics design={design} /> : null}
          {demDesign ? <DemDesignMetrics design={demDesign} /> : null}
          {demDesign?.replacementDiagnostics ? <ReplacementDiagnosticsPanel design={demDesign} /> : null}
          <button className="lego-design-full-button" disabled={!hasDesign} onClick={() => setBomModalOpen(true)} type="button">
            <List aria-hidden="true" />
            {legoDesignConfig.texts.openBom}
          </button>
          {design ? <ColorMappings design={design} /> : null}
          {demDesign ? <DemColorMappings design={demDesign} /> : null}
        </aside>

        <section className="lego-design-workspace">
          <div className="lego-design-title">
            <span>
              <Boxes aria-hidden="true" />
              {legoDesignConfig.texts.workspace}
            </span>
            <DesignDisplayControls
              previewFullscreen={previewFullscreen}
              previewZoom={previewZoom}
              showSizeLabels={showSizeLabels}
              setPreviewFullscreen={setPreviewFullscreen}
              setPreviewZoom={setPreviewZoom}
              setShowSizeLabels={setShowSizeLabels}
              clampPreviewZoom={clampPreviewZoom}
            />
          </div>
          <PreviewPanel title={legoDesignConfig.texts.legoPreview}>
            {design && !selectedTerrainAsset ? (
              <LegoPlacementPreview design={design} showSizeLabels={showSizeLabels} zoom={previewZoom} />
            ) : demDesign ? (
              <DemFinalDesignPreview design={demDesign} showSizeLabels={showSizeLabels} zoom={previewZoom} />
            ) : (
              <div>{legoDesignConfig.texts.emptyDesign}</div>
            )}
          </PreviewPanel>
        </section>
      </section>

      {projectModalOpen ? (
        <ProjectPickerModal
          loading={loading}
          page={page}
          pendingProject={pendingProject}
          projectList={projectList}
          setPage={setPage}
          setPendingProject={setPendingProject}
          totalPages={totalPages}
          onCancel={() => setProjectModalOpen(false)}
          onConfirm={() => void confirmProject()}
        />
      ) : null}

      {demModalOpen ? (
        <DemModelPickerModal
          demAssetPage={demAssetPage}
          pendingDemAsset={pendingDemAsset}
          setPendingDemAsset={setPendingDemAsset}
          onCancel={() => setDemModalOpen(false)}
          onConfirm={() => void confirmDemAsset()}
        />
      ) : null}

      {bomModalOpen && activeBom ? (
        <BomModal bom={activeBom} onClose={() => setBomModalOpen(false)} />
      ) : null}

      {pixelPreviewOpen && selectedProject ? (
        <PixelPreviewModal project={selectedProject} onClose={() => setPixelPreviewOpen(false)} />
      ) : null}
    </main>
  );
}

function DesignDisplayControls({
  clampPreviewZoom,
  previewFullscreen,
  previewZoom,
  setPreviewFullscreen,
  setPreviewZoom,
  setShowSizeLabels,
  showSizeLabels,
}: {
  clampPreviewZoom: (nextZoom: number) => number;
  previewFullscreen: boolean;
  previewZoom: number;
  setPreviewFullscreen: React.Dispatch<React.SetStateAction<boolean>>;
  setPreviewZoom: React.Dispatch<React.SetStateAction<number>>;
  setShowSizeLabels: React.Dispatch<React.SetStateAction<boolean>>;
  showSizeLabels: boolean;
}) {
  return (
    <div className="lego-design-display-controls">
      <label className="lego-design-switch-row">
        <span>{legoDesignConfig.texts.sizeLabels}</span>
        <input
          checked={showSizeLabels}
          onChange={(event) => setShowSizeLabels(event.target.checked)}
          type="checkbox"
        />
      </label>
      <div className="lego-design-zoom-control">
        <span>{legoDesignConfig.texts.zoom}</span>
        <div>
          <button
            disabled={previewZoom <= legoDesignConfig.preview.zoomMinimum}
            onClick={() => setPreviewZoom((currentZoom) => clampPreviewZoom(currentZoom - legoDesignConfig.preview.zoomStep))}
            title={legoDesignConfig.texts.zoomOut}
            type="button"
          >
            <ZoomOut aria-hidden="true" />
          </button>
          <strong>{previewZoom.toFixed(legoDesignConfig.preview.zoomPrecision)}{legoDesignConfig.preview.zoomSuffix}</strong>
          <button
            disabled={previewZoom >= legoDesignConfig.preview.zoomMaximum}
            onClick={() => setPreviewZoom((currentZoom) => clampPreviewZoom(currentZoom + legoDesignConfig.preview.zoomStep))}
            title={legoDesignConfig.texts.zoomIn}
            type="button"
          >
            <ZoomIn aria-hidden="true" />
          </button>
        </div>
      </div>
      <button className="lego-design-control-button" onClick={() => setPreviewFullscreen((currentValue) => !currentValue)} type="button">
        {previewFullscreen ? <Minimize2 aria-hidden="true" /> : <Maximize2 aria-hidden="true" />}
        {previewFullscreen ? legoDesignConfig.texts.windowed : legoDesignConfig.texts.fullscreen}
      </button>
    </div>
  );
}

function SelectedProject({ project }: { project: PixelArtProject }) {
  return (
    <div className="lego-design-source">
      <ImageIcon aria-hidden="true" />
      <span>
        <strong>{project.name}</strong>
        <em>{legoDesignConfig.texts.projectId}: {project.modelId}</em>
      </span>
    </div>
  );
}

function SelectedDemModel({ asset }: { asset: ModelAsset }) {
  return (
    <div className="lego-design-source">
      <Boxes aria-hidden="true" />
      <span>
        <strong>{asset.name}</strong>
        <em>{legoDesignConfig.texts.modelId}: {asset.id}</em>
      </span>
    </div>
  );
}

function DemGenerationStrategyControl({
  strategy,
  setStrategy,
}: {
  strategy: string;
  setStrategy: (nextStrategy: string) => void;
}) {
  const selectedOption = legoDesignConfig.demGenerationStrategy.options.find((option) => option.value === strategy);
  return (
    <section className="lego-design-list-section">
      <h3>{legoDesignConfig.texts.demGenerationStrategy}</h3>
      <label className="lego-design-control-field">
        <span>{legoDesignConfig.texts.demGenerationStrategy}</span>
        <select
          onChange={(event) => setStrategy(event.target.value)}
          value={strategy}
        >
          {legoDesignConfig.demGenerationStrategy.options.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
      </label>
      {selectedOption ? <p className="lego-design-strategy-description">{selectedOption.description}</p> : null}
    </section>
  );
}

function HeightmapScaleControls({
  scale,
  setScale,
}: {
  scale: LegoHeightmapScale;
  setScale: React.Dispatch<React.SetStateAction<LegoHeightmapScale>>;
}) {
  return (
    <section className="lego-design-list-section">
      <h3>{legoDesignConfig.texts.heightmapScale}</h3>
      <label className="lego-design-control-field">
        <span>{legoDesignConfig.texts.horizontalKmPerStud}</span>
        <input
          max={legoTerrainConfig.scale.maxHorizontalKmPerStud}
          min={legoTerrainConfig.scale.minHorizontalKmPerStud}
          onChange={(event) =>
            setScale((currentScale) => ({ ...currentScale, horizontalKmPerStud: Number(event.target.value) }))
          }
          step={legoTerrainConfig.scale.horizontalKmStep}
          type="number"
          value={scale.horizontalKmPerStud}
        />
      </label>
      <label className="lego-design-control-field">
        <span>{legoDesignConfig.texts.verticalMetersPerPlate}</span>
        <input
          max={legoTerrainConfig.scale.maxVerticalMetersPerPlate}
          min={legoTerrainConfig.scale.minVerticalMetersPerPlate}
          onChange={(event) =>
            setScale((currentScale) => ({ ...currentScale, verticalMetersPerPlate: Number(event.target.value) }))
          }
          step={legoTerrainConfig.scale.verticalMetersStep}
          type="number"
          value={scale.verticalMetersPerPlate}
        />
      </label>
      <label className="lego-design-control-field">
        <span>{legoTerrainConfig.texts.aggregation}</span>
        <select
          onChange={(event) => setScale((currentScale) => ({ ...currentScale, aggregation: event.target.value }))}
          value={scale.aggregation}
        >
          <option value={legoTerrainConfig.heightmap.aggregation.percentile}>{legoTerrainConfig.texts.percentile}</option>
          <option value={legoTerrainConfig.heightmap.aggregation.mean}>{legoTerrainConfig.texts.mean}</option>
          <option value={legoTerrainConfig.heightmap.aggregation.max}>{legoTerrainConfig.texts.max}</option>
        </select>
      </label>
      <label className="lego-design-control-field">
        <span>{legoDesignConfig.texts.coverage}</span>
        <input
          max={legoTerrainConfig.scale.maxCoverageRatio}
          min={legoTerrainConfig.scale.minCoverageRatio}
          onChange={(event) =>
            setScale((currentScale) => ({ ...currentScale, minCoverageRatio: Number(event.target.value) }))
          }
          step={legoTerrainConfig.scale.coverageStep}
          type="number"
          value={scale.minCoverageRatio}
        />
      </label>
    </section>
  );
}

function DemFinalDesignPreview({
  design,
  showSizeLabels,
  zoom,
}: {
  design: DemFinalDesign;
  showSizeLabels: boolean;
  zoom: number;
}) {
  const cellSize = Math.max(
    legoDesignConfig.preview.minimumCellSizePixels,
    Math.min(legoDesignConfig.preview.maximumCellSizePixels, legoDesignConfig.preview.cellSizePixels),
  );
  const boardWidth = design.surfacePlan.widthStud * cellSize;
  const boardHeight = design.surfacePlan.depthStud * cellSize;
  return (
    <div className="lego-design-board-shell" style={{ width: boardWidth * zoom, height: boardHeight * zoom }}>
      <div
        className="lego-design-board"
        style={{
          width: boardWidth,
          height: boardHeight,
          backgroundSize: `${cellSize}px ${cellSize}px`,
          transform: `scale(${zoom})`,
        }}
      >
        {design.surfacePlacements.map((placement, index) => (
          <DemPlacementBlock
            cellSize={cellSize}
            index={index}
            key={`${placement.partId}-${placement.xStud}-${placement.zStud}-${index}`}
            placement={placement}
            showSizeLabels={showSizeLabels}
          />
        ))}
      </div>
    </div>
  );
}

function DemPlacementBlock({
  cellSize,
  index,
  placement,
  showSizeLabels,
}: {
  cellSize: number;
  index: number;
  placement: DemSurfacePlacement;
  showSizeLabels: boolean;
}) {
  return (
    <div
      className="lego-design-placement"
      style={{
        left: placement.xStud * cellSize,
        top: placement.zStud * cellSize,
        width: placement.widthStud * cellSize,
        height: placement.depthStud * cellSize,
        backgroundColor: placement.colorRgb,
        zIndex: index + legoDesignConfig.pagination.pageStep,
      }}
      title={`${placement.partId} ${placement.widthStud}x${placement.depthStud} @ ${placement.basePlate}`}
    >
      {showSizeLabels ? <span>{placement.widthStud}x{placement.depthStud}</span> : null}
    </div>
  );
}

function ProgressPanel({ job }: { job: LegoDesignJob }) {
  return (
    <div className="lego-design-progress">
      <span>{localizeStructuredMessage(job.progress, 'tasks')}</span>
      <div>
        <div style={{ width: `${job.progress.percent}%` }} />
      </div>
    </div>
  );
}

function ProjectPickerModal({
  loading,
  page,
  pendingProject,
  projectList,
  setPage,
  setPendingProject,
  totalPages,
  onCancel,
  onConfirm,
}: {
  loading: boolean;
  page: number;
  pendingProject: PixelArtProjectSummary | null;
  projectList: PixelArtProjectList | null;
  setPage: React.Dispatch<React.SetStateAction<number>>;
  setPendingProject: React.Dispatch<React.SetStateAction<PixelArtProjectSummary | null>>;
  totalPages: number;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="lego-design-modal-backdrop">
      <section className="lego-design-modal lego-design-project-modal">
        <header>
          <h2>{legoDesignConfig.texts.choosePixelArt}</h2>
          <div>
            <button onClick={onCancel} type="button">{legoDesignConfig.texts.cancel}</button>
            <button disabled={!pendingProject} onClick={onConfirm} type="button">{legoDesignConfig.texts.confirm}</button>
          </div>
        </header>
        {loading ? <div className="asset-loading">{legoDesignConfig.texts.loading}</div> : null}
        {projectList && projectList.items.length === legoDesignConfig.emptyCount ? (
          <div className="asset-empty">{legoDesignConfig.texts.emptyProjects}</div>
        ) : null}
        <div className="lego-design-project-grid-modal">
          {projectList?.items.map((project) => (
            <button
              className={
                pendingProject?.modelId === project.modelId
                  ? 'lego-design-project lego-design-project-active'
                  : 'lego-design-project'
              }
              key={project.modelId}
              onClick={() => setPendingProject(project)}
              type="button"
            >
              {project.previewImage ? <img alt={project.name} src={project.previewImage} /> : <span>{legoDesignConfig.texts.loading}</span>}
              <span>
                <strong>{project.name}</strong>
                <em>{project.gridWidth} x {project.gridHeight}</em>
              </span>
              <small>{pendingProject?.modelId === project.modelId ? legoDesignConfig.texts.selected : legoDesignConfig.texts.select}</small>
            </button>
          ))}
        </div>
        <div className="asset-pagination">
          <button
            disabled={page <= legoDesignConfig.pagination.initialPage}
            onClick={() => setPage((currentPage) => currentPage - legoDesignConfig.pagination.pageStep)}
            type="button"
          >
            <ChevronLeft aria-hidden="true" />
            {page - legoDesignConfig.pagination.pageStep}
          </button>
          <span>{page} / {totalPages}</span>
          <button
            disabled={page >= totalPages}
            onClick={() => setPage((currentPage) => currentPage + legoDesignConfig.pagination.pageStep)}
            type="button"
          >
            {page + legoDesignConfig.pagination.pageStep}
            <ChevronRight aria-hidden="true" />
          </button>
        </div>
      </section>
    </div>
  );
}

function DemModelPickerModal({
  demAssetPage,
  pendingDemAsset,
  setPendingDemAsset,
  onCancel,
  onConfirm,
}: {
  demAssetPage: ModelAssetPage | null;
  pendingDemAsset: ModelAsset | null;
  setPendingDemAsset: React.Dispatch<React.SetStateAction<ModelAsset | null>>;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const demAssets = demAssetPage?.items.filter((asset) => asset.modelType === appConfig.modelTypes.dem) ?? [];
  return (
    <div className="lego-design-modal-backdrop">
      <section className="lego-design-modal lego-design-project-modal">
        <header>
          <h2>{legoDesignConfig.texts.chooseDemModel}</h2>
          <div>
            <button onClick={onCancel} type="button">{legoDesignConfig.texts.cancel}</button>
            <button disabled={!pendingDemAsset} onClick={onConfirm} type="button">{legoDesignConfig.texts.confirm}</button>
          </div>
        </header>
        {demAssets.length === legoDesignConfig.emptyCount ? (
          <div className="asset-empty">{appConfig.texts.emptyModels}</div>
        ) : null}
        <div className="lego-design-project-grid-modal">
          {demAssets.map((asset) => (
            <button
              className={
                pendingDemAsset?.id === asset.id
                  ? 'lego-design-project lego-design-project-active'
                  : 'lego-design-project'
              }
              key={asset.id}
              onClick={() => setPendingDemAsset(asset)}
              type="button"
            >
              <Boxes aria-hidden="true" />
              <span>
                <strong>{asset.name}</strong>
                <em>{asset.columns && asset.rows ? `${asset.columns} x ${asset.rows}` : asset.sourceName}</em>
              </span>
              <small>{pendingDemAsset?.id === asset.id ? legoDesignConfig.texts.selected : legoDesignConfig.texts.select}</small>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

function PixelPreviewModal({ project, onClose }: { project: PixelArtProject; onClose: () => void }) {
  const [position, setPosition] = React.useState({
    x: legoDesignConfig.draggablePreview.initialX,
    y: legoDesignConfig.draggablePreview.initialY,
  });
  const dragStart = React.useRef<{ pointerX: number; pointerY: number; x: number; y: number } | null>(null);

  const movePreview = (event: React.PointerEvent) => {
    if (!dragStart.current) {
      return;
    }
    setPosition({
      x: dragStart.current.x + event.clientX - dragStart.current.pointerX,
      y: dragStart.current.y + event.clientY - dragStart.current.pointerY,
    });
  };

  return (
    <section
      className="lego-design-floating-preview"
      style={{ left: position.x, top: position.y }}
      onPointerMove={movePreview}
      onPointerUp={() => {
        dragStart.current = null;
      }}
    >
      <header
        onPointerDown={(event) => {
          dragStart.current = {
            pointerX: event.clientX,
            pointerY: event.clientY,
            x: position.x,
            y: position.y,
          };
        }}
      >
        <h2>{legoDesignConfig.texts.sourcePreview}</h2>
        <button onClick={onClose} type="button">
          <X aria-hidden="true" />
          {legoDesignConfig.texts.close}
        </button>
      </header>
      <img alt={project.name} src={project.previewImage} />
    </section>
  );
}

function BomModal({ bom, onClose }: { bom: Array<LegoBomItem | DemFinalBomItem>; onClose: () => void }) {
  return (
    <div className="lego-design-modal-backdrop">
      <section className="lego-design-modal">
        <header>
          <h2>{legoDesignConfig.texts.bom}</h2>
          <div>
            <button onClick={onClose} type="button">{legoDesignConfig.texts.confirm}</button>
          </div>
        </header>
        <BomList bom={bom} />
      </section>
    </div>
  );
}

function PreviewPanel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <article className="lego-design-preview-panel">
      <h2>{title}</h2>
      <div>{children}</div>
    </article>
  );
}

function LegoPlacementPreview({
  design,
  showSizeLabels,
  zoom,
}: {
  design: LegoDesignResult;
  showSizeLabels: boolean;
  zoom: number;
}) {
  const cellSize = Math.max(
    legoDesignConfig.preview.minimumCellSizePixels,
    Math.min(
      legoDesignConfig.preview.maximumCellSizePixels,
      legoDesignConfig.preview.cellSizePixels,
    ),
  );
  const boardWidth = design.width * cellSize;
  const boardHeight = design.height * cellSize;
  return (
    <div className="lego-design-board-shell" style={{ width: boardWidth * zoom, height: boardHeight * zoom }}>
      <div
        className="lego-design-board"
        style={{
          width: boardWidth,
          height: boardHeight,
          backgroundSize: `${cellSize}px ${cellSize}px`,
          transform: `scale(${zoom})`,
        }}
      >
        {design.placements.map((placement, index) => (
          <PlacementBlock
            cellSize={cellSize}
            index={index}
            key={`${placement.partId}-${placement.x}-${placement.y}-${index}`}
            placement={placement}
            showSizeLabels={showSizeLabels}
          />
        ))}
      </div>
    </div>
  );
}

function PlacementBlock({
  cellSize,
  index,
  placement,
  showSizeLabels,
}: {
  cellSize: number;
  index: number;
  placement: LegoPlacement;
  showSizeLabels: boolean;
}) {
  return (
    <div
      className="lego-design-placement"
      style={{
        left: placement.x * cellSize,
        top: placement.y * cellSize,
        width: placement.width * cellSize,
        height: placement.height * cellSize,
        backgroundColor: placement.colorRgb,
        zIndex: index + legoDesignConfig.pagination.pageStep,
      }}
      title={`${placement.partId} ${placement.width}x${placement.height}`}
    >
      {showSizeLabels ? <span>{placement.width}x{placement.height}</span> : null}
    </div>
  );
}

function DesignMetrics({ design }: { design: LegoDesignResult }) {
  return (
    <div className="lego-design-metadata">
      <Metric label={legoDesignConfig.texts.grid} value={`${design.width} x ${design.height}`} />
      <Metric label={legoDesignConfig.texts.modelDimensions} value={modelDimensionStudText(design)} />
      <Metric label={legoDesignConfig.texts.physicalDimensions} value={modelDimensionCentimeterText(design)} />
      <Metric label={legoDesignConfig.texts.parts} value={String(design.placements.length)} />
      <Metric label={legoDesignConfig.texts.uniqueParts} value={String(design.bom.length)} />
      <Metric label={legoDesignConfig.texts.colors} value={String(design.colorMappings.length)} />
    </div>
  );
}

function DemDesignMetrics({ design }: { design: DemFinalDesign }) {
  const maximumHeightPlate = Math.max(
    legoDesignConfig.emptyCount,
    ...design.baseStructure.placements.map((placement) => placement.basePlate + placement.heightPlate),
    ...design.surfacePlacements.map((placement) => placement.basePlate + placement.heightPlate),
  );
  const colorCount = new Set(design.bom.map((item) => item.colorId)).size;
  const modelDimensions = [
    `${design.surfacePlan.widthStud} ${legoDesignConfig.dimensions.studUnit}`,
    `${design.surfacePlan.depthStud} ${legoDesignConfig.dimensions.studUnit}`,
    `${formatDimension(maximumHeightPlate)} ${legoDesignConfig.dimensions.plateUnit}`,
  ].join(legoDesignConfig.dimensions.separator);
  return (
    <div className="lego-design-metadata">
      <Metric
        label={legoDesignConfig.texts.grid}
        value={`${design.surfacePlan.widthStud} x ${design.surfacePlan.depthStud}`}
      />
      <Metric label={legoDesignConfig.texts.modelDimensions} value={modelDimensions} />
      <Metric label={legoDesignConfig.texts.parts} value={String(design.validation.totalPlacementCount)} />
      <Metric label={legoDesignConfig.texts.uniqueParts} value={String(design.bom.length)} />
      <Metric label={legoDesignConfig.texts.colors} value={String(colorCount)} />
    </div>
  );
}

function ReplacementDiagnosticsPanel({ design }: { design: DemFinalDesign }) {
  const diagnostics = design.replacementDiagnostics;
  if (!diagnostics) {
    return null;
  }
  return (
    <section className="lego-design-list-section">
      <h3>{legoDesignConfig.texts.replacementDiagnostics}</h3>
      <div className="lego-design-metadata">
        <Metric
          label={legoDesignConfig.texts.replacementCoverage}
          value={`${diagnostics.solvedSlopeEdgeCount} / ${diagnostics.targetSlopeEdgeCount}`}
        />
        <Metric
          label={legoDesignConfig.texts.replacementMissingColors}
          value={String(diagnostics.missingColorRequirementTypeCount)}
        />
        <Metric
          label={legoDesignConfig.texts.replacementColorSubstitutions}
          value={String(diagnostics.colorSubstitutionCount)}
        />
      </div>
      {diagnostics.phaseSummaries.length ? (
        <div className="lego-design-bom-list">
          <h4>{legoDesignConfig.texts.replacementPhases}</h4>
          {diagnostics.phaseSummaries.map((phase) => (
            <article className="lego-design-bom-row" key={phase.connectionClass}>
              <div>
                <strong>{phase.connectionClass}</strong>
                <em>
                  {legoDesignConfig.texts.replacementPhaseIncrement} {phase.incrementalPlacementCount}
                  {' / '}
                  {phase.solvedSlopeEdgeCount} / {phase.targetSlopeEdgeCount}
                </em>
              </div>
              <b>{phase.placementCount}</b>
            </article>
          ))}
        </div>
      ) : null}
      {diagnostics.missingColorSummary.length ? (
        <div className="lego-design-bom-list">
          {diagnostics.missingColorSummary.map((item) => (
            <article
              className="lego-design-bom-row"
              key={`${item.targetColor}-${item.partId}-${item.widthStud}-${item.depthStud}-${item.slopeDirections.join('-')}`}
            >
              <span style={{ backgroundColor: item.targetColor }} />
              <div>
                <strong>{item.partId}</strong>
                <em>{item.widthStud} x {item.depthStud} / {item.slopeDirections.join(', ')}</em>
                <em>
                  {legoDesignConfig.texts.replacementMissingReason}: {item.reason}
                  {item.nearestColorDistance !== undefined && item.maximumSquaredDistance !== undefined
                    ? ` / ${legoDesignConfig.texts.replacementNearestColorDistance}: ${item.nearestColorDistance} > ${item.maximumSquaredDistance}`
                    : ''}
                </em>
              </div>
              <b>{item.occurrenceCount}</b>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function modelDimensionStudText(design: LegoDesignResult): string {
  const dimensions = design.modelDimensions;
  return [
    `${dimensions.lengthStud} ${legoDesignConfig.dimensions.studUnit}`,
    `${dimensions.widthStud} ${legoDesignConfig.dimensions.studUnit}`,
    `${dimensions.heightPlate} ${legoDesignConfig.dimensions.plateUnit}`,
  ].join(legoDesignConfig.dimensions.separator);
}

function modelDimensionCentimeterText(design: LegoDesignResult): string {
  const dimensions = design.modelDimensions;
  return [
    `${formatDimension(dimensions.lengthCm)} ${legoDesignConfig.dimensions.centimeterUnit}`,
    `${formatDimension(dimensions.widthCm)} ${legoDesignConfig.dimensions.centimeterUnit}`,
    `${formatDimension(dimensions.heightCm)} ${legoDesignConfig.dimensions.centimeterUnit}`,
  ].join(legoDesignConfig.dimensions.separator);
}

function formatDimension(value: number): string {
  return value.toFixed(legoDesignConfig.dimensions.precision);
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="lego-design-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ColorMappings({ design }: { design: LegoDesignResult }) {
  return (
    <section className="lego-design-list-section">
      <div className="lego-design-color-list">
        {design.colorMappings.map((mapping) => (
          <div className="lego-design-color-row" key={mapping.sourceRgb}>
            <span style={{ backgroundColor: mapping.sourceRgb }} />
            <span style={{ backgroundColor: mapping.colorRgb }} />
            <strong>{mapping.colorName}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function DemColorMappings({ design }: { design: DemFinalDesign }) {
  const colors = Array.from(
    new Map(design.bom.map((item) => [item.colorId, item])).values(),
  );
  return (
    <section className="lego-design-list-section">
      <div className="lego-design-color-list">
        {colors.map((item) => (
          <div className="lego-design-color-row" key={item.colorId}>
            <span style={{ backgroundColor: item.colorRgb }} />
            <strong>{item.colorName}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function BomList({ bom }: { bom: Array<LegoBomItem | DemFinalBomItem> }) {
  return (
    <section className="lego-design-list-section">
      <div className="lego-design-bom-list">
        {bom.map((item) => (
          <article className="lego-design-bom-row" key={bomItemKey(item)}>
            <span style={{ backgroundColor: item.colorRgb }} />
            <div>
              <strong>{item.partId}</strong>
              <em>{item.colorName} · {bomItemDimensions(item)}</em>
            </div>
            <b>{item.quantity}</b>
          </article>
        ))}
      </div>
    </section>
  );
}

function bomItemKey(item: LegoBomItem | DemFinalBomItem): string {
  return 'key' in item ? item.key : `${item.partId}-${item.colorId}-${item.role}`;
}

function bomItemDimensions(item: LegoBomItem | DemFinalBomItem): string {
  return 'width' in item
    ? `${item.width} x ${item.height}`
    : `${item.widthStud} x ${item.depthStud} x ${formatDimension(item.heightPlate)}`;
}
