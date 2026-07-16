import { describe, expect, it } from 'vitest';
import { createLegoHeightmapAsset } from '../legoHeightmapAsset';
import { createLegoHeightmap, terrainBoundsSize } from '../legoHeightmap';
import type { TerrainAsset } from '../../terrain/terrainTypes';

const TEST_HEIGHTMAP_CONFIG = {
  latitudeMetersPerDegree: 1000,
  radiansPerDegree: 0,
  metersPerKilometer: 1000,
  kilometersPerMeter: 0.001,
  coordinateAverageDivisor: 2,
  minimumStudCount: 1,
  minimumPlateHeight: 0,
  emptyElevationHeightPlate: 0,
  coveragePrecision: 100,
  aggregation: {
    percentile: 'percentile',
    mean: 'mean',
    max: 'max',
  },
  percentileRatio: 0.75,
  invalidAggregationMessage: 'unsupported aggregation',
};

const TEST_SCALE = {
  horizontalKmPerStud: 1,
  verticalMetersPerPlate: 10,
  aggregation: TEST_HEIGHTMAP_CONFIG.aggregation.percentile,
  minCoverageRatio: 0,
};

const TEST_ASSET: TerrainAsset = {
  schema: 'terrain-dem-v1',
  source: 'test',
  columns: 3,
  rows: 3,
  bounds: {
    west: 0,
    south: 0,
    east: 2,
    north: 2,
  },
  minElevation: 0,
  maxElevation: 80,
  elevations: [0, 10, 20, 30, null, 50, 60, 70, 80],
  landCover: [60, 70, 70, 60, null, 70, 60, 70, 70],
  landCoverLegend: {
    60: { label: 'Bare', color: '#bfa77a' },
    70: { label: 'Snow', color: '#f2f7fb' },
  },
  boundary: [],
};

describe('lego heightmap', () => {
  it('computes geographic bounds size in kilometers', () => {
    expect(terrainBoundsSize(TEST_ASSET.bounds, TEST_HEIGHTMAP_CONFIG)).toEqual({
      widthKm: 2,
      depthKm: 2,
    });
  });

  it('aggregates DEM samples into LEGO stud cells', () => {
    const heightmap = createLegoHeightmap(TEST_ASSET, TEST_SCALE, TEST_HEIGHTMAP_CONFIG);
    expect(heightmap.metrics.widthStud).toBe(2);
    expect(heightmap.metrics.depthStud).toBe(2);
    expect(heightmap.metrics.totalCellCount).toBe(4);
    expect(heightmap.metrics.validCellCount).toBe(4);
    expect(heightmap.cells.map((cell) => cell.heightPlate)).toEqual([0, 2, 6, 8]);
    expect(heightmap.cells.map((cell) => cell.landCoverCode)).toEqual([60, 70, 60, 70]);
    expect(heightmap.cells[0].landCoverColor).toBe('#bfa77a');
  });

  it('marks cells below configured coverage as empty', () => {
    const heightmap = createLegoHeightmap(
      TEST_ASSET,
      {
        ...TEST_SCALE,
        minCoverageRatio: 1,
      },
      TEST_HEIGHTMAP_CONFIG,
    );
    expect(heightmap.metrics.validCellCount).toBe(3);
    expect(heightmap.cells[3].elevationMeters).toBeNull();
    expect(heightmap.cells[3].heightPlate).toBe(TEST_HEIGHTMAP_CONFIG.emptyElevationHeightPlate);
  });

  it('creates a saveable LEGO heightmap asset', () => {
    const heightmap = createLegoHeightmap(TEST_ASSET, TEST_SCALE, TEST_HEIGHTMAP_CONFIG);
    const asset = createLegoHeightmapAsset(heightmap, 'test.geojson', 'lego-heightmap-v1');
    expect(asset.schema).toBe('lego-heightmap-v1');
    expect(asset.source).toBe('test.geojson');
    expect(asset.metrics.widthStud).toBe(heightmap.metrics.widthStud);
    expect(asset.cells).toHaveLength(heightmap.cells.length);
  });
});
