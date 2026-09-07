import { useSearchParams } from 'react-router-dom';
import { waitForPixelProject } from './pixelArtApi';
import React from 'react';
import {
  Check,
  Grid3X3,
  Image as ImageIcon,
  Move,
  Palette,
  Redo2,
  Save,
  SlidersHorizontal,
  Undo2,
  Upload,
} from 'lucide-react';
import {
  submitPixelArtProject,
  updatePixelArtProjectPixels,
  type PixelArtProject,
  type PixelArtPreprocessing,
  type PixelArtSettings,
  type PixelCell,
  type PixelPaletteColor,
  type PixelTaskSnapshot,
  type PixelWriteAccepted,
} from './pixelArtApi';
import pixelArtConfig from './pixelArtConfig';

type SourceImage = {
  file: File;
  objectUrl: string;
  width: number;
  height: number;
};

type AlgorithmConfig = (typeof pixelArtConfig.algorithms.options)[number];

type CropRatio = {
  label: string;
  width: number;
  height: number;
};

type CropBox = {
  x: number;
  y: number;
  width: number;
  height: number;
};

type CanvasView = {
  zoom: number;
  offsetX: number;
  offsetY: number;
};

type GridDisplayMetrics = {
  cellWidth: number;
  cellHeight: number;
  width: number;
  height: number;
};

type GridTransform = GridDisplayMetrics & {
  originX: number;
  originY: number;
  scale: number;
};

type SideLayoutStats = {
  bricks: number;
  plates: number;
};

type ImageElementState = {
  element: HTMLImageElement | null;
  source: string | null;
};

type CropDragState = {
  mode: 'draw' | 'move' | 'pan';
  startCanvasX: number;
  startCanvasY: number;
  startImageX: number;
  startImageY: number;
  startCrop: CropBox;
  startView: CanvasView;
};

type PixelDragState = {
  mode: 'select' | 'pan';
  startX: number;
  startY: number;
  startCellX: number;
  startCellY: number;
  startView: CanvasView;
};

type SourceDragState = {
  mode: 'sample' | 'pan';
  startX: number;
  startY: number;
  startView: CanvasView;
};

/** 编排照片裁剪、预览和持久任务；页面卸载仅停止等待，不删除已提交任务。 */
export function PixelArtPage() {
  const pageRequests = React.useRef<AbortController | null>(null);
  React.useEffect(() => {
    pageRequests.current = new AbortController();
    return () => { pageRequests.current?.abort(); };
  }, []);
  const [searchParams, setSearchParams] = useSearchParams();
  const resumeProjectId = searchParams.get('project');
  const acceptedTaskRef = React.useRef<PixelWriteAccepted | null>(null);
  const [sourceImage, setSourceImage] = React.useState<SourceImage | null>(null);
  const [sourceElement, setSourceElement] = React.useState<ImageElementState>({
    element: null,
    source: null,
  });
  const [projectName, setProjectName] = React.useState(pixelArtConfig.defaultProjectName);
  const [activeStep, setActiveStep] = React.useState(pixelArtConfig.workflow.initialStep);
  const [selectedRatio, setSelectedRatio] = React.useState<CropRatio>(pixelArtConfig.ratios[0]);
  const [customRatio, setCustomRatio] = React.useState<CropRatio>({
    label: pixelArtConfig.texts.customRatio,
    width: pixelArtConfig.crop.customRatioDefaultWidth,
    height: pixelArtConfig.crop.customRatioDefaultHeight,
  });
  const [crop, setCrop] = React.useState<CropBox>({
    x: pixelArtConfig.crop.defaultX,
    y: pixelArtConfig.crop.defaultY,
    width: pixelArtConfig.grid.defaultWidth,
    height: linkedHeight(pixelArtConfig.grid.defaultWidth, pixelArtConfig.ratios[0]),
  });
  const [gridWidth, setGridWidth] = React.useState(pixelArtConfig.grid.defaultWidth);
  const [gridHeight, setGridHeight] = React.useState(linkedHeight(pixelArtConfig.grid.defaultWidth, pixelArtConfig.ratios[0]));
  const [colorCount, setColorCount] = React.useState(pixelArtConfig.color.defaultCount);
  const [selectedAlgorithm, setSelectedAlgorithm] = React.useState(pixelArtConfig.algorithms.default);
  const [preprocessing, setPreprocessing] = React.useState<PixelArtPreprocessing>({
    brightness: pixelArtConfig.preprocessing.brightness.default,
    contrast: pixelArtConfig.preprocessing.contrast.default,
    saturation: pixelArtConfig.preprocessing.saturation.default,
    sharpness: pixelArtConfig.preprocessing.sharpness.default,
    localContrast: pixelArtConfig.preprocessing.localContrast.default,
    preserveLightDetails: pixelArtConfig.preprocessing.preserveLightDetails,
  });
  const [cropView, setCropView] = React.useState<CanvasView>(initialCanvasView());
  const [sourceView, setSourceView] = React.useState<CanvasView>(initialCanvasView());
  const [pixelView, setPixelView] = React.useState<CanvasView>(initialCanvasView());
  const [project, setProject] = React.useState<PixelArtProject | null>(null);
  const [undoHistory, setUndoHistory] = React.useState<PixelArtProject[]>([]);
  const [redoHistory, setRedoHistory] = React.useState<PixelArtProject[]>([]);
  const [selectedCells, setSelectedCells] = React.useState<Set<string>>(new Set());
  const [pixelTool, setPixelTool] = React.useState<'select' | 'pan'>('select');
  const [pickFromSource, setPickFromSource] = React.useState(false);
  const [sampledColor, setSampledColor] = React.useState<string | null>(null);
  const [isGenerating, setIsGenerating] = React.useState(false);
  const [isSavingEdits, setIsSavingEdits] = React.useState(false);
  const [message, setMessage] = React.useState<string | null>(null);
  const [taskProgress, setTaskProgress] = React.useState<PixelTaskSnapshot | null>(null);

  React.useEffect(() => {
    return () => {
      if (sourceImage) {
        URL.revokeObjectURL(sourceImage.objectUrl);
      }
    };
  }, [sourceImage]);

  const selectImage = async (file: File) => {
    const imageInfo = await loadImageInfo(file);
    if (sourceImage) {
      URL.revokeObjectURL(sourceImage.objectUrl);
    }
    const centeredCrop = centeredRatioCrop(imageInfo, selectedRatio);
    setSourceImage(imageInfo);
    setSourceElement({ element: null, source: null });
    setCrop(centeredCrop);
    setCropView(initialCanvasView());
    setSourceView(initialCanvasView());
    setPixelView(initialCanvasView());
    setProject(null);
    setUndoHistory([]);
    setRedoHistory([]);
    setSelectedCells(new Set());
    setSampledColor(null);
    setActiveStep(pixelArtConfig.workflow.uploadStep);
    setMessage(null);
  };

  const changeRatio = (ratio: CropRatio) => {
    setSelectedRatio(ratio);
    setGridHeight(linkedHeight(gridWidth, ratio));
    if (sourceImage) {
      setCrop(centeredRatioCrop(sourceImage, ratio));
    }
    setProject(null);
    setUndoHistory([]);
    setRedoHistory([]);
    setSelectedCells(new Set());
  };

  const updateCustomRatioWidth = (width: number) => {
    const ratio = {
      ...customRatio,
      width: clamp(width, pixelArtConfig.crop.customRatioMinimum, pixelArtConfig.crop.customRatioMaximum),
    };
    setCustomRatio(ratio);
    changeRatio(ratio);
  };

  const updateCustomRatioHeight = (height: number) => {
    const ratio = {
      ...customRatio,
      height: clamp(height, pixelArtConfig.crop.customRatioMinimum, pixelArtConfig.crop.customRatioMaximum),
    };
    setCustomRatio(ratio);
    changeRatio(ratio);
  };

  const updateGridWidth = (width: number) => {
    const dimensions = linkedDimensionsFromWidth(width, selectedRatio);
    setGridWidth(dimensions.width);
    setGridHeight(dimensions.height);
  };

  const updateGridHeight = (height: number) => {
    const dimensions = linkedDimensionsFromHeight(height, selectedRatio);
    setGridWidth(dimensions.width);
    setGridHeight(dimensions.height);
  };

  const updatePreprocessing = (key: keyof PixelArtPreprocessing, value: number | boolean) => {
    setPreprocessing((currentSettings) => ({
      ...currentSettings,
      [key]: value,
    }));
  };

  const generateProject = async () => {
    if (!sourceImage || !projectName.trim()) {
      return;
    }
    setIsGenerating(true);
    setTaskProgress({ taskId: '', status: 'uploading', percent: null });
    setMessage(null);
    try {
      const settings: PixelArtSettings = {
        algorithm: selectedAlgorithm,
        gridWidth,
        gridHeight,
        colorCount,
        crop: roundedCrop(crop),
        preprocessing,
      };
      const accepted = await submitPixelArtProject(projectName.trim(), sourceImage.file, settings, pageRequests.current?.signal);
      acceptedTaskRef.current = accepted;
      setTaskProgress({ taskId: accepted.taskId, status: 'queued', percent: null });
      setSearchParams({ project: accepted.modelId }, { replace: true });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : pixelArtConfig.texts.saveFailed);
      setIsGenerating(false);
      setTaskProgress(null);
    }
  };

  const applyColorToSelectedCells = (rgb: string) => {
    if (!project || selectedCells.size === pixelArtConfig.emptyFileCount) {
      return;
    }
    setUndoHistory((currentHistory) => limitedHistory([...currentHistory, cloneProject(project)]));
    setRedoHistory([]);
    const updatedPixels = project.pixels.map((pixel) => {
      if (!selectedCells.has(cellKey(pixel.x, pixel.y))) {
        return pixel;
      }
      return {
        ...pixel,
        rgb,
        colorIndex: colorIndexForRgb(project.palette, rgb),
      };
    });
    setProject({
      ...project,
      pixels: updatedPixels,
      palette: paletteFromPixels(updatedPixels),
    });
  };

  const undoEdit = () => {
    if (!project || undoHistory.length === pixelArtConfig.emptyFileCount) {
      return;
    }
    const previousProject = undoHistory[undoHistory.length - pixelArtConfig.workflow.initialStep];
    setUndoHistory((currentHistory) => currentHistory.slice(pixelArtConfig.emptyFileCount, currentHistory.length - pixelArtConfig.workflow.initialStep));
    setRedoHistory((currentHistory) => limitedHistory([...currentHistory, cloneProject(project)]));
    // 撤销只恢复像素内容，保存并发基线仍使用最近一次已提交修订。
    setProject({ ...previousProject, revisionId: project.revisionId });
  };

  const redoEdit = () => {
    if (!project || redoHistory.length === pixelArtConfig.emptyFileCount) {
      return;
    }
    const nextProject = redoHistory[redoHistory.length - pixelArtConfig.workflow.initialStep];
    setRedoHistory((currentHistory) => currentHistory.slice(pixelArtConfig.emptyFileCount, currentHistory.length - pixelArtConfig.workflow.initialStep));
    setUndoHistory((currentHistory) => limitedHistory([...currentHistory, cloneProject(project)]));
    setProject({ ...nextProject, revisionId: project.revisionId });
  };

  const saveEditedProject = async () => {
    if (!project) {
      return;
    }
    setIsSavingEdits(true);
    setMessage(null);
    try {
      const savedProject = await updatePixelArtProjectPixels(project, pageRequests.current?.signal);
      setProject(savedProject);
      setMessage(`${pixelArtConfig.texts.editsSaved}: ${savedProject.name}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : pixelArtConfig.texts.saveFailed);
    } finally {
      setIsSavingEdits(false);
    }
  };

  React.useEffect(() => {
    if (!resumeProjectId) return;
    let active = true;
    const controller = new AbortController();
    const accepted = acceptedTaskRef.current?.modelId === resumeProjectId ? acceptedTaskRef.current : null;
    setIsGenerating(true);
    setActiveStep(pixelArtConfig.workflow.gridStep);
    if (!accepted) setTaskProgress({ taskId: '', status: 'queued', percent: null });
    void waitForPixelProject(resumeProjectId, controller.signal, accepted?.taskId, (progress) => {
      if (active) setTaskProgress(progress);
    }).then((saved) => {
      if (!active) return;
      acceptedTaskRef.current = null;
      setProject(saved);
      setGridWidth(saved.gridWidth);
      setGridHeight(saved.gridHeight);
      setActiveStep(pixelArtConfig.workflow.editStep);
      setTaskProgress((current) => ({ taskId: current?.taskId ?? accepted?.taskId ?? '', status: 'succeeded', percent: 100 }));
      setMessage(`${pixelArtConfig.texts.saved}: ${saved.name}`);
    }).catch((error: Error) => {
      if (!active) return;
      setTaskProgress((current) => ({ taskId: current?.taskId ?? '', status: 'failed', percent: 100 }));
      setMessage(error.message);
    })
      .finally(() => { if (active) setIsGenerating(false); });
    return () => { active = false; controller.abort(); };
  }, [resumeProjectId]);

  const totalCells = gridWidth * gridHeight;
  const candidateColors = sampledColor
    ? [{ colorIndex: pixelArtConfig.color.sampleColorIndex, rgb: sampledColor, count: selectedCells.size }, ...project?.palette ?? []]
    : project?.palette ?? [];

  return (
    <main className="pixel-art-page">
      <header className="pixel-art-header">
        <div>
          <h1>{pixelArtConfig.texts.title}</h1>
          <p>{pixelArtConfig.texts.subtitle}</p>
        </div>
        <label htmlFor={pixelArtConfig.fileInputId}>
          <Upload aria-hidden="true" />
          {pixelArtConfig.texts.uploadImage}
        </label>
        <input
          accept={pixelArtConfig.fileAccept}
          id={pixelArtConfig.fileInputId}
          onChange={(event) => {
            const files = Array.from(event.target.files ?? []);
            event.target.value = '';
            if (files.length > pixelArtConfig.emptyFileCount) {
              void selectImage(files[pixelArtConfig.emptyFileCount]);
            }
          }}
          type="file"
        />
      </header>

      <section className="pixel-art-steps">
        <StepBadge active={activeStep === pixelArtConfig.workflow.uploadStep} label={pixelArtConfig.texts.stepUpload} />
        <StepBadge active={activeStep === pixelArtConfig.workflow.preprocessingStep} label={pixelArtConfig.texts.stepPreprocessing} />
        <StepBadge active={activeStep === pixelArtConfig.workflow.gridStep} label={pixelArtConfig.texts.stepGrid} />
        <StepBadge active={activeStep === pixelArtConfig.workflow.editStep} label={pixelArtConfig.texts.stepEdit} />
      </section>

      {taskProgress ? <PixelTaskProgressView progress={taskProgress} /> : null}

      {activeStep === pixelArtConfig.workflow.uploadStep ? (
        <section className="pixel-art-stage-layout">
          <aside className="pixel-art-panel">
            <h2>{pixelArtConfig.texts.sourceImage}</h2>
            {sourceImage ? (
              <div className="pixel-art-source">
                <strong>{sourceImage.file.name}</strong>
                <span>
                  {pixelArtConfig.texts.imageSize}: {sourceImage.width} x {sourceImage.height}
                </span>
              </div>
            ) : (
              <div className="pixel-art-empty">{pixelArtConfig.texts.emptyImage}</div>
            )}

            <label className="pixel-art-control">
              <span>{pixelArtConfig.texts.projectName}</span>
              <input
                onChange={(event) => setProjectName(event.target.value)}
                placeholder={pixelArtConfig.texts.projectNamePlaceholder}
                type="text"
                value={projectName}
              />
            </label>

            <h2>{pixelArtConfig.texts.ratio}</h2>
            <div className="pixel-art-ratio-grid">
              {pixelArtConfig.ratios.map((ratio) => (
                <button
                  className={ratio.label === selectedRatio.label ? 'pixel-art-ratio-active' : ''}
                  key={ratio.label}
                  onClick={() => changeRatio(ratio)}
                  type="button"
                >
                  {ratio.label}
                </button>
              ))}
            </div>
            <div className="pixel-art-custom-ratio">
              <NumberInput
                label={pixelArtConfig.texts.customRatioWidth}
                max={pixelArtConfig.crop.customRatioMaximum}
                min={pixelArtConfig.crop.customRatioMinimum}
                onChange={updateCustomRatioWidth}
                step={pixelArtConfig.crop.customRatioStep}
                value={customRatio.width}
              />
              <NumberInput
                label={pixelArtConfig.texts.customRatioHeight}
                max={pixelArtConfig.crop.customRatioMaximum}
                min={pixelArtConfig.crop.customRatioMinimum}
                onChange={updateCustomRatioHeight}
                step={pixelArtConfig.crop.customRatioStep}
                value={customRatio.height}
              />
            </div>

            <button
              className="pixel-art-save"
              disabled={!sourceImage}
              onClick={() => setActiveStep(pixelArtConfig.workflow.preprocessingStep)}
              type="button"
            >
              <Check aria-hidden="true" />
              {pixelArtConfig.texts.confirmCrop}
            </button>
          </aside>

          <section className="pixel-art-workspace">
            <div className="pixel-art-title">
              <ImageIcon aria-hidden="true" />
              <span>{pixelArtConfig.texts.cropWorkspace}</span>
            </div>
            {sourceImage ? (
              <CropCanvas
                crop={crop}
                image={sourceImage}
                imageElement={sourceElement}
                onCropChange={setCrop}
                onImageElementChange={setSourceElement}
                onViewChange={setCropView}
                ratio={selectedRatio}
                view={cropView}
              />
            ) : (
              <div className="pixel-art-canvas-empty">{pixelArtConfig.texts.emptyImage}</div>
            )}
          </section>
        </section>
      ) : null}

      {activeStep === pixelArtConfig.workflow.preprocessingStep ? (
        <section className="pixel-art-stage-layout">
          <aside className="pixel-art-panel">
            <h2>{pixelArtConfig.texts.preprocessing}</h2>
            <NumberInput
              label={pixelArtConfig.texts.brightness}
              max={pixelArtConfig.preprocessing.brightness.maximum}
              min={pixelArtConfig.preprocessing.brightness.minimum}
              onChange={(value) => updatePreprocessing('brightness', value)}
              step={pixelArtConfig.preprocessing.brightness.step}
              value={preprocessing.brightness}
            />
            <NumberInput
              label={pixelArtConfig.texts.contrast}
              max={pixelArtConfig.preprocessing.contrast.maximum}
              min={pixelArtConfig.preprocessing.contrast.minimum}
              onChange={(value) => updatePreprocessing('contrast', value)}
              step={pixelArtConfig.preprocessing.contrast.step}
              value={preprocessing.contrast}
            />
            <NumberInput
              label={pixelArtConfig.texts.saturation}
              max={pixelArtConfig.preprocessing.saturation.maximum}
              min={pixelArtConfig.preprocessing.saturation.minimum}
              onChange={(value) => updatePreprocessing('saturation', value)}
              step={pixelArtConfig.preprocessing.saturation.step}
              value={preprocessing.saturation}
            />
            <NumberInput
              label={pixelArtConfig.texts.sharpness}
              max={pixelArtConfig.preprocessing.sharpness.maximum}
              min={pixelArtConfig.preprocessing.sharpness.minimum}
              onChange={(value) => updatePreprocessing('sharpness', value)}
              step={pixelArtConfig.preprocessing.sharpness.step}
              value={preprocessing.sharpness}
            />
            <NumberInput
              label={pixelArtConfig.texts.localContrast}
              max={pixelArtConfig.preprocessing.localContrast.maximum}
              min={pixelArtConfig.preprocessing.localContrast.minimum}
              onChange={(value) => updatePreprocessing('localContrast', value)}
              step={pixelArtConfig.preprocessing.localContrast.step}
              value={preprocessing.localContrast}
            />
            <label className="pixel-art-control pixel-art-checkbox-control">
              <span>{pixelArtConfig.texts.preserveLightDetails}</span>
              <input
                checked={preprocessing.preserveLightDetails}
                onChange={(event) => updatePreprocessing('preserveLightDetails', event.target.checked)}
                type="checkbox"
              />
            </label>
            <button
              className="pixel-art-save pixel-art-secondary"
              onClick={() => setActiveStep(pixelArtConfig.workflow.uploadStep)}
              type="button"
            >
              {pixelArtConfig.texts.backToCrop}
            </button>
            <button
              className="pixel-art-save"
              disabled={!sourceImage}
              onClick={() => setActiveStep(pixelArtConfig.workflow.gridStep)}
              type="button"
            >
              <SlidersHorizontal aria-hidden="true" />
              {pixelArtConfig.texts.confirmPreprocessing}
            </button>
          </aside>

          <section className="pixel-art-workspace">
            <div className="pixel-art-title">
              <SlidersHorizontal aria-hidden="true" />
              <span>{pixelArtConfig.texts.preprocessing}</span>
            </div>
            {sourceImage ? (
              <PreprocessingPreviewCanvas
                crop={crop}
                image={sourceImage}
                imageElement={sourceElement}
                onImageElementChange={setSourceElement}
                preprocessing={preprocessing}
              />
            ) : (
              <div className="pixel-art-canvas-empty">{pixelArtConfig.texts.emptyImage}</div>
            )}
          </section>
        </section>
      ) : null}

      {activeStep === pixelArtConfig.workflow.gridStep ? (
        <section className="pixel-art-stage-layout">
          <aside className="pixel-art-panel">
            <h2>{pixelArtConfig.texts.outputGrid}</h2>
            <NumberInput
              label={pixelArtConfig.texts.gridWidth}
              max={pixelArtConfig.grid.maximumWidth}
              min={pixelArtConfig.grid.minimumDimension}
              onChange={updateGridWidth}
              step={pixelArtConfig.grid.dimensionStep}
              value={gridWidth}
            />
            <NumberInput
              label={pixelArtConfig.texts.gridHeight}
              max={pixelArtConfig.grid.maximumHeight}
              min={pixelArtConfig.grid.minimumDimension}
              onChange={updateGridHeight}
              step={pixelArtConfig.grid.dimensionStep}
              value={gridHeight}
            />
            <label className="pixel-art-control">
              <span>{pixelArtConfig.texts.colorCount}</span>
              <select
                onChange={(event) => setColorCount(Number(event.target.value))}
                value={colorCount}
              >
                {pixelArtConfig.color.options.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
            <h2>{pixelArtConfig.texts.algorithm}</h2>
            <div className="pixel-art-ratio-grid">
              {pixelArtConfig.algorithms.options.map((algorithm: AlgorithmConfig) => (
                <button
                  className={algorithm.id === selectedAlgorithm ? 'pixel-art-ratio-active' : ''}
                  key={algorithm.id}
                  onClick={() => setSelectedAlgorithm(algorithm.id)}
                  type="button"
                >
                  {algorithm.label}
                </button>
              ))}
            </div>
            <div className="pixel-art-metadata">
              <span>{pixelArtConfig.texts.ratio}</span>
              <strong>{selectedRatio.label}</strong>
              <span>{pixelArtConfig.texts.totalCells}</span>
              <strong>{totalCells}</strong>
            </div>
            <button
              className="pixel-art-save pixel-art-secondary"
              onClick={() => setActiveStep(pixelArtConfig.workflow.preprocessingStep)}
              type="button"
            >
              {pixelArtConfig.texts.backToPreprocessing}
            </button>
            <button
              className="pixel-art-save"
              disabled={!sourceImage || isGenerating}
              onClick={() => void generateProject()}
              type="button"
            >
              <Grid3X3 aria-hidden="true" />
              {isGenerating ? pixelArtConfig.texts.generating : pixelArtConfig.texts.generate}
            </button>
            {message ? <div className="pixel-art-message">{message}</div> : null}
          </aside>

          <section className="pixel-art-workspace">
            <div className="pixel-art-title">
              <Grid3X3 aria-hidden="true" />
              <span>{pixelArtConfig.texts.outputGrid}</span>
            </div>
            <GridPreview algorithm={selectedAlgorithm} width={gridWidth} height={gridHeight} />
          </section>
        </section>
      ) : null}

      {activeStep === pixelArtConfig.workflow.editStep ? (
        <section className="pixel-art-editor-layout">
          <section className="pixel-art-editor-column">
            <div className="pixel-art-title">
              <ImageIcon aria-hidden="true" />
              <span>{pixelArtConfig.texts.editSource}</span>
            </div>
            {sourceImage ? (
              <SourceCanvas
                crop={crop}
                image={sourceImage}
                imageElement={sourceElement}
                onImageElementChange={setSourceElement}
                onSampleColor={(rgb) => {
                  setSampledColor(rgb);
                  if (pickFromSource) {
                    applyColorToSelectedCells(rgb);
                  }
                }}
                onViewChange={setSourceView}
                pickEnabled={pickFromSource}
                view={sourceView}
              />
            ) : null}
          </section>

          <section className="pixel-art-editor-column">
            <div className="pixel-art-title">
              <Palette aria-hidden="true" />
              <span>{pixelArtConfig.texts.pixelEditor}</span>
            </div>
            {project ? (
              <PixelEditorCanvas
                onSelectionChange={setSelectedCells}
                onViewChange={setPixelView}
                project={project}
                selectedCells={selectedCells}
                tool={pixelTool}
                view={pixelView}
              />
            ) : (
              <div className="pixel-art-canvas-empty">{pixelArtConfig.texts.emptyResult}</div>
            )}
          </section>

          <aside className="pixel-art-panel">
            <h2>{pixelArtConfig.texts.stepEdit}</h2>
            <button
              className="pixel-art-save pixel-art-secondary"
              onClick={() => setActiveStep(pixelArtConfig.workflow.gridStep)}
              type="button"
            >
              {pixelArtConfig.texts.backToGrid}
            </button>
            <div className="pixel-art-tool-row">
              <button
                className={pixelTool === 'select' ? 'pixel-art-ratio-active' : ''}
                onClick={() => setPixelTool('select')}
                type="button"
              >
                <Grid3X3 aria-hidden="true" />
                {pixelArtConfig.texts.selectCells}
              </button>
              <button
                className={pixelTool === 'pan' ? 'pixel-art-ratio-active' : ''}
                onClick={() => setPixelTool('pan')}
                type="button"
              >
                <Move aria-hidden="true" />
                {pixelArtConfig.texts.panCanvas}
              </button>
            </div>
            <button
              className={pickFromSource ? 'pixel-art-save' : 'pixel-art-save pixel-art-secondary'}
              onClick={() => setPickFromSource((currentValue) => !currentValue)}
              type="button"
            >
              <ImageIcon aria-hidden="true" />
              {pixelArtConfig.texts.pickFromSource}
            </button>
            <button
              className="pixel-art-save pixel-art-secondary"
              onClick={() => setSelectedCells(new Set())}
              type="button"
            >
              {pixelArtConfig.texts.clearSelection}
            </button>
            <div className="pixel-art-tool-row">
              <button
                disabled={undoHistory.length === pixelArtConfig.emptyFileCount}
                onClick={undoEdit}
                type="button"
              >
                <Undo2 aria-hidden="true" />
                {pixelArtConfig.texts.undo}
              </button>
              <button
                disabled={redoHistory.length === pixelArtConfig.emptyFileCount}
                onClick={redoEdit}
                type="button"
              >
                <Redo2 aria-hidden="true" />
                {pixelArtConfig.texts.redo}
              </button>
            </div>
            <div className="pixel-art-metadata">
              <span>{pixelArtConfig.texts.selectedCells}</span>
              <strong>{selectedCells.size}</strong>
              <span>{pixelArtConfig.texts.pixelCount}</span>
              <strong>{project?.pixels.length ?? pixelArtConfig.emptyFileCount}</strong>
              <span>{pixelArtConfig.texts.modelId}</span>
              <strong>{project?.modelId ?? ''}</strong>
            </div>
            {project ? <SideLayoutSummary project={project} /> : null}
            <h2>{pixelArtConfig.texts.candidateColors}</h2>
            <ColorPalette colors={candidateColors} onColorSelect={applyColorToSelectedCells} />
            <button
              className="pixel-art-save"
              disabled={!project || isSavingEdits}
              onClick={() => void saveEditedProject()}
              type="button"
            >
              <Save aria-hidden="true" />
              {isSavingEdits ? pixelArtConfig.texts.savingEdits : pixelArtConfig.texts.saveEdits}
            </button>
            {message ? <div className="pixel-art-message">{message}</div> : null}
          </aside>
        </section>
      ) : null}
    </main>
  );
}

function StepBadge({ active, label }: { active: boolean; label: string }) {
  return <div className={active ? 'pixel-art-step pixel-art-step-active' : 'pixel-art-step'}>{label}</div>;
}

/** 展示可恢复任务的阶段进度；taskId 是机器标识，状态说明来自多语言资源。 */
function PixelTaskProgressView({ progress }: { progress: PixelTaskSnapshot }) {
  const labels = {
    uploading: pixelArtConfig.texts.taskUploading,
    queued: pixelArtConfig.texts.taskQueued,
    running: pixelArtConfig.texts.taskProcessing,
    succeeded: pixelArtConfig.texts.taskCompleted,
    failed: pixelArtConfig.texts.taskFailed,
    cancelled: pixelArtConfig.texts.taskFailed,
  };
  return (
    <section aria-live="polite" className="pixel-art-task-progress">
      <div>
        <strong>{labels[progress.status]}</strong>
        {progress.percent !== null ? <span>{Math.round(progress.percent)}%</span> : null}
      </div>
      <progress aria-label={labels[progress.status]} max={100} value={progress.percent ?? undefined} />
      {progress.taskId ? <small>{pixelArtConfig.texts.safeToClose}</small> : null}
    </section>
  );
}

function PreprocessingPreviewCanvas({
  crop,
  image,
  imageElement,
  onImageElementChange,
  preprocessing,
}: {
  crop: CropBox;
  image: SourceImage;
  imageElement: ImageElementState;
  onImageElementChange: (state: ImageElementState) => void;
  preprocessing: PixelArtPreprocessing;
}) {
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null);
  const [previewFailed, setPreviewFailed] = React.useState(false);

  React.useEffect(() => {
    loadCanvasImage(image.objectUrl, imageElement, onImageElementChange);
  }, [image.objectUrl, imageElement, onImageElementChange]);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !imageElement.element) {
      return;
    }
    const loadedImage = imageElement.element;
    const context = canvas.getContext('2d');
    if (!context) {
      return;
    }
    // 参数变化终止旧 Worker，拖动滑块不堆积过期任务，也不把邻域循环留在 UI 线程。
    const worker = new Worker(new URL('./preview.worker.ts', import.meta.url), { type: 'module' });
    let requestId = 0;
    let frame = 0;
    setPreviewFailed(false);
    worker.onerror = () => { setPreviewFailed(true); worker.terminate(); };
    const draw = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => drawPreprocessingPreview(canvas, context, loadedImage, crop, preprocessing, worker, ++requestId));
    };
    draw();
    const resizeObserver = new ResizeObserver(draw);
    resizeObserver.observe(canvas);
    return () => { cancelAnimationFrame(frame); resizeObserver.disconnect(); worker.terminate(); };
  }, [crop, imageElement.element, preprocessing]);

  return <>
    {previewFailed && <p role="alert">{pixelArtConfig.texts.previewFailed}</p>}
    <canvas className="pixel-art-canvas pixel-art-preview-canvas" ref={canvasRef} />
  </>;
}

function CropCanvas({
  crop,
  image,
  imageElement,
  onCropChange,
  onImageElementChange,
  onViewChange,
  ratio,
  view,
}: {
  crop: CropBox;
  image: SourceImage;
  imageElement: ImageElementState;
  onCropChange: (crop: CropBox) => void;
  onImageElementChange: (state: ImageElementState) => void;
  onViewChange: (view: CanvasView) => void;
  ratio: CropRatio;
  view: CanvasView;
}) {
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null);
  const dragRef = React.useRef<CropDragState | null>(null);

  React.useEffect(() => {
    loadCanvasImage(image.objectUrl, imageElement, onImageElementChange);
  }, [image.objectUrl, imageElement, onImageElementChange]);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !imageElement.element) {
      return;
    }
    const loadedImage = imageElement.element;
    const context = canvas.getContext('2d');
    if (!context) {
      return;
    }
    const draw = () => drawCropCanvas(canvas, context, loadedImage, crop, view);
    draw();
    const resizeObserver = new ResizeObserver(draw);
    resizeObserver.observe(canvas);
    return () => resizeObserver.disconnect();
  }, [crop, imageElement.element, view]);

  const pointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    stopCanvasPointerEvent(event);
    if (!imageElement.element || event.button !== pixelArtConfig.pointer.leftButton) {
      return;
    }
    const canvasPoint = canvasPointer(event);
    const imagePoint = canvasToImage(canvasPoint.x, canvasPoint.y, event.currentTarget, imageElement.element, view);
    dragRef.current = {
      mode: pointInCrop(imagePoint, crop) ? 'move' : 'draw',
      startCanvasX: canvasPoint.x,
      startCanvasY: canvasPoint.y,
      startImageX: imagePoint.x,
      startImageY: imagePoint.y,
      startCrop: crop,
      startView: view,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const pointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    stopCanvasPointerEvent(event);
    const dragState = dragRef.current;
    if (!dragState || !imageElement.element) {
      return;
    }
    const canvasPoint = canvasPointer(event);
    if (dragState.mode === 'move') {
      const transform = imageTransform(
        event.currentTarget.clientWidth,
        event.currentTarget.clientHeight,
        imageElement.element,
        dragState.startView,
      );
      onCropChange(
        clampCrop(
          {
            ...dragState.startCrop,
            x: dragState.startCrop.x + (canvasPoint.x - dragState.startCanvasX) / transform.scale,
            y: dragState.startCrop.y + (canvasPoint.y - dragState.startCanvasY) / transform.scale,
          },
          image,
        ),
      );
      return;
    }
    const imagePoint = canvasToImage(canvasPoint.x, canvasPoint.y, event.currentTarget, imageElement.element, view);
    onCropChange(ratioCropFromDrag(dragState.startImageX, dragState.startImageY, imagePoint.x, imagePoint.y, ratio, image));
  };

  return (
    <canvas
      className="pixel-art-canvas"
      onPointerDown={pointerDown}
      onPointerMove={pointerMove}
      onPointerUp={(event) => {
        stopCanvasPointerEvent(event);
        dragRef.current = null;
        releaseCanvasPointer(event);
      }}
      onWheel={(event) => zoomCanvas(event, imageElement.element, view, onViewChange)}
      ref={canvasRef}
    />
  );
}

function SourceCanvas({
  crop,
  image,
  imageElement,
  onImageElementChange,
  onSampleColor,
  onViewChange,
  pickEnabled,
  view,
}: {
  crop: CropBox;
  image: SourceImage;
  imageElement: ImageElementState;
  onImageElementChange: (state: ImageElementState) => void;
  onSampleColor: (rgb: string) => void;
  onViewChange: (view: CanvasView) => void;
  pickEnabled: boolean;
  view: CanvasView;
}) {
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null);
  const dragRef = React.useRef<SourceDragState | null>(null);

  React.useEffect(() => {
    loadCanvasImage(image.objectUrl, imageElement, onImageElementChange);
  }, [image.objectUrl, imageElement, onImageElementChange]);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !imageElement.element) {
      return;
    }
    const loadedImage = imageElement.element;
    const context = canvas.getContext('2d');
    if (!context) {
      return;
    }
    const draw = () => drawSourceCanvas(canvas, context, loadedImage, crop, view);
    draw();
    const resizeObserver = new ResizeObserver(draw);
    resizeObserver.observe(canvas);
    return () => resizeObserver.disconnect();
  }, [crop, imageElement.element, view]);

  const pointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    stopCanvasPointerEvent(event);
    const canvasPoint = canvasPointer(event);
    dragRef.current = {
      mode: pickEnabled ? 'sample' : 'pan',
      startX: canvasPoint.x,
      startY: canvasPoint.y,
      startView: view,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const pointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    stopCanvasPointerEvent(event);
    const dragState = dragRef.current;
    if (!dragState || dragState.mode !== 'pan') {
      return;
    }
    const canvasPoint = canvasPointer(event);
    onViewChange({
      ...view,
      offsetX: dragState.startView.offsetX + canvasPoint.x - dragState.startX,
      offsetY: dragState.startView.offsetY + canvasPoint.y - dragState.startY,
    });
  };

  const pointerUp = (event: React.PointerEvent<HTMLCanvasElement>) => {
    stopCanvasPointerEvent(event);
    const dragState = dragRef.current;
    if (dragState?.mode === 'sample' && imageElement.element) {
      const canvasPoint = canvasPointer(event);
      const imagePoint = canvasToImage(canvasPoint.x, canvasPoint.y, event.currentTarget, imageElement.element, view);
      onSampleColor(sampleImageColor(imageElement.element, imagePoint));
    }
    dragRef.current = null;
    releaseCanvasPointer(event);
  };

  return (
    <canvas
      className="pixel-art-canvas pixel-art-editor-canvas"
      onPointerDown={pointerDown}
      onPointerMove={pointerMove}
      onPointerUp={pointerUp}
      onWheel={(event) => zoomCanvas(event, imageElement.element, view, onViewChange)}
      ref={canvasRef}
    />
  );
}

function PixelEditorCanvas({
  onSelectionChange,
  onViewChange,
  project,
  selectedCells,
  tool,
  view,
}: {
  onSelectionChange: (cells: Set<string>) => void;
  onViewChange: (view: CanvasView) => void;
  project: PixelArtProject;
  selectedCells: Set<string>;
  tool: 'select' | 'pan';
  view: CanvasView;
}) {
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null);
  const dragRef = React.useRef<PixelDragState | null>(null);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }
    const context = canvas.getContext('2d');
    if (!context) {
      return;
    }
    const draw = () => drawPixelEditor(canvas, context, project, selectedCells, view);
    draw();
    const resizeObserver = new ResizeObserver(draw);
    resizeObserver.observe(canvas);
    return () => resizeObserver.disconnect();
  }, [project, selectedCells, view]);

  const pointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    stopCanvasPointerEvent(event);
    const canvasPoint = canvasPointer(event);
    const cell = canvasToCell(canvasPoint.x, canvasPoint.y, event.currentTarget, project, view);
    dragRef.current = {
      mode: tool,
      startX: canvasPoint.x,
      startY: canvasPoint.y,
      startCellX: cell.x,
      startCellY: cell.y,
      startView: view,
    };
    if (tool === 'select') {
      onSelectionChange(selectionRectangle(cell.x, cell.y, cell.x, cell.y, project));
    }
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const pointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    stopCanvasPointerEvent(event);
    const dragState = dragRef.current;
    if (!dragState) {
      return;
    }
    const canvasPoint = canvasPointer(event);
    if (dragState.mode === 'pan') {
      onViewChange({
        ...view,
        offsetX: dragState.startView.offsetX + canvasPoint.x - dragState.startX,
        offsetY: dragState.startView.offsetY + canvasPoint.y - dragState.startY,
      });
      return;
    }
    const cell = canvasToCell(canvasPoint.x, canvasPoint.y, event.currentTarget, project, view);
    onSelectionChange(selectionRectangle(dragState.startCellX, dragState.startCellY, cell.x, cell.y, project));
  };

  return (
    <canvas
      className="pixel-art-canvas pixel-art-editor-canvas"
      onPointerDown={pointerDown}
      onPointerMove={pointerMove}
      onPointerUp={(event) => {
        stopCanvasPointerEvent(event);
        dragRef.current = null;
        releaseCanvasPointer(event);
      }}
      onWheel={(event) => zoomGridCanvas(event, project, view, onViewChange)}
      ref={canvasRef}
    />
  );
}

function SideLayoutSummary({ project }: { project: PixelArtProject }) {
  const stats = sideLayoutStats(project);
  if (!stats) {
    return null;
  }
  return (
    <div className="pixel-art-metadata">
      <span>{pixelArtConfig.sideLayout.summaryLabel}</span>
      <strong>{pixelArtConfig.sideLayout.sidePixelLabel}</strong>
      <span>{pixelArtConfig.sideLayout.brickLabel}</span>
      <strong>{stats.bricks}</strong>
      <span>{pixelArtConfig.sideLayout.plateLabel}</span>
      <strong>{stats.plates}</strong>
    </div>
  );
}

function GridPreview({
  algorithm,
  width,
  height,
}: {
  algorithm: string;
  width: number;
  height: number;
}) {
  const metrics = gridPreviewMetrics(algorithm, width, height);
  return (
    <div className="pixel-art-grid-preview">
      <div
        style={{
          aspectRatio: `${metrics.width} / ${metrics.height}`,
        }}
      >
        <span>{width} x {height}</span>
        {isSideMixedAlgorithm(algorithm) ? <em>{pixelArtConfig.sideLayout.sidePixelLabel}</em> : null}
      </div>
    </div>
  );
}

function ColorPalette({
  colors,
  onColorSelect,
}: {
  colors: PixelPaletteColor[];
  onColorSelect: (rgb: string) => void;
}) {
  return (
    <div className="pixel-art-palette">
      {colors.map((color) => (
        <button className="pixel-art-palette-row" key={`${color.rgb}-${color.colorIndex}`} onClick={() => onColorSelect(color.rgb)} type="button">
          <span style={{ background: color.rgb }} />
          <strong>{color.rgb}</strong>
          <em>{color.count}</em>
        </button>
      ))}
    </div>
  );
}

function NumberInput({
  label,
  max,
  min,
  onChange,
  step,
  value,
}: {
  label: string;
  max?: number;
  min: number;
  onChange: (value: number) => void;
  step: number;
  value: number;
}) {
  return (
    <label className="pixel-art-control">
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

function drawCropCanvas(
  canvas: HTMLCanvasElement,
  context: CanvasRenderingContext2D,
  image: HTMLImageElement,
  crop: CropBox,
  view: CanvasView,
): void {
  const viewport = prepareCanvas(canvas, context, pixelArtConfig.canvas.cropCanvasFallbackWidth, pixelArtConfig.canvas.cropCanvasFallbackHeight);
  drawImage(context, image, viewport.width, viewport.height, view);
  const transform = imageTransform(viewport.width, viewport.height, image, view);
  const cropScreen = cropToScreen(crop, transform);
  context.fillStyle = pixelArtConfig.crop.overlayFill;
  context.fillRect(pixelArtConfig.emptyFileCount, pixelArtConfig.emptyFileCount, viewport.width, viewport.height);
  context.save();
  context.beginPath();
  context.rect(cropScreen.x, cropScreen.y, cropScreen.width, cropScreen.height);
  context.clip();
  drawImage(context, image, viewport.width, viewport.height, view);
  context.restore();
  context.strokeStyle = pixelArtConfig.crop.frameColor;
  context.lineWidth = pixelArtConfig.crop.handleStrokeWidth;
  context.strokeRect(cropScreen.x, cropScreen.y, cropScreen.width, cropScreen.height);
  context.fillStyle = pixelArtConfig.crop.handleColor;
  context.beginPath();
  context.arc(cropScreen.x + cropScreen.width, cropScreen.y + cropScreen.height, pixelArtConfig.crop.handleRadius, pixelArtConfig.emptyFileCount, Math.PI * pixelArtConfig.canvas.screenCenterDivisor);
  context.fill();
}

function drawSourceCanvas(
  canvas: HTMLCanvasElement,
  context: CanvasRenderingContext2D,
  image: HTMLImageElement,
  crop: CropBox,
  view: CanvasView,
): void {
  const viewport = prepareCanvas(canvas, context, pixelArtConfig.canvas.editorCanvasFallbackWidth, pixelArtConfig.canvas.editorCanvasFallbackHeight);
  drawImage(context, image, viewport.width, viewport.height, view);
  const transform = imageTransform(viewport.width, viewport.height, image, view);
  const cropScreen = cropToScreen(crop, transform);
  context.strokeStyle = pixelArtConfig.crop.handleColor;
  context.lineWidth = pixelArtConfig.crop.handleStrokeWidth;
  context.strokeRect(cropScreen.x, cropScreen.y, cropScreen.width, cropScreen.height);
}

function drawPreprocessingPreview(
  canvas: HTMLCanvasElement,
  context: CanvasRenderingContext2D,
  image: HTMLImageElement,
  crop: CropBox,
  preprocessing: PixelArtPreprocessing,
  worker: Worker,
  requestId: number,
): void {
  const viewport = prepareCanvas(canvas, context, pixelArtConfig.canvas.cropCanvasFallbackWidth, pixelArtConfig.canvas.cropCanvasFallbackHeight);
  const previewScale = Math.min(viewport.width / crop.width, viewport.height / crop.height, 640 / Math.max(crop.width, crop.height));
  const previewWidth = Math.max(pixelArtConfig.canvas.minimumCanvasPixels, Math.round(crop.width * previewScale));
  const previewHeight = Math.max(pixelArtConfig.canvas.minimumCanvasPixels, Math.round(crop.height * previewScale));
  const previewCanvas = document.createElement('canvas');
  previewCanvas.width = previewWidth;
  previewCanvas.height = previewHeight;
  const previewContext = previewCanvas.getContext('2d');
  if (!previewContext) {
    return;
  }
  previewContext.filter = preprocessingFilter(preprocessing);
  previewContext.drawImage(
    image,
    crop.x,
    crop.y,
    crop.width,
    crop.height,
    pixelArtConfig.emptyFileCount,
    pixelArtConfig.emptyFileCount,
    previewWidth,
    previewHeight,
  );
  const displayScale = Math.min(viewport.width / previewWidth, viewport.height / previewHeight);
  const drawPreview = () => context.drawImage(previewCanvas,
    (viewport.width - previewWidth * displayScale) / 2, (viewport.height - previewHeight * displayScale) / 2,
    previewWidth * displayScale, previewHeight * displayScale);
  if (preprocessing.sharpness === 1 && preprocessing.localContrast === 0) { drawPreview(); return; }
  const pixels = previewContext.getImageData(0, 0, previewWidth, previewHeight);
  worker.onmessage = (event: MessageEvent<{ id: number; data: ArrayBuffer }>) => {
    if (event.data.id !== requestId) return;
    previewContext.putImageData(new ImageData(new Uint8ClampedArray(event.data.data), previewWidth, previewHeight), 0, 0);
    drawPreview();
  };
  // 上传保持原始文件；这里只降低交互预览分辨率，最终 Go 计算仍读取完整裁剪区域。
  worker.postMessage({ id: requestId, data: pixels.data.buffer, width: previewWidth, height: previewHeight, preprocessing }, [pixels.data.buffer]);
}

function preprocessingFilter(preprocessing: PixelArtPreprocessing): string {
  return `brightness(${preprocessing.brightness}) contrast(${preprocessing.contrast}) saturate(${preprocessing.saturation})`;
}

function isSideMixedAlgorithm(algorithm: string): boolean {
  return algorithm === pixelArtConfig.algorithms.sideMixedPlateBrickPixel;
}

function hasSideLayout(project: PixelArtProject): boolean {
  return project.pixels.some((pixel) => Boolean(pixel.sidePartType));
}

function gridPreviewMetrics(algorithm: string, width: number, height: number): GridDisplayMetrics {
  if (!isSideMixedAlgorithm(algorithm)) {
    return gridDisplayMetricsFromCellSize(
      width,
      height,
      pixelArtConfig.grid.dimensionStep,
      pixelArtConfig.grid.dimensionStep,
    );
  }
  return gridDisplayMetricsFromCellSize(
    width,
    height,
    pixelArtConfig.sideLayout.pixelWidthPlates,
    pixelArtConfig.sideLayout.pixelHeightPlates,
  );
}

function gridDisplayMetrics(project: PixelArtProject): GridDisplayMetrics {
  const sidePixel = project.pixels.find((pixel) => pixel.sidePixelWidthPlates && pixel.sidePixelHeightPlates);
  if (!sidePixel) {
    return gridDisplayMetricsFromCellSize(
      project.gridWidth,
      project.gridHeight,
      pixelArtConfig.grid.dimensionStep,
      pixelArtConfig.grid.dimensionStep,
    );
  }
  return gridDisplayMetricsFromCellSize(
    project.gridWidth,
    project.gridHeight,
    sidePixel.sidePixelWidthPlates ?? pixelArtConfig.sideLayout.pixelWidthPlates,
    sidePixel.sidePixelHeightPlates ?? pixelArtConfig.sideLayout.pixelHeightPlates,
  );
}

function gridDisplayMetricsFromCellSize(
  gridWidth: number,
  gridHeight: number,
  cellWidth: number,
  cellHeight: number,
): GridDisplayMetrics {
  return {
    cellWidth,
    cellHeight,
    width: gridWidth * cellWidth,
    height: gridHeight * cellHeight,
  };
}

function sideLayoutStats(project: PixelArtProject): SideLayoutStats | null {
  if (!hasSideLayout(project)) {
    return null;
  }
  return project.pixels.reduce<SideLayoutStats>(
    (stats, pixel) => {
      if (!shouldDrawSidePartOutline(pixel, project)) {
        return stats;
      }
      if (pixel.sidePartType === pixelArtConfig.sideLayout.brickPartType) {
        return { ...stats, bricks: stats.bricks + pixelArtConfig.grid.dimensionStep };
      }
      if (pixel.sidePartType === pixelArtConfig.sideLayout.platePartType) {
        return { ...stats, plates: stats.plates + pixelArtConfig.grid.dimensionStep };
      }
      return stats;
    },
    {
      bricks: pixelArtConfig.emptyFileCount,
      plates: pixelArtConfig.emptyFileCount,
    },
  );
}

function shouldDrawSidePartOutline(pixel: PixelCell, project: PixelArtProject): boolean {
  if (!isSidePartVerticalStart(pixel)) {
    return false;
  }
  return isSidePartHorizontalStart(pixel, project);
}

function isSidePartVerticalStart(pixel: PixelCell): boolean {
  if (pixel.sidePartType === pixelArtConfig.sideLayout.brickPartType) {
    return pixel.sidePartRole === pixelArtConfig.sideLayout.brickStartRole;
  }
  return pixel.sidePartType === pixelArtConfig.sideLayout.platePartType;
}

function isSidePartHorizontalStart(pixel: PixelCell, project: PixelArtProject): boolean {
  if (pixel.x === pixelArtConfig.emptyFileCount) {
    return true;
  }
  const previousPixel = project.pixels[pixel.y * project.gridWidth + pixel.x - pixelArtConfig.grid.dimensionStep];
  return (
    previousPixel.rgb !== pixel.rgb
    || previousPixel.sidePartType !== pixel.sidePartType
    || previousPixel.sidePartRole !== pixel.sidePartRole
    || previousPixel.sidePartWidthPlates !== pixel.sidePartWidthPlates
  );
}

function sidePartStrokeColor(pixel: PixelCell): string {
  if (pixel.sidePartType === pixelArtConfig.sideLayout.brickPartType) {
    return pixelArtConfig.sideLayout.brickStrokeColor;
  }
  return pixelArtConfig.sideLayout.plateStrokeColor;
}

function drawPixelEditor(
  canvas: HTMLCanvasElement,
  context: CanvasRenderingContext2D,
  project: PixelArtProject,
  selectedCells: Set<string>,
  view: CanvasView,
): void {
  const viewport = prepareCanvas(canvas, context, pixelArtConfig.canvas.editorCanvasFallbackWidth, pixelArtConfig.canvas.editorCanvasFallbackHeight);
  const transform = gridTransform(viewport.width, viewport.height, project, view);
  for (const pixel of project.pixels) {
    context.fillStyle = pixel.rgb;
    context.fillRect(
      transform.originX + pixel.x * transform.cellWidth * transform.scale,
      transform.originY + pixel.y * transform.cellHeight * transform.scale,
      transform.cellWidth * transform.scale,
      transform.cellHeight * transform.scale,
    );
  }
  drawSideLayoutOverlay(context, project, transform);
  if (transform.scale >= pixelArtConfig.canvas.gridLineMinCellPixels) {
    drawGrid(context, project, transform);
  }
  context.fillStyle = pixelArtConfig.canvas.selectionColor;
  context.strokeStyle = pixelArtConfig.canvas.selectionStrokeColor;
  context.lineWidth = pixelArtConfig.canvas.selectionStrokeWidth;
  selectedCells.forEach((key) => {
    const cell = parseCellKey(key);
    const x = transform.originX + cell.x * transform.cellWidth * transform.scale;
    const y = transform.originY + cell.y * transform.cellHeight * transform.scale;
    context.fillRect(x, y, transform.cellWidth * transform.scale, transform.cellHeight * transform.scale);
    context.strokeRect(x, y, transform.cellWidth * transform.scale, transform.cellHeight * transform.scale);
  });
}

function prepareCanvas(
  canvas: HTMLCanvasElement,
  context: CanvasRenderingContext2D,
  fallbackWidth: number,
  fallbackHeight: number,
): { width: number; height: number } {
  const pixelRatio = Math.min(window.devicePixelRatio, pixelArtConfig.canvas.pixelRatioLimit);
  const width = Math.max(pixelArtConfig.canvas.minimumCanvasPixels, canvas.clientWidth || fallbackWidth);
  const height = Math.max(pixelArtConfig.canvas.minimumCanvasPixels, canvas.clientHeight || fallbackHeight);
  if (canvas.width !== Math.round(width * pixelRatio)) canvas.width = Math.round(width * pixelRatio);
  if (canvas.height !== Math.round(height * pixelRatio)) canvas.height = Math.round(height * pixelRatio);
  context.setTransform(pixelRatio, pixelArtConfig.emptyFileCount, pixelArtConfig.emptyFileCount, pixelRatio, pixelArtConfig.emptyFileCount, pixelArtConfig.emptyFileCount);
  context.fillStyle = pixelArtConfig.canvas.backgroundColor;
  context.fillRect(pixelArtConfig.emptyFileCount, pixelArtConfig.emptyFileCount, width, height);
  return { width, height };
}

function drawImage(
  context: CanvasRenderingContext2D,
  image: HTMLImageElement,
  canvasWidth: number,
  canvasHeight: number,
  view: CanvasView,
): void {
  const transform = imageTransform(canvasWidth, canvasHeight, image, view);
  context.drawImage(image, transform.originX, transform.originY, image.width * transform.scale, image.height * transform.scale);
}

function drawGrid(
  context: CanvasRenderingContext2D,
  project: PixelArtProject,
  transform: GridTransform,
): void {
  context.strokeStyle = pixelArtConfig.canvas.gridColor;
  context.lineWidth = pixelArtConfig.canvas.gridLineWidth;
  for (let x = pixelArtConfig.emptyFileCount; x <= project.gridWidth; x += pixelArtConfig.grid.dimensionStep) {
    const lineX = transform.originX + x * transform.cellWidth * transform.scale;
    context.beginPath();
    context.moveTo(lineX, transform.originY);
    context.lineTo(lineX, transform.originY + transform.height * transform.scale);
    context.stroke();
  }
  for (let y = pixelArtConfig.emptyFileCount; y <= project.gridHeight; y += pixelArtConfig.grid.dimensionStep) {
    const lineY = transform.originY + y * transform.cellHeight * transform.scale;
    context.beginPath();
    context.moveTo(transform.originX, lineY);
    context.lineTo(transform.originX + transform.width * transform.scale, lineY);
    context.stroke();
  }
}

function drawSideLayoutOverlay(
  context: CanvasRenderingContext2D,
  project: PixelArtProject,
  transform: GridTransform,
): void {
  if (!hasSideLayout(project)) {
    return;
  }
  context.lineWidth = pixelArtConfig.sideLayout.overlayLineWidth;
  for (const pixel of project.pixels) {
    if (!shouldDrawSidePartOutline(pixel, project)) {
      continue;
    }
    context.strokeStyle = sidePartStrokeColor(pixel);
    context.strokeRect(
      transform.originX + pixel.x * transform.cellWidth * transform.scale,
      transform.originY + pixel.y * transform.cellHeight * transform.scale,
      (pixel.sidePartWidthPlates ?? transform.cellWidth) * transform.scale,
      (pixel.sidePartHeightPlates ?? transform.cellHeight) * transform.scale,
    );
  }
}

function imageTransform(
  canvasWidth: number,
  canvasHeight: number,
  image: HTMLImageElement,
  view: CanvasView,
): { originX: number; originY: number; scale: number } {
  const scale = Math.min(canvasWidth / image.width, canvasHeight / image.height) * view.zoom;
  return {
    scale,
    originX: (canvasWidth - image.width * scale) / pixelArtConfig.canvas.screenCenterDivisor + view.offsetX,
    originY: (canvasHeight - image.height * scale) / pixelArtConfig.canvas.screenCenterDivisor + view.offsetY,
  };
}

function gridTransform(
  canvasWidth: number,
  canvasHeight: number,
  project: PixelArtProject,
  view: CanvasView,
): GridTransform {
  const metrics = gridDisplayMetrics(project);
  const scale = Math.min(canvasWidth / metrics.width, canvasHeight / metrics.height) * view.zoom;
  return {
    ...metrics,
    scale,
    originX: (canvasWidth - metrics.width * scale) / pixelArtConfig.canvas.screenCenterDivisor + view.offsetX,
    originY: (canvasHeight - metrics.height * scale) / pixelArtConfig.canvas.screenCenterDivisor + view.offsetY,
  };
}

function cropToScreen(crop: CropBox, transform: { originX: number; originY: number; scale: number }): CropBox {
  return {
    x: transform.originX + crop.x * transform.scale,
    y: transform.originY + crop.y * transform.scale,
    width: crop.width * transform.scale,
    height: crop.height * transform.scale,
  };
}

function canvasToImage(
  canvasX: number,
  canvasY: number,
  canvas: HTMLCanvasElement,
  image: HTMLImageElement,
  view: CanvasView,
): { x: number; y: number } {
  const transform = imageTransform(canvas.clientWidth, canvas.clientHeight, image, view);
  return {
    x: (canvasX - transform.originX) / transform.scale,
    y: (canvasY - transform.originY) / transform.scale,
  };
}

function canvasToCell(
  canvasX: number,
  canvasY: number,
  canvas: HTMLCanvasElement,
  project: PixelArtProject,
  view: CanvasView,
): { x: number; y: number } {
  const transform = gridTransform(canvas.clientWidth, canvas.clientHeight, project, view);
  return {
    x: clamp(Math.floor((canvasX - transform.originX) / (transform.cellWidth * transform.scale)), pixelArtConfig.emptyFileCount, project.gridWidth - pixelArtConfig.grid.dimensionStep),
    y: clamp(Math.floor((canvasY - transform.originY) / (transform.cellHeight * transform.scale)), pixelArtConfig.emptyFileCount, project.gridHeight - pixelArtConfig.grid.dimensionStep),
  };
}

function zoomCanvas(
  event: React.WheelEvent<HTMLCanvasElement>,
  image: HTMLImageElement | null,
  view: CanvasView,
  onViewChange: (view: CanvasView) => void,
): void {
  stopCanvasWheelEvent(event);
  if (!image) {
    return;
  }
  const zoomFactor = event.deltaY < pixelArtConfig.canvas.wheelZoomInDirection ? pixelArtConfig.canvas.zoomStep : 1 / pixelArtConfig.canvas.zoomStep;
  onViewChange({
    ...view,
    zoom: clamp(view.zoom * zoomFactor, pixelArtConfig.canvas.minimumZoom, pixelArtConfig.canvas.maximumZoom),
  });
}

function zoomGridCanvas(
  event: React.WheelEvent<HTMLCanvasElement>,
  project: PixelArtProject,
  view: CanvasView,
  onViewChange: (view: CanvasView) => void,
): void {
  stopCanvasWheelEvent(event);
  if (!project) {
    return;
  }
  const zoomFactor = event.deltaY < pixelArtConfig.canvas.wheelZoomInDirection ? pixelArtConfig.canvas.zoomStep : 1 / pixelArtConfig.canvas.zoomStep;
  onViewChange({
    ...view,
    zoom: clamp(view.zoom * zoomFactor, pixelArtConfig.canvas.minimumZoom, pixelArtConfig.canvas.maximumZoom),
  });
}

function sampleImageColor(image: HTMLImageElement, point: { x: number; y: number }): string {
  const canvas = document.createElement('canvas');
  canvas.width = image.width;
  canvas.height = image.height;
  const context = canvas.getContext('2d');
  if (!context) {
    return pixelArtConfig.canvas.backgroundColor;
  }
  context.drawImage(image, pixelArtConfig.emptyFileCount, pixelArtConfig.emptyFileCount);
  const x = clamp(Math.round(point.x), pixelArtConfig.emptyFileCount, image.width - pixelArtConfig.grid.dimensionStep);
  const y = clamp(Math.round(point.y), pixelArtConfig.emptyFileCount, image.height - pixelArtConfig.grid.dimensionStep);
  const pixel = context.getImageData(x, y, pixelArtConfig.grid.dimensionStep, pixelArtConfig.grid.dimensionStep).data;
  return rgbToHex(pixel[pixelArtConfig.emptyFileCount], pixel[pixelArtConfig.grid.dimensionStep], pixel[pixelArtConfig.canvas.screenCenterDivisor]);
}

function loadCanvasImage(
  source: string,
  currentState: ImageElementState,
  onImageElementChange: (state: ImageElementState) => void,
): void {
  if (currentState.source === source && currentState.element) {
    return;
  }
  const image = new Image();
  image.onload = () => onImageElementChange({ element: image, source });
  image.src = source;
}

function canvasPointer(event: React.PointerEvent<HTMLCanvasElement>): { x: number; y: number } {
  const rect = event.currentTarget.getBoundingClientRect();
  return {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top,
  };
}

function stopCanvasPointerEvent(event: React.PointerEvent<HTMLCanvasElement>): void {
  event.preventDefault();
  event.stopPropagation();
}

function stopCanvasWheelEvent(event: React.WheelEvent<HTMLCanvasElement>): void {
  event.preventDefault();
  event.stopPropagation();
}

function releaseCanvasPointer(event: React.PointerEvent<HTMLCanvasElement>): void {
  if (event.currentTarget.hasPointerCapture(event.pointerId)) {
    event.currentTarget.releasePointerCapture(event.pointerId);
  }
}

function pointInCrop(point: { x: number; y: number }, crop: CropBox): boolean {
  return point.x >= crop.x && point.x <= crop.x + crop.width && point.y >= crop.y && point.y <= crop.y + crop.height;
}

function centeredRatioCrop(image: Pick<SourceImage, 'width' | 'height'>, ratio: CropRatio): CropBox {
  const availableWidth = image.width * pixelArtConfig.crop.initialCoverageRatio;
  const availableHeight = image.height * pixelArtConfig.crop.initialCoverageRatio;
  const ratioValue = ratio.width / ratio.height;
  let width = availableWidth;
  let height = width / ratioValue;
  if (height > availableHeight) {
    height = availableHeight;
    width = height * ratioValue;
  }
  return {
    x: (image.width - width) / pixelArtConfig.canvas.screenCenterDivisor,
    y: (image.height - height) / pixelArtConfig.canvas.screenCenterDivisor,
    width,
    height,
  };
}

function ratioCropFromDrag(
  startX: number,
  startY: number,
  endX: number,
  endY: number,
  ratio: CropRatio,
  image: Pick<SourceImage, 'width' | 'height'>,
): CropBox {
  const rawStartX = clamp(startX, pixelArtConfig.emptyFileCount, image.width);
  const rawStartY = clamp(startY, pixelArtConfig.emptyFileCount, image.height);
  const directionX = endX >= rawStartX ? pixelArtConfig.grid.dimensionStep : -pixelArtConfig.grid.dimensionStep;
  const directionY = endY >= rawStartY ? pixelArtConfig.grid.dimensionStep : -pixelArtConfig.grid.dimensionStep;
  const boundedStartX = clamp(
    rawStartX,
    directionX > pixelArtConfig.emptyFileCount ? pixelArtConfig.emptyFileCount : pixelArtConfig.crop.minimumDimension,
    directionX > pixelArtConfig.emptyFileCount ? image.width - pixelArtConfig.crop.minimumDimension : image.width,
  );
  const boundedStartY = clamp(
    rawStartY,
    directionY > pixelArtConfig.emptyFileCount ? pixelArtConfig.emptyFileCount : pixelArtConfig.crop.minimumDimension,
    directionY > pixelArtConfig.emptyFileCount ? image.height - pixelArtConfig.crop.minimumDimension : image.height,
  );
  const dragWidth = Math.abs(endX - boundedStartX);
  const dragHeight = Math.abs(endY - boundedStartY);
  const boundaryWidth = directionX > pixelArtConfig.emptyFileCount ? image.width - boundedStartX : boundedStartX;
  const boundaryHeight = directionY > pixelArtConfig.emptyFileCount ? image.height - boundedStartY : boundedStartY;
  const size = ratioSizeWithinBounds(
    ratio,
    Math.min(dragWidth, boundaryWidth),
    Math.min(dragHeight, boundaryHeight),
  );
  return {
    x: directionX > pixelArtConfig.emptyFileCount ? boundedStartX : boundedStartX - size.width,
    y: directionY > pixelArtConfig.emptyFileCount ? boundedStartY : boundedStartY - size.height,
    width: size.width,
    height: size.height,
  };
}

function ratioSizeWithinBounds(
  ratio: CropRatio,
  availableWidth: number,
  availableHeight: number,
): { width: number; height: number } {
  const ratioValue = ratio.width / ratio.height;
  const usableWidth = Math.max(pixelArtConfig.crop.minimumDimension, availableWidth);
  const usableHeight = Math.max(pixelArtConfig.crop.minimumDimension, availableHeight);
  let width = usableWidth;
  let height = width / ratioValue;
  if (height > usableHeight) {
    height = usableHeight;
    width = height * ratioValue;
  }
  return { width, height };
}

function clampCrop(crop: CropBox, image: Pick<SourceImage, 'width' | 'height'>): CropBox {
  const width = clamp(crop.width, pixelArtConfig.crop.minimumDimension, image.width);
  const height = clamp(crop.height, pixelArtConfig.crop.minimumDimension, image.height);
  return {
    x: clamp(crop.x, pixelArtConfig.emptyFileCount, image.width - width),
    y: clamp(crop.y, pixelArtConfig.emptyFileCount, image.height - height),
    width,
    height,
  };
}

function roundedCrop(crop: CropBox): CropBox {
  return {
    x: Math.round(crop.x),
    y: Math.round(crop.y),
    width: Math.round(crop.width),
    height: Math.round(crop.height),
  };
}

function linkedDimensionsFromWidth(width: number, ratio: CropRatio): { width: number; height: number } {
  const boundedWidth = clamp(width, pixelArtConfig.grid.minimumDimension, pixelArtConfig.grid.maximumWidth);
  const height = linkedHeight(boundedWidth, ratio);
  if (height <= pixelArtConfig.grid.maximumHeight) {
    return { width: boundedWidth, height };
  }
  const boundedHeight = pixelArtConfig.grid.maximumHeight;
  return { width: linkedWidth(boundedHeight, ratio), height: boundedHeight };
}

function linkedDimensionsFromHeight(height: number, ratio: CropRatio): { width: number; height: number } {
  const boundedHeight = clamp(height, pixelArtConfig.grid.minimumDimension, pixelArtConfig.grid.maximumHeight);
  const width = linkedWidth(boundedHeight, ratio);
  if (width <= pixelArtConfig.grid.maximumWidth) {
    return { width, height: boundedHeight };
  }
  const boundedWidth = pixelArtConfig.grid.maximumWidth;
  return { width: boundedWidth, height: linkedHeight(boundedWidth, ratio) };
}

function linkedHeight(width: number, ratio: CropRatio): number {
  return clamp(Math.round((width * ratio.height) / ratio.width), pixelArtConfig.grid.minimumDimension, pixelArtConfig.grid.maximumHeight);
}

function linkedWidth(height: number, ratio: CropRatio): number {
  return clamp(Math.round((height * ratio.width) / ratio.height), pixelArtConfig.grid.minimumDimension, pixelArtConfig.grid.maximumWidth);
}

function selectionRectangle(
  startX: number,
  startY: number,
  endX: number,
  endY: number,
  project: PixelArtProject,
): Set<string> {
  const cells = new Set<string>();
  const minX = clamp(Math.min(startX, endX), pixelArtConfig.emptyFileCount, project.gridWidth - pixelArtConfig.grid.dimensionStep);
  const maxX = clamp(Math.max(startX, endX), pixelArtConfig.emptyFileCount, project.gridWidth - pixelArtConfig.grid.dimensionStep);
  const minY = clamp(Math.min(startY, endY), pixelArtConfig.emptyFileCount, project.gridHeight - pixelArtConfig.grid.dimensionStep);
  const maxY = clamp(Math.max(startY, endY), pixelArtConfig.emptyFileCount, project.gridHeight - pixelArtConfig.grid.dimensionStep);
  for (let y = minY; y <= maxY; y += pixelArtConfig.grid.dimensionStep) {
    for (let x = minX; x <= maxX; x += pixelArtConfig.grid.dimensionStep) {
      cells.add(cellKey(x, y));
    }
  }
  return cells;
}

function paletteFromPixels(pixels: PixelCell[]): PixelPaletteColor[] {
  const counts = new Map<string, number>();
  pixels.forEach((pixel) => counts.set(pixel.rgb, (counts.get(pixel.rgb) ?? pixelArtConfig.emptyFileCount) + pixelArtConfig.grid.dimensionStep));
  return Array.from(counts.entries()).map(([rgb, count], index) => ({ colorIndex: index, rgb, count }));
}

function colorIndexForRgb(palette: PixelPaletteColor[], rgb: string): number {
  const existingColor = palette.find((color) => color.rgb === rgb);
  return existingColor?.colorIndex ?? pixelArtConfig.color.sampleColorIndex;
}

function limitedHistory(history: PixelArtProject[]): PixelArtProject[] {
  return history.slice(Math.max(pixelArtConfig.emptyFileCount, history.length - pixelArtConfig.history.maxSteps));
}

function cloneProject(project: PixelArtProject): PixelArtProject {
  return {
    ...project,
    palette: project.palette.map((color) => ({ ...color })),
    pixels: project.pixels.map((pixel) => ({ ...pixel })),
  };
}

function cellKey(x: number, y: number): string {
  return `${x}${pixelArtConfig.selection.keySeparator}${y}`;
}

function parseCellKey(key: string): { x: number; y: number } {
  const [x, y] = key.split(pixelArtConfig.selection.keySeparator).map(Number);
  return { x, y };
}

function rgbToHex(red: number, green: number, blue: number): string {
  return `#${hexChannel(red)}${hexChannel(green)}${hexChannel(blue)}`;
}

function hexChannel(value: number): string {
  return value.toString(16).padStart(pixelArtConfig.canvas.screenCenterDivisor, '0').toUpperCase();
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function initialCanvasView(): CanvasView {
  return {
    zoom: pixelArtConfig.canvas.initialZoom,
    offsetX: pixelArtConfig.canvas.initialOffsetX,
    offsetY: pixelArtConfig.canvas.initialOffsetY,
  };
}

function loadImageInfo(file: File): Promise<SourceImage> {
  return new Promise((resolve, reject) => {
    const objectUrl = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      resolve({
        file,
        objectUrl,
        width: image.naturalWidth,
        height: image.naturalHeight,
      });
    };
    image.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      reject(new Error(pixelArtConfig.texts.emptyImage));
    };
    image.src = objectUrl;
  });
}
