"""Recall fitting candidates from persisted candidate profiles."""

from __future__ import annotations

from difflib import SequenceMatcher
from math import ceil
from typing import Any

from sqlalchemy import Engine, and_, func, literal, or_, select, true, union_all
from sqlalchemy.orm import load_only, sessionmaker

from src.i18n.messages import message
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
    PartImage,
    XrefPartNumber,
)
from src.services.fitting_candidate_search_fields import normalize_search_text


def recall_fitting_candidates(
    engine: Engine,
    config: dict[str, Any],
    request: FittingCandidateRecallRequest,
    component_config: dict[str, Any] | None = None,
    include_images: bool = False,
) -> FittingCandidateRecallResponse:
    query = normalized_recall_query(config, request)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        candidates = ready_candidate_responses(session, config, query)
        if query["include_irregular"]:
            candidates.extend(irregular_candidate_responses(session, config, query))
        candidates.sort(
            key=lambda candidate: (
                -candidate.score,
                candidate.candidateType,
                candidate.candidateId,
            )
        )
        page_start = (query["page"] - 1) * query["page_size"]
        limited_candidates = candidates[page_start : page_start + query["page_size"]]
        if include_images:
            limited_candidates = candidates_with_images(
                session,
                config,
                limited_candidates,
            )
    return FittingCandidateRecallResponse(
        total=len(candidates),
        returned=len(limited_candidates),
        page=query["page"],
        pageSize=query["page_size"],
        totalPages=ceil(len(candidates) / query["page_size"]),
        includeIrregular=query["include_irregular"],
        candidates=limited_candidates,
    )


def candidates_with_images(
    session: object,
    config: dict[str, Any],
    candidates: list[FittingCandidateRecallCandidateResponse],
) -> list[FittingCandidateRecallCandidateResponse]:
    image_urls = candidate_image_urls(session, config, candidates)
    return [
        candidate.model_copy(update={"imageUrl": image_urls.get(candidate.candidateId)})
        for candidate in candidates
    ]


def candidate_image_urls(
    session: object,
    config: dict[str, Any],
    candidates: list[FittingCandidateRecallCandidateResponse],
) -> dict[str, str]:
    image_config = config["part_images"]
    candidate_ids = [
        candidate.candidateId
        for candidate in candidates
        if candidate.candidateType == image_config["candidate_type"]
    ]
    if not candidate_ids:
        return {}

    suffix = image_config["ldraw_suffix"]
    stem_to_candidate_id = {
        candidate_id.removesuffix(suffix): candidate_id for candidate_id in candidate_ids
    }
    direct_images = (
        select(
            PartImage.part_num.label("lookup_key"),
            PartImage.img_url.label("image_url"),
            literal(2).label("priority"),
            literal(1.0).label("confidence"),
        )
        .where(PartImage.part_num.in_(stem_to_candidate_id))
    )
    mapped_images = (
        select(
            XrefPartNumber.ldraw_part_num.label("lookup_key"),
            PartImage.img_url.label("image_url"),
            literal(1).label("priority"),
            XrefPartNumber.confidence.label("confidence"),
        )
        .join(
            PartImage,
            PartImage.part_num == XrefPartNumber.rebrickable_part_num,
        )
        .where(XrefPartNumber.ldraw_part_num.in_(candidate_ids))
    )

    selected: dict[str, tuple[tuple[int, float], str]] = {}
    for lookup_key, image_url, priority, confidence in session.execute(
        union_all(direct_images, mapped_images)
    ):
        candidate_id = (
            stem_to_candidate_id.get(lookup_key)
            if priority == 2
            else lookup_key
        )
        if candidate_id is None:
            continue
        rank = (int(priority), float(confidence or 0))
        current = selected.get(candidate_id)
        if current is None or rank > current[0]:
            selected[candidate_id] = (rank, image_url)
    return {candidate_id: value[1] for candidate_id, value in selected.items()}


def normalized_recall_query(
    config: dict[str, Any],
    request: FittingCandidateRecallRequest,
) -> dict[str, Any]:
    page_size = (
        request.pageSize
        if request.pageSize is not None
        else request.limit
        if request.limit is not None
        else config["defaults"]["limit"]
    )
    if page_size <= 0:
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
        "key": normalize_search_text(request.key),
        "allow_planar_rotation": request.allowPlanarRotation,
        "include_irregular": (
            request.includeIrregular
            if request.includeIrregular is not None
            else config["defaults"]["include_irregular"]
        ),
        "page": request.page,
        "page_size": min(page_size, config["limits"]["max_limit"]),
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
    supported_candidate_types = set(
        config["defaults"].get(
            "supported_candidate_types",
            config["defaults"]["candidate_types"],
        )
    )
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
    statement = (
        select(FittingCandidateProfile)
        .options(
            load_only(
                FittingCandidateProfile.candidate_type,
                FittingCandidateProfile.candidate_id,
                FittingCandidateProfile.profile_status,
                FittingCandidateProfile.bbox_json,
                FittingCandidateProfile.logical_size_json,
                FittingCandidateProfile.appearance_tags_json,
                FittingCandidateProfile.color_summary_json,
                FittingCandidateProfile.connector_summary_json,
                FittingCandidateProfile.source_metadata_json,
                FittingCandidateProfile.profile_error_code,
                FittingCandidateProfile.profile_error_params_json,
            )
        )
        .where(FittingCandidateProfile.candidate_type.in_(query["candidate_types"]))
        .where(FittingCandidateProfile.profile_status.in_(query["profile_statuses"]))
    )
    if config["part_filters"]["exclude_stickers"]:
        statement = statement.where(
            or_(
                FittingCandidateProfile.candidate_type != "part",
                FittingCandidateProfile.is_sticker.is_(False),
            )
        )
    if query["logical_size"] is not None:
        statement = statement.where(persisted_logical_size_filter(config, query))
    if query["key"] is not None:
        statement = statement.where(persisted_name_filter(config, query["key"]))
    profiles = session.scalars(statement).all()
    responses = []
    for profile in profiles:
        candidate = ready_candidate_response(
            session,
            config,
            query,
            profile,
        )
        if candidate is not None:
            responses.append(candidate)
    return responses


def persisted_name_filter(config: dict[str, Any], key: str):
    """Match every normalized key token against the persisted source name."""
    name = FittingCandidateProfile.appearance_tags_json[
        config["json_keys"]["name"]
    ].as_string()
    return and_(
        *(func.lower(name).contains(token, autoescape=True) for token in key.split())
    )


def persisted_logical_size_filter(
    config: dict[str, Any],
    query: dict[str, Any],
):
    """Filter persisted profiles by dimensions before loading their full JSON payload."""
    return persisted_dimension_filter(
        config,
        query,
        FittingCandidateProfile.width_stud,
        FittingCandidateProfile.depth_stud,
        FittingCandidateProfile.height_plate,
    )


def persisted_dimension_filter(
    config: dict[str, Any],
    query: dict[str, Any],
    stored_width,
    stored_depth,
    stored_height,
):
    logical_query = query["logical_size"]
    keys = config["json_keys"]
    width_key = keys["width_stud"]
    depth_key = keys["depth_stud"]
    height_key = keys["height_plate"]
    tolerance = logical_query["tolerance"]

    filters = []
    direct_planar_filters = []
    if logical_query[width_key] is not None:
        direct_planar_filters.append(
            stored_width.between(
                logical_query[width_key] - tolerance,
                logical_query[width_key] + tolerance,
            )
        )
    if logical_query[depth_key] is not None:
        direct_planar_filters.append(
            stored_depth.between(
                logical_query[depth_key] - tolerance,
                logical_query[depth_key] + tolerance,
            )
        )

    if direct_planar_filters:
        planar_filters = [and_(*direct_planar_filters)]
        if (
            query["allow_planar_rotation"]
            and logical_query[width_key] is not None
            and logical_query[depth_key] is not None
        ):
            planar_filters.append(
                and_(
                    stored_width.between(
                        logical_query[depth_key] - tolerance,
                        logical_query[depth_key] + tolerance,
                    ),
                    stored_depth.between(
                        logical_query[width_key] - tolerance,
                        logical_query[width_key] + tolerance,
                    ),
                )
            )
        filters.append(or_(*planar_filters))

    if logical_query[height_key] is not None:
        filters.append(
            stored_height.between(
                logical_query[height_key] - tolerance,
                logical_query[height_key] + tolerance,
            )
        )
    return and_(*filters) if filters else true()


def ready_candidate_response(
    _session: object,
    config: dict[str, Any],
    query: dict[str, Any],
    profile: FittingCandidateProfile,
) -> FittingCandidateRecallCandidateResponse | None:
    payload = candidate_payload(config, profile)
    if profile.candidate_type == "part" and is_sticker_part_payload(config, payload):
        return None
    key_match = fuzzy_name_match(config, query, payload)
    reasons = filter_reasons(config, query, payload, key_match)
    if reasons is None:
        return None
    score = candidate_score(config, query, profile, reasons, key_match)
    content = profile_source_content(profile)
    return FittingCandidateRecallCandidateResponse(
        candidateType=profile.candidate_type,
        candidateId=profile.candidate_id,
        profileStatus=profile.profile_status,
        source=config["response"]["ready_source"],
        score=score,
        scoreReasons=reasons,
        name=content["name"],
        description=content["description"],
        contentLocale=content["contentLocale"],
        translationStatus=content["translationStatus"],
        matchedName=key_match["value"] if key_match is not None else None,
        keyScore=key_match["score"] if key_match is not None else None,
        bbox=profile.bbox_json,
        logicalSize=profile.logical_size_json,
        appearanceTags=profile.appearance_tags_json,
        colorSummary=profile.color_summary_json,
        connectorSummary=profile.connector_summary_json,
        sourceMetadata=profile.source_metadata_json,
        profileError=(
            message(profile.profile_error_code, profile.profile_error_params_json)
            if profile.profile_error_code
            else None
        ),
        profileErrorType=None,
    )


def irregular_candidate_responses(
    session: object,
    config: dict[str, Any],
    query: dict[str, Any],
) -> list[FittingCandidateRecallCandidateResponse]:
    if config["irregular"]["candidate_type"] not in query["candidate_types"]:
        return []
    statement = (
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
    if query["key"] is not None:
        statement = statement.where(
            and_(
                *(
                    func.lower(LDrawPart.name).contains(token, autoescape=True)
                    for token in query["key"].split()
                )
            )
        )
    rows = session.execute(statement)
    responses = []
    for part, geometry, profile in rows:
        candidate = irregular_candidate_response(session, config, query, part, geometry, profile)
        if candidate is not None:
            responses.append(candidate)
    return responses


def irregular_candidate_response(
    _session: object,
    config: dict[str, Any],
    query: dict[str, Any],
    part: LDrawPart,
    geometry: LDrawPartGeometry,
    profile: LDrawPartShapeProfile,
) -> FittingCandidateRecallCandidateResponse | None:
    payload = irregular_candidate_payload(config, part, geometry)
    if is_sticker_part_payload(config, payload):
        return None
    key_match = fuzzy_name_match(config, query, payload)
    reasons = filter_reasons(config, query, payload, key_match)
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
        + key_match_score(config, key_match)
    )
    content = part_source_content(part)
    return FittingCandidateRecallCandidateResponse(
        candidateType=config["irregular"]["candidate_type"],
        candidateId=part.ldraw_part_num,
        profileStatus=profile.profile_status,
        source=config["irregular"]["source"],
        score=score,
        scoreReasons=reasons,
        name=content["name"],
        description=content["description"],
        contentLocale=content["contentLocale"],
        translationStatus=content["translationStatus"],
        matchedName=key_match["value"] if key_match is not None else None,
        keyScore=key_match["score"] if key_match is not None else None,
        bbox=payload["bbox"],
        logicalSize=payload["logical_size"],
        appearanceTags=payload["appearance_tags"],
        colorSummary=None,
        connectorSummary=None,
        sourceMetadata={
            config["json_keys"]["profile_error_type"]: profile.profile_error_type,
        },
        profileError=(
            message(profile.profile_error_code, profile.profile_error_params_json)
            if profile.profile_error_code
            else None
        ),
        profileErrorType=profile.profile_error_type,
    )


def profile_source_content(
    profile: FittingCandidateProfile,
) -> dict[str, Any]:
    metadata = profile.source_metadata_json or {}
    source_locale = metadata.get("contentLocale") or "en-US"
    appearance = profile.appearance_tags_json or {}
    content = {
        "name": appearance.get("name") or profile.candidate_id,
        "description": (
            appearance.get("remarks")
            if profile.candidate_type == "component"
            else None
        ),
        "contentLocale": source_locale,
        "translationStatus": "source",
    }
    if profile.candidate_type == "component":
        content["tags"] = appearance.get("tags") or []
    return content


def part_source_content(part: LDrawPart) -> dict[str, Any]:
    return {
        "name": part.name,
        "description": None,
        "contentLocale": part.content_locale,
        "translationStatus": "source",
    }


def normalize_type_text(value: str | None) -> str | None:
    return normalize_search_text(value)


def is_sticker_part_payload(
    config: dict[str, Any],
    payload: dict[str, Any],
) -> bool:
    part_filters = config["part_filters"]
    if not part_filters["exclude_stickers"]:
        return False
    appearance = payload.get("appearance_tags") or {}
    values = (
        appearance.get(config["json_keys"]["category"]),
        appearance.get(config["json_keys"]["name"]),
    )
    roots = tuple(part_filters["sticker_term_roots"])
    return any(
        token.startswith(roots)
        for value in values
        if isinstance(value, str)
        for token in (normalize_type_text(value) or "").split()
    )


def fuzzy_name_match(
    config: dict[str, Any],
    query: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    key = query["key"]
    if key is None:
        return None
    appearance = payload.get("appearance_tags") or {}
    value = appearance.get(config["json_keys"]["name"])
    if not isinstance(value, str) or normalize_search_text(value) is None:
        return None
    score = name_similarity(key, value)
    if score < config["fuzzy_key"]["minimum_score"]:
        return None
    return {"value": value, "score": round(score, 4)}


def name_similarity(query: str, candidate: str) -> float:
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


def payload_candidate_score(
    config: dict[str, Any],
    query: dict[str, Any],
    payload: dict[str, Any],
    reasons: list[str],
    key_match: dict[str, Any] | None,
) -> float:
    return (
        config["scoring"]["base_score"]
        - bbox_distance(config, query, payload) * config["scoring"]["bbox_weight"]
        - logical_size_distance(config, query, payload)
        * config["scoring"]["logical_size_weight"]
        + connector_score(config, query)
        + category_score(config, query)
        + color_score(config, query)
        + key_match_score(config, key_match)
        + len(reasons)
    )


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
    key_match: dict[str, Any] | None = None,
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
    if query["key"] is not None:
        if key_match is None:
            return None
        reasons.append(config["response"]["key_filter_reason"])
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
        if logical_query[query_key] is not None and logical_size[payload_key] is None:
            return False
    direct_match = all(
        logical_query[query_key] is None
        or abs(logical_size[payload_key] - logical_query[query_key]) <= tolerance
        for query_key, payload_key in logical_size_pairs(config)
    )
    if direct_match or not query["allow_planar_rotation"]:
        return direct_match
    width_key = config["json_keys"]["width_stud"]
    depth_key = config["json_keys"]["depth_stud"]
    if logical_query.get(width_key) is None or logical_query.get(depth_key) is None:
        return False
    return (
        abs(logical_size[width_key] - logical_query[depth_key]) <= tolerance
        and abs(logical_size[depth_key] - logical_query[width_key]) <= tolerance
        and (
            logical_query[config["json_keys"]["height_plate"]] is None
            or abs(
                logical_size[config["json_keys"]["height_plate"]]
                - logical_query[config["json_keys"]["height_plate"]]
            )
            <= tolerance
        )
    )


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
    key_match: dict[str, Any] | None = None,
) -> float:
    payload = candidate_payload(config, profile)
    return payload_candidate_score(config, query, payload, reasons, key_match)


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
    direct_distance = sum(
        abs(logical_size[payload_key] - logical_query[query_key])
        for query_key, payload_key in logical_size_pairs(config)
        if logical_query[query_key] is not None and logical_size[payload_key] is not None
    )
    if not query["allow_planar_rotation"]:
        return direct_distance
    width_key = config["json_keys"]["width_stud"]
    depth_key = config["json_keys"]["depth_stud"]
    query_width = logical_query.get(width_key)
    query_depth = logical_query.get(depth_key)
    candidate_width = logical_size.get(width_key)
    candidate_depth = logical_size.get(depth_key)
    if None in (query_width, query_depth, candidate_width, candidate_depth):
        return direct_distance
    planar_direct = abs(candidate_width - query_width) + abs(candidate_depth - query_depth)
    planar_rotated = abs(candidate_width - query_depth) + abs(candidate_depth - query_width)
    return direct_distance - planar_direct + min(planar_direct, planar_rotated)


def key_match_score(
    config: dict[str, Any],
    key_match: dict[str, Any] | None,
) -> float:
    if key_match is None:
        return 0.0
    return key_match["score"] * config["scoring"]["key_match_weight"]


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
