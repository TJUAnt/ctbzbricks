import type { TerrainAsset, TerrainBounds } from '../terrain/terrainTypes';

export type LegoHeightmapScale = {
  horizontalKmPerStud: number;
  verticalMetersPerPlate: number;
  aggregation: string;
  minCoverageRatio: number;
};

export type LegoHeightmapConfig = {
  latitudeMetersPerDegree: number;
  radiansPerDegree: number;
  metersPerKilometer: number;
  kilometersPerMeter: number;
  coordinateAverageDivisor: number;
  minimumStudCount: number;
  minimumPlateHeight: number;
  emptyElevationHeightPlate: number;
  coveragePrecision: number;
  aggregation: {
    percentile: string;
    mean: string;
    max: string;
  };
  percentileRatio: number;
  invalidAggregationMessage: string;
};

export type LegoHeightCell = {
  x: number;
  z: number;
  heightPlate: number;
  elevationMeters: number | null;
  landCoverCode: number | null;
  landCoverColor: string | null;
  coverageRatio: number;
};

export type LegoHeightmapMetrics = {
  widthKm: number;
  depthKm: number;
  widthStud: number;
  depthStud: number;
  maxHeightPlate: number;
  validCellCount: number;
  totalCellCount: number;
  averageCoverageRatio: number;
};

export type LegoHeightmap = {
  bounds: TerrainBounds;
  scale: LegoHeightmapScale;
  cells: LegoHeightCell[];
  metrics: LegoHeightmapMetrics;
};

type ElevationBucket = {
  sampleCount: number;
  elevations: number[];
  landCoverCodes: number[];
};

export function createLegoHeightmap(
  asset: TerrainAsset,
  scale: LegoHeightmapScale,
  config: LegoHeightmapConfig,
): LegoHeightmap {
  const boundsSize = terrainBoundsSize(asset.bounds, config);
  const widthStud = Math.max(
    config.minimumStudCount,
    Math.ceil(boundsSize.widthKm / scale.horizontalKmPerStud),
  );
  const depthStud = Math.max(
    config.minimumStudCount,
    Math.ceil(boundsSize.depthKm / scale.horizontalKmPerStud),
  );
  const buckets = createElevationBuckets(widthStud * depthStud);

  for (let rowIndex = 0; rowIndex < asset.rows; rowIndex += 1) {
    for (let columnIndex = 0; columnIndex < asset.columns; columnIndex += 1) {
      const bucket = buckets[
        studIndexForSample(asset, rowIndex, columnIndex, widthStud, depthStud)
      ];
      bucket.sampleCount += 1;
      const elevation = elevationAt(asset, rowIndex, columnIndex);
      if (elevation !== null) {
        bucket.elevations.push(elevation);
        const landCoverCode = landCoverCodeAt(asset, rowIndex, columnIndex);
        if (landCoverCode !== null) {
          bucket.landCoverCodes.push(landCoverCode);
        }
      }
    }
  }

  const cells = buckets.map((bucket, index) =>
    heightCellFromBucket(
      bucket,
      index,
      widthStud,
      asset,
      scale,
      config,
    ),
  );
  const validCells = cells.filter((cell) => cell.elevationMeters !== null);
  const maxHeightPlate = Math.max(
    config.minimumPlateHeight,
    ...validCells.map((cell) => cell.heightPlate),
  );

  return {
    bounds: asset.bounds,
    scale,
    cells,
    metrics: {
      widthKm: boundsSize.widthKm,
      depthKm: boundsSize.depthKm,
      widthStud,
      depthStud,
      maxHeightPlate,
      validCellCount: validCells.length,
      totalCellCount: cells.length,
      averageCoverageRatio: roundedCoverageRatio(
        validCells.reduce((total, cell) => total + cell.coverageRatio, config.minimumPlateHeight) /
          Math.max(config.minimumStudCount, validCells.length),
        config,
      ),
    },
  };
}

export function terrainBoundsSize(
  bounds: TerrainBounds,
  config: LegoHeightmapConfig,
): { widthKm: number; depthKm: number } {
  const latitudeSpan = bounds.north - bounds.south;
  const longitudeSpan = bounds.east - bounds.west;
  const middleLatitude = (bounds.north + bounds.south) / config.coordinateAverageDivisor;
  const depthMeters = latitudeSpan * config.latitudeMetersPerDegree;
  const widthMeters =
    longitudeSpan *
    config.latitudeMetersPerDegree *
    Math.cos(middleLatitude * config.radiansPerDegree);
  return {
    widthKm: widthMeters * config.kilometersPerMeter,
    depthKm: depthMeters * config.kilometersPerMeter,
  };
}

function createElevationBuckets(bucketCount: number): ElevationBucket[] {
  return Array.from({ length: bucketCount }, () => ({ sampleCount: 0, elevations: [], landCoverCodes: [] }));
}

function heightCellFromBucket(
  bucket: ElevationBucket,
  index: number,
  widthStud: number,
  asset: TerrainAsset,
  scale: LegoHeightmapScale,
  config: LegoHeightmapConfig,
): LegoHeightCell {
  const coverageRatio = roundedCoverageRatio(
    bucket.elevations.length / Math.max(config.minimumStudCount, bucket.sampleCount),
    config,
  );
  const x = index % widthStud;
  const z = Math.floor(index / widthStud);
  if (bucket.elevations.length === 0 || coverageRatio < scale.minCoverageRatio) {
    return {
      x,
      z,
      heightPlate: config.emptyElevationHeightPlate,
      elevationMeters: null,
      landCoverCode: null,
      landCoverColor: null,
      coverageRatio,
    };
  }
  const elevationMeters = aggregateElevations(bucket.elevations, scale.aggregation, config);
  const landCoverCode = dominantLandCoverCode(bucket.landCoverCodes);
  return {
    x,
    z,
    heightPlate: Math.max(
      config.minimumPlateHeight,
      Math.round((elevationMeters - asset.minElevation) / scale.verticalMetersPerPlate),
    ),
    elevationMeters,
    landCoverCode,
    landCoverColor: landCoverCode === null ? null : (asset.landCoverLegend?.[String(landCoverCode)]?.color ?? null),
    coverageRatio,
  };
}

function aggregateElevations(
  elevations: number[],
  aggregation: string,
  config: LegoHeightmapConfig,
): number {
  if (aggregation === config.aggregation.mean) {
    return elevations.reduce((total, elevation) => total + elevation, 0) / elevations.length;
  }
  if (aggregation === config.aggregation.max) {
    return Math.max(...elevations);
  }
  if (aggregation === config.aggregation.percentile) {
    return percentileElevation(elevations, config.percentileRatio);
  }
  throw new Error(config.invalidAggregationMessage);
}

function percentileElevation(elevations: number[], percentileRatio: number): number {
  const sortedElevations = [...elevations].sort((first, second) => first - second);
  const index = Math.ceil((sortedElevations.length - 1) * percentileRatio);
  return sortedElevations[index];
}

function studIndexForSample(
  asset: TerrainAsset,
  rowIndex: number,
  columnIndex: number,
  widthStud: number,
  depthStud: number,
): number {
  const x = Math.min(
    widthStud - 1,
    Math.floor((columnIndex / (asset.columns - 1)) * widthStud),
  );
  const z = Math.min(
    depthStud - 1,
    Math.floor((rowIndex / (asset.rows - 1)) * depthStud),
  );
  return z * widthStud + x;
}

function elevationAt(asset: TerrainAsset, rowIndex: number, columnIndex: number): number | null {
  return asset.elevations[rowIndex * asset.columns + columnIndex];
}

function landCoverCodeAt(asset: TerrainAsset, rowIndex: number, columnIndex: number): number | null {
  const landCoverCode = asset.landCover?.[rowIndex * asset.columns + columnIndex];
  return landCoverCode === undefined ? null : landCoverCode;
}

function dominantLandCoverCode(landCoverCodes: number[]): number | null {
  if (landCoverCodes.length === 0) {
    return null;
  }
  const counts = new Map<number, number>();
  for (const landCoverCode of landCoverCodes) {
    counts.set(landCoverCode, (counts.get(landCoverCode) ?? 0) + 1);
  }
  return [...counts.entries()].sort((first, second) => second[1] - first[1] || first[0] - second[0])[0][0];
}

function roundedCoverageRatio(ratio: number, config: LegoHeightmapConfig): number {
  return Math.round(ratio * config.coveragePrecision) / config.coveragePrecision;
}
