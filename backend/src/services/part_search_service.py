"""Part search API service."""
import re
from typing import Any

from sqlalchemy import Engine, text

from src.api.schemas.part_search import (
    PartSearchCandidateResponse,
    PartSearchRequest,
    PartSearchResponse,
)
from src.ldraw.models import PartSearchCandidate
from src.ldraw.search import search_part_candidates


def contains_term(query: str, terms: list[str]) -> bool:
    normalized_query = query.lower()
    return any(term.lower() in normalized_query for term in terms)


def category_from_query(query: str, config: dict) -> tuple[list[str] | None, float | None]:
    for category_config in config["category_terms"]:
        if contains_term(query, category_config["terms"]):
            return [category_config["category"]], category_config["default_height_plate"]
    return None, None


def logical_size_from_query(query: str, config: dict) -> tuple[float, float, float] | None:
    match = re.search(config["logical_size_pattern"], query.lower())
    if match is None:
        return None

    _, default_height_plate = category_from_query(query, config)
    width = float(match.group(config["logical_size_match_groups"]["width"]))
    depth = float(match.group(config["logical_size_match_groups"]["depth"]))
    height = match.group(config["logical_size_match_groups"]["height"])
    if height is not None:
        return width, depth, float(height)
    if default_height_plate is None:
        return None
    return width, depth, float(default_height_plate)


def size_only_search_specs(query: str, config: dict) -> list[dict]:
    match = re.search(config["logical_size_pattern"], query.lower())
    if match is None:
        return []
    if category_from_query(query, config)[0] is not None:
        return []
    if match.group(config["logical_size_match_groups"]["height"]) is not None:
        return []

    width = float(match.group(config["logical_size_match_groups"]["width"]))
    depth = float(match.group(config["logical_size_match_groups"]["depth"]))
    return [
        {
            "category": [category_config["category"]],
            "logical_size": (
                width,
                depth,
                float(category_config["default_height_plate"]),
            ),
        }
        for category_config in config["category_terms"]
    ]


def required_connectors_from_query(query: str, config: dict) -> list[dict]:
    required_connectors = []
    for connector_config in config["connector_terms"]:
        if not contains_term(query, connector_config["terms"]):
            continue
        requirement = {
            config["connector_requirement_fields"]["type"]: connector_config["type"],
            config["connector_requirement_fields"]["gender"]: connector_config["gender"],
            config["connector_requirement_fields"]["min_count"]: config[
                "default_connector_min_count"
            ],
        }
        if contains_term(query, config["side_terms"]):
            requirement[config["connector_requirement_fields"]["direction_group"]] = config[
                "direction_groups"
            ]["side"]
        elif contains_term(query, config["vertical_terms"]):
            requirement[config["connector_requirement_fields"]["direction_group"]] = config[
                "direction_groups"
            ]["vertical"]
        required_connectors.append(requirement)
        break
    return required_connectors


def rebrickable_part_num_from_query(query: str, config: dict) -> str | None:
    normalized_query = query.strip()
    if not normalized_query:
        return None
    if contains_term(normalized_query, config["part_number_rejected_terms"]):
        return None
    if re.fullmatch(config["part_number_pattern"], normalized_query):
        return normalized_query.removesuffix(config["ldraw_suffix"])
    return None


def search_kwargs_from_request(request: PartSearchRequest, config: dict) -> dict:
    query = request.query.strip()
    category, _ = category_from_query(query, config)
    # 搜索阶段不限量，获取全部候选结果，分页在 search_parts 中处理
    kwargs: dict[str, Any] = {
        "strict_bbox": request.strict_bbox,
        "category": category,
        "include_substitutes": request.include_substitutes,
        "limit": None,
    }

    logical_size = logical_size_from_query(query, config)
    if logical_size is not None:
        kwargs["logical_size"] = logical_size

    required_connectors = required_connectors_from_query(query, config)
    if required_connectors:
        kwargs["required_connectors"] = required_connectors

    rebrickable_part_num = rebrickable_part_num_from_query(query, config)
    if rebrickable_part_num is not None and logical_size is None:
        kwargs["rebrickable_part_num"] = rebrickable_part_num

    return kwargs


def search_kwargs_options_from_request(
    request: PartSearchRequest,
    config: dict,
) -> list[dict]:
    kwargs = search_kwargs_from_request(request, config)
    if "logical_size" in kwargs or "rebrickable_part_num" in kwargs:
        return [kwargs]

    search_specs = size_only_search_specs(request.query.strip(), config)
    if not search_specs:
        return [kwargs]

    return [
        {
            **kwargs,
            "category": search_spec["category"],
            "logical_size": search_spec["logical_size"],
        }
        for search_spec in search_specs
    ]


def image_part_nums(candidate: PartSearchCandidate, config: dict) -> list[str]:
    values = []
    if (
        config["image_part_candidates"]["include_mapping_rebrickable"]
        and candidate.mapping is not None
        and candidate.mapping.rebrickable_part_num is not None
    ):
        values.append(candidate.mapping.rebrickable_part_num)
    if config["image_part_candidates"]["include_ldraw_stem"]:
        values.append(candidate.geometry.ldraw_part_num.removesuffix(config["ldraw_suffix"]))
    return list(dict.fromkeys(values))


def image_url(part_nums: list[str], engine: Engine, config: dict) -> str | None:
    if not part_nums:
        return None
    with engine.connect() as connection:
        for part_num in part_nums:
            row = connection.execute(
                text(config["image_lookup_sql"]),
                {
                    "part_num": part_num,
                    "limit": config["image_lookup_limit"],
                },
            ).first()
            if row is not None:
                return row[0]
    return None


def candidate_response(
    candidate: PartSearchCandidate,
    engine: Engine,
    config: dict,
) -> PartSearchCandidateResponse:
    part_nums = image_part_nums(candidate, config)
    return PartSearchCandidateResponse(
        ldrawPartNum=candidate.geometry.ldraw_part_num,
        name=candidate.geometry.name,
        category=candidate.geometry.category,
        relationType=candidate.mapping.relation_type if candidate.mapping else None,
        rebrickablePartNum=(
            candidate.mapping.rebrickable_part_num if candidate.mapping else None
        ),
        score=candidate.score,
        scoreReason=candidate.score_reason,
        connectorCounts=candidate.connector_counts,
        logicalSize=[
            candidate.geometry.logical_width_stud,
            candidate.geometry.logical_depth_stud,
            candidate.geometry.logical_height_plate,
        ],
        bbox=[
            candidate.geometry.width_ldu,
            candidate.geometry.height_ldu,
            candidate.geometry.depth_ldu,
        ],
        imageUrl=image_url(part_nums, engine, config),
    )


def search_parts(
    request: PartSearchRequest,
    engine: Engine,
    config: dict,
) -> PartSearchResponse:
    kwargs_options = search_kwargs_options_from_request(request, config)
    candidates_by_part_num = {}
    for kwargs in kwargs_options:
        for candidate in search_part_candidates(**kwargs):
            candidates_by_part_num.setdefault(candidate.geometry.ldraw_part_num, candidate)
    candidates = list(candidates_by_part_num.values())
    total = len(candidates)

    # 分页：对最终结果按 score 排序后切片
    candidates.sort(key=lambda c: (c.score, c.geometry.ldraw_part_num))
    page = max(request.page, 1)
    page_size = max(request.page_size, 1)
    start = (page - 1) * page_size
    candidates = candidates[start:start + page_size]

    return PartSearchResponse(
        query=request.query,
        parsed={"searches": kwargs_options},
        count=total,
        candidates=[
            candidate_response(candidate, engine, config)
            for candidate in candidates
        ],
    )
