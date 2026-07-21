import type { ModelAsset } from '../assets/modelAssetApi';
import { requestJson } from '../api/client';
import { currentTaskContext } from '../api/taskContext';

export async function uploadMeshModel(
  apiUrl: string,
  name: string,
  model: File,
): Promise<ModelAsset> {
  const formData = new FormData();
  formData.append('name', name);
  formData.append('contentLocale', currentTaskContext().locale);
  formData.append('model', model);
  return requestJson<ModelAsset>(apiUrl, {
    method: 'POST',
    body: formData,
  });
}

export function meshModelFileUrl(
  apiUrl: string,
  placeholder: string,
  modelId: string,
): string {
  return apiUrl.replace(placeholder, encodeURIComponent(modelId));
}
