import { requestJson } from '../api/client';
import { currentTaskContext, type TaskContext } from '../api/taskContext';
import type { TerrainAsset, TerrainJob, TerrainModelMetadata } from './terrainTypes';

export type TerrainUploadPayload = TaskContext & {
  source_name: string;
  geojson: Record<string, unknown>;
  dem_dataset_key: string;
};

export type TerrainGeojsonMergeConfig = {
  typeKey: string;
  featuresKey: string;
  featureCollectionType: string;
};

export type TerrainGeojsonInfoConfig = TerrainGeojsonMergeConfig & {
  propertiesKey: string;
  modelNamePropertyKeys: string[];
  modelNameEmptyValue: string;
  propertyValueLimit: number;
  nullValue: string;
  arrayValue: string;
  objectValue: string;
  emptyValue: string;
};

export type TerrainGeojsonPropertyInfo = {
  key: string;
  value: string;
};

export type TerrainGeojsonFileInfo = {
  sourceName: string;
  properties: TerrainGeojsonPropertyInfo[];
};

export function combineGeojsonFeatureCollections(
  geojsonDocuments: unknown[],
  config: TerrainGeojsonMergeConfig,
  invalidGeojsonMessage: string,
): Record<string, unknown> {
  return {
    [config.typeKey]: config.featureCollectionType,
    [config.featuresKey]: geojsonDocuments.flatMap((geojsonDocument) =>
      featureCollectionFeatures(geojsonDocument, config, invalidGeojsonMessage),
    ),
  };
}

export function createTerrainUploadPayload(
  sourceName: string,
  geojson: unknown,
  demDatasetKey: string,
  invalidGeojsonMessage: string,
): TerrainUploadPayload {
  if (!geojson || typeof geojson !== 'object' || Array.isArray(geojson)) {
    throw new Error(invalidGeojsonMessage);
  }
  return {
    source_name: sourceName,
    geojson: geojson as Record<string, unknown>,
    dem_dataset_key: demDatasetKey,
    ...currentTaskContext(),
  };
}

export function summarizeGeojsonDocuments(
  geojsonDocuments: unknown[],
  sourceNames: string[],
  config: TerrainGeojsonInfoConfig,
  invalidGeojsonMessage: string,
): TerrainGeojsonFileInfo[] {
  return geojsonDocuments.map((geojsonDocument, documentIndex) =>
    summarizeGeojsonDocument(
      geojsonDocument,
      sourceNames[documentIndex],
      config,
      invalidGeojsonMessage,
    ),
  );
}

export function geojsonModelName(
  geojsonDocuments: unknown[],
  config: TerrainGeojsonInfoConfig,
  invalidGeojsonMessage: string,
): string {
  for (const geojsonDocument of geojsonDocuments) {
    const features = featureCollectionFeatures(geojsonDocument, config, invalidGeojsonMessage);
    for (const feature of features) {
      if (!isRecord(feature)) {
        continue;
      }
      const properties = feature[config.propertiesKey];
      if (!isRecord(properties)) {
        continue;
      }
      for (const propertyKey of config.modelNamePropertyKeys) {
        const propertyValue = properties[propertyKey];
        if (typeof propertyValue === 'string' && propertyValue.trim()) {
          return propertyValue.trim();
        }
      }
    }
  }
  return config.modelNameEmptyValue;
}

export async function createTerrainJob(
  apiUrl: string,
  payload: TerrainUploadPayload,
): Promise<TerrainJob> {
  return requestJson<TerrainJob>(apiUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function loadTerrainJob(apiUrl: string): Promise<TerrainJob> {
  return requestJson<TerrainJob>(apiUrl);
}

export async function loadTerrainModels(apiUrl: string): Promise<TerrainModelMetadata[]> {
  const response = await requestJson<{ models: TerrainModelMetadata[] }>(apiUrl);
  return response.models;
}

export async function loadTerrainModel(
  apiUrl: string,
  expectedSchema: string,
  invalidAssetMessage: string,
): Promise<TerrainAsset> {
  const asset = await requestJson<TerrainAsset>(apiUrl);
  if (asset.schema !== expectedSchema) {
    throw new Error(invalidAssetMessage);
  }
  return asset;
}

export async function saveTerrainModel(
  apiUrl: string,
  name: string,
  asset: TerrainAsset,
): Promise<TerrainModelMetadata> {
  return requestJson<TerrainModelMetadata>(apiUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, asset, contentLocale: currentTaskContext().locale }),
  });
}

export function routeWithParam(template: string, placeholder: string, value: string): string {
  return template.replace(placeholder, encodeURIComponent(value));
}

function featureCollectionFeatures(
  geojsonDocument: unknown,
  config: TerrainGeojsonMergeConfig,
  invalidGeojsonMessage: string,
): unknown[] {
  if (!geojsonDocument || typeof geojsonDocument !== 'object' || Array.isArray(geojsonDocument)) {
    throw new Error(invalidGeojsonMessage);
  }
  const featureCollection = geojsonDocument as Record<string, unknown>;
  const features = featureCollection[config.featuresKey];
  if (
    featureCollection[config.typeKey] !== config.featureCollectionType ||
    !Array.isArray(features)
  ) {
    throw new Error(invalidGeojsonMessage);
  }
  return features;
}

function summarizeGeojsonDocument(
  geojsonDocument: unknown,
  sourceName: string,
  config: TerrainGeojsonInfoConfig,
  invalidGeojsonMessage: string,
): TerrainGeojsonFileInfo {
  const features = featureCollectionFeatures(geojsonDocument, config, invalidGeojsonMessage);
  const propertiesInfo: TerrainGeojsonPropertyInfo[] = [];
  features.forEach((feature) => {
    if (!isRecord(feature)) {
      return;
    }
    const properties = feature[config.propertiesKey];
    if (!isRecord(properties)) {
      return;
    }
    Object.entries(properties).forEach(([key, value]) => {
      if (propertiesInfo.length < config.propertyValueLimit) {
        propertiesInfo.push({
          key,
          value: geojsonPropertyValue(value, config),
        });
      }
    });
  });
  return {
    sourceName,
    properties: propertiesInfo,
  };
}

function geojsonPropertyValue(value: unknown, config: TerrainGeojsonInfoConfig): string {
  if (value === null) {
    return config.nullValue;
  }
  if (Array.isArray(value)) {
    return config.arrayValue;
  }
  if (typeof value === 'object') {
    return config.objectValue;
  }
  if (typeof value === 'string') {
    return value || config.emptyValue;
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return config.emptyValue;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}
