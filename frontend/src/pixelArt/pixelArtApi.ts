import { requestJson } from '../api/client';
import pixelArtConfig from './pixelArtConfig';
import { currentTaskContext } from '../api/taskContext';

export type PixelArtCrop = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type PixelArtPreprocessing = {
  brightness: number;
  contrast: number;
  saturation: number;
  sharpness: number;
  localContrast: number;
  preserveLightDetails: boolean;
};

export type PixelArtSettings = {
  algorithm: string;
  gridWidth: number;
  gridHeight: number;
  colorCount: number;
  crop: PixelArtCrop;
  preprocessing: PixelArtPreprocessing;
};

export type PixelCell = {
  x: number;
  y: number;
  colorIndex: number;
  rgb: string;
  sourceColor?: string;
  quantizedColor?: string;
  featureScore?: number;
  edgeStrength?: number;
  localContrast?: number;
  sidePixelWidthPlates?: number;
  sidePixelHeightPlates?: number;
  sidePartWidthPlates?: number;
  sidePartHeightPlates?: number;
  sidePartType?: string;
  sidePartRole?: string;
  modified?: boolean;
  locked?: boolean;
};

export type PixelPaletteColor = {
  colorIndex: number;
  rgb: string;
  count: number;
};

export type PixelArtProject = {
  modelId: string;
  name: string;
  contentLocale: 'zh-CN' | 'en-US';
  source: string;
  createdAt: string;
  schema: string;
  gridWidth: number;
  gridHeight: number;
  colorCount: number;
  palette: PixelPaletteColor[];
  pixels: PixelCell[];
  previewImage: string;
};

export type PixelArtProjectSummary = {
  modelId: string;
  name: string;
  contentLocale: 'zh-CN' | 'en-US';
  source: string;
  createdAt: string;
  gridWidth: number;
  gridHeight: number;
  colorCount: number;
  previewImage: string;
};

export type PixelArtProjectList = {
  page: number;
  pageSize: number;
  total: number;
  items: PixelArtProjectSummary[];
};

export async function loadPixelArtProjects(page: number, pageSize: number): Promise<PixelArtProjectList> {
  const url = new URL(pixelArtConfig.projectsApiUrl, window.location.origin);
  url.searchParams.set('page', String(page));
  url.searchParams.set('page_size', String(pageSize));
  return requestJson<PixelArtProjectList>(`${url.pathname}${url.search}`);
}

export async function savePixelArtProject(
  name: string,
  image: File,
  settings: PixelArtSettings,
): Promise<PixelArtProject> {
  const formData = new FormData();
  formData.append(pixelArtConfig.request.formKeys.name, name);
  formData.append(pixelArtConfig.request.formKeys.contentLocale, currentTaskContext().locale);
  formData.append(pixelArtConfig.request.formKeys.settings, JSON.stringify(settings));
  formData.append(pixelArtConfig.request.formKeys.image, image);

  return requestJson<PixelArtProject>(pixelArtConfig.projectsApiUrl, {
    method: pixelArtConfig.request.method,
    body: formData,
  });
}

export async function updatePixelArtProjectPixels(
  project: PixelArtProject,
): Promise<PixelArtProject> {
  return requestJson<PixelArtProject>(
    pixelArtConfig.projectPixelsApiUrl.replace(
      pixelArtConfig.routePlaceholders.projectId,
      project.modelId,
    ),
    {
      method: pixelArtConfig.request.updateMethod,
      headers: {
        [pixelArtConfig.request.contentTypeHeader]: pixelArtConfig.request.jsonContentType,
      },
      body: JSON.stringify({
        palette: project.palette,
        pixels: project.pixels,
      }),
    },
  );
}
