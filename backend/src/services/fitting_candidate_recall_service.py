"""Recall fitting candidates from persisted candidate profiles."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from src.api.schemas.fitting_candidate_recall import (
    FittingCandidateRecallCandidateResponse,
    FittingCandidateRecallRequest,
    FittingCandidateRecallResponse,
)
from src.model.models import (
    FittingCandidateProfile,
    LDrawPart,
    LDrawPartGeometry,
    LDrawPartShapeProfile,
)


def recall_fitting_candidates(
    engine: Engine,
    config: dict[str, Any],
    request: FittingCandidateRecallRequest,
) -> FittingCandidateRecallResponse:
    query = normalized_recall_query(config, request)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        candidates = ready_candidate_responses(session, config, query)
        if query["include_irregular"]:
            candidates.extend(irregular_candidate_responses(session, config, query))
    candidates.sort(key=lambda candidate: (-candidate.score, candidate.candidateType, candidate.candidateId))
    limited_candidates = candidates[: query["limit"]]
    return FittingCandidateRecallResponse(
        total=len(candidates),
        returned=len(limited_candidates),
        includeIrregular=query["include_irregular"],
        candidates=limited_candidates,
    )


def normalized_recall_query(
    config: dict[str, Any],
    request: FittingCandidateRecallRequest,
) -> dict[str, Any]:
    limit = request.limit if request.limit is not None else config["defaults"]["limit"]
    if limit <= 0:
        raise ValueError(config["errors"]["invalid_limit"])
    return {
        "candidate_types": checked_candidate_types(config, request.candidateTypes),
        "profile_statuses": checked_profile_statuses(config, request.profileStatuses),
        "bbox": normalized_bbox_query(config, request),
        "logical_size": (
            normalized_logical_size_query(config, request)
            if request.logicalSize is not None
            else None
        ),
        "connectors": (
            [connector.model_dump() for connector in request.connectors]
            if request.connectors is not None
            else []
        ),
        "categories": request.categories,
        "color_codes": request.colorCodes,
        "include_irregular": (
            request.includeIrregular
            if request.includeIrregular is not None
            else config["defaults"]["include_irregular"]
        ),
        "limit": min(limit, config["limits"]["max_limit"]),
    }


def normalized_bbox_query(
    config: dict[str, Any],
    request: FittingCandidateRecallRequest,
) -> dict[str, Any] | None:
    if request.bbox is None:
        return None
    bbox_query = request.bbox.model_dump()
    if bbox_query["toleranceLdu"] is None:
        bbox_query["toleranceLdu"] = config["defaults"]["bbox_tolerance_ldu"]
    return bbox_query


def normalized_logical_size_query(
    config: dict[str, Any],
    request: FittingCandidateRecallRequest,
) -> dict[str, Any]:
    logical_size_query = request.logicalSize.model_dump()
    if logical_size_query["tolerance"] is None:
        logical_size_query["tolerance"] = config["defaults"]["logical_size_tolerance"]
    return logical_size_query


def checked_candidate_types(
    config: dict[str, Any],
    candidate_types: list[str] | None,
) -> list[str]:
    active_candidate_types = (
        candidate_types
        if candidate_types is not None
        else config["defaults"]["candidate_types"]
    )
    supported_candidate_types = set(config["defaults"]["candidate_types"])
    for candidate_type in active_candidate_types:
        if candidate_type not in supported_candidate_types:
            raise ValueError(
                config["errors"]["unsupported_candidate_type"].format(
                    candidate_type=candidate_type,
                )
            )
    return active_candidate_types


def checked_profile_statuses(
    config: dict[str, Any],
    profile_statuses: list[str] | None,
) -> list[str]:
    active_profile_statuses = (
        profile_statuses
        if profile_statuses is not None
        else config["defaults"]["profile_statuses"]
    )
    supported_profile_statuses = set(
        config["defaults"]["profile_statuses"]
        + [config["irregular"]["degraded_profile_status"]]
    )
    for profile_status in active_profile_statuses:
        if profile_status not in supported_profile_statuses:
            raise ValueError(
                config["errors"]["unsupported_profile_status"].format(
                    profile_status=profile_status,
                )
            )
    return active_profile_statuses


def ready_candidate_responses(
    session: object,
    config: dict[str, Any],
    query: dict[str, Any],
) -> list[FittingCandidateRecallCandidateResponse]:
    profiles = session.scalars(
        select(FittingCandidateProfile)
        .where(FittingCandidateProfile.candidate_type.in_(query["candidate_types"]))
        .where(FittingCandidateProfile.profile_status.in_(query["profile_statuses"]))
    ).all()
    responses = []
    for profile in profiles:
        candidate = ready_candidate_response(config, query, profile)
        if candidate is not None:
            responses.append(candidate)
    return responses


def ready_candidate_response(
    config: dict[str, Any],
    query: dict[str, Any],
    profile: FittingCandidateProfile,
) -> FittingCandidateRecallCandidateResponse | None:
    reasons = filter_reasons(config, query, candidate_payload(config, profile))
    if reasons is None:
        return None
    score = candidate_score(config, query, profile, reasons)
    return FittingCandidateRecallCandidateResponse(
        candidateType=profile.candidate_type,
        candidateId=profile.candidate_id,
        profileStatus=profile.profile_status,
        source=config["response"]["ready_source"],
        score=score,
        scoreReasons=reasons,
        bbox=profile.bbox_json,
        logicalSize=profile.logical_size_json,
        appearanceTags=profile.appearance_tags_json,
        colorSummary=profile.color_summary_json,
        connectorSummary=profile.connector_summary_json,
        sourceMetadata=profile.source_metadata_json,
        profileError=profile.profile_error,
        profileErrorType=None,
    )


def irregular_candidate_responses(
    session: object,
    config: dict[str, Any],
    query: dict[str, Any],
) -> list[FittingCandidateRecallCandidateResponse]:
    if config["irregular"]["candidate_type"] not in query["candidate_types"]:
        return []
    rows = session.execute(
        select(LDrawPart, LDrawPartGeometry, LDrawPartShapeProfile)
        .join(LDrawPartGeometry, LDrawPartGeometry.ldraw_part_id == LDrawPart.id)
        .join(LDrawPartShapeProfile, LDrawPartShapeProfile.ldraw_part_id == LDrawPart.id)
        .where(
            LDrawPartShapeProfile.profile_status
            == config["irregular"]["degraded_profile_status"]
        )
        .where(
            LDrawPartShapeProfile.profile_error_type.in_(
                config["irregular"]["allowed_error_types"]
            )
        )
    )
    responses = []
    for part, geometry, profile in rows:
        candidate = irregular_candidate_response(config, query, part, geometry, profile)
        if candidate is not None:
            responses.append(candidate)
    return responses


def irregular_candidate_response(
    config: dict[str, Any],
    query: dict[str, Any],
    part: LDrawPart,
    geometry: LDrawPartGeometry,
    profile: LDrawPartShapeProfile,
) -> FittingCandidateRecallCandidateResponse | None:
    payload = irregular_candidate_payload(config, part, geometry)
    reasons = filter_reasons(config, query, payload)
    if reasons is None:
        return None
    reasons.append(config["response"]["irregular_reason"])
    score = (
        config["scoring"]["base_score"]
        - bbox_distance(config, query, payload)
        * config["scoring"]["bbox_weight"]
        - logical_size_distance(config, query, payload)
        * config["scoring"]["logical_size_weight"]
        - config["scoring"]["irregular_penalty"]
    )
    return FittingCandidateRecallCandidateResponse(
        candidateType=config["irregular"]["candidate_type"],
        candidateId=part.ldraw_part_num,
        profileStatus=profile.profile_status,
        source=config["irregular"]["source"],
        score=score,
        scoreReasons=reasons,
        bbox=payload["bbox"],
        logicalSize=payload["logical_size"],
        appearanceTags=payload["appearance_tags"],
        colorSummary=None,
        connectorSummary=None,
        sourceMetadata={
            config["json_keys"]["profile_error_type"]: profile.profile_error_type,
        },
        profileError=profile.profile_error,
        profileErrorType=profile.profile_error_type,
    )


def candidate_payload(
    config: dict[str, Any],
    profile: FittingCandidateProfile,
) -> dict[str, Any]:
    return {
        "bbox": profile.bbox_json,
        "logical_size": profile.logical_size_json,
        "appearance_tags": profile.appearance_tags_json,
        "color_summary": profile.color_summary_json,
        "connector_summary": profile.connector_summary_json,
        "source_metadata": profile.source_metadata_json,
    }


def irregular_candidate_payload(
    config: dict[str, Any],
    part: LDrawPart,
    geometry: LDrawPartGeometry,
) -> dict[str, Any]:
    keys = config["json_keys"]
    return {
        "bbox": {
            keys["bbox"]: {
                keys["width_ldu"]: geometry.width_ldu,
                keys["height_ldu"]: geometry.height_ldu,
                keys["depth_ldu"]: geometry.depth_ldu,
            }
        },
        "logical_size": {
            keys["logical_size"]: {
                keys["width_stud"]: geometry.logical_width_stud,
                keys["depth_stud"]: geometry.logical_depth_stud,
                keys["height_plate"]: geometry.logical_height_plate,
            }
        },
        "appearance_tags": {
            keys["category"]: part.category,
            keys["name"]: part.name,
        },
        "color_summary": None,
        "connector_summary": None,
        "source_metadata": None,
    }


def filter_reasons(
    config: dict[str, Any],
    query: dict[str, Any],
    payload: dict[str, Any],
) -> list[str] | None:
    reasons = []
    if not bbox_matches(config, query, payload):
        return None
    if query["bbox"] is not None:
        reasons.append(config["response"]["bbox_filter_reason"])
    if not logical_size_matches(config, query, payload):
        return None
    if query["logical_size"] is not None:
        reasons.append(config["response"]["logical_size_filter_reason"])
    if not connectors_match(config, query, payload):
        return None
    if query["connectors"]:
        reasons.append(config["response"]["connector_filter_reason"])
    if not categories_match(config, query, payload):
        return None
    if query["categories"] is not None:
        reasons.append(config["response"]["category_filter_reason"])
    if not colors_match(config, query, payload):
        return None
    if query["color_codes"] is not None:
        reasons.append(config["response"]["color_filter_reason"])
    return reasons


def bbox_matches(
    config: dict[str, Any],
    query: dict[str, Any],
    payload: dict[str, Any],
) -> bool:
    bbox_query = query["bbox"]
    if bbox_query is None:
        return True
    dimensions = payload["bbox"][config["json_keys"]["bbox"]]
    tolerance = bbox_query["toleranceLdu"]
    for query_key, payload_key in bbox_dimension_pairs(config):
        if bbox_query[query_key] is None:
            continue
        if dimensions[payload_key] is None:
            return False
        if abs(dimensions[payload_key] - bbox_query[query_key]) > tolerance:
            return False
    return True


def logical_size_matches(
    config: dict[str, Any],
    query: dict[str, Any],
    payload: dict[str, Any],
) -> bool:
    logical_query = query["logical_size"]
    if logical_query is None:
        return True
    logical_size = payload["logical_size"][config["json_keys"]["logical_size"]]
    tolerance = logical_query["tolerance"]
    for query_key, payload_key in logical_size_pairs(config):
        if logical_query[query_key] is None:
            continue
        if logical_size[payload_key] is None:
            return False
        if abs(logical_size[payload_key] - logical_query[query_key]) > tolerance:
            return False
    return True


def connectors_match(
    config: dict[str, Any],
    query: dict[str, Any],
    payload: dict[str, Any],
) -> bool:
    if not query["connectors"]:
        return True
    connector_summary = payload["connector_summary"]
    if connector_summary is None:
        return False
    connector_rows = connector_summary[config["json_keys"]["by_type_gender"]]
    for connector_query in query["connectors"]:
        if not connector_requirement_matches(config, connector_rows, connector_query):
            return False
    return True


def connector_requirement_matches(
    config: dict[str, Any],
    connector_rows: list[dict[str, Any]],
    connector_query: dict[str, Any],
) -> bool:
    keys = config["json_keys"]
    for connector_row in connector_rows:
        if connector_row[keys["connector_type"]] != connector_query["connectorType"]:
            continue
        if (
            connector_query["connectorGender"] is not None
            and connector_row[keys["connector_gender"]]
            != connector_query["connectorGender"]
        ):
            continue
        if connector_row[keys["count"]] >= connector_min_count(connector_query):
            return True
    return False


def connector_min_count(connector_query: dict[str, Any]) -> int:
    if connector_query["minCount"] is None:
        return 1
    return connector_query["minCount"]


def categories_match(
    config: dict[str, Any],
    query: dict[str, Any],
    payload: dict[str, Any],
) -> bool:
    categories = query["categories"]
    if categories is None:
        return True
    category_set = set(categories)
    appearance_tags = payload["appearance_tags"]
    if (
        appearance_tags is not None
        and appearance_tags.get(config["json_keys"]["category"]) in category_set
    ):
        return True
    source_metadata = payload["source_metadata"]
    if source_metadata is None:
        return False
    part_summary = source_metadata.get(config["json_keys"]["part_summary"])
    if part_summary is None:
        return False
    return any(
        item[config["json_keys"]["category"]] in category_set
        for item in part_summary[config["json_keys"]["by_category"]]
    )


def colors_match(
    config: dict[str, Any],
    query: dict[str, Any],
    payload: dict[str, Any],
) -> bool:
    color_codes = query["color_codes"]
    if color_codes is None:
        return True
    color_summary = payload["color_summary"]
    if color_summary is None:
        return False
    color_code_set = set(color_codes)
    return any(
        color_row[config["json_keys"]["color_code"]] in color_code_set
        for color_row in color_summary
    )


def candidate_score(
    config: dict[str, Any],
    query: dict[str, Any],
    profile: FittingCandidateProfile,
    reasons: list[str],
) -> float:
    payload = candidate_payload(config, profile)
    return (
        config["scoring"]["base_score"]
        - bbox_distance(config, query, payload) * config["scoring"]["bbox_weight"]
        - logical_size_distance(config, query, payload)
        * config["scoring"]["logical_size_weight"]
        + connector_score(config, query)
        + category_score(config, query)
        + color_score(config, query)
        + len(reasons)
    )


def bbox_distance(
    config: dict[str, Any],
    query: dict[str, Any],
    payload: dict[str, Any],
) -> float:
    bbox_query = query["bbox"]
    if bbox_query is None:
        return 0.0
    dimensions = payload["bbox"][config["json_keys"]["bbox"]]
    return sum(
        abs(dimensions[payload_key] - bbox_query[query_key])
        for query_key, payload_key in bbox_dimension_pairs(config)
        if bbox_query[query_key] is not None and dimensions[payload_key] is not None
    )


def logical_size_distance(
    config: dict[str, Any],
    query: dict[str, Any],
    payload: dict[str, Any],
) -> float:
    logical_query = query["logical_size"]
    if logical_query is None:
        return 0.0
    logical_size = payload["logical_size"][config["json_keys"]["logical_size"]]
    return sum(
        abs(logical_size[payload_key] - logical_query[query_key])
        for query_key, payload_key in logical_size_pairs(config)
        if logical_query[query_key] is not None and logical_size[payload_key] is not None
    )


def connector_score(config: dict[str, Any], query: dict[str, Any]) -> float:
    return len(query["connectors"]) * config["scoring"]["connector_bonus"]


def category_score(config: dict[str, Any], query: dict[str, Any]) -> float:
    if query["categories"] is None:
        return 0.0
    return config["scoring"]["category_bonus"]


def color_score(config: dict[str, Any], query: dict[str, Any]) -> float:
    if query["color_codes"] is None:
        return 0.0
    return config["scoring"]["color_bonus"]


def bbox_dimension_pairs(config: dict[str, Any]) -> list[tuple[str, str]]:
    keys = config["json_keys"]
    return [
        (keys["width_ldu"], keys["width_ldu"]),
        (keys["height_ldu"], keys["height_ldu"]),
        (keys["depth_ldu"], keys["depth_ldu"]),
    ]


def logical_size_pairs(config: dict[str, Any]) -> list[tuple[str, str]]:
    keys = config["json_keys"]
    return [
        (keys["width_stud"], keys["width_stud"]),
        (keys["depth_stud"], keys["depth_stud"]),
        (keys["height_plate"], keys["height_plate"]),
    ]
