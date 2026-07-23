"""Stable, queryable search fields derived from candidate profile content."""

from __future__ import annotations

import re
from typing import Any, Iterable


STANDARD_CANDIDATE_TYPES = ("slope", "tile", "plate")
STICKER_TERM_ROOTS = ("sticker", "decal")


def normalize_search_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(
        re.findall(r"[\w]+", value.casefold(), flags=re.UNICODE)
    ).strip()
    return normalized or None


def normalized_candidate_type(values: Iterable[str | None]) -> str | None:
    normalized_values = [
        normalized
        for value in values
        if (normalized := normalize_search_text(value)) is not None
    ]
    for value in normalized_values:
        for token in value.split():
            for candidate_type in STANDARD_CANDIDATE_TYPES:
                if token == candidate_type or token.startswith(candidate_type):
                    return candidate_type
    return None


def is_sticker_candidate(values: Iterable[str | None]) -> bool:
    return any(
        token.startswith(STICKER_TERM_ROOTS)
        for value in values
        if isinstance(value, str)
        for token in (normalize_search_text(value) or "").split()
    )


def persisted_search_fields(
    candidate_type: str,
    logical_size_json: dict[str, Any],
    appearance_tags_json: dict[str, Any],
) -> dict[str, Any]:
    logical_size = logical_size_json.get("logicalSize") or {}
    appearance_values = (
        appearance_tags_json.get("category"),
        appearance_tags_json.get("name"),
        appearance_tags_json.get("remarks"),
        *(appearance_tags_json.get("tags") or []),
    )
    return {
        "width_stud": logical_size.get("widthStud"),
        "depth_stud": logical_size.get("depthStud"),
        "height_plate": logical_size.get("heightPlate"),
        "is_sticker": candidate_type == "part" and is_sticker_candidate(appearance_values),
        "normalized_type": normalized_candidate_type(appearance_values),
    }
