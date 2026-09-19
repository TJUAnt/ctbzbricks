import React from 'react';
import appConfig from '../app/appConfig';
import {
  getComponent,
  getValidationReport,
  listComponentGroupIds,
  listComponentGroups,
  listComponentVersions,
  loadComponentVersionParts,
  loadComponentVersionPreview,
  type ComponentGroupTreeResponse,
  type ComponentResponse,
  type ComponentValidationReportResponse,
  type ComponentVersionPartsResponse,
  type ComponentVersionPreviewModelResponse,
  type ComponentVersionResponse,
} from './componentRepoApi';

/** ComponentDetailState 汇总详情首屏及各个可独立降级的派生数据区域。 */
export type ComponentDetailState = {
  component: ComponentResponse | null;
  version: ComponentVersionResponse | null;
  versions: ComponentVersionResponse[];
  preview: ComponentVersionPreviewModelResponse | null;
  partDetails: ComponentVersionPartsResponse | null;
  validationReport: ComponentValidationReportResponse | null;
  groupTree: ComponentGroupTreeResponse | null;
  groupIds: string[];
  loading: boolean;
  previewLoading: boolean;
  partsLoading: boolean;
  validationLoading: boolean;
  error: string | null;
  previewError: string | null;
};

const initialState: ComponentDetailState = {
  component: null,
  version: null,
  versions: [],
  preview: null,
  partDetails: null,
  validationReport: null,
  groupTree: null,
  groupIds: [],
  loading: true,
  previewLoading: true,
  partsLoading: true,
  validationLoading: true,
  error: null,
  previewError: null,
};

/**
 * useComponentDetailData 负责详情页的读取编排和陈旧响应隔离。
 *
 * Component/Version 是主数据；Preview、BOM 与验证报告分别降级，任一派生读取失败都不能
 * 清空已确认的 Component，也不能改变 owner 权限。refreshToken 只表达显式 mutation 后的权威重读。
 */
export function useComponentDetailData(input: {
  componentId: string;
  contentLocale: string;
  refreshToken: number;
  noVersionsMessage: string;
  unknownErrorMessage: string;
}): [ComponentDetailState, React.Dispatch<React.SetStateAction<ComponentDetailState>>] {
  const [state, setState] = React.useState<ComponentDetailState>(initialState);

  React.useEffect(() => {
    let active = true;
    const load = async () => {
      setState((current) => ({
        ...current,
        loading: true,
        previewLoading: true,
        partsLoading: true,
        validationLoading: true,
        error: null,
        previewError: null,
      }));
      try {
        const [component, versions] = await Promise.all([
          getComponent(input.componentId),
          listComponentVersions(input.componentId),
        ]);
        // 分组关系属于 owner 私有数据；公开详情只读取 Component 和版本，不探测他人的分组。
        const [groupTree, groupIds] = component.ownedByActor
          ? await Promise.all([listComponentGroups(), listComponentGroupIds(input.componentId)])
          : [null, [] as string[]];
        const version = preferredDetailVersion(component, versions);
        if (!version) throw new Error(input.noVersionsMessage);
        // 连接分析属于 Candidate 工作台审核信息；详情页不预读该数据，避免公开阅读路径承担额外请求。
        const partDetailsPromise = loadComponentVersionParts(version.id)
          .then((partDetails) => ({ partDetails }))
          .catch(() => ({ partDetails: null }));
        const validationReportPromise = version.validationReportId
          ? getValidationReport(version.validationReportId)
            .then((validationReport) => ({ validationReport }))
            .catch(() => ({ validationReport: null }))
          : Promise.resolve({ validationReport: null });
        if (!active) return;
        setState((current) => ({
          ...current,
          component,
          version,
          versions,
          groupTree,
          groupIds,
          loading: false,
        }));
        // Preview 是可重建派生数据；失败只降级预览区域，主数据和 owner 动作保持可用。
        const previewResult = await loadComponentVersionPreview(version.id)
          .then((preview) => ({ preview, previewError: null as string | null }))
          .catch((previewError: unknown) => ({
            preview: null,
            previewError: previewError instanceof Error
              ? previewError.message
              : input.unknownErrorMessage,
          }));
        if (!active) return;
        setState({
          component,
          version,
          versions,
          preview: previewResult.preview,
          partDetails: null,
          validationReport: null,
          groupTree,
          groupIds,
          loading: false,
          previewLoading: false,
          partsLoading: true,
          validationLoading: true,
          error: null,
          previewError: previewResult.previewError,
        });

        const { partDetails } = await partDetailsPromise;
        if (!active) return;
        setState((current) => ({ ...current, partDetails, partsLoading: false }));

        const { validationReport } = await validationReportPromise;
        if (!active) return;
        setState((current) => ({ ...current, validationReport, validationLoading: false }));
      } catch (error) {
        if (!active) return;
        setState((current) => ({
          ...current,
          loading: false,
          previewLoading: false,
          partsLoading: false,
          validationLoading: false,
          error: error instanceof Error ? error.message : appConfig.texts.loadFailed,
        }));
      }
    };
    if (input.componentId) void load();
    return () => {
      active = false;
    };
  }, [input.componentId, input.contentLocale, input.refreshToken]);

  return [state, setState];
}

function preferredDetailVersion(
  component: ComponentResponse,
  versions: ComponentVersionResponse[],
): ComponentVersionResponse | undefined {
  const current = versions.find((item) => item.id === component.currentVersionId);
  const currentCreatedAt = current ? Date.parse(current.createdAt) : Number.NEGATIVE_INFINITY;
  const newerDraft = versions.find(
    (item) => item.status === 'draft' && Date.parse(item.createdAt) > currentCreatedAt,
  );
  return newerDraft ?? current ?? versions[0];
}
