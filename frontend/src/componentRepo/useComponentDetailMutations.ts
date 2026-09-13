import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useAppTranslation } from '../i18n';
import {
  deleteComponent,
  publishVersion,
  starComponent,
  unstarComponent,
  unwatchComponent,
  validateCandidate,
  watchComponent,
} from './componentRepoApi';
import { routeFor } from './ComponentRepoPresenters';
import type { ComponentDetailState } from './useComponentDetailData';

type DetailMutationInput = {
  isAuthConfigured: boolean;
  isAuthLoading: boolean;
  requestRefresh: () => void;
  setState: React.Dispatch<React.SetStateAction<ComponentDetailState>>;
  state: ComponentDetailState;
  userId: string | undefined;
};

/**
 * useComponentDetailMutations 集中处理详情页的权限投影、乐观更新和持久化操作。
 * Go API 仍是所有权与最终状态的权威来源；失败的乐观更新通过重新读取完整详情恢复。
 */
export function useComponentDetailMutations(input: DetailMutationInput) {
  const tr = useAppTranslation();
  const navigate = useNavigate();
  const [actionNotice, setActionNotice] = React.useState<string | null>(null);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [publishing, setPublishing] = React.useState(false);
  const [validating, setValidating] = React.useState(false);
  const [starring, setStarring] = React.useState(false);
  const [watchMutating, setWatchMutating] = React.useState(false);
  const [confirmingDeleteComponent, setConfirmingDeleteComponent] = React.useState(false);
  const [deletingComponent, setDeletingComponent] = React.useState(false);

  // 所有权由已鉴权的 Go API 投影；缺失时只为尚未重启的本地旧 API 保留兼容判断。
  const componentOwnedByActor = Boolean(
    input.state.component
      && (
        input.state.component.ownedByActor
        ?? (!input.isAuthConfigured || input.state.component.ownerId === input.userId)
      ),
  );
  const componentOwnershipResolved = Boolean(
    input.state.component
      && (typeof input.state.component.ownedByActor === 'boolean' || !input.isAuthLoading),
  );
  const canPublish = Boolean(
    input.state.component
      && input.state.version?.status === 'draft'
      && input.state.component.contentKind === 'user'
      && componentOwnershipResolved
      && componentOwnedByActor,
  );
  const canValidate = Boolean(
    input.state.component
      && input.state.version?.componentCandidateId
      && (input.state.version.status === 'draft' || input.state.version.status === 'published')
      && input.state.component.contentKind === 'user'
      && componentOwnershipResolved
      && componentOwnedByActor,
  );
  const canDeleteComponent = Boolean(
    input.state.component
      && input.state.component.contentKind === 'user'
      && componentOwnershipResolved
      && componentOwnedByActor,
  );
  const canStarComponent = Boolean(
    input.state.component && componentOwnershipResolved && !componentOwnedByActor,
  );
  const canWatchComponent = canStarComponent;

  const publish = async () => {
    if (!input.state.version || !canPublish) return;
    setPublishing(true);
    setActionError(null);
    setActionNotice(null);
    try {
      await publishVersion(input.state.version.id);
      setActionNotice(tr('componentRepo:componentVersionPublished'));
      input.requestRefresh();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : tr('errors:common.unknown'));
    } finally {
      setPublishing(false);
    }
  };

  // 验证任务与发布动作保持独立，完成后只更新当前详情中的验证报告。
  const validate = async () => {
    if (!input.state.version?.componentCandidateId || !canValidate) return;
    setValidating(true);
    setActionError(null);
    setActionNotice(null);
    try {
      const validationReport = await validateCandidate(input.state.version.componentCandidateId);
      input.setState((current) => ({ ...current, validationReport, validationLoading: false }));
      setActionNotice(tr('componentRepo:validationComplete'));
    } catch (error) {
      setActionError(error instanceof Error ? error.message : tr('errors:common.unknown'));
    } finally {
      setValidating(false);
    }
  };

  const confirmDeleteComponent = async () => {
    if (!input.state.component || !canDeleteComponent) return;
    setDeletingComponent(true);
    setActionError(null);
    setActionNotice(null);
    try {
      await deleteComponent(input.state.component.id);
      navigate(routeFor('componentRepo'));
    } catch (error) {
      setActionError(error instanceof Error ? error.message : tr('errors:common.unknown'));
      setConfirmingDeleteComponent(false);
    } finally {
      setDeletingComponent(false);
    }
  };

  const toggleStar = async () => {
    if (!input.state.component || !canStarComponent || starring) return;
    const componentId = input.state.component.id;
    const wasStarred = input.state.component.starredByActor;
    setStarring(true);
    setActionError(null);
    setActionNotice(null);
    input.setState((current) => current.component ? {
      ...current,
      component: {
        ...current.component,
        starredByActor: !wasStarred,
        starCount: Math.max(0, current.component.starCount + (wasStarred ? -1 : 1)),
      },
    } : current);
    try {
      if (wasStarred) await unstarComponent(componentId);
      else await starComponent(componentId);
      setActionNotice(tr(wasStarred ? 'componentRepo:componentUnstarred' : 'componentRepo:componentStarred'));
    } catch (error) {
      setActionError(error instanceof Error ? error.message : tr('errors:common.unknown'));
      input.requestRefresh();
    } finally {
      setStarring(false);
    }
  };

  // Watch 是独立偏好；乐观更新失败时重新读取服务端权威状态。
  const toggleWatch = async () => {
    if (!input.state.component || !canWatchComponent || watchMutating) return;
    const componentId = input.state.component.id;
    const wasWatching = Boolean(input.state.component.watch?.watching);
    setWatchMutating(true);
    setActionError(null);
    setActionNotice(null);
    input.setState((current) => current.component ? {
      ...current,
      component: {
        ...current.component,
        watch: wasWatching
          ? { watching: false, level: null, watchedAt: null }
          : { watching: true, level: 'releases_only', watchedAt: null },
      },
    } : current);
    try {
      if (wasWatching) {
        await unwatchComponent(componentId);
        setActionNotice(tr('componentRepo:componentUnwatched'));
      } else {
        const watch = await watchComponent(componentId);
        input.setState((current) => current.component ? {
          ...current,
          component: {
            ...current.component,
            watch: { watching: true, level: watch.level, watchedAt: watch.watchedAt },
          },
        } : current);
        setActionNotice(tr('componentRepo:componentWatched'));
      }
    } catch (error) {
      setActionError(error instanceof Error ? error.message : tr('errors:common.unknown'));
      input.requestRefresh();
    } finally {
      setWatchMutating(false);
    }
  };

  return {
    actionError,
    actionNotice,
    canDeleteComponent,
    canPublish,
    canStarComponent,
    canValidate,
    canWatchComponent,
    componentOwnedByActor,
    confirmingDeleteComponent,
    confirmDeleteComponent,
    deletingComponent,
    publish,
    publishing,
    setActionError,
    setActionNotice,
    setConfirmingDeleteComponent,
    starring,
    toggleStar,
    toggleWatch,
    validate,
    validating,
    watchMutating,
  };
}
