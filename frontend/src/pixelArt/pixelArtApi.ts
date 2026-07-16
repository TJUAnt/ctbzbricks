import pixelArtConfig from './pixelArtConfig.json';

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
  const response = await fetch(`${url.pathname}${url.search}`);
  if (!response.ok) {
    const errorBody = (await response.json()) as { detail?: string };
    throw new Error(errorBody.detail ?? response.statusText);
  }
  return (await response.json()) as PixelArtProjectList;
}

export async function savePixelArtProject(
  name: string,
  image: File,
  settings: PixelArtSettings,
): Promise<PixelArtProject> {
  const formData = new FormData();
  formData.append(pixelArtConfig.request.formKeys.name, name);
  formData.append(pixelArtConfig.request.formKeys.settings, JSON.stringify(settings));
  formData.append(pixelArtConfig.request.formKeys.image, image);

  const response = await fetch(pixelArtConfig.projectsApiUrl, {
    method: pixelArtConfig.request.method,
    body: formData,
  });
  if (!response.ok) {
    const errorBody = (await response.json()) as { detail?: string };
    throw new Error(errorBody.detail ?? response.statusText);
  }
  return (await response.json()) as PixelArtProject;
}

export async function updatePixelArtProjectPixels(
  project: PixelArtProject,
): Promise<PixelArtProject> {
  const response = await fetch(
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
  if (!response.ok) {
    const errorBody = (await response.json()) as { detail?: string };
    throw new Error(errorBody.detail ?? response.statusText);
  }
  return (await response.json()) as PixelArtProject;
}
