import { apiFetch, requestJson } from '../api/client';
import type { StructuredMessage } from '../api/client';
import { currentTaskContext } from '../api/taskContext';
import type { PixelArtProject, PixelArtProjectList } from '../pixelArt/pixelArtApi';
import legoDesignConfig from './legoDesignConfig';

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
  progress: StructuredMessage & { percent: number };
  projectId: string;
  result: LegoDesignResult | null;
  error: StructuredMessage | null;
  locale: string;
  timezone: string;
  catalogVersion: string;
};

export async function loadLegoDesignMetadata(): Promise<LegoDesignMetadata> {
  return requestJson<LegoDesignMetadata>(legoDesignConfig.metadataApiUrl);
}

export async function createLegoDesignJob(projectId: string): Promise<LegoDesignJob> {
  return requestJson<LegoDesignJob>(legoDesignConfig.jobsApiUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ projectId, ...currentTaskContext() }),
  });
}

export async function loadLegoDesignJob(jobId: string): Promise<LegoDesignJob> {
  return requestJson<LegoDesignJob>(
    legoDesignConfig.jobApiUrl.replace(legoDesignConfig.routePlaceholders.jobId, jobId),
  );
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
  const response = await apiFetch(`${url.pathname}${url.search}`);
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
  const response = await apiFetch(`${url.pathname}${url.search}`);
  return {
    blob: await response.blob(),
    fileName: responseFileName(response, legoDesignConfig.download.defaultPlanFileName),
  };
}

export function responseFileName(response: Response, defaultFileName: string): string {
  const disposition = response.headers.get(legoDesignConfig.download.contentDispositionHeader);
  if (!disposition) {
    return defaultFileName;
  }
  const encodedMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (encodedMatch?.[1]) {
    try {
      return decodeURIComponent(encodedMatch[1]);
    } catch {
      return defaultFileName;
    }
  }
  const plainMatch = disposition.match(/filename="?([^";]+)"?/i);
  return plainMatch?.[1] ?? defaultFileName;
}

export async function loadLegoDesignPixelProjects(page: number): Promise<PixelArtProjectList> {
  const url = new URL(legoDesignConfig.projectsApiUrl, window.location.origin);
  url.searchParams.set('page', String(page));
  url.searchParams.set('page_size', String(legoDesignConfig.pageSize));
  return requestJson<PixelArtProjectList>(`${url.pathname}${url.search}`);
}

export async function loadLegoDesignPixelProject(projectId: string): Promise<PixelArtProject> {
  return requestJson<PixelArtProject>(
    legoDesignConfig.projectApiUrl.replace(
      legoDesignConfig.routePlaceholders.projectId,
      projectId,
    ),
  );
}
