import type { PixelArtProject, PixelArtProjectList } from '../pixelArt/pixelArtApi';
import legoDesignConfig from './legoDesignConfig.json';

export type LegoDesignColor = {
  id: number;
  name: string;
  rgb: string;
  isTrans: boolean;
};

export type LegoDesignPart = {
  ldrawPartNum: string;
  rebrickablePartNum: string | null;
  legoDesignId: string | null;
  name: string | null;
  partRole: string;
  width: number;
  height: number;
  logicalHeightPlate: number;
  area: number;
};

export type LegoDesignMetadata = {
  colors: LegoDesignColor[];
  parts: LegoDesignPart[];
  terrainParts: LegoDesignPart[];
};

export type LegoPlacement = {
  partId: string;
  rebrickablePartNum: string | null;
  legoDesignId: string | null;
  colorId: number;
  colorName: string;
  colorRgb: string;
  ldrawColorCode: string;
  x: number;
  y: number;
  width: number;
  height: number;
  logicalHeightPlate: number;
  rotation: number;
  yLdu?: number;
  moduleId?: string;
  moduleStage?: string;
};

export type LegoColorMapping = {
  sourceRgb: string;
  colorId: number;
  colorName: string;
  colorRgb: string;
  ldrawColorCode: string;
};

export type LegoTerrainModule = {
  id: string;
  moduleType: string;
  originX: number;
  originZ: number;
  originYPlate: number;
  width: number;
  depth: number;
  heightPlate: number;
  wallThickness: number;
};

export type LegoBomItem = {
  key: string;
  partId: string;
  rebrickablePartNum: string | null;
  legoDesignId: string | null;
  colorId: number;
  colorName: string;
  colorRgb: string;
  ldrawColorCode: string;
  width: number;
  height: number;
  quantity: number;
};

export type LegoDesignResult = {
  width: number;
  height: number;
  placements: LegoPlacement[];
  bom: LegoBomItem[];
  colorMappings: LegoColorMapping[];
  modules?: LegoTerrainModule[];
  modelDimensions: LegoModelDimensions;
};

export type LegoModelDimensions = {
  lengthStud: number;
  widthStud: number;
  heightPlate: number;
  lengthCm: number;
  widthCm: number;
  heightCm: number;
};

export type LegoDesignJob = {
  jobId: string;
  status: string;
  progress: number;
  projectId: string;
  result: LegoDesignResult | null;
  error: string | null;
};

export async function loadLegoDesignMetadata(): Promise<LegoDesignMetadata> {
  const response = await fetch(legoDesignConfig.metadataApiUrl);
  if (!response.ok) {
    throw new Error(legoDesignConfig.texts.metadataFailed);
  }
  return (await response.json()) as LegoDesignMetadata;
}

export async function createLegoDesignJob(projectId: string): Promise<LegoDesignJob> {
  const response = await fetch(legoDesignConfig.jobsApiUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ projectId }),
  });
  if (!response.ok) {
    throw new Error(legoDesignConfig.texts.designFailed);
  }
  return (await response.json()) as LegoDesignJob;
}

export async function loadLegoDesignJob(jobId: string): Promise<LegoDesignJob> {
  const response = await fetch(
    legoDesignConfig.jobApiUrl.replace(legoDesignConfig.routePlaceholders.jobId, jobId),
  );
  if (!response.ok) {
    throw new Error(legoDesignConfig.texts.designFailed);
  }
  return (await response.json()) as LegoDesignJob;
}

export async function exportLegoDesign(
  jobId: string,
  includeSupportBase: boolean,
): Promise<{ blob: Blob; fileName: string }> {
  const url = new URL(
    legoDesignConfig.exportApiUrl.replace(legoDesignConfig.routePlaceholders.jobId, jobId),
    window.location.origin,
  );
  url.searchParams.set(legoDesignConfig.supportBase.queryParam, String(includeSupportBase));
  const response = await fetch(`${url.pathname}${url.search}`);
  if (!response.ok) {
    throw new Error(legoDesignConfig.texts.exportFailed);
  }
  return {
    blob: await response.blob(),
    fileName: responseFileName(response, legoDesignConfig.download.defaultFileName),
  };
}

export async function exportLegoDesignPlan(
  jobId: string,
  includeSupportBase: boolean,
): Promise<{ blob: Blob; fileName: string }> {
  const url = new URL(
    legoDesignConfig.exportPlanApiUrl.replace(legoDesignConfig.routePlaceholders.jobId, jobId),
    window.location.origin,
  );
  url.searchParams.set(legoDesignConfig.supportBase.queryParam, String(includeSupportBase));
  const response = await fetch(`${url.pathname}${url.search}`);
  if (!response.ok) {
    throw new Error(legoDesignConfig.texts.exportPlanFailed);
  }
  return {
    blob: await response.blob(),
    fileName: responseFileName(response, legoDesignConfig.download.defaultPlanFileName),
  };
}

function responseFileName(response: Response, defaultFileName: string): string {
  const disposition = response.headers.get(legoDesignConfig.download.contentDispositionHeader);
  const parameter = legoDesignConfig.download.fileNameParameter;
  if (!disposition || !disposition.includes(parameter)) {
    return defaultFileName;
  }
  return disposition.split(parameter)[legoDesignConfig.pagination.pageStep]?.split('"').join('')
    ?? defaultFileName;
}

export async function loadLegoDesignPixelProjects(page: number): Promise<PixelArtProjectList> {
  const url = new URL(legoDesignConfig.projectsApiUrl, window.location.origin);
  url.searchParams.set('page', String(page));
  url.searchParams.set('page_size', String(legoDesignConfig.pageSize));
  const response = await fetch(`${url.pathname}${url.search}`);
  if (!response.ok) {
    throw new Error(legoDesignConfig.texts.loadFailed);
  }
  return (await response.json()) as PixelArtProjectList;
}

export async function loadLegoDesignPixelProject(projectId: string): Promise<PixelArtProject> {
  const response = await fetch(
    legoDesignConfig.projectApiUrl.replace(
      legoDesignConfig.routePlaceholders.projectId,
      projectId,
    ),
  );
  if (!response.ok) {
    throw new Error(legoDesignConfig.texts.projectFailed);
  }
  return (await response.json()) as PixelArtProject;
}
