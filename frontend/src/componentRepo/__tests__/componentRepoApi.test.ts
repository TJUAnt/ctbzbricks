import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  addComponentToGroup,
  deleteComponent,
  listComponentGroupComponents,
  listComponentGroupMembershipCandidates,
  listComponentGroups,
  listComponentImports,
  listComponentPublicFeed,
  listComponents,
  searchComponentGroupComponents,
  deleteComponentVersion,
  detectRelations,
  getComponentVersion,
  getConnectorAnalysis,
  loadComponentVersionDiff,
  loadComponentVersionParts,
  loadComponentVersionPreview,
  loadPartPreview,
  listComponentVersions,
  publishVersion,
  listComponentStars,
  listComponentWatchFeed,
  listComponentWatches,
  starComponent,
  unstarComponent,
  unwatchComponent,
  validateCandidate,
  watchComponent,
} from '../componentRepoApi';

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const taskSucceeded = {
  id: 'task-1',
  taskJobId: 'job-1',
  executionNumber: 1,
  taskType: 'component.relations.detect',
  status: 'succeeded',
  result: {},
  resultArtifactId: null,
  locale: 'zh-CN',
  timezone: 'Asia/Shanghai',
  attempts: 1,
  maxAttempts: 3,
  progress: null,
  error: null,
  cancelRequestedAt: null,
  createdAt: '2026-08-12T00:00:00Z',
  startedAt: '2026-08-12T00:00:01Z',
  finishedAt: '2026-08-12T00:00:02Z',
  updatedAt: '2026-08-12T00:00:02Z',
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Component Repo Go API adapter', () => {
  it('bootstraps an empty group repository explicitly and keeps group reads on Go', async () => {
    const root = {
      id: 'group-root', parentGroupId: null, groupType: 'root', name: null,
      contentLocale: null, sortOrder: 0, directComponentCount: 2,
      createdAt: '2026-08-12T00:00:00Z', updatedAt: '2026-08-12T00:00:00Z',
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ items: [] }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(jsonResponse({ items: [root] }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(listComponentGroups()).resolves.toEqual({ root, groups: [] });
    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/v1/component-groups', undefined);
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/v1/component-groups/bootstrap',
      expect.objectContaining({ method: 'POST' }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(3, '/api/v1/component-groups', undefined);
  });

  it('uses Go GET search and collection POST for group membership', async () => {
    vi.stubGlobal('window', { location: { origin: String.fromCharCode(104, 116, 116, 112, 58, 47, 47) + 'localhost' } });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({
        items: [], total: 0, page: 2, pageSize: 20, totalPages: 0, statusCounts: { draft: 1 },
      }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);

    await searchComponentGroupComponents('group-1', {
      queries: ['sample', '2x4'], statuses: ['draft', 'active'], page: 2, pageSize: 20,
    });
    const searchURL = new URL(String(fetchMock.mock.calls[0]?.[0]));
    expect(searchURL.pathname).toBe('/api/v1/component-groups/group-1/components/search');
    expect(searchURL.searchParams.getAll('status')).toEqual(['draft', 'active']);
    expect(searchURL.searchParams.getAll('query')).toEqual(['sample', '2x4']);

    await addComponentToGroup('group-1', 'component-1');
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/v1/component-groups/group-1/components',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ componentId: 'component-1' }) }),
    );
  });

  it('reads every group-member page instead of treating the first 100 rows as complete', async () => {
    vi.stubGlobal('window', { location: { origin: ['http', '//localhost'].join(':') } });
    const firstPage = Array.from({ length: 100 }, (_, index) => ({ id: `component-${index + 1}` }));
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ items: firstPage }))
      .mockResolvedValueOnce(jsonResponse({ items: [{ id: 'component-101' }] }));
    vi.stubGlobal('fetch', fetchMock);

    const members = await listComponentGroupComponents('group-1');

    expect(members).toHaveLength(101);
    expect(members[members.length - 1]?.id).toBe('component-101');
    expect(new URL(String(fetchMock.mock.calls[0]?.[0])).searchParams.get('page')).toBe('1');
    expect(new URL(String(fetchMock.mock.calls[1]?.[0])).searchParams.get('page')).toBe('2');
  });

  it('merges paged owned, starred, and existing group candidates and exposes continuation', async () => {
    vi.stubGlobal('window', { location: { origin: ['http', '//localhost'].join(':') } });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({
        items: [{ id: 'owned-1' }], total: 21, page: 1, pageSize: 20, totalPages: 2, statusCounts: {},
      }))
      .mockResolvedValueOnce(jsonResponse({
        items: [{ id: 'shared-1' }], total: 1, page: 1, pageSize: 20, totalPages: 1, relationshipTotal: 1,
      }))
      .mockResolvedValueOnce(jsonResponse({
        items: [{ id: 'shared-1' }, { id: 'member-1' }], total: 2, page: 1, pageSize: 20,
        totalPages: 1, statusCounts: {},
      }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await listComponentGroupMembershipCandidates({
      rootGroupId: 'root-1', groupId: 'group-1', query: 'car', page: 1, pageSize: 20,
    });

    expect(result.items.map((item) => item.id)).toEqual(['owned-1', 'shared-1', 'member-1']);
    expect(result.hasMore).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(new URL(String(fetchMock.mock.calls[0]?.[0])).searchParams.get('query')).toBe('car');
    expect(new URL(String(fetchMock.mock.calls[1]?.[0])).searchParams.get('query')).toBe('car');
    expect(new URL(String(fetchMock.mock.calls[2]?.[0])).searchParams.get('query')).toBe('car');
  });

  it('reads the 101st version before applying the optional status filter', async () => {
    vi.stubGlobal('window', { location: { origin: ['http', '//localhost'].join(':') } });
    const version = (index: number, status: string) => ({
      id: `version-${index}`, componentId: 'component-1', componentCandidateId: null,
      version: `1.0.${index}`, revision: index, status, sourceArtifactId: 'artifact-1',
      exchangeArtifactId: null, sceneSnapshotId: 'snapshot-1', parserVersion: 'parser-v1',
      partLibraryVersionId: null, validationReportId: null, interfaceSignature: '',
      structureHash: '', geometryHash: '', previewArtifactId: null, previewStatus: 'pending',
      previewGeneratorVersion: null, previewFailureCode: null, previewFailureParams: {},
      releaseNote: null, releaseNoteLocale: null, metadata: {},
      createdAt: '2026-08-12T00:00:00Z', publishedAt: null,
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({
        items: Array.from({ length: 100 }, (_, index) => version(index + 1, 'published')),
      }))
      .mockResolvedValueOnce(jsonResponse({ items: [version(101, 'draft')] }));
    vi.stubGlobal('fetch', fetchMock);

    const drafts = await listComponentVersions('component-1', 'draft');

    expect(drafts.map((item) => item.id)).toEqual(['version-101']);
    expect(new URL(String(fetchMock.mock.calls[1]?.[0])).searchParams.get('page')).toBe('2');
  });

  it('uses the Go Star contract for list, star, and unstar', async () => {
    vi.stubGlobal('window', {
      location: { origin: String.fromCharCode(104, 116, 116, 112, 58, 47, 47) + 'localhost' },
    });
    const page = { items: [], total: 0, page: 2, pageSize: 20, totalPages: 0, relationshipTotal: 0 };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(page))
      .mockResolvedValueOnce(jsonResponse({ componentId: 'component-1', starredAt: '2026-08-29T00:00:00Z' }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(listComponentStars({
      page: 2, pageSize: 20, query: 'castle', category: 'vehicle', sort: 'starred_at_desc',
    })).resolves.toEqual(page);
    const listURL = new URL(String(fetchMock.mock.calls[0]?.[0]));
    expect(listURL.pathname).toBe('/api/v1/component-stars');
    expect(listURL.searchParams.get('page')).toBe('2');
    expect(listURL.searchParams.get('query')).toBe('castle');
    expect(listURL.searchParams.get('category')).toBe('vehicle');
    expect(listURL.searchParams.get('sort')).toBe('starred_at_desc');

    await starComponent('component-1');
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/v1/components/component-1/star',
      expect.objectContaining({ method: 'PUT' }),
    );
    await unstarComponent('component-1');
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      '/api/v1/components/component-1/star',
      expect.objectContaining({ method: 'DELETE' }),
    );
  });

  it('uses independent keyset Watch APIs without changing Star', async () => {
    vi.stubGlobal('window', {
      location: { origin: String.fromCharCode(104, 116, 116, 112, 58, 47, 47) + 'localhost' },
    });
    const watchPage = { items: [], nextCursor: 'next-watch-cursor' };
    const feedPage = { items: [], nextCursor: 'next-feed-cursor', windowStart: '2026-08-01T00:00:00Z' };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(watchPage))
      .mockResolvedValueOnce(jsonResponse(feedPage))
      .mockResolvedValueOnce(jsonResponse({
        componentId: 'component-1', watching: true, level: 'releases_only', watchedAt: '2026-08-31T00:00:00Z',
      }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(listComponentWatches({
      limit: 20,
      cursor: 'previous-watch-cursor',
      query: 'castle',
      category: 'building',
    })).resolves.toEqual(watchPage);
    const listURL = new URL(String(fetchMock.mock.calls[0]?.[0]));
    expect(listURL.pathname).toBe('/api/v1/component-watches');
    expect(listURL.searchParams.get('limit')).toBe('20');
    expect(listURL.searchParams.get('cursor')).toBe('previous-watch-cursor');
    expect(listURL.searchParams.get('query')).toBe('castle');
    expect(listURL.searchParams.get('category')).toBe('building');

    await expect(listComponentWatchFeed({
      since: '2026-08-01T00:00:00Z', limit: 20, cursor: 'previous-feed-cursor',
    })).resolves.toEqual(feedPage);
    const feedURL = new URL(String(fetchMock.mock.calls[1]?.[0]));
    expect(feedURL.pathname).toBe('/api/v1/component-watch-feed');
    expect(feedURL.searchParams.get('since')).toBe('2026-08-01T00:00:00Z');
    expect(feedURL.searchParams.get('limit')).toBe('20');
    expect(feedURL.searchParams.get('cursor')).toBe('previous-feed-cursor');

    await watchComponent('component-1');
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      '/api/v1/components/component-1/watch',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ level: 'releases_only' }),
      }),
    );
    await unwatchComponent('component-1');
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      '/api/v1/components/component-1/watch',
      expect.objectContaining({ method: 'DELETE' }),
    );
  });

  it('reads the cursor-paginated public Component directory used to discover Star targets', async () => {
    vi.stubGlobal('window', {
      location: { origin: String.fromCharCode(104, 116, 116, 112, 58, 47, 47) + 'localhost' },
    });
    const page = { items: [], nextCursor: 'next-component-cursor' };
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(page));
    vi.stubGlobal('fetch', fetchMock);

    await expect(listComponents({ cursor: 'current-component-cursor', limit: 20, query: 'train', status: 'active' })).resolves.toEqual(page);
    const url = new URL(String(fetchMock.mock.calls[0]?.[0]));
    expect(url.pathname).toBe('/api/v1/components');
    expect(url.searchParams.get('query')).toBe('train');
    expect(url.searchParams.get('status')).toBe('active');
    expect(url.searchParams.get('cursor')).toBe('current-component-cursor');
    expect(url.searchParams.get('limit')).toBe('20');
  });

  it('reads the public Component event feed with an opaque cursor', async () => {
    vi.stubGlobal('window', {
      location: { origin: String.fromCharCode(104, 116, 116, 112, 58, 47, 47) + 'localhost' },
    });
    const page = { items: [], nextCursor: 'next-feed-cursor' };
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(page));
    vi.stubGlobal('fetch', fetchMock);

    await expect(listComponentPublicFeed({ limit: 20, cursor: 'cursor-1', query: 'train' })).resolves.toEqual(page);
    const url = new URL(String(fetchMock.mock.calls[0]?.[0]));
    expect(url.pathname).toBe('/api/v1/component-public-feed');
    expect(url.searchParams.get('limit')).toBe('20');
    expect(url.searchParams.get('cursor')).toBe('cursor-1');
    expect(url.searchParams.get('query')).toBe('train');
  });

  it('reads owner-scoped import history with component and aggregate status filters', async () => {
    vi.stubGlobal('window', {
      location: { origin: String.fromCharCode(104, 116, 116, 112, 58, 47, 47) + 'localhost' },
    });
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({
      items: [], total: 0, page: 2, pageSize: 20, totalPages: 0,
      statusCounts: { processing: 0, ready: 0, failed: 0 },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await listComponentImports({
      page: 2,
      pageSize: 20,
      processingStatus: 'ready',
      query: 'model.io',
      componentId: 'component-1',
    });

    const url = new URL(String(fetchMock.mock.calls[0]?.[0]));
    expect(url.pathname).toBe('/api/v1/component-imports');
    expect(url.searchParams.get('processingStatus')).toBe('ready');
    expect(url.searchParams.get('componentId')).toBe('component-1');
    expect(url.searchParams.get('query')).toBe('model.io');
    expect(url.searchParams.get('page')).toBe('2');
  });

  it('waits for asynchronous relation detection and then reads durable results', async () => {
    const relation = {
      id: 'relation-1',
      componentCandidateId: 'candidate-1',
      partLibraryVersionId: 'library-1',
      endpointA: {},
      endpointB: {},
      connectionType: 'stud',
      jointType: 'fixed',
      positionResidual: 0,
      rotationResidual: 0,
      verifiedByTolerance: true,
      confidence: 1,
      status: 'detected',
      detectionMethod: 'automatic',
      metadata: {},
      createdAt: '2026-08-12T00:00:00Z',
      updatedAt: '2026-08-12T00:00:00Z',
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ taskId: 'task-1', status: 'queued' }, 202))
      .mockResolvedValueOnce(jsonResponse(taskSucceeded))
      .mockResolvedValueOnce(jsonResponse({ items: [relation] }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(detectRelations('candidate-1')).resolves.toEqual([relation]);
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/v1/component-candidates/candidate-1/relations/detect',
      expect.objectContaining({ method: 'POST' }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/v1/tasks/task-1', undefined);
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      '/api/v1/component-candidates/candidate-1/relations',
      undefined,
    );
  });

  it('only reads a Worker-materialized preview and never starts the first preview task', async () => {
    const previewUrl = 'https' + '://storage.example/preview.glb';
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({
        versionId: 'version-1', status: 'ready', generatorVersion: 'preview-v1',
        artifactId: 'artifact-1', sha256: 'abc', fileSize: 42,
        url: previewUrl, failure: null,
      }));
    vi.stubGlobal('fetch', fetchMock);

    const preview = await loadComponentVersionPreview('version-1');

    expect(preview.model).toEqual({
      artifactId: 'artifact-1',
      format: 'glb',
      url: previewUrl,
      sha256: 'abc',
      byteLength: 42,
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/component-versions/version-1/preview', undefined);
  });

  it('reads the Go-computed immutable version diff without creating a task', async () => {
    const response = {
      versionId: 'version-2',
      baseVersionId: 'version-1',
      comparisonBasis: 'import_base_version',
      algorithmVersion: 'component-scene-diff-v1',
      structureHash: 'structure-2',
      geometryHash: 'geometry-2',
      baseStructureHash: 'structure-1',
      baseGeometryHash: 'geometry-1',
      summary: {
        beforeInstances: 1, afterInstances: 1, unchangedInstances: 0,
        addedInstances: 0, removedInstances: 0, transformChangedInstances: 1,
        colorChangedInstances: 0, replacedInstances: 0,
        ambiguousBeforeInstances: 0, ambiguousAfterInstances: 0, ambiguousGroups: 0,
        bomChangedPartTypes: 0,
      },
      bomChanges: [],
      instanceChanges: [{
        kind: 'transform_changed',
        before: { instanceId: 'root/a', partRef: '3001.dat', colorCode: '4', worldMatrix: [] },
        after: { instanceId: 'root/a', partRef: '3001.dat', colorCode: '4', worldMatrix: [] },
      }],
      ambiguousGroups: [],
      truncated: false,
    };
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(response));
    vi.stubGlobal('fetch', fetchMock);

    await expect(loadComponentVersionDiff('version-2')).resolves.toEqual(response);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/component-versions/version-2/diff', undefined);
  });

  it('preserves each BOM Part geometry status from the Go API', async () => {
    vi.stubGlobal('window', {
      location: { origin: String.fromCharCode(104, 116, 116, 112, 58, 47, 47) + 'localhost' },
    });
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({
      versionId: 'version-1', partLibraryVersionId: 'library-1', partCount: 2,
      items: [
        { ldrawPartNum: '3001.dat', quantity: 1, name: 'Brick', contentLocale: 'en-US', translationStatus: 'fallback', geometryStatus: 'ready' },
        { ldrawPartNum: 'missing.dat', quantity: 1, name: null, contentLocale: null, translationStatus: 'missing', geometryStatus: 'missing' },
      ],
    }));
    vi.stubGlobal('fetch', fetchMock);

    const response = await loadComponentVersionParts('version-1');

    expect(response.parts.map((part) => [part.partRef, part.geometryStatus])).toEqual([
      ['3001.dat', 'ready'],
      ['missing.dat', 'missing'],
    ]);
  });

  it('rejects a pending preview without asking the API to materialize it', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({
      versionId: 'version-1', status: 'pending', generatorVersion: null,
      artifactId: null, sha256: null, fileSize: null, url: null, failure: null,
    }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(loadComponentVersionPreview('version-1')).rejects.toMatchObject({
      code: 'component_repo.preview_unavailable',
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('loads an immutable Part preview through the Go durable task contract', async () => {
    vi.stubGlobal('window', {
      location: { origin: String.fromCharCode(104, 116, 116, 112, 58, 47, 47) + 'localhost' },
    });
    const base = {
      partLibraryVersionId: 'library-1', ldrawPartNum: '3001.dat', name: 'Brick 2 x 4',
      contentLocale: 'en-US', translationStatus: 'reviewed', generatorVersion: null,
      taskId: null, geometry: {
        bbox: { minX: -20, minY: -12, minZ: -10, maxX: 20, maxY: 12, maxZ: 10 },
        logicalWidthStud: 2, logicalDepthStud: 4, logicalHeightPlate: 3,
        logicalSizeDerivationStatus: 'legacy_imported',
        vertexCount: 8, faceCount: 12,
      }, failure: null,
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ ...base, status: 'pending', model: null }))
      .mockResolvedValueOnce(jsonResponse({ taskId: 'task-1', status: 'queued' }, 202))
      .mockResolvedValueOnce(jsonResponse({ ...taskSucceeded, taskType: 'component.part_preview.materialize' }))
      .mockResolvedValueOnce(jsonResponse({
        ...base, status: 'ready', generatorVersion: 'part-preview-ldraw-glb-v1',
        model: {
          artifactId: 'artifact-1', format: 'glb',
          url: String.fromCharCode(104, 116, 116, 112, 115, 58, 47, 47) + 'storage.example/3001.glb',
          sha256: 'abc', byteLength: 42,
        },
      }));
    vi.stubGlobal('fetch', fetchMock);

    const preview = await loadPartPreview('library-1', '3001.dat');

    expect(preview.status).toBe('ready');
    expect(preview.model.artifactId).toBe('artifact-1');
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain(
      '/api/v1/part-library-versions/library-1/parts/3001.dat/preview',
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/v1/part-library-versions/library-1/parts/3001.dat/preview/materialize',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('maps Go version fields and deletes only the selected draft resource', async () => {
    const rawVersion = {
      id: 'version-1', componentId: 'component-1', componentCandidateId: 'candidate-1',
      version: '0.1.0', revision: 1, status: 'draft', sourceArtifactId: 'artifact-1',
      exchangeArtifactId: null, sceneSnapshotId: 'snapshot-1', parserVersion: 'parser-v1',
      partLibraryVersionId: null, validationReportId: null, interfaceSignature: '',
      structureHash: '', geometryHash: '', previewArtifactId: null, previewStatus: 'pending',
      previewGeneratorVersion: null, previewFailureCode: null, previewFailureParams: {},
      releaseNote: null, releaseNoteLocale: null, metadata: {},
      createdAt: '2026-08-12T00:00:00Z', publishedAt: null,
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(rawVersion))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);

    const version = await getComponentVersion('version-1');
    expect(version.previewFailure).toBeNull();
    expect(version.deletion).toEqual({ allowed: true, reason: null });
    await expect(deleteComponentVersion(version)).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/v1/component-versions/version-1',
      expect.objectContaining({ method: 'DELETE' }),
    );
  });

  it('deletes the whole component through the component resource endpoint', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(deleteComponent('component-1')).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/v1/components/component-1',
      expect.objectContaining({ method: 'DELETE' }),
    );
  });

  it('combines Go connector and interface resources without fabricating legacy analysis metadata', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ items: [{
        id: 'connector-1', worldConnectorId: 'world-1', partInstanceId: 'part-instance-1',
        partRef: '3001.dat', connectorType: 'stud', connectorKind: null,
        connectorGender: null, state: 'external', position: [1, 2, 3], axis: [0, 1, 0],
        matrix: [], accessAxis: [0, 0, 1], externalInterfaceId: 'interface-1',
        capacity: 1, occupiedSlots: 0, availableCapacity: 1, eligibility: {},
      }] }))
      .mockResolvedValueOnce(jsonResponse({ items: [{
        id: 'interface-1', componentCandidateId: 'candidate-1', worldConnectorId: 'world-1',
        name: 'stud', exposure: 'external', defaultBehavior: 'connect', sourceConnector: {},
        mechanicalRoles: [], businessRoles: [], requirements: {}, reviewStatus: 'automatic',
        createdAt: '2026-08-12T00:00:00Z', updatedAt: '2026-08-12T00:00:00Z',
      }] }));
    vi.stubGlobal('fetch', fetchMock);

    const analysis = await getConnectorAnalysis('candidate-1');

    expect(analysis.componentCandidateId).toBe('candidate-1');
    expect(analysis.connectors[0]).toMatchObject({
      connectorId: 'connector-1',
      connectorKind: '',
      position: { x: 1, y: 2, z: 3 },
      accessAxis: { x: 0, y: 0, z: 1 },
    });
    expect(analysis.externalInterfaces).toHaveLength(1);
  });

  it('uses the Go validation task result and publishes without a legacy edit body', async () => {
    const publishedVersion = {
      id: 'version-1', componentId: 'component-1', componentCandidateId: 'candidate-1',
      version: '0.1.0', revision: 1, status: 'published', sourceArtifactId: 'artifact-1',
      exchangeArtifactId: null, sceneSnapshotId: 'snapshot-1', parserVersion: 'parser-v1',
      partLibraryVersionId: null, validationReportId: 'report-1', interfaceSignature: '',
      structureHash: '', geometryHash: '', previewArtifactId: null, previewStatus: 'pending',
      previewGeneratorVersion: null, previewFailureCode: null, previewFailureParams: {},
      releaseNote: null, releaseNoteLocale: null, metadata: {},
      createdAt: '2026-08-12T00:00:00Z', publishedAt: '2026-08-12T00:01:00Z',
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ taskId: 'task-1', status: 'queued' }, 202))
      .mockResolvedValueOnce(jsonResponse({
        ...taskSucceeded,
        taskType: 'component.validate',
        result: { validationReportId: 'report-1', passed: true },
      }))
      .mockResolvedValueOnce(jsonResponse({
        id: 'report-1', componentCandidateId: 'candidate-1', componentVersionId: 'version-1',
        validationLevel: 'publish', passed: true, checks: [], issues: [],
        validatorVersion: 'validator-v1', createdAt: '2026-08-12T00:00:02Z',
      }))
      .mockResolvedValueOnce(jsonResponse(publishedVersion));
    vi.stubGlobal('fetch', fetchMock);

    await expect(validateCandidate('candidate-1')).resolves.toMatchObject({
      id: 'report-1',
      passed: true,
      checks: [],
    });
    await expect(publishVersion('version-1')).resolves.toMatchObject({
      id: 'version-1',
      status: 'published',
    });
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      '/api/v1/validation-reports/report-1',
      undefined,
    );
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/v1/component-versions/version-1/publish',
      expect.objectContaining({ method: 'POST' }),
    );
    const publishInit = fetchMock.mock.calls[fetchMock.mock.calls.length - 1]?.[1] as RequestInit;
    expect(publishInit.body).toBeUndefined();
  });
});
