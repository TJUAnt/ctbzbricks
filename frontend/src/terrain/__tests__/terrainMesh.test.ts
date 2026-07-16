import { describe, expect, it } from 'vitest';
import {
  combinedTerrainBounds,
  coordinateToScene,
  createBoundaryLines,
  createTerrainMeshData,
  createTerrainSceneFrame,
  createTerrainSceneScale,
} from '../terrainMesh';
import type { TerrainAsset, TerrainSceneConfig } from '../terrainTypes';

const TEST_SCENE: TerrainSceneConfig = {
  maxTerrainWidth: 4,
  maxTerrainDepth: 2,
  defaultVerticalExaggeration: 2,
  latitudeMetersPerDegree: 100,
  radiansPerDegree: Math.PI / 180,
  boundaryElevation: 0.2,
  colorRamp: {
    low: '#000000',
    mid: '#808080',
    high: '#ffffff',
  },
};

const TEST_ASSET: TerrainAsset = {
  schema: 'terrain-dem-v1',
  source: 'test',
  columns: 3,
  rows: 2,
  bounds: {
    west: 120,
    south: 20,
    east: 122,
    north: 21,
  },
  minElevation: 10,
  maxElevation: 30,
  renderOptions: {
    verticalExaggeration: 2,
  },
  elevations: [10, 20, null, 15, 25, 30],
  boundary: [[[[120, 20], [122, 20], [122, 21], [120, 21], [120, 20]]]],
};

const NEGATIVE_ELEVATION_ASSET: TerrainAsset = {
  ...TEST_ASSET,
  minElevation: -10,
  maxElevation: 30,
  elevations: [-10, 0, 10, -5, 5, 30],
};

const EAST_ASSET: TerrainAsset = {
  ...TEST_ASSET,
  bounds: {
    west: 122,
    south: 20,
    east: 124,
    north: 21,
  },
  boundary: [[[[122, 20], [124, 20], [124, 21], [122, 21], [122, 20]]]],
};

const TWO_CORNER_ASSET: TerrainAsset = {
  ...TEST_ASSET,
  elevations: [10, null, null, 15, null, null],
};

const LAND_COVER_ASSET: TerrainAsset = {
  ...TEST_ASSET,
  landCover: [60, 60, null, 60, 60, 60],
  landCoverLegend: {
    '60': {
      label: 'Bare',
      color: '#ff0000',
    },
  },
};

describe('terrain mesh helpers', () => {
  it('maps coordinates to centered scene space', () => {
    expect(coordinateToScene(121, 20.5, TEST_ASSET.bounds, 4, 2, 1)).toEqual({
      x: 0,
      y: 1,
      z: 0,
    });
  });

  it('maps west to negative x and east to positive x', () => {
    expect(coordinateToScene(120, 20.5, TEST_ASSET.bounds, 4, 2, 1).x).toBe(-2);
    expect(coordinateToScene(122, 20.5, TEST_ASSET.bounds, 4, 2, 1).x).toBe(2);
  });

  it('maps north to negative z and south to positive z', () => {
    expect(coordinateToScene(121, 21, TEST_ASSET.bounds, 4, 2, 1).z).toBe(-1);
    expect(coordinateToScene(121, 20, TEST_ASSET.bounds, 4, 2, 1).z).toBe(1);
  });

  it('keeps terrain cells with one missing elevation sample as one triangle', () => {
    const frame = createTerrainSceneFrame(
      TEST_ASSET.bounds,
      TEST_ASSET.renderOptions!.verticalExaggeration,
      TEST_SCENE,
    );
    const meshData = createTerrainMeshData(TEST_ASSET, TEST_SCENE, frame);
    expect(meshData.validSampleCount).toBe(5);
    expect(meshData.triangleCount).toBe(3);
    expect(meshData.positions.length).toBe(27);
    expect(meshData.colors.length).toBe(27);
  });

  it('uses land cover colors when terrain assets include WorldCover classes', () => {
    const frame = createTerrainSceneFrame(
      LAND_COVER_ASSET.bounds,
      LAND_COVER_ASSET.renderOptions!.verticalExaggeration,
      TEST_SCENE,
    );
    const meshData = createTerrainMeshData(LAND_COVER_ASSET, TEST_SCENE, frame);
    const colors = Array.from(meshData.colors);
    for (let colorIndex = 0; colorIndex < colors.length; colorIndex += 3) {
      expect(colors[colorIndex]).toBe(1);
      expect(colors[colorIndex + 1]).toBe(0);
      expect(colors[colorIndex + 2]).toBe(0);
    }
  });

  it('skips terrain cells with fewer than three elevation samples', () => {
    const frame = createTerrainSceneFrame(
      TWO_CORNER_ASSET.bounds,
      TWO_CORNER_ASSET.renderOptions!.verticalExaggeration,
      TEST_SCENE,
    );
    const meshData = createTerrainMeshData(TWO_CORNER_ASSET, TEST_SCENE, frame);
    expect(meshData.validSampleCount).toBe(2);
    expect(meshData.triangleCount).toBe(0);
    expect(meshData.positions.length).toBe(0);
    expect(meshData.colors.length).toBe(0);
  });

  it('scales scene dimensions from geographic meters and vertical exaggeration', () => {
    const scale = createTerrainSceneScale(TEST_ASSET, TEST_SCENE);
    expect(scale.terrainWidth).toBeCloseTo(3.7467, 4);
    expect(scale.terrainDepth).toBe(2);
    expect(scale.elevationScale).toBe(0.04);
  });

  it('creates one line for each boundary ring', () => {
    const frame = createTerrainSceneFrame(
      TEST_ASSET.bounds,
      TEST_ASSET.renderOptions!.verticalExaggeration,
      TEST_SCENE,
    );
    const lines = createBoundaryLines(TEST_ASSET, TEST_SCENE, frame);
    expect(lines).toHaveLength(1);
    expect(lines[0]).toHaveLength(15);
  });

  it('places negative elevations below sea level instead of lifting terrain to zero', () => {
    const frame = createTerrainSceneFrame(
      NEGATIVE_ELEVATION_ASSET.bounds,
      NEGATIVE_ELEVATION_ASSET.renderOptions!.verticalExaggeration,
      TEST_SCENE,
    );
    const meshData = createTerrainMeshData(NEGATIVE_ELEVATION_ASSET, TEST_SCENE, frame);
    const yValues = Array.from(meshData.positions).filter((_, index) => index % 3 === 1);
    expect(yValues.some((value) => value < 0)).toBe(true);
    expect(yValues.some((value) => value === 0)).toBe(true);
  });

  it('uses combined bounds to keep multiple terrain assets in one geographic frame', () => {
    const frame = createTerrainSceneFrame(
      combinedTerrainBounds([TEST_ASSET, EAST_ASSET]),
      TEST_ASSET.renderOptions!.verticalExaggeration,
      TEST_SCENE,
    );
    const westMesh = createTerrainMeshData(TEST_ASSET, TEST_SCENE, frame);
    const eastMesh = createTerrainMeshData(EAST_ASSET, TEST_SCENE, frame);
    const westXValues = Array.from(westMesh.positions).filter((_, index) => index % 3 === 0);
    const eastXValues = Array.from(eastMesh.positions).filter((_, index) => index % 3 === 0);
    expect(Math.max(...westXValues)).toBeLessThanOrEqual(Math.min(...eastXValues));
  });
});
