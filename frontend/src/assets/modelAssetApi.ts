import { apiFetch, requestJson } from '../api/client';

export type ModelAsset = {
  id: string;
  name: string;
  contentLocale: 'zh-CN' | 'en-US';
  modelType: string;
  sourceType: string;
  sourceName: string;
  assetPath: string;
  previewPath: string | null;
  status: string;
  columns: number | null;
  rows: number | null;
  minElevation: number | null;
  maxElevation: number | null;
  validSampleCount: number | null;
  metadata: Record<string, unknown> | null;
  createdAt: string;
};

export type ModelAssetPage = {
  page: number;
  pageSize: number;
  total: number;
  items: ModelAsset[];
};

export async function loadModelAssetPage(
  apiUrl: string,
  page: number,
  pageSize: number,
): Promise<ModelAssetPage> {
  const url = new URL(apiUrl, window.location.origin);
  url.searchParams.set('page', String(page));
  url.searchParams.set('page_size', String(pageSize));
  return requestJson<ModelAssetPage>(url);
}

export async function deleteModelAsset(apiUrl: string, assetId: string): Promise<void> {
  await apiFetch(`${apiUrl}/${encodeURIComponent(assetId)}`, {
    method: 'DELETE',
  });
}
