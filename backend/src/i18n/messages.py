"""Structured task messages and normalized locale context."""

from __future__ import annotations

import re
import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


MACHINE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$")
_CATALOG_PATH = Path(__file__).resolve().parents[2] / "config" / "i18n.json"


@lru_cache(maxsize=1)
def locale_catalog() -> dict[str, Any]:
    with _CATALOG_PATH.open(encoding="utf-8") as catalog_file:
        return json.load(catalog_file)


SUPPORTED_LOCALES = tuple(locale_catalog()["product_locales"])


def normalize_locale_for_catalog(
    locale: str,
    supported_locales: tuple[str, ...] | list[str],
    aliases: Mapping[str, str] | None = None,
) -> str:
    normalized = locale.strip().replace("_", "-").lower()
    exact = next(
        (candidate for candidate in supported_locales if candidate.lower() == normalized),
        None,
    )
    if exact:
        return exact
    for prefix, target in sorted((aliases or {}).items(), key=lambda item: -len(item[0])):
        normalized_prefix = prefix.lower()
        if normalized == normalized_prefix or normalized.startswith(f"{normalized_prefix}-"):
            if target in supported_locales:
                return target
    language = normalized.split("-", 1)[0]
    candidates = [
        candidate
        for candidate in supported_locales
        if candidate.lower().split("-", 1)[0] == language
    ]
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError("request.locale_unsupported")


def normalize_task_locale(locale: str) -> str:
    catalog = locale_catalog()
    return normalize_locale_for_catalog(
        locale,
        SUPPORTED_LOCALES,
        catalog["locale_aliases"],
    )


def normalize_timezone(timezone_name: str) -> str:
    value = timezone_name.strip()
    if not value:
        raise ValueError("request.timezone_invalid")
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
        raise ValueError("request.timezone_invalid") from error
    return value


def message(code: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not MACHINE_CODE_PATTERN.fullmatch(code):
        raise ValueError(f"Invalid structured message code: {code!r}")
    return {"code": code, "params": dict(params or {})}


def progress(percent: int | float, code: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
    bounded_percent = max(0, min(100, round(percent)))
    return {
        "percent": bounded_percent,
        **message(code, {"percent": bounded_percent, **dict(params or {})}),
    }


def error_from_exception(
    error: Exception,
    fallback_code: str,
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    code = getattr(error, "code", None)
    error_params = getattr(error, "params", None)
    if isinstance(code, str) and MACHINE_CODE_PATTERN.fullmatch(code):
        return message(code, error_params if isinstance(error_params, Mapping) else params)
    candidate = str(error)
    if MACHINE_CODE_PATTERN.fullmatch(candidate):
        return message(candidate, params)
    return message(fallback_code, params)
