import type { LegoHeightmap } from './legoHeightmap';

export type LegoHeightmapAsset = LegoHeightmap & {
  schema: string;
  source: string;
  name?: string;
  modelId?: string;
  createdAt?: string;
};

export type LegoHeightmapModelMetadata = {
  modelId: string;
  name: string;
  source: string;
  createdAt: string;
  columns: number;
  rows: number;
  maxHeightPlate: number;
  validCellCount: number;
  totalCellCount: number;
};

export function createLegoHeightmapAsset(
  heightmap: LegoHeightmap,
  source: string,
  schema: string,
): LegoHeightmapAsset {
  return {
    schema,
    source,
    bounds: heightmap.bounds,
    scale: heightmap.scale,
    cells: heightmap.cells,
    metrics: heightmap.metrics,
  };
}

export async function saveLegoHeightmapModel(
  apiUrl: string,
  name: string,
  asset: LegoHeightmapAsset,
): Promise<LegoHeightmapModelMetadata> {
  const response = await fetch(apiUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, asset: { ...asset, name } }),
  });
  if (!response.ok) {
    const errorBody = (await response.json()) as { detail?: string };
    throw new Error(errorBody.detail ?? response.statusText);
  }
  return (await response.json()) as LegoHeightmapModelMetadata;
}

export async function loadLegoHeightmapModel(
  apiUrl: string,
  expectedSchema: string,
  invalidAssetMessage: string,
): Promise<LegoHeightmapAsset> {
  const response = await fetch(apiUrl);
  if (!response.ok) {
    const errorBody = (await response.json()) as { detail?: string };
    throw new Error(errorBody.detail ?? response.statusText);
  }
  const asset = (await response.json()) as LegoHeightmapAsset;
  if (asset.schema !== expectedSchema) {
    throw new Error(invalidAssetMessage);
  }
  return asset;
}
