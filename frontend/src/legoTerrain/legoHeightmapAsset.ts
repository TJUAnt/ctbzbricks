import { requestJson } from '../api/client';
import type { LegoHeightmap } from './legoHeightmap';
import { currentTaskContext } from '../api/taskContext';

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
  return requestJson<LegoHeightmapModelMetadata>(apiUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name,
      asset: { ...asset, name },
      contentLocale: currentTaskContext().locale,
    }),
  });
}

export async function loadLegoHeightmapModel(
  apiUrl: string,
  expectedSchema: string,
  invalidAssetMessage: string,
): Promise<LegoHeightmapAsset> {
  const asset = await requestJson<LegoHeightmapAsset>(apiUrl);
  if (asset.schema !== expectedSchema) {
    throw new Error(invalidAssetMessage);
  }
  return asset;
}
