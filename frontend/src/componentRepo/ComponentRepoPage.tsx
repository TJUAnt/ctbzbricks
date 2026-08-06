import React from 'react';
import {
  AlertCircle,
  Boxes,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  FileArchive,
  FileUp,
  Folder,
  FolderOpen,
  Layers3,
  LoaderCircle,
  PackageCheck,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import appConfig from '../app/appConfig';
import { resolvedLocale, useAppTranslation, useDynamicTranslation, type TranslationKey } from '../i18n';
import { formatDateTime, formatNumber } from '../i18n/formatters';
import {
  addComponentToGroup,
  createComponentGroup,
  createComponentImportWithProgress,
  type ComponentCandidateResponse,
  deleteComponentGroup,
  listComponentGroupComponents,
  listComponentGroupIds,
  listComponentGroups,
  listComponentVersions,
  moveComponentGroup,
  removeComponentFromGroup,
  searchComponentGroupComponents,
  updateComponentGroup,
  type ComponentGroupResponse,
  type ComponentGroupTreeResponse,
  type ComponentResponse,
  type ComponentVersionResponse,
  type ComponentVersionDeleteResponse,
} from './componentRepoApi';
import { ComponentVersionActions } from './ComponentVersionActions';

type ComponentRepoListState = {
  status: 'loading' | 'ready' | 'error';
  components: ComponentResponse[];
  error: string | null;
  total: number;
  page: number;
  totalPages: number;
  statusCounts: Record<string, number>;
};

type UploadState = 'idle' | 'uploading' | 'error';
type LibraryFilter = 'all' | 'processing' | 'review' | 'published' | 'failed';

const componentSearchPageSize = 20;
const componentSearchDebounceMs = 300;

type LibraryItem = {
  id: string;
  name: string;
  status: string;
  createdAt: string;
  data: ComponentResponse;
};

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
  const [query, setQuery] = React.useState('');
  const [filter, setFilter] = React.useState<LibraryFilter>('all');
  const [page, setPage] = React.useState(1);
  const [refreshRevision, setRefreshRevision] = React.useState(0);
  const [isUploadOpen, setIsUploadOpen] = React.useState(false);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [actionNotice, setActionNotice] = React.useState<string | null>(null);
  const [selectedComponent, setSelectedComponent] = React.useState<ComponentResponse | null>(null);
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
    void loadLibrary();
    return () => {
      groupRequestIdRef.current += 1;
      searchRequestIdRef.current += 1;
    };
  }, [loadLibrary]);

  React.useEffect(() => {
    if (!selectedGroupId) return undefined;
    const requestId = ++searchRequestIdRef.current;
    const timeoutId = window.setTimeout(() => {
      setState((current) => ({ ...current, status: 'loading', error: null }));
      void searchComponentGroupComponents(selectedGroupId, {
        query,
        statuses: statusesForFilter(filter),
        page,
        pageSize: componentSearchPageSize,
      })
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
  }, [contentLocale, filter, page, query, refreshRevision, selectedGroupId]);

  const items = React.useMemo(
    () => buildLibraryItems(state.components),
    [state.components],
  );
  const stats = React.useMemo(() => ({
    total: sumStatusCounts(state.statusCounts),
    processing: sumStatuses(state.statusCounts, ['uploaded', 'parsing']),
    review: sumStatuses(state.statusCounts, ['parsed', 'pending_review', 'draft']),
    published: sumStatuses(state.statusCounts, ['active', 'published']),
  }), [state.statusCounts]);
  const selectedGroup = groupTree
    ? [groupTree.root, ...groupTree.groups].find((group) => group.id === selectedGroupId)
      ?? groupTree.root
    : null;
  const selectedGroupName = selectedGroup?.groupType === 'root'
    ? tr('componentRepo:groupRootName')
    : selectedGroup?.name ?? tr('componentRepo:groupRootName');

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

  const toggleVersions = async (component: ComponentResponse) => {
    if (selectedComponent?.id === component.id) {
      setSelectedComponent(null);
      return;
    }
    setSelectedComponent(component);
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
            <h1>{tr('componentRepo:componentLibrary')}</h1>
            <p>{tr('componentRepo:manageReviewAndPublishReusableLegoComponents')}</p>
          </div>
        </div>
        <nav aria-label={tr('componentRepo:componentLibrarySections')} className="component-library-tabs">
          <button className="component-library-tab component-library-tab-active" type="button">
            <FolderOpen aria-hidden="true" />
            {tr('componentRepo:myComponentLibrary')}
          </button>
          <button aria-disabled="true" className="component-library-tab component-library-tab-disabled" type="button">
            <Sparkles aria-hidden="true" />
            {tr('componentRepo:communityLibrary')}
            <span>{tr('componentRepo:comingSoon')}</span>
          </button>
        </nav>
      </header>

      <section className="component-library-summary" aria-label={tr('componentRepo:componentStatusOverview')}>
        <SummaryCard icon={<Boxes />} label={tr('componentRepo:allComponents')} tone="blue" value={stats.total} />
        <SummaryCard icon={<Clock3 />} label={tr('componentRepo:processing')} tone="amber" value={stats.processing} />
        <SummaryCard icon={<FileArchive />} label={tr('componentRepo:pendingReview')} tone="purple" value={stats.review} />
        <SummaryCard icon={<PackageCheck />} label={tr('componentRepo:published')} tone="green" value={stats.published} />
      </section>

      <section className="component-library-panel">
        <header className="component-library-panel-header">
          <div>
            <div className="component-library-title-row">
              <h2>{selectedGroupName}</h2>
              <span>{stats.total}</span>
            </div>
            <p>{tr(selectedGroup?.groupType === 'custom' ? 'componentRepo:customGroupDescription' : 'componentRepo:rootGroupDescription')}</p>
          </div>
          <button className="component-library-upload-button" onClick={() => setIsUploadOpen(true)} type="button">
            <Upload aria-hidden="true" />
            {tr('componentRepo:uploadComponent')}
          </button>
        </header>

        <div className="component-library-workspace">
          <ComponentGroupSidebar
            onCreate={(parentGroupId) => setGroupEditor({ mode: 'create', parentGroupId })}
            onDelete={(group) => void removeGroup(group)}
            onEdit={(group) => setGroupEditor({ mode: 'edit', group, parentGroupId: group.parentGroupId ?? groupTree?.root.id ?? '' })}
            onAddComponents={setMembershipGroup}
            onMove={(groupId, parentGroupId, position) => void moveGroup(groupId, parentGroupId, position)}
            onSelect={selectGroup}
            selectedGroupId={selectedGroupId}
            tree={groupTree}
          />
          <div className="component-library-main">
        <div className="component-library-toolbar">
          <label className="component-library-search">
            <Search aria-hidden="true" />
            <input
              aria-label={tr('componentRepo:searchComponents')}
              onChange={(event) => {
                setQuery(event.target.value);
                setPage(1);
              }}
              placeholder={tr('componentRepo:searchComponentNameOrId')}
              value={query}
            />
          </label>
          <div className="component-library-filters" role="group" aria-label={tr('componentRepo:filterByStatus')}>
            {([
              ['all', 'componentRepo:all'],
              ['processing', 'componentRepo:processing'],
              ['review', 'componentRepo:pendingReview'],
              ['published', 'componentRepo:published'],
              ['failed', 'componentRepo:failed'],
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
          </div>
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
            <span role="columnheader">{tr('componentRepo:uploadedAt')}</span>
            <span role="columnheader">{tr('componentRepo:actions')}</span>
          </div>
          {items.map((item) => (
            <article className="component-library-row" key={item.id} role="row">
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
              <span className="component-library-date" role="cell">{formatDate(item.createdAt)}</span>
              <div className="component-library-row-action" role="cell">
                <div className="component-library-component-actions">
                  <Link to={routeFor('componentRepoDetail').replace(':componentId', encodeURIComponent(item.id))}>
                    {tr('componentRepo:details')}<ChevronRight aria-hidden="true" />
                  </Link>
                  <button onClick={() => setMembershipComponent(item.data)} type="button">
                    <Layers3 aria-hidden="true" />{tr('componentRepo:manageGroups')}
                  </button>
                  <button aria-expanded={selectedComponent?.id === item.id} onClick={() => void toggleVersions(item.data)} type="button">
                    {tr('componentRepo:viewVersions')}<ChevronDown aria-hidden="true" />
                  </button>
                  {selectedComponent?.id === item.id ? (
                    <VersionDropdown
                      component={item.data}
                      onDeleted={(result, deletedVersion) => {
                        setVersions((current) => current.filter(
                          (version) => version.id !== deletedVersion.id,
                        ));
                        setActionNotice(tr('componentRepo:versionDeleted', {
                          version: deletedVersion.version,
                        }));
                        if (result.componentDeleted) {
                          setSelectedComponent(null);
                          refreshLibrary();
                        }
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
            <strong>{tr(stats.total === 0 ? 'componentRepo:noComponentsUploaded' : 'componentRepo:noMatchingComponents')}</strong>
            <p>{tr(stats.total === 0 ? 'componentRepo:uploadYourFirstComponentToStartBuildingYourLibrary' : 'componentRepo:tryChangingTheSearchTermOrStatusFilter')}</p>
            {stats.total === 0 ? <button onClick={() => setIsUploadOpen(true)} type="button">{tr('componentRepo:uploadComponent')}</button> : null}
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
          onUploaded={(result) => {
            setIsUploadOpen(false);
            navigate(routeFor('componentRepoCandidate').replace(
              ':candidateId',
              encodeURIComponent(result.id),
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

function ComponentGroupSidebar({
  onAddComponents,
  onCreate,
  onDelete,
  onEdit,
  onMove,
  onSelect,
  selectedGroupId,
  tree,
}: {
  onAddComponents: (group: ComponentGroupResponse) => void;
  onCreate: (parentGroupId: string) => void;
  onDelete: (group: ComponentGroupResponse) => void;
  onEdit: (group: ComponentGroupResponse) => void;
  onMove: (groupId: string, parentGroupId: string, position: number) => void;
  onSelect: (groupId: string) => void;
  selectedGroupId: string | null;
  tree: ComponentGroupTreeResponse | null;
}) {
  const tr = useAppTranslation();
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());
  const [openMenuId, setOpenMenuId] = React.useState<string | null>(null);
  const [draggingId, setDraggingId] = React.useState<string | null>(null);
  const [dropTarget, setDropTarget] = React.useState<{
    groupId: string;
    position: 'before' | 'inside' | 'after';
  } | null>(null);

  React.useEffect(() => {
    if (tree) {
      setExpanded((current) => new Set([...current, tree.root.id]));
    }
  }, [tree]);

  React.useEffect(() => {
    if (!openMenuId) return undefined;
    const closeMenu = () => setOpenMenuId(null);
    document.addEventListener('click', closeMenu);
    return () => document.removeEventListener('click', closeMenu);
  }, [openMenuId]);

  if (!tree) {
    return (
      <aside className="component-group-sidebar">
        <div className="component-group-loading"><LoaderCircle className="component-library-spin" />{tr('componentRepo:loadingGroups')}</div>
      </aside>
    );
  }

  const childrenByParent = new Map<string, ComponentGroupResponse[]>();
  for (const group of tree.groups) {
    if (group.parentGroupId) {
      const siblings = childrenByParent.get(group.parentGroupId) ?? [];
      siblings.push(group);
      childrenByParent.set(group.parentGroupId, siblings);
    }
  }
  for (const siblings of childrenByParent.values()) {
    siblings.sort((left, right) => left.sortOrder - right.sortOrder || left.createdAt.localeCompare(right.createdAt));
  }
  const invalidDropIds = draggingId
    ? new Set([draggingId, ...groupDescendantIds(tree.groups, draggingId)])
    : new Set<string>();

  const renderNode = (group: ComponentGroupResponse, depth: number): React.ReactNode => {
    const children = childrenByParent.get(group.id) ?? [];
    const isRoot = group.groupType === 'root';
    const isExpanded = expanded.has(group.id);
    const dropPosition = dropTarget?.groupId === group.id ? dropTarget.position : null;
    const handleDragOver = (event: React.DragEvent<HTMLDivElement>) => {
      if (!draggingId || invalidDropIds.has(group.id)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = 'move';
      if (isRoot) {
        setDropTarget({ groupId: group.id, position: 'inside' });
        return;
      }
      const bounds = event.currentTarget.getBoundingClientRect();
      const relativeY = (event.clientY - bounds.top) / bounds.height;
      const position = relativeY < 0.25
        ? 'before'
        : relativeY > 0.75
          ? 'after'
          : 'inside';
      setDropTarget({ groupId: group.id, position });
    };
    const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      event.stopPropagation();
      if (!draggingId || !dropPosition || invalidDropIds.has(group.id)) return;
      let parentGroupId = group.id;
      let position = (childrenByParent.get(group.id) ?? [])
        .filter((item) => item.id !== draggingId).length;
      if (dropPosition !== 'inside' && group.parentGroupId) {
        parentGroupId = group.parentGroupId;
        const siblings = (childrenByParent.get(parentGroupId) ?? [])
          .filter((item) => item.id !== draggingId);
        const targetIndex = siblings.findIndex((item) => item.id === group.id);
        position = targetIndex + (dropPosition === 'after' ? 1 : 0);
      }
      setExpanded((current) => new Set([...current, parentGroupId]));
      setDraggingId(null);
      setDropTarget(null);
      onMove(draggingId, parentGroupId, position);
    };
    return (
      <React.Fragment key={group.id}>
        <div
          aria-grabbed={!isRoot ? draggingId === group.id : undefined}
          className={[
            'component-group-node',
            selectedGroupId === group.id ? 'component-group-node-selected' : '',
            draggingId === group.id ? 'component-group-node-dragging' : '',
            dropPosition ? `component-group-node-drop-${dropPosition}` : '',
          ].filter(Boolean).join(' ')}
          draggable={!isRoot}
          onDragEnd={() => {
            setDraggingId(null);
            setDropTarget(null);
          }}
          onDragOver={handleDragOver}
          onDragStart={(event) => {
            if (isRoot) return;
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', group.id);
            setDraggingId(group.id);
            setOpenMenuId(null);
          }}
          onDrop={handleDrop}
          style={{ paddingInlineStart: `${10 + depth * 16}px` }}
          title={!isRoot ? tr('componentRepo:dragGroupHint') : undefined}
        >
          <button
            aria-label={tr(isExpanded ? 'componentRepo:collapseGroup' : 'componentRepo:expandGroup')}
            className="component-group-expander"
            disabled={children.length === 0}
            onClick={() => setExpanded((current) => {
              const next = new Set(current);
              if (next.has(group.id)) next.delete(group.id);
              else next.add(group.id);
              return next;
            })}
            type="button"
          >
            {children.length > 0 ? (isExpanded ? <ChevronDown /> : <ChevronRight />) : <span />}
          </button>
          <button className="component-group-select" onClick={() => onSelect(group.id)} type="button">
            {isRoot ? <FolderOpen /> : <Folder />}
            <span>{isRoot ? tr('componentRepo:groupRootName') : group.name}</span>
            <em>{group.directComponentCount}</em>
          </button>
          <div className="component-group-actions">
            <div className="component-group-add-menu">
              <button
                aria-expanded={openMenuId === group.id}
                aria-haspopup="menu"
                aria-label={tr('componentRepo:addToGroup')}
                className="component-group-add-button"
                onClick={(event) => {
                  event.stopPropagation();
                  setOpenMenuId((current) => current === group.id ? null : group.id);
                }}
                title={tr('componentRepo:addToGroup')}
                type="button"
              >
                <Plus />
              </button>
              {openMenuId === group.id ? (
                <div className="component-group-action-menu" onClick={(event) => event.stopPropagation()} role="menu">
                  <button onClick={() => {
                    setOpenMenuId(null);
                    onCreate(group.id);
                  }} role="menuitem" type="button">
                    <Folder aria-hidden="true" />
                    {tr('componentRepo:createChildGroup')}
                  </button>
                  <button
                    disabled={isRoot}
                    onClick={() => {
                      setOpenMenuId(null);
                      onAddComponents(group);
                    }}
                    role="menuitem"
                    title={isRoot ? tr('componentRepo:rootGroupIncludesAllComponents') : undefined}
                    type="button"
                  >
                    <Layers3 aria-hidden="true" />
                    {tr('componentRepo:addComponentsToGroup')}
                  </button>
                </div>
              ) : null}
            </div>
            {!isRoot ? (
              <>
                <button aria-label={tr('componentRepo:editGroup')} onClick={() => onEdit(group)} title={tr('componentRepo:editGroup')} type="button"><Pencil /></button>
                <button aria-label={tr('componentRepo:deleteGroup')} onClick={() => onDelete(group)} title={tr('componentRepo:deleteGroup')} type="button"><Trash2 /></button>
              </>
            ) : null}
          </div>
        </div>
        {isExpanded ? children.map((child) => renderNode(child, depth + 1)) : null}
      </React.Fragment>
    );
  };

  return (
    <aside className="component-group-sidebar">
      <header><h3>{tr('componentRepo:componentGroups')}</h3></header>
      <nav aria-label={tr('componentRepo:componentGroups')}>{renderNode(tree.root, 0)}</nav>
      {tree.groups.length === 0 ? <p className="component-group-empty">{tr('componentRepo:noCustomGroups')}</p> : null}
    </aside>
  );
}

function ComponentGroupDialog({
  editor,
  onClose,
  onSaved,
  tree,
}: {
  editor: { mode: 'create' | 'edit'; group?: ComponentGroupResponse; parentGroupId: string };
  onClose: () => void;
  onSaved: (groupId: string) => void;
  tree: ComponentGroupTreeResponse;
}) {
  const tr = useAppTranslation();
  const [name, setName] = React.useState(editor.group?.name ?? '');
  const [parentGroupId, setParentGroupId] = React.useState(editor.parentGroupId);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const excludedIds = editor.group
    ? new Set([editor.group.id, ...groupDescendantIds(tree.groups, editor.group.id)])
    : new Set<string>();
  const parentOptions = [tree.root, ...tree.groups].filter((group) => !excludedIds.has(group.id));

  const save = async () => {
    if (!name.trim()) {
      setError(tr('componentRepo:groupNameRequired'));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const group = editor.mode === 'create'
        ? await createComponentGroup({
          parentGroupId,
          name: name.trim(),
          contentLocale: resolvedLocale(),
        })
        : await updateComponentGroup(editor.group!.id, {
          name: name.trim(),
          contentLocale: resolvedLocale(),
        });
      onSaved(group.id);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : appConfig.texts.loadFailed);
      setSaving(false);
    }
  };

  return (
    <div className="component-upload-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !saving) onClose();
    }}>
      <section aria-labelledby="component-group-dialog-title" aria-modal="true" className="component-group-dialog" role="dialog">
        <header>
          <div>
            <Folder aria-hidden="true" />
            <h2 id="component-group-dialog-title">{tr(editor.mode === 'create' ? 'componentRepo:createGroupTitle' : 'componentRepo:editGroupTitle')}</h2>
          </div>
          <button aria-label={tr('componentRepo:closeGroupDialog')} disabled={saving} onClick={onClose} type="button"><X /></button>
        </header>
        <div className="component-group-dialog-body">
          <label>
            <span>{tr('componentRepo:groupName')}</span>
            <input autoFocus maxLength={100} onChange={(event) => setName(event.target.value)} placeholder={tr('componentRepo:groupNamePlaceholder')} value={name} />
          </label>
          {editor.mode === 'create' ? (
            <label>
              <span>{tr('componentRepo:parentGroup')}</span>
              <select onChange={(event) => setParentGroupId(event.target.value)} value={parentGroupId}>
                {parentOptions.map((group) => (
                  <option key={group.id} value={group.id}>
                    {group.groupType === 'root' ? tr('componentRepo:groupRootName') : group.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {error ? <div className="component-library-alert"><AlertCircle />{error}</div> : null}
        </div>
        <footer>
          <button disabled={saving} onClick={onClose} type="button">{tr('componentRepo:cancel')}</button>
          <button disabled={saving} onClick={() => void save()} type="button">{saving ? <LoaderCircle className="component-library-spin" /> : null}{tr(saving ? 'componentRepo:saving' : 'componentRepo:saveGroup')}</button>
        </footer>
      </section>
    </div>
  );
}

function ComponentGroupMembershipDialog({
  component,
  onClose,
  onSaved,
  tree,
}: {
  component: ComponentResponse;
  onClose: () => void;
  onSaved: () => void;
  tree: ComponentGroupTreeResponse;
}) {
  const tr = useAppTranslation();
  const [initialIds, setInitialIds] = React.useState<Set<string>>(new Set());
  const [selectedIds, setSelectedIds] = React.useState<Set<string>>(new Set());
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    listComponentGroupIds(component.id)
      .then((ids) => {
        const next = new Set(ids);
        setInitialIds(next);
        setSelectedIds(next);
        setLoading(false);
      })
      .catch((loadError: Error) => {
        setError(loadError.message);
        setLoading(false);
      });
  }, [component.id]);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await Promise.all([
        ...[...selectedIds].filter((id) => !initialIds.has(id)).map((id) => addComponentToGroup(id, component.id)),
        ...[...initialIds].filter((id) => !selectedIds.has(id)).map((id) => removeComponentFromGroup(id, component.id)),
      ]);
      onSaved();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : appConfig.texts.loadFailed);
      setSaving(false);
    }
  };

  return (
    <div className="component-upload-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !saving) onClose();
    }}>
      <section aria-labelledby="component-membership-dialog-title" aria-modal="true" className="component-group-dialog" role="dialog">
        <header>
          <div><Layers3 aria-hidden="true" /><div><h2 id="component-membership-dialog-title">{tr('componentRepo:manageComponentGroups')}</h2><p>{component.name}</p></div></div>
          <button aria-label={tr('componentRepo:closeGroupDialog')} disabled={saving} onClick={onClose} type="button"><X /></button>
        </header>
        <div className="component-group-dialog-body">
          <p>{tr('componentRepo:manageComponentGroupsDescription')}</p>
          {loading ? <div className="component-group-loading"><LoaderCircle className="component-library-spin" />{tr('componentRepo:loadingGroups')}</div> : null}
          {!loading && tree.groups.length === 0 ? <div className="component-group-empty">{tr('componentRepo:noCustomGroups')}</div> : null}
          <div className="component-membership-options">
            {tree.groups.map((group) => (
              <label key={group.id}>
                <input
                  checked={selectedIds.has(group.id)}
                  onChange={(event) => setSelectedIds((current) => {
                    const next = new Set(current);
                    if (event.target.checked) next.add(group.id);
                    else next.delete(group.id);
                    return next;
                  })}
                  type="checkbox"
                />
                <Folder aria-hidden="true" />
                <span>{group.name}</span>
              </label>
            ))}
          </div>
          {error ? <div className="component-library-alert"><AlertCircle />{error}</div> : null}
        </div>
        <footer>
          <button disabled={saving} onClick={onClose} type="button">{tr('componentRepo:cancel')}</button>
          <button disabled={saving || loading} onClick={() => void save()} type="button">{saving ? <LoaderCircle className="component-library-spin" /> : null}{tr(saving ? 'componentRepo:saving' : 'componentRepo:saveGroup')}</button>
        </footer>
      </section>
    </div>
  );
}

function GroupComponentMembershipDialog({
  group,
  onClose,
  onSaved,
  rootGroup,
}: {
  group: ComponentGroupResponse;
  onClose: () => void;
  onSaved: () => void;
  rootGroup: ComponentGroupResponse;
}) {
  const tr = useAppTranslation();
  const [components, setComponents] = React.useState<ComponentResponse[]>([]);
  const [initialIds, setInitialIds] = React.useState<Set<string>>(new Set());
  const [selectedIds, setSelectedIds] = React.useState<Set<string>>(new Set());
  const [query, setQuery] = React.useState('');
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    Promise.all([
      listComponentGroupComponents(rootGroup.id),
      listComponentGroupComponents(group.id),
    ])
      .then(([managedComponents, groupComponents]) => {
        const next = new Set(groupComponents.map((component) => component.id));
        setComponents(managedComponents);
        setInitialIds(next);
        setSelectedIds(next);
        setLoading(false);
      })
      .catch((loadError: Error) => {
        setError(loadError.message);
        setLoading(false);
      });
  }, [group.id, rootGroup.id]);

  const visibleComponents = React.useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    if (!normalizedQuery) return components;
    return components.filter((component) =>
      `${component.name} ${component.id}`.toLocaleLowerCase().includes(normalizedQuery));
  }, [components, query]);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await Promise.all([
        ...[...selectedIds]
          .filter((id) => !initialIds.has(id))
          .map((id) => addComponentToGroup(group.id, id)),
        ...[...initialIds]
          .filter((id) => !selectedIds.has(id))
          .map((id) => removeComponentFromGroup(group.id, id)),
      ]);
      onSaved();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : appConfig.texts.loadFailed);
      setSaving(false);
    }
  };

  return (
    <div className="component-upload-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !saving) onClose();
    }}>
      <section aria-labelledby="group-components-dialog-title" aria-modal="true" className="component-group-dialog component-group-components-dialog" role="dialog">
        <header>
          <div>
            <Layers3 aria-hidden="true" />
            <div>
              <h2 id="group-components-dialog-title">{tr('componentRepo:addComponentsToGroupTitle')}</h2>
              <p>{group.name}</p>
            </div>
          </div>
          <button aria-label={tr('componentRepo:closeGroupDialog')} disabled={saving} onClick={onClose} type="button"><X /></button>
        </header>
        <div className="component-group-dialog-body">
          <p>{tr('componentRepo:chooseComponentsForGroup')}</p>
          <label className="component-group-component-search">
            <Search aria-hidden="true" />
            <input
              aria-label={tr('componentRepo:searchManagedComponents')}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={tr('componentRepo:searchComponentNameOrId')}
              value={query}
            />
          </label>
          {loading ? <div className="component-group-loading"><LoaderCircle className="component-library-spin" />{tr('componentRepo:loadingComponents')}</div> : null}
          {!loading && components.length === 0 ? <div className="component-group-empty">{tr('componentRepo:noManagedComponents')}</div> : null}
          <div className="component-membership-options component-group-component-options">
            {visibleComponents.map((component) => (
              <label key={component.id}>
                <input
                  checked={selectedIds.has(component.id)}
                  onChange={(event) => setSelectedIds((current) => {
                    const next = new Set(current);
                    if (event.target.checked) next.add(component.id);
                    else next.delete(component.id);
                    return next;
                  })}
                  type="checkbox"
                />
                <Boxes aria-hidden="true" />
                <span><strong>{component.name}</strong><small>{shortId(component.id)}</small></span>
              </label>
            ))}
          </div>
          {error ? <div className="component-library-alert"><AlertCircle />{error}</div> : null}
        </div>
        <footer>
          <button disabled={saving} onClick={onClose} type="button">{tr('componentRepo:cancel')}</button>
          <button disabled={saving || loading} onClick={() => void save()} type="button">
            {saving ? <LoaderCircle className="component-library-spin" /> : null}
            {tr(saving ? 'componentRepo:saving' : 'componentRepo:saveComponents')}
          </button>
        </footer>
      </section>
    </div>
  );
}

function groupDescendantIds(groups: ComponentGroupResponse[], groupId: string): string[] {
  const result: string[] = [];
  const pending = [groupId];
  while (pending.length > 0) {
    const parentId = pending.pop()!;
    for (const group of groups) {
      if (group.parentGroupId === parentId) {
        result.push(group.id);
        pending.push(group.id);
      }
    }
  }
  return result;
}

export function ComponentUploadDialog({
  baseVersionId,
  onClose,
  onUploaded,
  targetComponentId,
}: {
  baseVersionId?: string | null;
  onClose: () => void;
  onUploaded: (result: ComponentCandidateResponse) => void;
  targetComponentId?: string | null;
}) {
  const tr = useAppTranslation();
  const [sourceFile, setSourceFile] = React.useState<File | null>(null);
  const [exchangeFile, setExchangeFile] = React.useState<File | null>(null);
  const [state, setState] = React.useState<UploadState>('idle');
  const [progress, setProgress] = React.useState(0);
  const [progressMessage, setProgressMessage] = React.useState(tr('componentRepo:readyToUpload'));
  const [error, setError] = React.useState<string | null>(null);
  const sourceInputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && state !== 'uploading') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose, state]);

  const submit = async () => {
    if (!sourceFile) return;
    setState('uploading');
    setProgress(0);
    setError(null);
    try {
      const uploaded = await createComponentImportWithProgress(
        sourceFile,
        exchangeFile,
        ({ percent, message }) => {
          setProgress(percent);
          setProgressMessage(message);
        },
        { targetComponentId, baseVersionId },
      );
      onUploaded(uploaded);
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : tr('componentRepo:componentUploadFailed'));
      setState('error');
    }
  };

  const reset = () => {
    setState('idle');
    setProgress(0);
    setProgressMessage(tr('componentRepo:readyToUpload'));
    setError(null);
  };

  return (
    <div className="component-upload-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget && state !== 'uploading') onClose();
    }}>
      <section aria-labelledby="component-upload-title" aria-modal="true" className="component-upload-dialog" role="dialog">
        <header className="component-upload-header">
          <div>
            <span><Upload aria-hidden="true" /></span>
            <div><h2 id="component-upload-title">{tr('componentRepo:uploadComponent')}</h2><p>{tr('componentRepo:uploadAStudioOrLDrawFileToYourComponentLibrary')}</p></div>
          </div>
          <button aria-label={tr('componentRepo:closeUploadDialog')} disabled={state === 'uploading'} onClick={onClose} type="button"><X /></button>
        </header>

        <div className="component-upload-body">
          {state === 'idle' ? (
            <>
              <input
                accept=".io,.ldr,.mpd"
                className="component-upload-hidden-input"
                onChange={(event) => setSourceFile(event.target.files?.item(0) ?? null)}
                ref={sourceInputRef}
                type="file"
              />
              <button
                className={sourceFile ? 'component-upload-dropzone component-upload-dropzone-selected' : 'component-upload-dropzone'}
                onClick={() => sourceInputRef.current?.click()}
                onDragOver={(event) => event.preventDefault()}
                onDrop={(event) => {
                  event.preventDefault();
                  const file = event.dataTransfer.files.item(0);
                  if (file && isComponentFile(file.name)) setSourceFile(file);
                }}
                type="button"
              >
                {sourceFile ? <CheckCircle2 aria-hidden="true" /> : <FileUp aria-hidden="true" />}
                <strong>{sourceFile ? sourceFile.name : tr('componentRepo:dropAComponentFileHereOrClickToSelect')}</strong>
                <span>{sourceFile ? formatFileSize(sourceFile.size) : tr('componentRepo:supportsIoLdrAndMpdFilesUpTo100Mb')}</span>
              </button>
              <label className="component-upload-secondary-file">
                <span><strong>{tr('componentRepo:exchangeFile')}</strong><em>{tr('componentRepo:optionalOnlyNeededForIoSourceFiles')}</em></span>
                <span className="component-upload-secondary-picker">{exchangeFile ? exchangeFile.name : tr('componentRepo:selectLdrMpd')}</span>
                <input accept=".ldr,.mpd" onChange={(event) => setExchangeFile(event.target.files?.item(0) ?? null)} type="file" />
              </label>
              <div className="component-upload-tip"><CheckCircle2 /><span><strong>{tr('componentRepo:whatHappensAfterUpload')}</strong>{tr('componentRepo:theFileWillBeStoredSecurelyAndEnterTheParsingAndReviewWorkflow')}</span></div>
            </>
          ) : null}

          {state === 'uploading' ? (
            <div className="component-upload-progress-state">
              <span className="component-upload-progress-icon"><Upload /></span>
              <h3>{tr('componentRepo:uploadingComponent')}</h3>
              <p>{sourceFile?.name}</p>
              <div className="component-upload-progress-meta"><span>{progressMessage}</span><strong>{progress}%</strong></div>
              <div aria-label={tr('componentRepo:uploadProgressValue', { percent: progress })} aria-valuemax={100} aria-valuemin={0} aria-valuenow={progress} className="component-upload-progress" role="progressbar">
                <span style={{ width: `${progress}%` }} />
              </div>
              <small>{tr('componentRepo:keepThisPageOpenUntilTheUploadIsComplete')}</small>
            </div>
          ) : null}

          {state === 'error' ? (
            <div className="component-upload-result component-upload-result-error">
              <span><AlertCircle /></span>
              <h3>{tr('componentRepo:uploadNotCompleted')}</h3>
              <p>{error}</p>
              <div><strong>{sourceFile?.name}</strong><span>{tr('componentRepo:checkTheNetworkOrFileAndTryAgain')}</span></div>
            </div>
          ) : null}
        </div>

        <footer className="component-upload-footer">
          {state === 'idle' ? <><button onClick={onClose} type="button">{tr('componentRepo:cancel')}</button><button disabled={!sourceFile} onClick={() => void submit()} type="button"><Upload />{tr('componentRepo:startUpload')}</button></> : null}
          {state === 'uploading' ? <span>{tr('componentRepo:processingPleaseWait')}</span> : null}
          {state === 'error' ? <><button onClick={onClose} type="button">{tr('componentRepo:close')}</button><button onClick={reset} type="button"><RefreshCw />{tr('componentRepo:retryUpload')}</button></> : null}
        </footer>
      </section>
    </div>
  );
}

function VersionDropdown({ component, onDeleted, state, versions }: {
  component: ComponentResponse;
  onDeleted: (
    result: ComponentVersionDeleteResponse,
    version: ComponentVersionResponse,
  ) => void;
  state: 'idle' | 'loading' | 'error';
  versions: ComponentVersionResponse[];
}) {
  const tr = useAppTranslation();
  return (
    <section className="component-version-dropdown" role="menu">
        <div className="component-version-list">
          {state === 'loading' ? <div className="component-library-empty"><LoaderCircle className="component-library-spin" /><strong>{tr('componentRepo:loadingVersions')}</strong></div> : null}
          {state === 'error' ? <div className="component-library-alert"><AlertCircle />{tr('componentRepo:failedToLoadVersions')}</div> : null}
          {state === 'idle' && versions.length === 0 ? <div className="component-library-empty"><strong>{tr('componentRepo:noComponentVersions')}</strong></div> : null}
          {versions.map((version) => (
            <article key={version.id}>
              <div><strong>v{version.version}</strong><span>{tr('componentRepo:revision')} {version.revision}</span></div>
              <StatusPill status={version.id === component.currentVersionId ? 'published' : 'draft'} />
              <ComponentVersionActions
                componentName={component.name}
                isOnlyVersion={versions.length === 1}
                onDeleted={onDeleted}
                version={version}
              />
            </article>
          ))}
        </div>
    </section>
  );
}

function SummaryCard({ icon, label, tone, value }: { icon: React.ReactNode; label: string; tone: string; value: number }) {
  return <article className={`component-library-summary-card component-library-summary-card-${tone}`}><span>{icon}</span><div><strong>{value}</strong><p>{label}</p></div></article>;
}

function ComponentLogicalSize({ size }: { size: ComponentResponse['logicalSize'] }) {
  const tr = useAppTranslation();
  if (!size) {
    return <span aria-label={tr('componentRepo:sizeUnavailable')} className="component-library-size-unavailable" role="cell">—</span>;
  }
  const width = formatDimension(size.widthStud);
  const depth = formatDimension(size.depthStud);
  const height = formatDimension(size.heightPlate);
  return (
    <div
      aria-label={tr('componentRepo:sizeAccessibleLabel', { width, depth, height })}
      className="component-library-size"
      role="cell"
    >
      <strong aria-hidden="true">{width} × {depth} × {height}</strong>
      <small aria-hidden="true">{tr('componentRepo:sizeUnits')}</small>
    </div>
  );
}

function buildLibraryItems(components: ComponentResponse[]): LibraryItem[] {
  return components.map((item) => ({
    id: item.id,
    name: item.name,
    status: item.status,
    createdAt: item.createdAt,
    data: item,
  }));
}

function statusesForFilter(filter: LibraryFilter): string[] | null {
  if (filter === 'all') return null;
  if (filter === 'processing') return ['uploaded', 'parsing'];
  if (filter === 'review') return ['parsed', 'pending_review', 'draft'];
  if (filter === 'published') return ['active', 'published'];
  return ['failed', 'blocked', 'rejected'];
}

function sumStatuses(counts: Record<string, number>, statuses: string[]): number {
  return statuses.reduce((total, status) => total + (counts[status] ?? 0), 0);
}

function sumStatusCounts(counts: Record<string, number>): number {
  return Object.values(counts).reduce((total, count) => total + count, 0);
}

function isComponentFile(name: string): boolean { return /\.(io|ldr|mpd)$/i.test(name); }
function shortId(id: string): string { return id.length > 16 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id; }
function formatFileSize(bytes: number): string { return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`; }
function formatDimension(value: number): string { return formatNumber(value, { maximumFractionDigits: 2 }); }
function formatDate(value: string): string { return formatDateTime(value, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }); }

const statusLabels: Partial<Record<string, TranslationKey>> = {
  uploaded: 'componentRepo:uploaded', parsing: 'componentRepo:parsing', parsed: 'componentRepo:pendingReview', pending_review: 'componentRepo:pendingReview', in_review: 'componentRepo:inReview',
  draft: 'componentRepo:draft', active: 'componentRepo:published', published: 'componentRepo:published', failed: 'componentRepo:failed', blocked: 'componentRepo:blocked', rejected: 'componentRepo:rejected', archived: 'componentRepo:archived',
  confirmed: 'componentRepo:confirmed', passed: 'componentRepo:passed', pass: 'componentRepo:passed', pending: 'componentRepo:pending',
};

export function StatusPill({ status }: { status: string }) {
  const trDynamic = useDynamicTranslation();
  const translationKey = statusLabels[status];
  return <span className={`component-repo-status component-repo-status-${status}`}>{translationKey ? trDynamic(translationKey) : status}</span>;
}

export function routeFor(page: keyof typeof appConfig.routePaths): string {
  return appConfig.routePaths[page];
}
