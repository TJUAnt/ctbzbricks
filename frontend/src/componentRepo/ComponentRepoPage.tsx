import React from 'react';
import {
  AlertCircle,
  Bell,
  Boxes,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileClock,
  Folder,
  FolderOpen,
  Layers3,
  LoaderCircle,
  PackageCheck,
  RefreshCw,
  Search,
  Star,
  Upload,
  X,
} from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import appConfig from '../app/appConfig';
import { resolvedLocale, useAppTranslation, useDynamicTranslation, type TranslationKey } from '../i18n';
import { formatNumber } from '../i18n/formatters';
import {
  deleteComponentGroup,
  listComponentGroups,
  listComponentStars,
  listComponentVersions,
  moveComponentGroup,
  searchComponentGroupComponents,
  starComponent,
  unstarComponent,
  type ComponentGroupResponse,
  type ComponentGroupTreeResponse,
  type ComponentResponse,
  type ComponentVersionResponse,
} from './componentRepoApi';
import {
  ComponentGroupDialog,
  ComponentGroupMembershipDialog,
  ComponentGroupSidebar,
  GroupComponentMembershipDialog,
} from './ComponentGroupControls';
import {
  buildLibraryItems,
  ComponentLogicalSize,
  formatDate,
  routeFor,
  shortId,
  StatusPill,
  statusesForFilter,
  SummaryCard,
  sumStatuses,
  VersionDropdown,
  type LibraryFilter,
} from './ComponentRepoPresenters';
import { ComponentStarButton } from './ComponentStarButton';
import { ComponentUploadDialog } from './ComponentUploadDialog';

type ComponentRepoListState = {
  status: 'loading' | 'ready' | 'error';
  components: ComponentResponse[];
  error: string | null;
  total: number;
  page: number;
  totalPages: number;
  statusCounts: Record<string, number>;
};

type LibraryView = 'library' | 'starred';

const componentSearchPageSize = 20;
const componentSearchDebounceMs = 300;

/** ComponentRepoPage 只管理当前 actor 的个人仓库、分组、收藏和版本入口。 */
export function ComponentRepoPage() {
  const navigate = useNavigate();
  const tr = useAppTranslation();
  const trDynamic = useDynamicTranslation();
  const contentLocale = resolvedLocale();
  const [state, setState] = React.useState<ComponentRepoListState>({
    status: 'loading',
    components: [],
    error: null,
    total: 0,
    page: 1,
    totalPages: 0,
    statusCounts: {},
  });
  const [queries, setQueries] = React.useState<string[]>([]);
  const [queryDraft, setQueryDraft] = React.useState('');
  const [filter, setFilter] = React.useState<LibraryFilter>('all');
  const [category, setCategory] = React.useState('');
  const [libraryView, setLibraryView] = React.useState<LibraryView>('library');
  const [page, setPage] = React.useState(1);
  const [refreshRevision, setRefreshRevision] = React.useState(0);
  const [isUploadOpen, setIsUploadOpen] = React.useState(false);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [actionNotice, setActionNotice] = React.useState<string | null>(null);
  const [selectedComponent, setSelectedComponent] = React.useState<ComponentResponse | null>(null);
  const [selectedComponentKey, setSelectedComponentKey] = React.useState<string | null>(null);
  const [versions, setVersions] = React.useState<ComponentVersionResponse[]>([]);
  const [versionState, setVersionState] = React.useState<'idle' | 'loading' | 'error'>('idle');
  const [groupTree, setGroupTree] = React.useState<ComponentGroupTreeResponse | null>(null);
  const [selectedGroupId, setSelectedGroupId] = React.useState<string | null>(null);
  const selectedGroupIdRef = React.useRef<string | null>(null);
  const groupRequestIdRef = React.useRef(0);
  const searchRequestIdRef = React.useRef(0);
  const [groupEditor, setGroupEditor] = React.useState<{
    mode: 'create' | 'edit';
    group?: ComponentGroupResponse;
    parentGroupId: string;
  } | null>(null);
  const [membershipComponent, setMembershipComponent] = React.useState<ComponentResponse | null>(null);
  const [membershipGroup, setMembershipGroup] = React.useState<ComponentGroupResponse | null>(null);
  const [starMutations, setStarMutations] = React.useState<Set<string>>(new Set());

  const loadLibrary = React.useCallback(async (preferredGroupId?: string | null) => {
    const requestId = ++groupRequestIdRef.current;
    try {
      const tree = await listComponentGroups();
      if (requestId !== groupRequestIdRef.current) return;

      const availableIds = new Set([tree.root.id, ...tree.groups.map((group) => group.id)]);
      const requestedGroupId = preferredGroupId === undefined
        ? selectedGroupIdRef.current
        : preferredGroupId;
      const groupId = requestedGroupId && availableIds.has(requestedGroupId)
        ? requestedGroupId
        : tree.root.id;
      selectedGroupIdRef.current = groupId;
      setGroupTree(tree);
      setSelectedGroupId(groupId);
    } catch (error) {
      if (requestId !== groupRequestIdRef.current) return;
      setState((current) => ({
        ...current,
        status: 'error',
        error: error instanceof Error ? error.message : appConfig.texts.loadFailed,
      }));
    }
  }, []);

  const refreshLibrary = React.useCallback(() => {
    void loadLibrary();
    setRefreshRevision((current) => current + 1);
  }, [loadLibrary]);

  const selectGroup = React.useCallback((groupId: string) => {
    selectedGroupIdRef.current = groupId;
    setSelectedGroupId(groupId);
    setPage(1);
  }, []);

  React.useEffect(() => {
    // 重新请求可确保已进入错误态的结构化错误随当前语言重新渲染，避免把切换前的译文固化在页面中。
    void loadLibrary();
    return () => {
      groupRequestIdRef.current += 1;
      searchRequestIdRef.current += 1;
    };
  }, [contentLocale, loadLibrary]);

  React.useEffect(() => {
    if (libraryView === 'library' && !selectedGroupId) return undefined;
    const requestId = ++searchRequestIdRef.current;
    const timeoutId = window.setTimeout(() => {
      setState((current) => ({
        ...current,
        status: 'loading',
        error: null,
      }));
      const request = libraryView === 'starred'
        ? listComponentStars({
          page,
          pageSize: componentSearchPageSize,
          query: queries.join(' '),
          category,
          sort: 'starred_at_desc',
        }).then((result) => ({
          ...result,
          statusCounts: { active: result.total },
        }))
        : searchComponentGroupComponents(selectedGroupId!, {
          queries,
          statuses: statusesForFilter(filter),
          page,
          pageSize: componentSearchPageSize,
          });
      void request
        .then((result) => {
          if (requestId !== searchRequestIdRef.current) return;
          setState({
            status: 'ready',
            components: result.items,
            error: null,
            total: result.total,
            page: result.page,
            totalPages: result.totalPages,
            statusCounts: result.statusCounts,
          });
        })
        .catch((error: Error) => {
          if (requestId !== searchRequestIdRef.current) return;
          setState((current) => ({
            ...current,
            status: 'error',
            error: error instanceof Error ? error.message : appConfig.texts.loadFailed,
          }));
        });
    }, componentSearchDebounceMs);
    return () => {
      window.clearTimeout(timeoutId);
      searchRequestIdRef.current += 1;
    };
  }, [category, contentLocale, filter, libraryView, page, queries, refreshRevision, selectedGroupId]);

  const items = React.useMemo(
    () => buildLibraryItems(state.components),
    [state.components],
  );
  const stats = React.useMemo(() => ({
    total: state.total,
    draft: sumStatuses(state.statusCounts, ['draft']),
    published: sumStatuses(state.statusCounts, ['active']),
  }), [state.statusCounts, state.total]);
  const selectedGroup = groupTree
    ? [groupTree.root, ...groupTree.groups].find((group) => group.id === selectedGroupId)
      ?? groupTree.root
    : null;
  const selectedGroupName = selectedGroup?.groupType === 'root'
    ? tr('componentRepo:groupRootName')
    : selectedGroup?.name ?? tr('componentRepo:groupRootName');

  const toggleStar = async (component: ComponentResponse) => {
    if (component.ownedByActor || starMutations.has(component.id)) return;
    const nextStarred = !component.starredByActor;
    const shouldMoveToPreviousPage = libraryView === 'starred'
      && !nextStarred
      && state.components.length === 1
      && page > 1;
    setActionError(null);
    setActionNotice(null);
    setStarMutations((current) => new Set(current).add(component.id));
    setState((current) => ({
      ...current,
      components: current.components
        .map((item) => item.id === component.id ? {
          ...item,
          starredByActor: nextStarred,
          starCount: Math.max(0, item.starCount + (nextStarred ? 1 : -1)),
        } : item)
        .filter((item) => libraryView !== 'starred' || item.starredByActor),
      total: libraryView === 'starred' && !nextStarred ? Math.max(0, current.total - 1) : current.total,
    }));
    try {
      if (nextStarred) await starComponent(component.id);
      else await unstarComponent(component.id);
      setActionNotice(tr(nextStarred ? 'componentRepo:componentStarred' : 'componentRepo:componentUnstarred'));
      if (shouldMoveToPreviousPage) setPage((current) => Math.max(1, current - 1));
      setRefreshRevision((current) => current + 1);
      void loadLibrary();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : appConfig.texts.loadFailed);
      setRefreshRevision((current) => current + 1);
    } finally {
      setStarMutations((current) => {
        const next = new Set(current);
        next.delete(component.id);
        return next;
      });
    }
  };

  const removeGroup = async (group: ComponentGroupResponse) => {
    if (!window.confirm(tr('componentRepo:deleteGroupConfirmation', { name: group.name ?? '' }))) return;
    setActionError(null);
    try {
      await deleteComponentGroup(group.id);
      if (groupTree) selectGroup(groupTree.root.id);
      else refreshLibrary();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : appConfig.texts.loadFailed);
    }
  };
  const moveGroup = async (groupId: string, parentGroupId: string, position: number) => {
    setActionError(null);
    try {
      await moveComponentGroup(groupId, parentGroupId, position);
      refreshLibrary();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : appConfig.texts.loadFailed);
    }
  };

  const toggleVersions = async (component: ComponentResponse, itemKey: string) => {
    if (selectedComponentKey === itemKey) {
      setSelectedComponent(null);
      setSelectedComponentKey(null);
      return;
    }
    setSelectedComponent(component);
    setSelectedComponentKey(itemKey);
    setVersions([]);
    setVersionState('loading');
    try {
      setVersions(await listComponentVersions(component.id));
      setVersionState('idle');
    } catch {
      setVersionState('error');
    }
  };

  return (
    <section className="component-library-page">
      <header className="component-library-hero">
        <div className="component-library-heading">
          <span className="component-library-heading-icon"><Boxes aria-hidden="true" /></span>
          <div>
            <h1>{tr('app:navigation.myModels')}</h1>
            <p>{tr('app:navigation.myModelsDescription')}</p>
          </div>
        </div>
        <nav aria-label={tr('componentRepo:componentLibrarySections')} className="component-library-tabs">
          <button
            aria-pressed={libraryView === 'library'}
            className={`component-library-tab ${libraryView === 'library' ? 'component-library-tab-active' : ''}`}
            onClick={() => {
              setLibraryView('library');
              setFilter('all');
              setCategory('');
              setPage(1);
            }}
            type="button"
          >
            <FolderOpen aria-hidden="true" />
            {tr('componentRepo:myComponentLibrary')}
          </button>
          <button
            aria-pressed={libraryView === 'starred'}
            className={`component-library-tab ${libraryView === 'starred' ? 'component-library-tab-active' : ''}`}
            onClick={() => {
              setLibraryView('starred');
              setFilter('all');
              setPage(1);
            }}
            type="button"
          >
            <Star aria-hidden="true" />
            {tr('componentRepo:myStarredComponents')}
          </button>
          <Link className="component-library-tab" to={routeFor('componentRepoWatches')}>
            <Bell aria-hidden="true" />
            {tr('componentRepo:mySubscriptions')}
          </Link>
        </nav>
      </header>

      <section className="component-library-summary" aria-label={tr('componentRepo:componentStatusOverview')}>
        <SummaryCard icon={<Boxes />} label={tr('componentRepo:allComponents')} tone="blue" value={stats.total} />
        <SummaryCard icon={<Layers3 />} label={tr('componentRepo:draft')} tone="purple" value={stats.draft} />
        <SummaryCard icon={<PackageCheck />} label={tr('componentRepo:published')} tone="green" value={stats.published} />
      </section>

      <section className="component-library-panel">
        <header className="component-library-panel-header">
          <div>
            <div className="component-library-title-row">
              <h2>{libraryView === 'starred' ? tr('componentRepo:myStarredComponents') : selectedGroupName}</h2>
              <span>{stats.total}</span>
            </div>
            <p>{tr(libraryView === 'starred'
              ? 'componentRepo:starredComponentsDescription'
              : selectedGroup?.groupType === 'custom'
                ? 'componentRepo:customGroupDescription'
                : 'componentRepo:rootGroupDescription')}</p>
          </div>
          <div className="component-library-panel-actions">
            <button onClick={() => navigate(routeFor('componentRepoImportHistory'))} type="button">
              <FileClock aria-hidden="true" />
              {tr('componentRepo:importHistory')}
            </button>
            <button className="component-library-upload-button" onClick={() => setIsUploadOpen(true)} type="button">
              <Upload aria-hidden="true" />
              {tr('componentRepo:uploadComponent')}
            </button>
          </div>
        </header>

        <div className={`component-library-workspace ${libraryView !== 'library' ? 'component-library-workspace-starred' : ''}`}>
          {libraryView === 'library' ? <ComponentGroupSidebar
            onCreate={(parentGroupId) => setGroupEditor({ mode: 'create', parentGroupId })}
            onDelete={(group) => void removeGroup(group)}
            onEdit={(group) => setGroupEditor({ mode: 'edit', group, parentGroupId: group.parentGroupId ?? groupTree?.root.id ?? '' })}
            onAddComponents={setMembershipGroup}
            onMove={(groupId, parentGroupId, position) => void moveGroup(groupId, parentGroupId, position)}
            onSelect={selectGroup}
            selectedGroupId={selectedGroupId}
            tree={groupTree}
          /> : null}
          <div className="component-library-main">
        <div className="component-library-toolbar">
          <form
            className="component-library-search-form"
            onSubmit={(event) => {
              event.preventDefault();
              const nextQuery = queryDraft.trim();
              if (!nextQuery) return;
              // 个人分组支持多个 AND 条件；收藏 API 是单查询契约，因此新条件替换旧条件。
              setQueries((current) => libraryView !== 'library'
                ? [nextQuery]
                : current.some(
                  (condition) => condition.toLocaleLowerCase() === nextQuery.toLocaleLowerCase(),
                ) ? current : [...current, nextQuery]);
              setQueryDraft('');
              setPage(1);
            }}
          >
            <label className="component-library-search">
              <Search aria-hidden="true" />
              <input
                aria-label={tr('componentRepo:searchComponents')}
                onChange={(event) => setQueryDraft(event.target.value)}
                placeholder={tr('componentRepo:searchComponentNameIdOrSize')}
                value={queryDraft}
              />
            </label>
            {queries.map((query) => (
              <span
                aria-label={tr('componentRepo:activeSearchCondition')}
                className="component-library-search-condition"
                key={query}
              >
                <span title={query}>{query}</span>
                <button
                  aria-label={tr('componentRepo:clearSearchCondition', { query })}
                  onClick={() => {
                    // 单个标签只撤销自身条件，其他已固化条件必须继续参与搜索。
                    setQueries((current) => current.filter((condition) => condition !== query));
                    setPage(1);
                  }}
                  type="button"
                >
                  <X aria-hidden="true" />
                </button>
              </span>
            ))}
          </form>
          {libraryView === 'starred' ? <label className="component-library-category-filter">
            <span>{tr('componentRepo:categoryFilter')}</span>
            <input
              aria-label={tr('componentRepo:categoryFilter')}
              maxLength={128}
              onChange={(event) => {
                setCategory(event.target.value);
                setPage(1);
              }}
              placeholder={tr('componentRepo:allCategories')}
              value={category}
            />
          </label> : null}
          {libraryView === 'library' ? <div className="component-library-filters" role="group" aria-label={tr('componentRepo:filterByStatus')}>
            {([
              ['all', 'componentRepo:all'],
              ['draft', 'componentRepo:draft'],
              ['published', 'componentRepo:published'],
            ] as Array<[LibraryFilter, TranslationKey]>).map(([value, label]) => (
              <button
                className={filter === value ? 'component-library-filter-active' : undefined}
                key={value}
                onClick={() => {
                  setFilter(value);
                  setPage(1);
                }}
                type="button"
              >
                {trDynamic(label)}
              </button>
            ))}
          </div> : null}
          <button aria-label={tr('componentRepo:refreshComponentList')} className="component-library-refresh" onClick={refreshLibrary} type="button">
            <RefreshCw aria-hidden="true" className={state.status === 'loading' ? 'component-library-spin' : undefined} />
          </button>
        </div>

        {state.status === 'error' ? <div className="component-library-alert"><AlertCircle />{state.error}</div> : null}
        {actionError ? <div className="component-library-alert"><AlertCircle />{actionError}</div> : null}
        {actionNotice ? <div className="component-library-notice"><CheckCircle2 />{actionNotice}</div> : null}

        <div className="component-library-table" role="table" aria-label={tr('componentRepo:myComponentList')}>
          <div className="component-library-table-head" role="row">
            <span role="columnheader">{tr('componentRepo:component')}</span>
            <span role="columnheader">{tr('componentRepo:occupiedSize')}</span>
            <span role="columnheader">{tr('componentRepo:status')}</span>
            <span role="columnheader">{tr(libraryView === 'starred' ? 'componentRepo:starredAt' : 'componentRepo:uploadedAt')}</span>
            <span role="columnheader">{tr('componentRepo:actions')}</span>
          </div>
          {items.map((item) => (
            <article className="component-library-row" key={item.key} role="row">
              <div className="component-library-item-main" role="cell">
                <span className="component-library-file-icon component-library-file-icon-blue">
                  <Boxes />
                </span>
                <div>
                  <strong>{item.name}</strong>
                  <span>{shortId(item.id)}</span>
                </div>
              </div>
              <ComponentLogicalSize size={item.data.logicalSize} />
              <div role="cell"><StatusPill status={item.status} /></div>
              <span className="component-library-date" role="cell">{formatDate(libraryView === 'starred' && item.starredAt ? item.starredAt : item.createdAt)}</span>
              <div className="component-library-row-action" role="cell">
                <div className="component-library-component-actions">
                  <Link to={routeFor('componentRepoDetail').replace(':componentId', encodeURIComponent(item.id))}>
                    {tr('componentRepo:details')}<ChevronRight aria-hidden="true" />
                  </Link>
                  {!item.data.ownedByActor ? <ComponentStarButton
                    disabled={starMutations.has(item.id)}
                    onClick={() => void toggleStar(item.data)}
                    starred={item.data.starredByActor}
                  >
                    {starMutations.has(item.id) ? <LoaderCircle className="component-library-spin" /> : <Star aria-hidden="true" fill={item.data.starredByActor ? 'currentColor' : 'none'} />}
                    {formatNumber(item.data.starCount)}
                  </ComponentStarButton> : <span className="component-library-star-count" title={tr('componentRepo:starCount')}>
                    <Star aria-hidden="true" />{formatNumber(item.data.starCount)}
                  </span>}
                  {item.data.ownedByActor || item.data.starredByActor || (libraryView === 'library' && selectedGroup?.groupType === 'custom') ? <button onClick={() => setMembershipComponent(item.data)} type="button">
                    <Layers3 aria-hidden="true" />{tr('componentRepo:manageGroups')}
                  </button> : null}
                  <button aria-expanded={selectedComponentKey === item.key} onClick={() => void toggleVersions(item.data, item.key)} type="button">
                    {tr('componentRepo:viewVersions')}<ChevronDown aria-hidden="true" />
                  </button>
                  {selectedComponentKey === item.key && selectedComponent?.id === item.id ? (
                    <VersionDropdown
                      component={item.data}
                      onDeleted={(deletedVersion) => {
                        setVersions((current) => current.filter(
                          (version) => version.id !== deletedVersion.id,
                        ));
                        setActionNotice(tr('componentRepo:versionDeleted', {
                          version: deletedVersion.version,
                        }));
                      }}
                      state={versionState}
                      versions={versions}
                    />
                  ) : null}
                </div>
              </div>
            </article>
          ))}
        </div>

        {state.status === 'loading' && items.length === 0 ? (
          <div className="component-library-empty"><LoaderCircle className="component-library-spin" /><strong>{tr('componentRepo:loadingComponents')}</strong></div>
        ) : null}
        {state.status !== 'loading' && items.length === 0 ? (
          <div className="component-library-empty">
            <span><Search aria-hidden="true" /></span>
            <strong>{tr(libraryView === 'starred'
              ? queries.length > 0 || category.trim() !== ''
                ? 'componentRepo:noMatchingComponents'
                : 'componentRepo:noStarredComponents'
              : stats.total === 0
                ? 'componentRepo:noComponentsUploaded'
                : 'componentRepo:noMatchingComponents')}</strong>
            <p>{tr(libraryView === 'starred'
              ? queries.length > 0 || category.trim() !== ''
                ? 'componentRepo:tryChangingStarFilters'
                : 'componentRepo:browseComponentsToStar'
              : stats.total === 0
                ? 'componentRepo:uploadYourFirstComponentToStartBuildingYourLibrary'
                : 'componentRepo:tryChangingTheSearchTermOrStatusFilter')}</p>
            {libraryView === 'library' && stats.total === 0 ? <button onClick={() => setIsUploadOpen(true)} type="button">{tr('componentRepo:uploadComponent')}</button> : null}
          </div>
        ) : null}
        {state.totalPages > 1 ? (
          <nav aria-label={tr('componentRepo:componentSearchPagination')} className="component-library-pagination">
            <button disabled={state.status === 'loading' || state.page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))} type="button">
              {tr('componentRepo:previousPage')}
            </button>
            <span>{tr('componentRepo:pageOf', { page: state.page, totalPages: state.totalPages })}</span>
            <button disabled={state.status === 'loading' || state.page >= state.totalPages} onClick={() => setPage((current) => current + 1)} type="button">
              {tr('componentRepo:nextPage')}
            </button>
          </nav>
        ) : null}
          </div>
        </div>
      </section>

      {isUploadOpen ? (
        <ComponentUploadDialog
          onClose={() => setIsUploadOpen(false)}
          onUploadCompleted={(result) => {
            setIsUploadOpen(false);
            navigate(routeFor('componentRepoImportStatus').replace(
              ':importId',
              encodeURIComponent(result.importId),
            ));
          }}
        />
      ) : null}
      {groupEditor && groupTree ? (
        <ComponentGroupDialog
          editor={groupEditor}
          onClose={() => setGroupEditor(null)}
          onSaved={(groupId) => {
            setGroupEditor(null);
            selectGroup(groupId);
          }}
          tree={groupTree}
        />
      ) : null}
      {membershipComponent && groupTree ? (
        <ComponentGroupMembershipDialog
          component={membershipComponent}
          onClose={() => setMembershipComponent(null)}
          onSaved={() => {
            setMembershipComponent(null);
            refreshLibrary();
          }}
          tree={groupTree}
        />
      ) : null}
      {membershipGroup && groupTree ? (
        <GroupComponentMembershipDialog
          group={membershipGroup}
          onClose={() => setMembershipGroup(null)}
          onSaved={() => {
            setMembershipGroup(null);
            refreshLibrary();
          }}
          rootGroup={groupTree.root}
        />
      ) : null}
    </section>
  );
}
