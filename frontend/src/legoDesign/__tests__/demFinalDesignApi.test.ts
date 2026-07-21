import { describe, expect, it } from 'vitest';
import { currentTaskContext } from '../../api/taskContext';
import { createDemFinalDesignRequest } from '../demFinalDesignApi';

describe('DEM final design request', () => {
  it('freezes locale and timezone with the model identity and user scale', () => {
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
      ...currentTaskContext(),
    });
  });
});
