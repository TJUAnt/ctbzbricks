import React from 'react';
import {
  AlertCircle,
  Boxes,
  ChevronDown,
  ChevronRight,
  Folder,
  FolderOpen,
  Layers3,
  LoaderCircle,
  Pencil,
  Plus,
  Search,
  Trash2,
  X,
} from 'lucide-react';
import appConfig from '../app/appConfig';
import { resolvedLocale, useAppTranslation } from '../i18n';
import {
  addComponentToGroup,
  createComponentGroup,
  deleteComponentGroup,
  listComponentGroupComponents,
  listComponentGroupIds,
  listComponentGroupMembershipCandidates,
  moveComponentGroup,
  removeComponentFromGroup,
  updateComponentGroup,
  type ComponentGroupResponse,
  type ComponentGroupTreeResponse,
  type ComponentResponse,
} from './componentRepoApi';

export function ComponentGroupSidebar({
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

export function ComponentGroupDialog({
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

export function ComponentGroupMembershipDialog({
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

export function GroupComponentMembershipDialog({
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
  const [existingMembers, setExistingMembers] = React.useState<ComponentResponse[]>([]);
  const [components, setComponents] = React.useState<ComponentResponse[]>([]);
  const [initialIds, setInitialIds] = React.useState<Set<string>>(new Set());
  const [selectedIds, setSelectedIds] = React.useState<Set<string>>(new Set());
  const [query, setQuery] = React.useState('');
  const [page, setPage] = React.useState(1);
  const [hasMore, setHasMore] = React.useState(false);
  const [membersLoading, setMembersLoading] = React.useState(true);
  const [membersReady, setMembersReady] = React.useState(false);
  const [searchLoading, setSearchLoading] = React.useState(true);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const requestIdRef = React.useRef(0);

  React.useEffect(() => {
    listComponentGroupComponents(group.id)
      .then((groupComponents) => {
        const next = new Set(groupComponents.map((component) => component.id));
        setExistingMembers(groupComponents);
        setInitialIds(next);
        setSelectedIds(next);
        setMembersReady(true);
        setMembersLoading(false);
      })
      .catch((loadError: Error) => {
        setError(loadError.message);
        setMembersLoading(false);
      });
  }, [group.id]);

  React.useEffect(() => {
    const requestId = ++requestIdRef.current;
    setSearchLoading(true);
    setLoadingMore(false);
    const timeoutId = window.setTimeout(() => {
      void listComponentGroupMembershipCandidates({
        rootGroupId: rootGroup.id,
        groupId: group.id,
        query,
        page: 1,
        pageSize: 20,
      }).then((result) => {
        if (requestId !== requestIdRef.current) return;
        setComponents(result.items);
        setPage(1);
        setHasMore(result.hasMore);
        setSearchLoading(false);
      }).catch((loadError: Error) => {
        if (requestId !== requestIdRef.current) return;
        setError(loadError.message);
        setSearchLoading(false);
      });
    }, 300);
    return () => {
      window.clearTimeout(timeoutId);
      requestIdRef.current += 1;
    };
  }, [group.id, query, rootGroup.id]);

  const visibleComponents = React.useMemo(
    () => query.trim() ? components : mergeComponents(existingMembers, components),
    [components, existingMembers, query],
  );

  const loadMore = async () => {
    if (!hasMore || loadingMore || searchLoading) return;
    const requestId = requestIdRef.current;
    const nextPage = page + 1;
    setLoadingMore(true);
    try {
      const result = await listComponentGroupMembershipCandidates({
        rootGroupId: rootGroup.id,
        groupId: group.id,
        query,
        page: nextPage,
        pageSize: 20,
      });
      if (requestId !== requestIdRef.current) return;
      setComponents((current) => mergeComponents(current, result.items));
      setPage(nextPage);
      setHasMore(result.hasMore);
      setLoadingMore(false);
    } catch (loadError) {
      if (requestId !== requestIdRef.current) return;
      setError(loadError instanceof Error ? loadError.message : appConfig.texts.loadFailed);
      setLoadingMore(false);
    }
  };

  const loading = membersLoading || searchLoading;

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
          <GroupMembershipCandidateList
            components={visibleComponents}
            hasMore={hasMore}
            loadMoreLabel={tr(loadingMore ? 'componentRepo:loadingMore' : 'componentRepo:loadMore')}
            loadingMore={loadingMore}
            onLoadMore={() => void loadMore()}
            onToggle={(componentId, selected) => setSelectedIds((current) => {
              const next = new Set(current);
              if (selected) next.add(componentId);
              else next.delete(componentId);
              return next;
            })}
            selectedIds={selectedIds}
          />
          {error ? <div className="component-library-alert"><AlertCircle />{error}</div> : null}
        </div>
        <footer>
          <button disabled={saving} onClick={onClose} type="button">{tr('componentRepo:cancel')}</button>
          <button disabled={saving || loading || !membersReady} onClick={() => void save()} type="button">
            {saving ? <LoaderCircle className="component-library-spin" /> : null}
            {tr(saving ? 'componentRepo:saving' : 'componentRepo:saveComponents')}
          </button>
        </footer>
      </section>
    </div>
  );
}

/** GroupMembershipCandidateList 只负责候选展示和显式续页，便于用 101+ 条数据独立验证 UI 不截断。 */
export function GroupMembershipCandidateList({
  components,
  hasMore,
  loadMoreLabel,
  loadingMore,
  onLoadMore,
  onToggle,
  selectedIds,
}: {
  components: ComponentResponse[];
  hasMore: boolean;
  loadMoreLabel: string;
  loadingMore: boolean;
  onLoadMore: () => void;
  onToggle: (componentId: string, selected: boolean) => void;
  selectedIds: Set<string>;
}) {
  return (
    <>
      <div className="component-membership-options component-group-component-options">
        {components.map((component) => (
          <label key={component.id}>
            <input
              checked={selectedIds.has(component.id)}
              onChange={(event) => onToggle(component.id, event.target.checked)}
              type="checkbox"
            />
            <Boxes aria-hidden="true" />
            <span><strong>{component.name}</strong><small>{shortId(component.id)}</small></span>
          </label>
        ))}
      </div>
      {hasMore ? (
        <button disabled={loadingMore} onClick={onLoadMore} type="button">{loadMoreLabel}</button>
      ) : null}
    </>
  );
}

function mergeComponents(...collections: ComponentResponse[][]): ComponentResponse[] {
  const byID = new Map<string, ComponentResponse>();
  collections.flat().forEach((component) => byID.set(component.id, component));
  return [...byID.values()];
}

function shortId(id: string): string {
  return id.length > 16 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id;
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
