"""Unified part candidate search over geometry, xref, and connectors."""
import json
import os
from pathlib import Path

from src.config.app_settings import config_file
from src.ldraw.models import (
    LDrawPartCandidate,
    PartSearchCandidate,
    ResolvedLDrawPartCandidate,
    XrefPartMapping,
)
from src.ldraw.repositories import (
    get_part_connectors,
    get_part_geometry,
    get_resolved_part_geometry_candidates,
    search_geometry_candidates,
    search_parts_by_bbox,
    search_parts_by_connector,
)
from src.ldraw.xref_config import (
    get_default_recall_relation_types,
    get_obsolete_ldraw_name_prefixes,
    get_obsolete_ldraw_name_tokens,
    get_relation_type_sort_priority,
    get_substitute_recall_relation_types,
)


REQUIRED_CONFIG_KEYS = (
    "default_limit",
    "pool_multiplier",
    "minimum_pool_size",
    "missing_relation_priority",
    "connector_count_weight",
    "required_connector_keys",
    "score_reason_labels",
)


def _load_config() -> dict:
    config_path = Path(
        os.getenv(
            "PART_CANDIDATE_SEARCH_CONFIG",
            config_file("part_candidate_search.json"),
        )
    )
    config = json.loads(config_path.read_text(encoding="utf-8"))
    missing_keys = [key for key in REQUIRED_CONFIG_KEYS if key not in config]
    if missing_keys:
        raise KeyError(
            f"Missing part candidate search config keys: {', '.join(missing_keys)}"
        )
    return config


def _pool_limit(limit: int | None, config: dict) -> int:
    """计算候选池大小。limit 为 None 时返回一个足够大的值。"""
    if limit is None:
        return 10000
    return max(limit * config["pool_multiplier"], config["minimum_pool_size"])


def _is_obsolete_geometry(geometry: LDrawPartCandidate) -> bool:
    if geometry.name is None:
        return False
    name = geometry.name.strip().lower()
    return any(
        name.startswith(prefix)
        for prefix in get_obsolete_ldraw_name_prefixes()
    ) or any(
        token in name
        for token in get_obsolete_ldraw_name_tokens()
    )


def _filter_obsolete_geometries(
    candidates: list[LDrawPartCandidate],
    exclude_obsolete: bool,
) -> list[LDrawPartCandidate]:
    if not exclude_obsolete:
        return candidates
    return [
        candidate
        for candidate in candidates
        if not _is_obsolete_geometry(candidate)
    ]


def _connector_requirement_value(requirement: dict, key: str, config: dict):
    return requirement.get(config["required_connector_keys"][key])


def _connector_count_key(requirement: dict, config: dict) -> str:
    values = [
        _connector_requirement_value(requirement, "type", config),
        _connector_requirement_value(requirement, "gender", config),
        _connector_requirement_value(requirement, "direction_group", config),
        _connector_requirement_value(requirement, "direction_label", config),
    ]
    return "|".join(str(value) for value in values)


def _matching_connector_count(
    ldraw_part_num: str,
    requirement: dict,
    config: dict,
) -> int:
    connectors = get_part_connectors(
        ldraw_part_num,
        connector_type=_connector_requirement_value(requirement, "type", config),
        connector_gender=_connector_requirement_value(requirement, "gender", config),
        direction_group=_connector_requirement_value(
            requirement,
            "direction_group",
            config,
        ),
        direction_label=_connector_requirement_value(
            requirement,
            "direction_label",
            config,
        ),
    )
    return len(connectors)


def _connector_counts_for_candidate(
    ldraw_part_num: str,
    requirements: list[dict],
    config: dict,
) -> dict[str, int] | None:
    counts = {}
    for requirement in requirements:
        count = _matching_connector_count(ldraw_part_num, requirement, config)
        minimum_count = _connector_requirement_value(requirement, "min_count", config)
        if count < minimum_count:
            return None
        counts[_connector_count_key(requirement, config)] = count
    return counts


def _connector_only_geometries(
    requirements: list[dict],
    limit: int,
    config: dict,
) -> list[LDrawPartCandidate]:
    if not requirements:
        return []

    first_requirement = requirements[0]
    rows = search_parts_by_connector(
        _connector_requirement_value(first_requirement, "type", config),
        connector_gender=_connector_requirement_value(first_requirement, "gender", config),
        direction_group=_connector_requirement_value(
            first_requirement,
            "direction_group",
            config,
        ),
        direction_label=_connector_requirement_value(
            first_requirement,
            "direction_label",
            config,
        ),
        minimum_count=_connector_requirement_value(first_requirement, "min_count", config),
        limit=_pool_limit(limit, config),
    )

    candidates = []
    for ldraw_part_num, _ in rows:
        geometry = get_part_geometry(ldraw_part_num)
        if geometry is not None:
            candidates.append(geometry)
    return candidates


def _base_geometry_candidates(
    logical_size: tuple[float, float, float] | None,
    bbox: tuple[float, float, float] | None,
    strict_bbox: bool,
    bbox_tolerance_ldu: float,
    allow_rotate: bool,
    category: list[str] | None,
    exclude_obsolete: bool,
    required_connectors: list[dict],
    limit: int,
    config: dict,
) -> list[LDrawPartCandidate]:
    if logical_size is not None:
        return _filter_obsolete_geometries(search_geometry_candidates(
            logical_size,
            strict_bbox=strict_bbox,
            bbox_tolerance_ldu=bbox_tolerance_ldu,
            allow_rotate=allow_rotate,
            category=category,
            exclude_obsolete=exclude_obsolete,
            limit=_pool_limit(limit, config),
        ), exclude_obsolete)
    if bbox is not None:
        return _filter_obsolete_geometries(search_parts_by_bbox(
            bbox[0],
            bbox[1],
            bbox[2],
            tolerance_ldu=bbox_tolerance_ldu,
            allow_rotate=allow_rotate,
            category=category,
            limit=_pool_limit(limit, config),
        ), exclude_obsolete)
    return _filter_obsolete_geometries(
        _connector_only_geometries(required_connectors, limit, config),
        exclude_obsolete,
    )


def _resolved_candidates_by_geometry(
    resolved_candidates: list[ResolvedLDrawPartCandidate],
) -> dict[str, ResolvedLDrawPartCandidate]:
    return {
        candidate.geometry.ldraw_part_num: candidate
        for candidate in resolved_candidates
    }


def _relation_priority(mapping: XrefPartMapping | None, config: dict) -> int:
    if mapping is None:
        return config["missing_relation_priority"]
    return get_relation_type_sort_priority()[mapping.relation_type]


def _score(
    geometry: LDrawPartCandidate,
    mapping: XrefPartMapping | None,
    connector_counts: dict[str, int],
    required_connectors: list[dict],
    config: dict,
) -> tuple[float, str]:
    relation_priority = _relation_priority(mapping, config)
    connector_surplus = 0
    for requirement in required_connectors:
        key = _connector_count_key(requirement, config)
        minimum_count = _connector_requirement_value(requirement, "min_count", config)
        connector_surplus += connector_counts[key] - minimum_count

    score = (
        relation_priority
        + geometry.score
        - connector_surplus * config["connector_count_weight"]
    )
    labels = config["score_reason_labels"]
    reason = (
        f"{labels['relation_priority']}={relation_priority}; "
        f"{labels['geometry_score']}={geometry.score:.3f}; "
        f"{labels['connector_surplus']}={connector_surplus}"
    )
    return score, reason


def _to_part_search_candidate(
    geometry: LDrawPartCandidate,
    mapping: XrefPartMapping | None,
    connector_counts: dict[str, int],
    required_connectors: list[dict],
    config: dict,
) -> PartSearchCandidate:
    score, reason = _score(
        geometry,
        mapping,
        connector_counts,
        required_connectors,
        config,
    )
    return PartSearchCandidate(
        geometry=geometry,
        mapping=mapping,
        connector_counts=connector_counts,
        score=score,
        score_reason=reason,
    )


def search_part_candidates(
    logical_size: tuple[float, float, float] | None = None,
    bbox: tuple[float, float, float] | None = None,
    strict_bbox: bool = False,
    bbox_tolerance_ldu: float = 1.0,
    allow_rotate: bool = True,
    category: list[str] | None = None,
    rebrickable_part_num: str | None = None,
    required_connectors: list[dict] | None = None,
    include_substitutes: bool = False,
    exclude_obsolete: bool = True,
    limit: int | None = None,
) -> list[PartSearchCandidate]:
    """Search part candidates using available geometry, xref, and connector data."""
    config = _load_config()
    active_limit = limit if limit is not None else config["default_limit"]
    active_required_connectors = required_connectors or []

    mapping_by_part_num = {}
    if rebrickable_part_num is not None:
        relation_types = (
            get_substitute_recall_relation_types()
            if include_substitutes
            else get_default_recall_relation_types()
        )
        resolved_candidates = get_resolved_part_geometry_candidates(
            rebrickable_part_num,
            relation_types=relation_types,
            exclude_obsolete=exclude_obsolete,
        )
        geometry_candidates = [candidate.geometry for candidate in resolved_candidates]
        mapping_by_part_num = _resolved_candidates_by_geometry(resolved_candidates)
    else:
        geometry_candidates = _base_geometry_candidates(
            logical_size,
            bbox,
            strict_bbox,
            bbox_tolerance_ldu,
            allow_rotate,
            category,
            exclude_obsolete,
            active_required_connectors,
            active_limit,
            config,
        )

    candidates = []
    for geometry in geometry_candidates:
        connector_counts = _connector_counts_for_candidate(
            geometry.ldraw_part_num,
            active_required_connectors,
            config,
        )
        if connector_counts is None:
            continue
        resolved_candidate = mapping_by_part_num.get(geometry.ldraw_part_num)
        mapping = resolved_candidate.mapping if resolved_candidate is not None else None
        candidates.append(
            _to_part_search_candidate(
                geometry,
                mapping,
                connector_counts,
                active_required_connectors,
                config,
            )
        )

    candidates = sorted(
        candidates,
        key=lambda candidate: (
            candidate.score,
            candidate.geometry.ldraw_part_num,
        ),
    )
    # limit 为 None 表示不限量，返回全部结果
    if active_limit is not None:
        candidates = candidates[:active_limit]
    return candidates
