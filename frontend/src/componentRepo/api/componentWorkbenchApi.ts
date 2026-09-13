import appConfig from '../../app/appConfig';
import { ApiError } from '../../api/client';
import { currentTaskContext } from '../../api/taskContext';
import { componentRepoPath as pathFor, componentRepoRequestJson as requestJson } from '../componentRepoTransport';
import type {
  ComponentCandidateResponse,
  ComponentConnectorAnalysisResponse,
  ComponentConnectorResponse,
  ComponentInterfaceResponse,
  ComponentRelationCandidateResponse,
  ComponentValidationReportResponse,
  PartLibraryVersionResponse,
  PartPreviewResponse,
  ReadyPartPreviewResponse,
} from '../componentRepoTypes';
import { waitForTask } from './componentTaskApi';

type AcceptedTask = { taskId: string; status: string };

type GoConnector = Omit<ComponentConnectorResponse, 'accessAxis' | 'connectorId' | 'connectorKind' | 'position'> & {
  id: string;
  connectorKind: string | null;
  position: number[];
  axis: number[];
  matrix: number[];
  accessAxis: number[];
};

export async function getActivePartLibraryVersion(): Promise<PartLibraryVersionResponse> {
  return requestJson<PartLibraryVersionResponse>(appConfig.componentRepoApi.activePartLibraryVersion);
}

/** Load one immutable Part resource and materialize its GLB through the durable task system. */

export async function loadPartPreview(
  partLibraryVersionId: string,
  ldrawPartNum: string,
): Promise<ReadyPartPreviewResponse> {
  const previewPath = pathFor('partPreview', { partLibraryVersionId, ldrawPartNum });
  const previewUrl = new URL(previewPath, window.location.origin);
  previewUrl.searchParams.set('locale', currentTaskContext().locale);
  let preview = await requestJson<PartPreviewResponse>(previewUrl.toString());
  if (preview.status !== 'ready') {
    const context = currentTaskContext();
    const accepted = await requestJson<AcceptedTask>(
      pathFor('partPreviewMaterialize', { partLibraryVersionId, ldrawPartNum }),
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(context),
      },
    );
    await waitForTask(accepted.taskId);
    preview = await requestJson<PartPreviewResponse>(previewUrl.toString());
  }
  if (preview.status === 'failed' || !preview.model) {
    throw new ApiError(
      preview.failure?.code ?? 'component_repo.part_preview_unavailable',
      preview.failure?.params ?? { partLibraryVersionId, ldrawPartNum },
      null,
      409,
    );
  }
  if (!preview.geometry) {
    throw new ApiError(
      'component_repo.part_preview_unavailable',
      { partLibraryVersionId, ldrawPartNum },
      null,
      409,
    );
  }
  return preview as ReadyPartPreviewResponse;
}

export async function getCandidate(candidateId: string): Promise<ComponentCandidateResponse> {
  return requestJson<ComponentCandidateResponse>(pathFor('candidateDetail', { candidateId }));
}

export async function listRelations(candidateId: string): Promise<ComponentRelationCandidateResponse[]> {
  const response = await requestJson<{ items: ComponentRelationCandidateResponse[] }>(
    pathFor('candidateRelations', { candidateId }),
  );
  return response.items;
}

export async function detectRelations(candidateId: string): Promise<ComponentRelationCandidateResponse[]> {
  const accepted = await requestJson<AcceptedTask>(pathFor('candidateRelationsDetect', { candidateId }), {
    method: 'POST',
  });
  await waitForTask(accepted.taskId);
  return listRelations(candidateId);
}

export async function confirmRelation(
  candidateId: string,
  relationId: string,
): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>(pathFor('candidateRelationConfirm', { candidateId, relationId }), {
    method: 'POST',
  });
}

export async function rejectRelation(
  candidateId: string,
  relationId: string,
): Promise<ComponentRelationCandidateResponse> {
  return requestJson<ComponentRelationCandidateResponse>(pathFor('candidateRelationReject', { candidateId, relationId }), {
    method: 'POST',
  });
}

export async function getConnectorAnalysis(candidateId: string): Promise<ComponentConnectorAnalysisResponse> {
  const [connectors, externalInterfaces] = await Promise.all([
    listConnectors(candidateId),
    listInterfaces(candidateId),
  ]);
  return { componentCandidateId: candidateId, connectors, externalInterfaces };
}

export async function listInterfaces(candidateId: string): Promise<ComponentInterfaceResponse[]> {
  const response = await requestJson<{ items: ComponentInterfaceResponse[] }>(
    pathFor('candidateInterfaces', { candidateId }),
  );
  return response.items;
}

export async function validateCandidate(candidateId: string): Promise<ComponentValidationReportResponse> {
  const accepted = await requestJson<AcceptedTask>(pathFor('candidateValidate', { candidateId }), {
    method: 'POST',
  });
  const task = await waitForTask(accepted.taskId);
  const reportId = String(task.result.validationReportId ?? '');
  if (!reportId) throw new ApiError('common.invalid_response');
  return getValidationReport(reportId);
}

// 读取持久化验证报告；可见性由 Go Backend 按 Draft/Published Version 边界判定。

export async function getValidationReport(reportId: string): Promise<ComponentValidationReportResponse> {
  return requestJson<ComponentValidationReportResponse>(pathFor('validationReport', { reportId }));
}

async function listConnectors(candidateId: string): Promise<ComponentConnectorResponse[]> {
  const response = await requestJson<{ items: GoConnector[] }>(
    pathFor('candidateConnectors', { candidateId }),
  );
  return response.items.map((connector) => ({
    ...connector,
    connectorId: connector.id,
    connectorKind: connector.connectorKind ?? '',
    position: vectorFromGo(connector.position),
    accessAxis: vectorFromGo(connector.accessAxis),
  }));
}

function vectorFromGo(value: number[]): Record<string, number> {
  return { x: value[0] ?? 0, y: value[1] ?? 0, z: value[2] ?? 0 };
}
