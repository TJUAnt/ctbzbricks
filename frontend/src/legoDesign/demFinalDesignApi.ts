import { apiFetch, requestJson } from '../api/client';
import { currentTaskContext } from '../api/taskContext';
import type { LegoHeightmapScale } from '../legoTerrain/legoHeightmap';
import legoDesignConfig from './legoDesignConfig';
import { responseFileName } from './legoDesignApi';

export type DemFinalDesignRequest = {
  modelId: string;
  strategy: string;
  horizontalKmPerStud: number;
  verticalMetersPerPlate: number;
  aggregation: string;
  minCoverageRatio: number;
  locale: string;
  timezone: string;
};

export type DemFinalBomItem = {
  partId: string;
  rebrickablePartNum: string | null;
  legoDesignId: string | null;
  role: string;
  colorId: number;
  colorName: string;
  colorRgb: string;
  ldrawColorCode: string;
  widthStud: number;
  depthStud: number;
  heightPlate: number;
  quantity: number;
};

export type DemSurfacePlacement = {
  partId: string;
  ldrawOriginToBaseLdu: number;
  ldrawCenterXLdu: number;
  ldrawCenterZLdu: number;
  xStud: number;
  zStud: number;
  widthStud: number;
  depthStud: number;
  rotationDegrees: number;
  basePlate: number;
  colorId: number;
  targetColorId: number;
  colorDistance: number;
  usesNearestColor: boolean;
  usesApproximateGeometry: boolean;
  colorName: string;
  colorRgb: string;
  ldrawColorCode: string;
  heightPlate: number;
};

export type DemReplacementPlacement = {
  partId: string;
  ldrawOriginToBaseLdu: number;
  ldrawCenterXLdu: number;
  ldrawCenterZLdu: number;
  xStud: number;
  zStud: number;
  widthStud: number;
  depthStud: number;
  rotationDegrees: number;
  basePlate: number;
  colorId: number;
  targetColorId: number;
  colorDistance: number;
  usesNearestColor: boolean;
  usesApproximateGeometry: boolean;
  coveredCells: Array<[number, number]>;
  requiredSupportCells: Array<[number, number]>;
  baseHeightCells: Array<[number, number, number]>;
  topConnectCells: Array<[number, number]>;
  topConnectionClass: string;
  slopeEdges: Array<[number, number, number, number, string]>;
  slopeDirections: string[];
  matchedSlopeDirectionCount: number;
};

export type DemStructurePlacement = {
  partId: string;
  x: number;
  z: number;
  width: number;
  depth: number;
  rotation: number;
  basePlate: number;
  heightPlate: number;
  colorId: number;
  colorName: string;
  colorRgb: string;
  ldrawColorCode: string;
};

export type DemFinalDesign = {
  modelId: string;
  exportContext: {
    locale: string;
    timezone: string;
    catalogVersion: string;
  };
  strategy: string;
  replacementDiagnostics: {
    heightmapModelId: string;
    connectedRegionCount: number;
    patternCount: number;
    geometricMatchCount: number;
    colorMatchedCount: number;
    colorSubstitutionCount: number;
    missingColorRequirementCount: number;
    missingColorRequirementTypeCount: number;
    replacementPlacementCount: number;
    targetSlopeEdgeCount: number;
    solvedSlopeEdgeCount: number;
    unresolvedSlopeEdgeCount: number;
    phaseSummaries: Array<{
      connectionClass: string;
      placementCount: number;
      incrementalPlacementCount: number;
      targetSlopeEdgeCount: number;
      solvedSlopeEdgeCount: number;
      unresolvedSlopeEdgeCount: number;
      nearestColorPlacementCount: number;
      approximateGeometryPlacementCount: number;
    }>;
    missingColorSummary: Array<{
      targetColor: string;
      partId: string;
      widthStud: number;
      depthStud: number;
      slopeDirections: string[];
      slopeDirectionCount: number;
      occurrenceCount: number;
      reason: string;
      nearestColorId?: number;
      nearestColorName?: string;
      nearestColorRgb?: string;
      nearestColorDistance?: number;
      maximumSquaredDistance?: number;
    }>;
  } | null;
  surfacePlan: {
    widthStud: number;
    depthStud: number;
    samplesPerStudAxis: number;
    partCount: number;
    candidateCount: number;
    maximumAbsoluteErrorPlate: number;
    totalAbsoluteErrorPlate: number;
    seamErrorPlate: number;
    replacementPhases: Array<{
      connectionClass: string;
      placements: DemReplacementPlacement[];
      baseH: number[][];
      solvedSlopeEdgeCount: number;
      unresolvedSlopeEdgeCount: number;
    }>;
  };
  baseStructure: {
    baseH: number[][];
    placements: DemStructurePlacement[];
  };
  surfacePlacements: DemSurfacePlacement[];
  bom: DemFinalBomItem[];
  steps: Array<{
    id: string;
    name: string;
    order: number;
    stage: string;
    basePlate: number;
    placementRefs: Array<{ kind: string; index: number }>;
  }>;
  validation: {
    rejectedBaseHCount: number;
    inventoryColorMappingCount: number;
    approximateGeometryPlacementCount: number;
    excludedColorCandidateCount: number;
    totalPlacementCount: number;
    stepPlacementCount: number;
    surfaceCollisionSampleCount: number;
    surfaceUnsupportedPlacementCount: number;
    structureUnsupportedPlacementCount: number;
    targetVolumeStudPlate: number;
    placedVolumeStudPlate: number;
    verticalContinuity: Array<{
      connectionClass: string;
      checkedColumnCount: number;
      occupiedColumnCount: number;
      discontinuousColumnCount: number;
      gapCount: number;
      maximumGapLdu: number;
      gapExamples: Array<{
        xLdu: number;
        zLdu: number;
        lowerLdu: number;
        upperLdu: number;
      }>;
    }>;
  };
};

export function createDemFinalDesignRequest(
  modelId: string,
  strategy: string,
  scale: LegoHeightmapScale,
): DemFinalDesignRequest {
  return {
    modelId,
    strategy,
    horizontalKmPerStud: scale.horizontalKmPerStud,
    verticalMetersPerPlate: scale.verticalMetersPerPlate,
    aggregation: scale.aggregation,
    minCoverageRatio: scale.minCoverageRatio,
    ...currentTaskContext(),
  };
}

export async function createDemFinalDesign(request: DemFinalDesignRequest): Promise<DemFinalDesign> {
  return requestJson<DemFinalDesign>(legoDesignConfig.demFinalDesignApiUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
}

export async function exportDemFinalDesignLdraw(
  design: DemFinalDesign,
): Promise<{ blob: Blob; fileName: string }> {
  const response = await apiFetch(legoDesignConfig.demFinalDesignLdrawApiUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(design),
  });
  return {
    blob: await response.blob(),
    fileName: responseFileName(response, 'dem-lego-design.ldr'),
  };
}

export async function exportDemFinalDesignReport(
  design: DemFinalDesign,
): Promise<{ blob: Blob; fileName: string }> {
  const response = await apiFetch(legoDesignConfig.demFinalDesignReportApiUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(design),
  });
  return {
    blob: await response.blob(),
    fileName: responseFileName(response, 'dem-lego-design-report.json'),
  };
}
