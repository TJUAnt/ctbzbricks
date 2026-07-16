import { describe, expect, it } from 'vitest';
import { createDemFinalDesignRequest } from '../demFinalDesignApi';

describe('DEM final design request', () => {
  it('sends only the model identity and user scale to the backend', () => {
    const request = createDemFinalDesignRequest(
      'model-id',
      'surface-plan',
      {
        horizontalKmPerStud: 20,
        verticalMetersPerPlate: 500,
        aggregation: 'percentile',
        minCoverageRatio: 0.25,
      },
    );

    expect(request).toEqual({
      modelId: 'model-id',
      strategy: 'surface-plan',
      horizontalKmPerStud: 20,
      verticalMetersPerPlate: 500,
      aggregation: 'percentile',
      minCoverageRatio: 0.25,
    });
  });
});
