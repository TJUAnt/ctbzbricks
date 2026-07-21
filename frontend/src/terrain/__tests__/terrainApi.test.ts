import { describe, expect, it } from 'vitest';
import {
  combineGeojsonFeatureCollections,
  createTerrainUploadPayload,
  geojsonModelName,
  routeWithParam,
  summarizeGeojsonDocuments,
} from '../terrainApi';

const TEST_API_CONFIG = {
  sourceName: 'custom.geojson',
  demDatasetKey: 'dem_250m',
  invalidGeojsonMessage: 'invalid geojson',
  routeTemplate: '/api/terrain/dem/jobs/{jobId}',
  routePlaceholder: '{jobId}',
  routeValue: 'abc 123',
  geojson: {
    typeKey: 'type',
    featuresKey: 'features',
    featureCollectionType: 'FeatureCollection',
    propertiesKey: 'properties',
    modelNamePropertyKeys: ['name'],
    modelNameEmptyValue: '',
    propertyValueLimit: 4,
    nullValue: 'null',
    arrayValue: '[array]',
    objectValue: '[object]',
    emptyValue: '-',
    firstFeatureId: 'first',
    secondFeatureId: 'second',
  },
};

describe('terrain api helpers', () => {
  it('creates upload payload with source name and geojson object', () => {
    const geojson = { type: 'FeatureCollection', features: [] };
    const payload = createTerrainUploadPayload(
      TEST_API_CONFIG.sourceName,
      geojson,
      TEST_API_CONFIG.demDatasetKey,
      TEST_API_CONFIG.invalidGeojsonMessage,
    );
    expect(payload).toMatchObject({
      source_name: TEST_API_CONFIG.sourceName,
      geojson,
      dem_dataset_key: TEST_API_CONFIG.demDatasetKey,
    });
    expect(["zh-CN", "en-US"]).toContain(payload.locale);
    expect(payload.timezone).not.toBe("");
  });

  it('rejects non-object geojson payloads', () => {
    expect(() =>
      createTerrainUploadPayload(
        TEST_API_CONFIG.sourceName,
        null,
        TEST_API_CONFIG.demDatasetKey,
        TEST_API_CONFIG.invalidGeojsonMessage,
      ),
    ).toThrow(TEST_API_CONFIG.invalidGeojsonMessage);
  });

  it('replaces encoded route parameters', () => {
    expect(
      routeWithParam(
        TEST_API_CONFIG.routeTemplate,
        TEST_API_CONFIG.routePlaceholder,
        TEST_API_CONFIG.routeValue,
      ),
    ).toBe('/api/terrain/dem/jobs/abc%20123');
  });

  it('combines multiple geojson feature collections into one feature collection', () => {
    const firstFeature = { id: TEST_API_CONFIG.geojson.firstFeatureId };
    const secondFeature = { id: TEST_API_CONFIG.geojson.secondFeatureId };
    const combinedGeojson = combineGeojsonFeatureCollections(
      [
        {
          [TEST_API_CONFIG.geojson.typeKey]: TEST_API_CONFIG.geojson.featureCollectionType,
          [TEST_API_CONFIG.geojson.featuresKey]: [firstFeature],
        },
        {
          [TEST_API_CONFIG.geojson.typeKey]: TEST_API_CONFIG.geojson.featureCollectionType,
          [TEST_API_CONFIG.geojson.featuresKey]: [secondFeature],
        },
      ],
      TEST_API_CONFIG.geojson,
      TEST_API_CONFIG.invalidGeojsonMessage,
    );

    expect(combinedGeojson).toEqual({
      [TEST_API_CONFIG.geojson.typeKey]: TEST_API_CONFIG.geojson.featureCollectionType,
      [TEST_API_CONFIG.geojson.featuresKey]: [firstFeature, secondFeature],
    });
  });

  it('rejects geojson documents that are not feature collections', () => {
    expect(() =>
      combineGeojsonFeatureCollections(
        [
          {
            [TEST_API_CONFIG.geojson.typeKey]: TEST_API_CONFIG.sourceName,
            [TEST_API_CONFIG.geojson.featuresKey]: [],
          },
        ],
        TEST_API_CONFIG.geojson,
        TEST_API_CONFIG.invalidGeojsonMessage,
      ),
    ).toThrow(TEST_API_CONFIG.invalidGeojsonMessage);
  });

  it('summarizes only geojson properties for the right panel', () => {
    const summary = summarizeGeojsonDocuments(
      [
        {
          [TEST_API_CONFIG.geojson.typeKey]: TEST_API_CONFIG.geojson.featureCollectionType,
          [TEST_API_CONFIG.geojson.featuresKey]: [
            {
              [TEST_API_CONFIG.geojson.propertiesKey]: {
                name: 'Taipei',
                level: 3,
                active: true,
                tags: ['city'],
                metadata: { id: 1 },
                note: null,
              },
            },
          ],
        },
      ],
      [TEST_API_CONFIG.sourceName],
      TEST_API_CONFIG.geojson,
      TEST_API_CONFIG.invalidGeojsonMessage,
    );

    expect(summary).toEqual([
      {
        sourceName: TEST_API_CONFIG.sourceName,
        properties: [
          { key: 'name', value: 'Taipei' },
          { key: 'level', value: '3' },
          { key: 'active', value: 'true' },
          { key: 'tags', value: TEST_API_CONFIG.geojson.arrayValue },
        ],
      },
    ]);
  });

  it('reads the model name from configured geojson properties', () => {
    const modelName = geojsonModelName(
      [
        {
          [TEST_API_CONFIG.geojson.typeKey]: TEST_API_CONFIG.geojson.featureCollectionType,
          [TEST_API_CONFIG.geojson.featuresKey]: [
            {
              [TEST_API_CONFIG.geojson.propertiesKey]: {
                name: 'Taipei terrain',
              },
            },
          ],
        },
      ],
      TEST_API_CONFIG.geojson,
      TEST_API_CONFIG.invalidGeojsonMessage,
    );

    expect(modelName).toBe('Taipei terrain');
  });
});
