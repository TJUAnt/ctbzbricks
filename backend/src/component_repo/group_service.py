"""Per-user Component library grouping and subscription services."""

from __future__ import annotations

from datetime import datetime, timezone
from difflib import SequenceMatcher
from math import ceil
import re
from uuid import uuid4

from sqlalchemy import Engine, and_, delete, exists, func, or_, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from src.api.errors import DomainError
from src.component_repo.component_service import component_response
from src.i18n.domain_content import normalize_content_locale
from src.model.models import (
    Component,
    ComponentGroup,
    ComponentGroupMembership,
    ComponentSubscription,
)
from src.services.domain_content_service import localized_component_content
from src.services.fitting_candidate_search_fields import normalize_search_text


ROOT_GROUP_TYPE = "root"
CUSTOM_GROUP_TYPE = "custom"
MAX_GROUP_DEPTH = 8
MAX_GROUP_NAME_LENGTH = 100
COMPONENT_SEARCH_MINIMUM_NAME_SCORE = 0.72


def list_group_tree(engine: Engine, user_id: str) -> dict:
    Session = sessionmaker(bind=engine)
    with Session.begin() as session:
        root = get_or_create_root_group(session, user_id)
        groups = session.scalars(
            select(ComponentGroup)
            .where(
                ComponentGroup.owner_id == user_id,
                ComponentGroup.group_type == CUSTOM_GROUP_TYPE,
            )
            .order_by(
                ComponentGroup.parent_group_id,
                ComponentGroup.sort_order,
                ComponentGroup.created_at,
            )
        ).all()
        counts = dict(
            session.execute(
                select(
                    ComponentGroupMembership.group_id,
                    func.count(ComponentGroupMembership.component_id),
                )
                .join(
                    ComponentGroup,
                    ComponentGroup.id == ComponentGroupMembership.group_id,
                )
                .join(
                    Component,
                    Component.id == ComponentGroupMembership.component_id,
                )
                .where(ComponentGroup.owner_id == user_id)
                .where(managed_component_predicate(user_id))
                .group_by(ComponentGroupMembership.group_id)
            ).all()
        )
        return {
            "root": group_response(
                root,
                direct_component_count=managed_component_count(session, user_id),
            ),
            "groups": [
                group_response(group, direct_component_count=int(counts.get(group.id, 0)))
                for group in groups
            ],
        }


def create_group(
    engine: Engine,
    user_id: str,
    parent_group_id: str,
    name: str,
    content_locale: str,
) -> dict:
    normalized_locale = normalize_content_locale(content_locale)
    display_name, normalized_name = validate_group_name(name)
    Session = sessionmaker(bind=engine)
    with Session.begin() as session:
        get_or_create_root_group(session, user_id)
        parent = owned_group(session, user_id, parent_group_id)
        if group_depth(session, parent, user_id) >= MAX_GROUP_DEPTH:
            raise DomainError(
                "component_repo.group_depth_exceeded",
                {"maximumDepth": MAX_GROUP_DEPTH},
                409,
            )
        ensure_unique_sibling_name(
            session,
            user_id,
            parent.id,
            normalized_name,
        )
        now = utcnow()
        sort_order = session.scalar(
            select(func.coalesce(func.max(ComponentGroup.sort_order), -1) + 1).where(
                ComponentGroup.owner_id == user_id,
                ComponentGroup.parent_group_id == parent.id,
            )
        )
        group = ComponentGroup(
            id=str(uuid4()),
            owner_id=user_id,
            parent_group_id=parent.id,
            group_type=CUSTOM_GROUP_TYPE,
            name=display_name,
            normalized_name=normalized_name,
            content_locale=normalized_locale,
            sort_order=int(sort_order or 0),
            created_at=now,
            updated_at=now,
        )
        session.add(group)
        session.flush()
        return group_response(group, direct_component_count=0)


def update_group(
    engine: Engine,
    user_id: str,
    group_id: str,
    *,
    name: str | None = None,
    content_locale: str | None = None,
    parent_group_id: str | None = None,
    sort_order: int | None = None,
) -> dict:
    Session = sessionmaker(bind=engine)
    with Session.begin() as session:
        group = mutable_owned_group(session, user_id, group_id)
        next_parent_id = group.parent_group_id
        if parent_group_id is not None and parent_group_id != group.parent_group_id:
            parent = owned_group(session, user_id, parent_group_id)
            descendants = descendant_ids(session, user_id, group.id)
            if parent.id == group.id or parent.id in descendants:
                raise DomainError("component_repo.group_cycle", http_status=409)
            subtree_height = group_subtree_height(session, user_id, group.id)
            if group_depth(session, parent, user_id) + 1 + subtree_height > MAX_GROUP_DEPTH:
                raise DomainError(
                    "component_repo.group_depth_exceeded",
                    {"maximumDepth": MAX_GROUP_DEPTH},
                    409,
                )
            next_parent_id = parent.id

        next_name = group.name or ""
        next_normalized_name = group.normalized_name or ""
        if name is not None:
            next_name, next_normalized_name = validate_group_name(name)
        ensure_unique_sibling_name(
            session,
            user_id,
            next_parent_id,
            next_normalized_name,
            excluding_group_id=group.id,
        )
        if content_locale is not None:
            group.content_locale = normalize_content_locale(content_locale)
        group.name = next_name
        group.normalized_name = next_normalized_name
        group.parent_group_id = next_parent_id
        if sort_order is not None:
            group.sort_order = max(0, sort_order)
        group.updated_at = utcnow()
        count = session.scalar(
            select(func.count(ComponentGroupMembership.component_id)).where(
                ComponentGroupMembership.group_id == group.id
            )
        )
        session.flush()
        return group_response(group, direct_component_count=int(count or 0))


def move_group(
    engine: Engine,
    user_id: str,
    group_id: str,
    parent_group_id: str,
    position: int,
) -> dict:
    """Atomically move one custom group and normalize affected sibling ordering."""
    Session = sessionmaker(bind=engine)
    with Session.begin() as session:
        group = mutable_owned_group(session, user_id, group_id)
        parent = owned_group(session, user_id, parent_group_id)
        descendants = descendant_ids(session, user_id, group.id)
        if parent.id == group.id or parent.id in descendants:
            raise DomainError("component_repo.group_cycle", http_status=409)
        subtree_height = group_subtree_height(session, user_id, group.id)
        if group_depth(session, parent, user_id) + 1 + subtree_height > MAX_GROUP_DEPTH:
            raise DomainError(
                "component_repo.group_depth_exceeded",
                {"maximumDepth": MAX_GROUP_DEPTH},
                409,
            )
        ensure_unique_sibling_name(
            session,
            user_id,
            parent.id,
            group.normalized_name or "",
            excluding_group_id=group.id,
        )

        old_parent_id = group.parent_group_id
        target_siblings = list(
            session.scalars(
                select(ComponentGroup)
                .where(
                    ComponentGroup.owner_id == user_id,
                    ComponentGroup.parent_group_id == parent.id,
                    ComponentGroup.group_type == CUSTOM_GROUP_TYPE,
                    ComponentGroup.id != group.id,
                )
                .order_by(ComponentGroup.sort_order, ComponentGroup.created_at)
                .with_for_update()
            ).all()
        )
        insertion_position = min(position, len(target_siblings))
        target_siblings.insert(insertion_position, group)
        now = utcnow()
        group.parent_group_id = parent.id
        for index, sibling in enumerate(target_siblings):
            sibling.sort_order = index
            sibling.updated_at = now

        if old_parent_id != parent.id:
            old_siblings = session.scalars(
                select(ComponentGroup)
                .where(
                    ComponentGroup.owner_id == user_id,
                    ComponentGroup.parent_group_id == old_parent_id,
                    ComponentGroup.group_type == CUSTOM_GROUP_TYPE,
                    ComponentGroup.id != group.id,
                )
                .order_by(ComponentGroup.sort_order, ComponentGroup.created_at)
                .with_for_update()
            ).all()
            for index, sibling in enumerate(old_siblings):
                sibling.sort_order = index
                sibling.updated_at = now

        count = session.scalar(
            select(func.count(ComponentGroupMembership.component_id)).where(
                ComponentGroupMembership.group_id == group.id
            )
        )
        session.flush()
        return group_response(group, direct_component_count=int(count or 0))


def delete_group(engine: Engine, user_id: str, group_id: str) -> None:
    Session = sessionmaker(bind=engine)
    with Session.begin() as session:
        group = mutable_owned_group(session, user_id, group_id)
        ids = [group.id, *descendant_ids(session, user_id, group.id)]
        session.execute(
            delete(ComponentGroupMembership).where(
                ComponentGroupMembership.group_id.in_(ids)
            )
        )
        session.execute(delete(ComponentGroup).where(ComponentGroup.id.in_(ids)))


def list_group_components(
    engine: Engine,
    user_id: str,
    group_id: str,
    content_locale: str,
) -> list[dict]:
    normalized_locale = normalize_content_locale(content_locale)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        group = owned_group(session, user_id, group_id)
        if group.group_type == ROOT_GROUP_TYPE:
            rows = managed_component_rows(session, user_id)
        else:
            rows = session.scalars(
                select(Component)
                .join(
                    ComponentGroupMembership,
                    ComponentGroupMembership.component_id == Component.id,
                )
                .where(
                    ComponentGroupMembership.group_id == group.id,
                    managed_component_predicate(user_id),
                )
                .options(selectinload(Component.translations))
                .order_by(Component.created_at.desc(), Component.id)
            ).all()
        return [
            component_response(
                component,
                localized_component_content(session, component, normalized_locale),
            )
            for component in rows
        ]


def search_group_components(
    engine: Engine,
    user_id: str,
    group_id: str,
    content_locale: str,
    query: str,
    statuses: list[str] | None,
    allow_planar_rotation: bool,
    size_tolerance: float,
    page: int,
    page_size: int,
) -> dict:
    """Search one user's managed Components within a selected library group."""
    normalized_locale = normalize_content_locale(content_locale)
    parsed_query = parse_component_search_query(query)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        group = owned_group(session, user_id, group_id)
        if group.group_type == ROOT_GROUP_TYPE:
            statement = select(Component).where(managed_component_predicate(user_id))
        else:
            statement = (
                select(Component)
                .join(
                    ComponentGroupMembership,
                    ComponentGroupMembership.component_id == Component.id,
                )
                .where(
                    ComponentGroupMembership.group_id == group.id,
                    managed_component_predicate(user_id),
                )
            )
        components = session.scalars(
            statement.options(selectinload(Component.translations))
        ).unique().all()

        status_counts: dict[str, int] = {}
        matches: list[tuple[tuple[int, int, int, float], Component, dict]] = []
        active_statuses = set(statuses) if statuses is not None else None
        for component in components:
            status_counts[component.status] = status_counts.get(component.status, 0) + 1
            if active_statuses is not None and component.status not in active_statuses:
                continue
            if not component_dimensions_match(
                component,
                parsed_query["dimensions"],
                allow_planar_rotation,
                size_tolerance,
            ):
                continue
            content = localized_component_content(session, component, normalized_locale)
            text_rank = component_text_match_rank(component, content["name"], parsed_query)
            if text_rank is None:
                continue
            matches.append((text_rank, component, content))

        matches.sort(key=lambda item: item[1].id)
        matches.sort(key=lambda item: item[1].created_at, reverse=True)
        matches.sort(key=lambda item: item[0], reverse=True)
        total = len(matches)
        start = (page - 1) * page_size
        selected = matches[start : start + page_size]
        return {
            "items": [
                component_response(component, content)
                for _rank, component, content in selected
            ],
            "total": total,
            "page": page,
            "pageSize": page_size,
            "totalPages": ceil(total / page_size),
            "statusCounts": status_counts,
        }


def parse_component_search_query(value: str) -> dict[str, list]:
    """Split one search box into dimension alternatives and fuzzy-name fragments."""
    dimensions: list[tuple[float, ...]] = []
    keywords: list[str] = []
    raw_keywords: list[str] = []
    dimension_pattern = re.compile(
        r"(?<![\d.])(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)"
        r"(?:\s*[xX×]\s*(\d+(?:\.\d+)?))?(?![\d.])"
    )
    for match in dimension_pattern.finditer(value):
        dimension = tuple(
            float(item) for item in match.groups() if item is not None
        )
        if dimension not in dimensions:
            dimensions.append(dimension)

    remaining_value = dimension_pattern.sub(" ", value)
    for raw_fragment in re.split(r"[,，\s]+", remaining_value):
        fragment = raw_fragment.strip()
        if not fragment:
            continue
        normalized = normalize_search_text(fragment)
        if normalized is not None and normalized not in keywords:
            keywords.append(normalized)
        raw_keyword = fragment.casefold()
        if raw_keyword not in raw_keywords:
            raw_keywords.append(raw_keyword)
    return {
        "dimensions": dimensions,
        "keywords": keywords,
        "raw_keywords": raw_keywords,
    }


def component_dimensions_match(
    component: Component,
    dimensions: list[tuple[float, ...]],
    allow_planar_rotation: bool,
    tolerance: float,
) -> bool:
    if not dimensions:
        return True
    stored = (
        component.logical_width_stud,
        component.logical_depth_stud,
        component.logical_height_plate,
    )
    width, depth, height = stored
    if width is None or depth is None:
        return False
    for dimension in dimensions:
        direct = close_dimension(width, dimension[0], tolerance) and close_dimension(
            depth,
            dimension[1],
            tolerance,
        )
        rotated = allow_planar_rotation and close_dimension(
            width,
            dimension[1],
            tolerance,
        ) and close_dimension(depth, dimension[0], tolerance)
        if not (direct or rotated):
            continue
        if len(dimension) == 2:
            return True
        if height is not None and close_dimension(height, dimension[2], tolerance):
            return True
    return False


def close_dimension(actual: float, expected: float, tolerance: float) -> bool:
    # The list exposes logical dimensions to two decimal places, while geometry is
    # persisted from matrix-transformed bounds. Treat half of that display unit as
    # the minimum comparison precision so a displayed 9 × 16 remains searchable as
    # 9x16 even when the stored bounds are 8.996 × 16.004.
    return abs(actual - expected) <= max(tolerance, 0.005)


def component_text_match_rank(
    component: Component,
    display_name: str,
    parsed_query: dict[str, list],
) -> tuple[int, int, int, float] | None:
    keywords = parsed_query["keywords"]
    raw_keywords = parsed_query["raw_keywords"]
    if not keywords and not raw_keywords:
        return (0, 0, 0, 0.0)
    component_id = component.id.casefold()
    id_exact = int(any(keyword == component_id for keyword in raw_keywords))
    id_contains = int(any(keyword in component_id for keyword in raw_keywords))
    scores = [component_name_similarity(keyword, display_name) for keyword in keywords]
    matched_scores = [
        score for score in scores if score >= COMPONENT_SEARCH_MINIMUM_NAME_SCORE
    ]
    if not id_contains and not matched_scores:
        return None
    average_score = (
        sum(matched_scores) / len(matched_scores) if matched_scores else 0.0
    )
    return (id_exact, id_contains, len(matched_scores), average_score)


def component_name_similarity(query: str, candidate: str) -> float:
    normalized_candidate = normalize_search_text(candidate)
    if normalized_candidate is None:
        return 0.0
    if query == normalized_candidate:
        return 1.0
    query_tokens = query.split()
    candidate_tokens = normalized_candidate.split()
    scores = [SequenceMatcher(None, query, normalized_candidate).ratio()]
    scores.extend(
        SequenceMatcher(None, query_token, candidate_token).ratio()
        for query_token in query_tokens
        for candidate_token in candidate_tokens
    )
    if all(query_token in candidate_tokens for query_token in query_tokens):
        scores.append(0.98)
    elif all(query_token in normalized_candidate for query_token in query_tokens):
        scores.append(0.9)
    if any(
        candidate_token.startswith(query) or candidate_token.endswith(query)
        for candidate_token in candidate_tokens
    ):
        scores.append(0.92)
    return max(scores)


def add_component_to_group(
    engine: Engine,
    user_id: str,
    group_id: str,
    component_id: str,
) -> None:
    Session = sessionmaker(bind=engine)
    with Session.begin() as session:
        group = mutable_owned_group(session, user_id, group_id)
        require_managed_component(session, user_id, component_id)
        existing = session.get(
            ComponentGroupMembership,
            {"group_id": group.id, "component_id": component_id},
        )
        if existing is None:
            session.add(
                ComponentGroupMembership(
                    group_id=group.id,
                    component_id=component_id,
                    added_by=user_id,
                    added_at=utcnow(),
                )
            )


def remove_component_from_group(
    engine: Engine,
    user_id: str,
    group_id: str,
    component_id: str,
) -> None:
    Session = sessionmaker(bind=engine)
    with Session.begin() as session:
        group = mutable_owned_group(session, user_id, group_id)
        session.execute(
            delete(ComponentGroupMembership).where(
                ComponentGroupMembership.group_id == group.id,
                ComponentGroupMembership.component_id == component_id,
            )
        )


def list_component_group_ids(
    engine: Engine,
    user_id: str,
    component_id: str,
) -> list[str]:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        require_managed_component(session, user_id, component_id)
        return list(
            session.scalars(
                select(ComponentGroupMembership.group_id)
                .join(ComponentGroup, ComponentGroup.id == ComponentGroupMembership.group_id)
                .where(
                    ComponentGroup.owner_id == user_id,
                    ComponentGroupMembership.component_id == component_id,
                )
                .order_by(ComponentGroup.sort_order, ComponentGroup.created_at)
            ).all()
        )


def subscribe_component(engine: Engine, user_id: str, component_id: str) -> None:
    Session = sessionmaker(bind=engine)
    with Session.begin() as session:
        component = session.get(Component, component_id)
        if (
            component is None
            or component.deleted_at is not None
            or component.status != "active"
        ):
            raise DomainError(
                "component_repo.subscription_component_unavailable",
                {"componentId": component_id},
                404,
            )
        if component.created_by == audit_actor(user_id):
            raise DomainError(
                "component_repo.subscription_own_component_forbidden",
                {"componentId": component_id},
                409,
            )
        if session.get(
            ComponentSubscription,
            {"user_id": user_id, "component_id": component_id},
        ) is None:
            session.add(
                ComponentSubscription(
                    user_id=user_id,
                    component_id=component_id,
                    subscribed_at=utcnow(),
                )
            )


def unsubscribe_component(engine: Engine, user_id: str, component_id: str) -> None:
    Session = sessionmaker(bind=engine)
    with Session.begin() as session:
        session.execute(
            delete(ComponentSubscription).where(
                ComponentSubscription.user_id == user_id,
                ComponentSubscription.component_id == component_id,
            )
        )
        session.execute(
            delete(ComponentGroupMembership).where(
                ComponentGroupMembership.component_id == component_id,
                ComponentGroupMembership.group_id.in_(
                    select(ComponentGroup.id).where(ComponentGroup.owner_id == user_id)
                ),
            )
        )


def get_or_create_root_group(session: Session, user_id: str) -> ComponentGroup:
    root = session.scalar(
        select(ComponentGroup).where(
            ComponentGroup.owner_id == user_id,
            ComponentGroup.group_type == ROOT_GROUP_TYPE,
        )
    )
    if root is not None:
        return root
    now = utcnow()
    root = ComponentGroup(
        id=str(uuid4()),
        owner_id=user_id,
        parent_group_id=None,
        group_type=ROOT_GROUP_TYPE,
        name=None,
        normalized_name=None,
        content_locale=None,
        sort_order=0,
        created_at=now,
        updated_at=now,
    )
    session.add(root)
    session.flush()
    return root


def managed_component_rows(session: Session, user_id: str) -> list[Component]:
    return list(
        session.scalars(
            select(Component)
            .where(managed_component_predicate(user_id))
            .options(selectinload(Component.translations))
            .order_by(Component.created_at.desc(), Component.id)
        ).all()
    )


def managed_component_count(session: Session, user_id: str) -> int:
    return int(
        session.scalar(
            select(func.count(Component.id)).where(managed_component_predicate(user_id))
        )
        or 0
    )


def require_managed_component(
    session: Session,
    user_id: str,
    component_id: str,
) -> Component:
    component = session.get(Component, component_id)
    subscribed = session.get(
        ComponentSubscription,
        {"user_id": user_id, "component_id": component_id},
    )
    if component is None or component.deleted_at is not None or not (
        component.created_by == audit_actor(user_id)
        or (component.status == "active" and subscribed is not None)
    ):
        raise DomainError(
            "component_repo.component_not_managed",
            {"componentId": component_id},
            403,
        )
    return component


def owned_group(session: Session, user_id: str, group_id: str) -> ComponentGroup:
    group = session.get(ComponentGroup, group_id)
    if group is None or group.owner_id != user_id:
        raise DomainError(
            "component_repo.group_not_found",
            {"groupId": group_id},
            404,
        )
    return group


def mutable_owned_group(session: Session, user_id: str, group_id: str) -> ComponentGroup:
    group = owned_group(session, user_id, group_id)
    if group.group_type == ROOT_GROUP_TYPE:
        raise DomainError(
            "component_repo.group_root_immutable",
            {"groupId": group_id},
            409,
        )
    return group


def validate_group_name(name: str) -> tuple[str, str]:
    display_name = name.strip()
    if not display_name or len(display_name) > MAX_GROUP_NAME_LENGTH:
        raise DomainError(
            "component_repo.group_name_invalid",
            {"maximumLength": MAX_GROUP_NAME_LENGTH},
            400,
        )
    return display_name, display_name.casefold()


def ensure_unique_sibling_name(
    session: Session,
    user_id: str,
    parent_group_id: str | None,
    normalized_name: str,
    excluding_group_id: str | None = None,
) -> None:
    statement = select(ComponentGroup.id).where(
        ComponentGroup.owner_id == user_id,
        ComponentGroup.parent_group_id == parent_group_id,
        ComponentGroup.normalized_name == normalized_name,
    )
    if excluding_group_id is not None:
        statement = statement.where(ComponentGroup.id != excluding_group_id)
    if session.scalar(statement) is not None:
        raise DomainError(
            "component_repo.group_name_duplicate",
            {"name": normalized_name},
            409,
        )


def group_depth(session: Session, group: ComponentGroup, user_id: str) -> int:
    depth = 0
    cursor = group
    seen = {cursor.id}
    while cursor.parent_group_id is not None:
        parent = owned_group(session, user_id, cursor.parent_group_id)
        if parent.id in seen:
            raise DomainError("component_repo.group_cycle", http_status=409)
        seen.add(parent.id)
        depth += 1
        cursor = parent
    return depth


def descendant_ids(session: Session, user_id: str, group_id: str) -> list[str]:
    rows = session.execute(
        select(ComponentGroup.id, ComponentGroup.parent_group_id).where(
            ComponentGroup.owner_id == user_id,
            ComponentGroup.group_type == CUSTOM_GROUP_TYPE,
        )
    ).all()
    children: dict[str, list[str]] = {}
    for child_id, parent_id in rows:
        if parent_id is not None:
            children.setdefault(parent_id, []).append(child_id)
    result: list[str] = []
    pending = list(children.get(group_id, []))
    while pending:
        child_id = pending.pop()
        result.append(child_id)
        pending.extend(children.get(child_id, []))
    return result


def group_subtree_height(session: Session, user_id: str, group_id: str) -> int:
    rows = session.execute(
        select(ComponentGroup.id, ComponentGroup.parent_group_id).where(
            ComponentGroup.owner_id == user_id,
            ComponentGroup.group_type == CUSTOM_GROUP_TYPE,
        )
    ).all()
    children: dict[str, list[str]] = {}
    for child_id, parent_id in rows:
        if parent_id is not None:
            children.setdefault(parent_id, []).append(child_id)

    def height(node_id: str, seen: set[str]) -> int:
        if node_id in seen:
            raise DomainError("component_repo.group_cycle", http_status=409)
        child_ids = children.get(node_id, [])
        if not child_ids:
            return 0
        next_seen = {*seen, node_id}
        return 1 + max(height(child_id, next_seen) for child_id in child_ids)

    return height(group_id, set())


def group_response(group: ComponentGroup, direct_component_count: int) -> dict:
    return {
        "id": group.id,
        "parentGroupId": group.parent_group_id,
        "groupType": group.group_type,
        "name": group.name,
        "contentLocale": group.content_locale,
        "sortOrder": group.sort_order,
        "directComponentCount": direct_component_count,
        "createdAt": group.created_at.isoformat(),
        "updatedAt": group.updated_at.isoformat(),
    }


def audit_actor(user_id: str) -> str:
    return f"auth:{user_id}"


def managed_component_predicate(user_id: str):
    return and_(
        Component.deleted_at.is_(None),
        or_(
            Component.created_by == audit_actor(user_id),
            and_(
                Component.status == "active",
                exists(
                    select(ComponentSubscription.component_id).where(
                        ComponentSubscription.user_id == user_id,
                        ComponentSubscription.component_id == Component.id,
                    )
                )
            ),
        ),
    )


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
