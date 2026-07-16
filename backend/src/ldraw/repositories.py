"""Repository functions for LDraw part geometry."""
from dataclasses import replace
import math
import re

from sqlalchemy import create_engine, func, or_, select
from sqlalchemy.orm import sessionmaker

from src.config.db_config import get_db_url
from src.ldraw.models import (
    ConnectorInstanceCandidate,
    LDrawPartCandidate,
    ResolvedLDrawPartCandidate,
    XrefPartMapping,
)
from src.ldraw.xref_config import (
    get_default_recall_relation_types,
    get_obsolete_ldraw_name_prefixes,
    get_obsolete_ldraw_name_tokens,
    get_relation_type_sort_priority,
    get_substitute_recall_relation_types,
    should_exclude_obsolete_candidates_by_default,
)
from src.model.models import (
    ConnectorInstance,
    LDrawPart,
    LDrawPartGeometry,
    XrefPartNumber,
)


DEFAULT_GEOMETRY_STATUSES = ("parsed",)
STANDARD_STUD_LDU = 20.0
STANDARD_PLATE_HEIGHT_LDU = 8.0
STANDARD_BRICK_BBOX_HEIGHT_LDU = 28.0
STANDARD_PLATE_BBOX_HEIGHT_LDU = 12.0


def _make_session():
    engine = create_engine(get_db_url(), echo=False)
    return sessionmaker(bind=engine)()


def _to_candidate(part: LDrawPart, geometry: LDrawPartGeometry) -> LDrawPartCandidate:
    return LDrawPartCandidate(
        ldraw_part_num=part.ldraw_part_num,
        name=part.name,
        category=part.category,
        relative_path=part.relative_path,
        width_ldu=geometry.width_ldu,
        height_ldu=geometry.height_ldu,
        depth_ldu=geometry.depth_ldu,
        logical_width_stud=geometry.logical_width_stud,
        logical_depth_stud=geometry.logical_depth_stud,
        logical_height_plate=geometry.logical_height_plate,
        geometry_status=geometry.geometry_status,
    )


def _to_mapping(xref: XrefPartNumber) -> XrefPartMapping:
    return XrefPartMapping(
        rebrickable_part_num=xref.rebrickable_part_num,
        ldraw_part_num=xref.ldraw_part_num,
        bricklink_part_num=xref.bricklink_part_num,
        lego_design_id=xref.lego_design_id,
        relation_type=xref.relation_type,
        source=xref.source,
        confidence=float(xref.confidence),
    )


def _to_connector_candidate(
    connector: ConnectorInstance,
) -> ConnectorInstanceCandidate:
    return ConnectorInstanceCandidate(
        ldraw_part_num=connector.ldraw_part_num,
        source_type=connector.source_type,
        source_meta_id=connector.source_meta_id,
        connector_kind=connector.connector_kind,
        normalized_connector_type=connector.normalized_connector_type,
        connector_group=connector.connector_group,
        connector_gender=connector.connector_gender,
        pos_x=connector.pos_x,
        pos_y=connector.pos_y,
        pos_z=connector.pos_z,
        ori_11=connector.ori_11,
        ori_12=connector.ori_12,
        ori_13=connector.ori_13,
        ori_21=connector.ori_21,
        ori_22=connector.ori_22,
        ori_23=connector.ori_23,
        ori_31=connector.ori_31,
        ori_32=connector.ori_32,
        ori_33=connector.ori_33,
        direction_x=connector.direction_x,
        direction_y=connector.direction_y,
        direction_z=connector.direction_z,
        direction_label=connector.direction_label,
        direction_group=connector.direction_group,
        radius=connector.radius,
        length=connector.length,
        caps=connector.caps,
        center_flag=connector.center_flag,
        slide_flag=connector.slide_flag,
        confidence=float(connector.confidence),
    )


def _sort_mappings(mappings: list[XrefPartMapping]) -> list[XrefPartMapping]:
    priority = get_relation_type_sort_priority()
    return sorted(
        mappings,
        key=lambda mapping: (
            priority[mapping.relation_type],
            -mapping.confidence,
            mapping.ldraw_part_num,
        ),
    )


def _sort_resolved_candidates(
    candidates: list[ResolvedLDrawPartCandidate],
) -> list[ResolvedLDrawPartCandidate]:
    priority = get_relation_type_sort_priority()
    return sorted(
        candidates,
        key=lambda candidate: (
            priority[candidate.mapping.relation_type],
            -candidate.mapping.confidence,
            candidate.geometry.ldraw_part_num,
        ),
    )


def _is_obsolete_ldraw_name(name: str | None) -> bool:
    if name is None:
        return False

    normalized_name = name.strip().lower()
    return any(
        normalized_name.startswith(prefix)
        for prefix in get_obsolete_ldraw_name_prefixes()
    ) or any(
        token in normalized_name
        for token in get_obsolete_ldraw_name_tokens()
    )


def _is_obsolete_alias(candidate: LDrawPartCandidate) -> bool:
    name = (candidate.name or "").lower()
    return (
        name.startswith("~")
        or "obsolete" in name
        or "moved to" in name
    )


def _is_plain_part_num(part_num: str) -> bool:
    stem = part_num.removesuffix(".dat")
    return re.fullmatch(r"\d+[a-z]?", stem) is not None


def _name_penalty(candidate: LDrawPartCandidate) -> float:
    name = (candidate.name or "").lower()
    penalty = 0.0
    for token in (
        " sticker",
        " stickers",
        " print",
        " pattern",
        " shortcut",
        " with ",
        " complete assembly",
    ):
        if token in name:
            penalty += 20.0
    if _is_obsolete_alias(candidate):
        penalty += 200.0
    if not _is_plain_part_num(candidate.ldraw_part_num):
        penalty += 5.0
    return penalty


def _candidate_bbox_distance(
    candidate: LDrawPartCandidate,
    target_width_ldu: float,
    target_height_ldu: float,
    target_depth_ldu: float,
    allow_rotate: bool,
) -> float:
    if (
        candidate.width_ldu is None
        or candidate.height_ldu is None
        or candidate.depth_ldu is None
    ):
        return math.inf

    direct = (
        abs(candidate.width_ldu - target_width_ldu)
        + abs(candidate.height_ldu - target_height_ldu)
        + abs(candidate.depth_ldu - target_depth_ldu)
    )
    if not allow_rotate or target_width_ldu == target_depth_ldu:
        return direct

    rotated = (
        abs(candidate.width_ldu - target_depth_ldu)
        + abs(candidate.height_ldu - target_height_ldu)
        + abs(candidate.depth_ldu - target_width_ldu)
    )
    return min(direct, rotated)


def _target_bbox_from_logical_size(
    width_stud: float,
    depth_stud: float,
    height_plate: float,
) -> tuple[float, float, float]:
    width_ldu = width_stud * STANDARD_STUD_LDU
    depth_ldu = depth_stud * STANDARD_STUD_LDU

    if height_plate == 1:
        height_ldu = STANDARD_PLATE_BBOX_HEIGHT_LDU
    elif height_plate == 3:
        height_ldu = STANDARD_BRICK_BBOX_HEIGHT_LDU
    else:
        height_ldu = height_plate * STANDARD_PLATE_HEIGHT_LDU

    return width_ldu, height_ldu, depth_ldu


def _rank_geometry_candidates(
    candidates: list[LDrawPartCandidate],
    target_width_ldu: float,
    target_height_ldu: float,
    target_depth_ldu: float,
    allow_rotate: bool,
) -> list[LDrawPartCandidate]:
    ranked = []
    for candidate in candidates:
        bbox_distance = _candidate_bbox_distance(
            candidate,
            target_width_ldu,
            target_height_ldu,
            target_depth_ldu,
            allow_rotate,
        )
        name_penalty = _name_penalty(candidate)
        score = bbox_distance + name_penalty
        reason = f"bbox_distance={bbox_distance:.3f}; name_penalty={name_penalty:.1f}"
        ranked.append(replace(candidate, score=score, score_reason=reason))

    return sorted(
        ranked,
        key=lambda candidate: (
            candidate.score,
            len(candidate.ldraw_part_num),
            candidate.ldraw_part_num,
        ),
    )


def get_part_geometry(ldraw_part_num: str) -> LDrawPartCandidate | None:
    """Return one part geometry row by LDraw part number."""
    with _make_session() as session:
        row = session.execute(
            select(LDrawPart, LDrawPartGeometry)
            .join(LDrawPartGeometry, LDrawPartGeometry.ldraw_part_id == LDrawPart.id)
            .where(LDrawPart.ldraw_part_num == ldraw_part_num.lower())
        ).first()
        if row is None:
            return None
        return _to_candidate(row[0], row[1])


def get_part_connectors(
    ldraw_part_num: str,
    connector_type: str | None = None,
    connector_gender: str | None = None,
    direction_group: str | None = None,
    direction_label: str | None = None,
) -> list[ConnectorInstanceCandidate]:
    """Return connector instances for one LDraw part number."""
    with _make_session() as session:
        stmt = (
            select(ConnectorInstance)
            .where(ConnectorInstance.ldraw_part_num == ldraw_part_num.lower())
            .order_by(
                ConnectorInstance.normalized_connector_type,
                ConnectorInstance.connector_gender,
                ConnectorInstance.pos_x,
                ConnectorInstance.pos_y,
                ConnectorInstance.pos_z,
            )
        )
        if connector_type:
            stmt = stmt.where(
                ConnectorInstance.normalized_connector_type == connector_type
            )
        if connector_gender:
            stmt = stmt.where(ConnectorInstance.connector_gender == connector_gender)
        if direction_group:
            stmt = stmt.where(ConnectorInstance.direction_group == direction_group)
        if direction_label:
            stmt = stmt.where(ConnectorInstance.direction_label == direction_label)

        return [_to_connector_candidate(row[0]) for row in session.execute(stmt)]


def search_parts_by_connector(
    connector_type: str,
    connector_gender: str | None = None,
    direction_group: str | None = None,
    direction_label: str | None = None,
    minimum_count: int = 1,
    limit: int = 100,
) -> list[tuple[str, int]]:
    """Return LDraw part numbers having at least the requested connector count."""
    with _make_session() as session:
        stmt = (
            select(
                ConnectorInstance.ldraw_part_num,
                func.count().label("connector_count"),
            )
            .where(ConnectorInstance.normalized_connector_type == connector_type)
            .group_by(ConnectorInstance.ldraw_part_num)
            .having(func.count() >= minimum_count)
            .order_by(func.count().desc(), ConnectorInstance.ldraw_part_num)
            .limit(limit)
        )
        if connector_gender:
            stmt = stmt.where(ConnectorInstance.connector_gender == connector_gender)
        if direction_group:
            stmt = stmt.where(ConnectorInstance.direction_group == direction_group)
        if direction_label:
            stmt = stmt.where(ConnectorInstance.direction_label == direction_label)

        return [
            (ldraw_part_num, connector_count)
            for ldraw_part_num, connector_count in session.execute(stmt)
        ]


def resolve_ldraw_part_mappings(
    rebrickable_part_num: str,
    relation_types: tuple[str, ...] | None = None,
    sources: tuple[str, ...] | None = None,
) -> list[XrefPartMapping]:
    """Resolve LDraw part numbers through xref_part_numbers."""
    active_relation_types = relation_types or get_default_recall_relation_types()
    with _make_session() as session:
        stmt = (
            select(XrefPartNumber)
            .where(XrefPartNumber.rebrickable_part_num == rebrickable_part_num)
            .where(XrefPartNumber.ldraw_part_num.is_not(None))
            .order_by(
                XrefPartNumber.confidence.desc(),
                XrefPartNumber.ldraw_part_num,
            )
        )
        stmt = stmt.where(XrefPartNumber.relation_type.in_(active_relation_types))
        if sources:
            stmt = stmt.where(XrefPartNumber.source.in_(sources))

        return _sort_mappings([_to_mapping(row[0]) for row in session.execute(stmt)])


def get_resolved_part_geometry_candidates(
    rebrickable_part_num: str,
    relation_types: tuple[str, ...] | None = None,
    sources: tuple[str, ...] | None = None,
    exclude_obsolete: bool | None = None,
) -> list[ResolvedLDrawPartCandidate]:
    """Return xref-aware geometry candidates for one Rebrickable part."""
    active_relation_types = relation_types or get_default_recall_relation_types()
    active_exclude_obsolete = (
        should_exclude_obsolete_candidates_by_default()
        if exclude_obsolete is None
        else exclude_obsolete
    )
    with _make_session() as session:
        stmt = (
            select(XrefPartNumber, LDrawPart, LDrawPartGeometry)
            .join(LDrawPart, LDrawPart.ldraw_part_num == XrefPartNumber.ldraw_part_num)
            .join(LDrawPartGeometry, LDrawPartGeometry.ldraw_part_id == LDrawPart.id)
            .where(XrefPartNumber.rebrickable_part_num == rebrickable_part_num)
            .where(XrefPartNumber.ldraw_part_num.is_not(None))
            .where(XrefPartNumber.relation_type.in_(active_relation_types))
        )
        if sources:
            stmt = stmt.where(XrefPartNumber.source.in_(sources))

        candidates = [
            ResolvedLDrawPartCandidate(
                mapping=_to_mapping(xref),
                geometry=_to_candidate(part, geometry),
            )
            for xref, part, geometry in session.execute(stmt)
        ]
        if active_exclude_obsolete:
            candidates = [
                candidate
                for candidate in candidates
                if not _is_obsolete_ldraw_name(candidate.geometry.name)
            ]
        return _sort_resolved_candidates(candidates)


def get_resolved_part_geometry_candidates_with_substitutes(
    rebrickable_part_num: str,
    exclude_obsolete: bool | None = None,
) -> list[ResolvedLDrawPartCandidate]:
    """Return xref-aware geometry candidates including substitute candidates."""
    return get_resolved_part_geometry_candidates(
        rebrickable_part_num,
        relation_types=get_substitute_recall_relation_types(),
        exclude_obsolete=exclude_obsolete,
    )


def resolve_ldraw_part_numbers(
    rebrickable_part_num: str,
    relation_types: tuple[str, ...] | None = None,
    sources: tuple[str, ...] | None = None,
) -> list[str]:
    """Resolve LDraw part numbers through xref_part_numbers."""
    return [
        mapping.ldraw_part_num
        for mapping in resolve_ldraw_part_mappings(
            rebrickable_part_num,
            relation_types=relation_types,
            sources=sources,
        )
        if mapping.ldraw_part_num is not None
    ]


def get_part_geometries_by_rebrickable_part_num(
    rebrickable_part_num: str,
    relation_types: tuple[str, ...] | None = None,
    sources: tuple[str, ...] | None = None,
    exclude_obsolete: bool | None = None,
) -> list[LDrawPartCandidate]:
    """Return geometries after resolving Rebrickable part number through xref."""
    resolved_candidates = get_resolved_part_geometry_candidates(
        rebrickable_part_num,
        relation_types=relation_types,
        sources=sources,
        exclude_obsolete=exclude_obsolete,
    )
    return [candidate.geometry for candidate in resolved_candidates]


def search_parts_by_logical_size(
    width_stud: float,
    depth_stud: float,
    height_plate: float,
    allow_rotate: bool = True,
    category: list[str] | None = None,
    geometry_statuses: tuple[str, ...] = DEFAULT_GEOMETRY_STATUSES,
    limit: int = 100,
) -> list[LDrawPartCandidate]:
    """Search parts by logical LEGO size."""
    with _make_session() as session:
        conditions = [
            LDrawPartGeometry.logical_width_stud == width_stud,
            LDrawPartGeometry.logical_depth_stud == depth_stud,
        ]
        if allow_rotate and width_stud != depth_stud:
            size_condition = or_(
                conditions[0] & conditions[1],
                (
                    (LDrawPartGeometry.logical_width_stud == depth_stud)
                    & (LDrawPartGeometry.logical_depth_stud == width_stud)
                ),
            )
        else:
            size_condition = conditions[0] & conditions[1]

        stmt = (
            select(LDrawPart, LDrawPartGeometry)
            .join(LDrawPartGeometry, LDrawPartGeometry.ldraw_part_id == LDrawPart.id)
            .where(size_condition)
            .where(LDrawPartGeometry.logical_height_plate == height_plate)
            .where(LDrawPartGeometry.geometry_status.in_(geometry_statuses))
            .order_by(LDrawPart.ldraw_part_num)
            .limit(limit)
        )
        if category:
            stmt = stmt.where(LDrawPart.category.in_(category))

        return [_to_candidate(part, geometry) for part, geometry in session.execute(stmt)]


def search_parts_by_bbox(
    width_ldu: float,
    height_ldu: float,
    depth_ldu: float,
    tolerance_ldu: float = 1.0,
    allow_rotate: bool = True,
    category: list[str] | None = None,
    geometry_statuses: tuple[str, ...] = DEFAULT_GEOMETRY_STATUSES,
    limit: int = 100,
) -> list[LDrawPartCandidate]:
    """Search parts by geometry bbox dimensions."""

    def between(column, value):
        return column.between(value - tolerance_ldu, value + tolerance_ldu)

    with _make_session() as session:
        direct = (
            between(LDrawPartGeometry.width_ldu, width_ldu)
            & between(LDrawPartGeometry.height_ldu, height_ldu)
            & between(LDrawPartGeometry.depth_ldu, depth_ldu)
        )
        if allow_rotate and width_ldu != depth_ldu:
            size_condition = or_(
                direct,
                (
                    between(LDrawPartGeometry.width_ldu, depth_ldu)
                    & between(LDrawPartGeometry.height_ldu, height_ldu)
                    & between(LDrawPartGeometry.depth_ldu, width_ldu)
                ),
            )
        else:
            size_condition = direct

        stmt = (
            select(LDrawPart, LDrawPartGeometry)
            .join(LDrawPartGeometry, LDrawPartGeometry.ldraw_part_id == LDrawPart.id)
            .where(size_condition)
            .where(LDrawPartGeometry.geometry_status.in_(geometry_statuses))
            .order_by(LDrawPart.ldraw_part_num)
            .limit(limit)
        )
        if category:
            stmt = stmt.where(LDrawPart.category.in_(category))

        return [_to_candidate(part, geometry) for part, geometry in session.execute(stmt)]


def search_geometry_candidates(
    logical_size: tuple[float, float, float],
    strict_bbox: bool = False,
    bbox_tolerance_ldu: float = 1.0,
    allow_rotate: bool = True,
    category: list[str] | None = None,
    exclude_obsolete: bool = True,
    limit: int = 100,
) -> list[LDrawPartCandidate]:
    """Search geometry candidates with ranking and optional strict bbox filtering."""
    width_stud, depth_stud, height_plate = logical_size
    target_width_ldu, target_height_ldu, target_depth_ldu = _target_bbox_from_logical_size(
        width_stud,
        depth_stud,
        height_plate,
    )

    candidates = search_parts_by_logical_size(
        width_stud,
        depth_stud,
        height_plate,
        allow_rotate=allow_rotate,
        category=category,
        limit=max(limit * 20, 500) if limit is not None else 20000,
    )
    if exclude_obsolete:
        candidates = [
            candidate for candidate in candidates if not _is_obsolete_alias(candidate)
        ]

    if strict_bbox:
        candidates = [
            candidate
            for candidate in candidates
            if _candidate_bbox_distance(
                candidate,
                target_width_ldu,
                target_height_ldu,
                target_depth_ldu,
                allow_rotate,
            )
            <= bbox_tolerance_ldu
        ]

    return _rank_geometry_candidates(
        candidates,
        target_width_ldu,
        target_height_ldu,
        target_depth_ldu,
        allow_rotate,
    )[:limit]
