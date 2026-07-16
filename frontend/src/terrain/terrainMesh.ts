import type {
  TerrainAsset,
  TerrainBounds,
  TerrainMeshData,
  TerrainSceneConfig,
  TerrainSceneFrame,
  TerrainSceneScale,
} from './terrainTypes';

type ScenePoint = {
  x: number;
  y: number;
  z: number;
};

type ColorPoint = {
  r: number;
  g: number;
  b: number;
};

type TerrainCorner = {
  rowIndex: number;
  columnIndex: number;
  elevation: number;
};

export function createTerrainMeshData(
  asset: TerrainAsset,
  scene: TerrainSceneConfig,
  frame: TerrainSceneFrame,
): TerrainMeshData {
  const positions: number[] = [];
  const colors: number[] = [];
  const validSampleCount = asset.elevations.filter((elevation) => elevation !== null).length;

  for (let rowIndex = 0; rowIndex < asset.rows - 1; rowIndex += 1) {
    for (let columnIndex = 0; columnIndex < asset.columns - 1; columnIndex += 1) {
      const northWest = elevationAt(asset, rowIndex, columnIndex);
      const northEast = elevationAt(asset, rowIndex, columnIndex + 1);
      const southWest = elevationAt(asset, rowIndex + 1, columnIndex);
      const southEast = elevationAt(asset, rowIndex + 1, columnIndex + 1);

      if (northWest !== null && northEast !== null && southWest !== null && southEast !== null) {
        pushVertex(asset, scene, frame, positions, colors, rowIndex, columnIndex, northWest);
        pushVertex(asset, scene, frame, positions, colors, rowIndex + 1, columnIndex, southWest);
        pushVertex(asset, scene, frame, positions, colors, rowIndex, columnIndex + 1, northEast);
        pushVertex(asset, scene, frame, positions, colors, rowIndex, columnIndex + 1, northEast);
        pushVertex(asset, scene, frame, positions, colors, rowIndex + 1, columnIndex, southWest);
        pushVertex(
          asset,
          scene,
          frame,
          positions,
          colors,
          rowIndex + 1,
          columnIndex + 1,
          southEast,
        );
      } else if (northWest === null && northEast !== null && southWest !== null && southEast !== null) {
        pushCellTriangle(
          asset,
          scene,
          frame,
          positions,
          colors,
          corner(rowIndex, columnIndex + 1, northEast),
          corner(rowIndex + 1, columnIndex, southWest),
          corner(rowIndex + 1, columnIndex + 1, southEast),
        );
      } else if (northEast === null && northWest !== null && southWest !== null && southEast !== null) {
        pushCellTriangle(
          asset,
          scene,
          frame,
          positions,
          colors,
          corner(rowIndex, columnIndex, northWest),
          corner(rowIndex + 1, columnIndex, southWest),
          corner(rowIndex + 1, columnIndex + 1, southEast),
        );
      } else if (southWest === null && northWest !== null && northEast !== null && southEast !== null) {
        pushCellTriangle(
          asset,
          scene,
          frame,
          positions,
          colors,
          corner(rowIndex, columnIndex, northWest),
          corner(rowIndex + 1, columnIndex + 1, southEast),
          corner(rowIndex, columnIndex + 1, northEast),
        );
      } else if (southEast === null && northWest !== null && northEast !== null && southWest !== null) {
        pushCellTriangle(
          asset,
          scene,
          frame,
          positions,
          colors,
          corner(rowIndex, columnIndex, northWest),
          corner(rowIndex + 1, columnIndex, southWest),
          corner(rowIndex, columnIndex + 1, northEast),
        );
      }
    }
  }

  return {
    positions: new Float32Array(positions),
    colors: new Float32Array(colors),
    triangleCount: positions.length / 9,
    validSampleCount,
  };
}

export function createBoundaryLines(
  asset: TerrainAsset,
  scene: TerrainSceneConfig,
  frame: TerrainSceneFrame,
): Float32Array[] {
  return asset.boundary.flatMap((polygon) =>
    polygon.map((ring) => {
      const positions: number[] = [];
      for (const coordinate of ring) {
        const point = coordinateToScene(
          coordinate[0],
          coordinate[1],
          frame.bounds,
          frame.terrainWidth,
          frame.terrainDepth,
          scene.boundaryElevation,
        );
        positions.push(point.x, point.y, point.z);
      }
      return new Float32Array(positions);
    }),
  );
}

export function createTerrainSceneScale(
  asset: TerrainAsset,
  scene: TerrainSceneConfig,
): TerrainSceneScale {
  return createTerrainSceneFrame(
    asset.bounds,
    asset.renderOptions?.verticalExaggeration ?? scene.defaultVerticalExaggeration,
    scene,
  );
}

export function createTerrainSceneFrame(
  bounds: TerrainBounds,
  verticalExaggeration: number,
  scene: TerrainSceneConfig,
): TerrainSceneFrame {
  const latitudeSpan = bounds.north - bounds.south;
  const longitudeSpan = bounds.east - bounds.west;
  const middleLatitude = (bounds.north + bounds.south) / 2;
  const northSouthMeters = latitudeSpan * scene.latitudeMetersPerDegree;
  const eastWestMeters =
    longitudeSpan *
    scene.latitudeMetersPerDegree *
    Math.cos(middleLatitude * scene.radiansPerDegree);
  const terrainAspectRatio = eastWestMeters / northSouthMeters;
  const sceneAspectRatio = scene.maxTerrainWidth / scene.maxTerrainDepth;
  const terrainWidth =
    terrainAspectRatio >= sceneAspectRatio
      ? scene.maxTerrainWidth
      : scene.maxTerrainDepth * terrainAspectRatio;
  const terrainDepth =
    terrainAspectRatio >= sceneAspectRatio
      ? scene.maxTerrainWidth / terrainAspectRatio
      : scene.maxTerrainDepth;
  return {
    bounds,
    terrainWidth,
    terrainDepth,
    elevationScale: (terrainDepth / northSouthMeters) * verticalExaggeration,
  };
}

export function combinedTerrainBounds(assets: TerrainAsset[]): TerrainBounds {
  return {
    west: Math.min(...assets.map((asset) => asset.bounds.west)),
    south: Math.min(...assets.map((asset) => asset.bounds.south)),
    east: Math.max(...assets.map((asset) => asset.bounds.east)),
    north: Math.max(...assets.map((asset) => asset.bounds.north)),
  };
}

export function coordinateToScene(
  longitude: number,
  latitude: number,
  bounds: TerrainBounds,
  terrainWidth: number,
  terrainDepth: number,
  elevation: number,
): ScenePoint {
  const longitudeSpan = bounds.east - bounds.west;
  const latitudeSpan = bounds.north - bounds.south;
  const x = ((longitude - bounds.west) / longitudeSpan - 0.5) * terrainWidth;
  const z = (0.5 - (latitude - bounds.south) / latitudeSpan) * terrainDepth;
  return { x, y: elevation, z };
}

function corner(rowIndex: number, columnIndex: number, elevation: number): TerrainCorner {
  return { rowIndex, columnIndex, elevation };
}

function pushCellTriangle(
  asset: TerrainAsset,
  scene: TerrainSceneConfig,
  frame: TerrainSceneFrame,
  positions: number[],
  colors: number[],
  first: TerrainCorner,
  second: TerrainCorner,
  third: TerrainCorner,
): void {
  pushVertex(asset, scene, frame, positions, colors, first.rowIndex, first.columnIndex, first.elevation);
  pushVertex(asset, scene, frame, positions, colors, second.rowIndex, second.columnIndex, second.elevation);
  pushVertex(asset, scene, frame, positions, colors, third.rowIndex, third.columnIndex, third.elevation);
}

function pushVertex(
  asset: TerrainAsset,
  scene: TerrainSceneConfig,
  frame: TerrainSceneFrame,
  positions: number[],
  colors: number[],
  rowIndex: number,
  columnIndex: number,
  elevation: number,
): void {
  const longitude = coordinateValue(asset.bounds.west, asset.bounds.east, columnIndex, asset.columns);
  const latitude = coordinateValue(asset.bounds.north, asset.bounds.south, rowIndex, asset.rows);
  const height = elevation * frame.elevationScale;
  const point = coordinateToScene(
    longitude,
    latitude,
    frame.bounds,
    frame.terrainWidth,
    frame.terrainDepth,
    height,
  );
  const color = terrainColor(asset, rowIndex, columnIndex, elevation, scene.colorRamp);
  positions.push(point.x, point.y, point.z);
  colors.push(color.r, color.g, color.b);
}

function elevationAt(asset: TerrainAsset, rowIndex: number, columnIndex: number): number | null {
  return asset.elevations[rowIndex * asset.columns + columnIndex];
}

function terrainColor(
  asset: TerrainAsset,
  rowIndex: number,
  columnIndex: number,
  elevation: number,
  colorRamp: TerrainSceneConfig['colorRamp'],
): ColorPoint {
  const landCoverColor = landCoverColorAt(asset, rowIndex, columnIndex);
  return landCoverColor ?? elevationColor(elevation, asset.minElevation, asset.maxElevation, colorRamp);
}

function landCoverColorAt(asset: TerrainAsset, rowIndex: number, columnIndex: number): ColorPoint | null {
  const landCoverCode = asset.landCover?.[rowIndex * asset.columns + columnIndex];
  if (landCoverCode === undefined || landCoverCode === null) {
    return null;
  }
  const landCoverClass = asset.landCoverLegend?.[String(landCoverCode)];
  return landCoverClass ? hexToColor(landCoverClass.color) : null;
}

function coordinateValue(start: number, end: number, index: number, count: number): number {
  return start + (end - start) * (index / (count - 1));
}

function elevationColor(
  elevation: number,
  minElevation: number,
  maxElevation: number,
  colorRamp: TerrainSceneConfig['colorRamp'],
): ColorPoint {
  const normalized = (elevation - minElevation) / (maxElevation - minElevation);
  if (normalized <= 0.5) {
    return mixColor(hexToColor(colorRamp.low), hexToColor(colorRamp.mid), normalized / 0.5);
  }
  return mixColor(hexToColor(colorRamp.mid), hexToColor(colorRamp.high), (normalized - 0.5) / 0.5);
}

function hexToColor(hex: string): ColorPoint {
  const value = Number.parseInt(hex.slice(1), 16);
  return {
    r: ((value >> 16) & 255) / 255,
    g: ((value >> 8) & 255) / 255,
    b: (value & 255) / 255,
  };
}

function mixColor(start: ColorPoint, end: ColorPoint, ratio: number): ColorPoint {
  return {
    r: start.r + (end.r - start.r) * ratio,
    g: start.g + (end.g - start.g) * ratio,
    b: start.b + (end.b - start.b) * ratio,
  };
}
