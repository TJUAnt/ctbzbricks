import type { ModelAsset } from '../assets/modelAssetApi';

export async function uploadMeshModel(
  apiUrl: string,
  name: string,
  model: File,
): Promise<ModelAsset> {
  const formData = new FormData();
  formData.append('name', name);
  formData.append('model', model);
  const response = await fetch(apiUrl, {
    method: 'POST',
    body: formData,
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return (await response.json()) as ModelAsset;
}

export function meshModelFileUrl(
  apiUrl: string,
  placeholder: string,
  modelId: string,
): string {
  return apiUrl.replace(placeholder, encodeURIComponent(modelId));
}
