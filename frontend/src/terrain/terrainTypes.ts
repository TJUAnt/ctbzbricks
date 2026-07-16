export type TerrainBounds = {
  west: number;
  south: number;
  east: number;
  north: number;
};

export type TerrainAsset = {
  schema: string;
  source: string;
  name?: string;
  modelId?: string;
  createdAt?: string;
  columns: number;
  rows: number;
  bounds: TerrainBounds;
  minElevation: number;
  maxElevation: number;
  renderOptions?: {
    verticalExaggeration: number;
  };
  elevations: Array<number | null>;
  landCover?: Array<number | null>;
  landCoverLegend?: Record<string, TerrainLandCoverClass>;
  landCoverSource?: string | null;
  boundary: number[][][][];
};

export type TerrainLandCoverClass = {
  label: string;
  color: string;
};

export type TerrainModelMetadata = {
  modelId: string;
  name: string;
  source: string;
  createdAt: string;
  columns: number;
  rows: number;
  minElevation: number;
  maxElevation: number;
  validSampleCount: number;
  renderOptions?: {
    verticalExaggeration: number;
  };
};

export type TerrainJob = {
  jobId: string;
  status: string;
  progress: number;
  sourceName: string;
  asset: TerrainAsset | null;
  model: TerrainModelMetadata | null;
  error: string | null;
};

export type TerrainSceneConfig = {
  maxTerrainWidth: number;
  maxTerrainDepth: number;
  defaultVerticalExaggeration: number;
  latitudeMetersPerDegree: number;
  radiansPerDegree: number;
  boundaryElevation: number;
  colorRamp: {
    low: string;
    mid: string;
    high: string;
  };
};

export type TerrainMeshData = {
  positions: Float32Array;
  colors: Float32Array;
  triangleCount: number;
  validSampleCount: number;
};

export type TerrainSceneScale = {
  terrainWidth: number;
  terrainDepth: number;
  elevationScale: number;
};

export type TerrainSceneFrame = TerrainSceneScale & {
  bounds: TerrainBounds;
};
