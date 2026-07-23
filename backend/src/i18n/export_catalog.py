"""Versioned server-side resources for deterministic localized exports."""

from __future__ import annotations

import json
import re
import unicodedata
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote

from src.i18n.messages import normalize_task_locale, normalize_timezone


EXPORT_CATALOG_VERSION = "brickbuilder-export-2026.07.18.1"
EXPORT_SCHEMA = "brickbuilder.export.v1"
_RESOURCE_ROOT = Path(__file__).with_name("export_resources")
_TOKEN_PATTERN = re.compile(r"\{([A-Za-z][A-Za-z0-9]*)\}")
_SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def create_export_context(locale: str, timezone: str) -> dict[str, str]:
    return {
        "locale": normalize_task_locale(locale),
        "timezone": normalize_timezone(timezone),
        "catalogVersion": EXPORT_CATALOG_VERSION,
    }


def validate_export_context(context: dict[str, Any]) -> dict[str, str]:
    catalog_version = str(context.get("catalogVersion", ""))
    if catalog_version != EXPORT_CATALOG_VERSION:
        raise ValueError("export.catalog_version_unsupported")
    return {
        "locale": normalize_task_locale(str(context.get("locale", ""))),
        "timezone": normalize_timezone(str(context.get("timezone", ""))),
        "catalogVersion": catalog_version,
    }


def export_text(context: dict[str, Any], key: str, **params: Any) -> str:
    normalized = validate_export_context(context)
    value: Any = _catalog(normalized["locale"])
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(f"Unknown export resource: {normalized['locale']}:{key}")
        value = value[part]
    if not isinstance(value, str):
        raise TypeError(f"Export resource is not text: {normalized['locale']}:{key}")
    expected = set(_TOKEN_PATTERN.findall(value))
    supplied = set(params)
    if expected != supplied:
        raise ValueError(f"Export resource parameters differ for {key}: {expected} != {supplied}")
    return value.format(**params)


def export_document(context: dict[str, Any], kind: str) -> dict[str, Any]:
    normalized = validate_export_context(context)
    catalog = _catalog(normalized["locale"])
    return {
        "schema": EXPORT_SCHEMA,
        **normalized,
        "kind": kind,
        "title": export_text(normalized, f"documents.{kind}.title"),
        "description": export_text(normalized, f"documents.{kind}.description"),
        "sections": deepcopy(catalog["sections"]),
        "fields": deepcopy(catalog["fields"]),
    }


def localized_filename(context: dict[str, Any], kind: str, **params: Any) -> str:
    safe_params = {
        key: re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "-", str(value)).strip("-.") or "export"
        for key, value in params.items()
    }
    filename = export_text(context, f"filenames.{kind}", **safe_params)
    if any(character in filename for character in "\\/:*?\"<>|"):
        raise ValueError("export.filename_unsafe")
    if filename in {".", ".."} or not filename.strip():
        raise ValueError("export.filename_unsafe")
    return filename


def content_disposition(filename: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    ascii_name = _SAFE_FILENAME_PATTERN.sub("-", ascii_name).strip("-.") or "download"
    extension = Path(filename).suffix
    if extension and not ascii_name.endswith(extension):
        ascii_name += extension
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(filename)}'


def localize_lego_plan(plan: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    localized = deepcopy(plan)
    localized["document"] = export_document(context, "legoDesignPlan")
    layer_keys = {
        "blackSupport": "layers.blackSupport",
        "whiteBase": "layers.whiteBase",
        "topDesign": "layers.topDesign",
    }
    for layer in localized.get("layers", []):
        key = layer_keys.get(layer.get("id"))
        if key:
            layer["name"] = export_text(context, key)
    for step in localized.get("steps", []):
        step["name"] = localized_step_name(step, context, "lego")
    for submodel in localized.get("submodels", []):
        for step in submodel.get("steps", []):
            step["name"] = localized_step_name(step, context, "lego")
    return localized


def localize_dem_design(dem_design: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    localized = deepcopy(dem_design)
    localized["exportContext"] = validate_export_context(context)
    for step in localized.get("steps", []):
        step["name"] = localized_step_name(step, context, "dem")
    return localized


def dem_design_report(dem_design: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return {
        "document": export_document(context, "demDesignReport"),
        "design": localize_dem_design(dem_design, context),
    }


def localized_step_name(step: dict[str, Any], context: dict[str, Any], family: str) -> str:
    name = str(step.get("name", ""))
    if family == "dem":
        stage_keys = {
            "base": "steps.supportBase",
            "structure": "steps.structure",
            "surface-connected": "steps.surfaceConnected",
            "surface-finished": "steps.surfaceFinished",
            "surface-supplement": "steps.surfaceSupplement",
            "surface-fill": "steps.surfaceFill",
        }
        key = stage_keys.get(str(step.get("stage", step.get("layer", ""))))
        if key == "steps.supportBase":
            return export_text(context, key, index=_trailing_number(step.get("id"), 1))
        if key:
            return export_text(context, key, basePlate=step.get("basePlate", 0))
    layer = str(step.get("layer", ""))
    if layer == "base" or str(step.get("id", "")).startswith("base-"):
        return export_text(context, "steps.pixelBase", index=_trailing_number(step.get("id"), 1))
    if layer == "top" or str(step.get("id", "")).startswith("top-"):
        match = re.search(r"(-?\d+)\D+(-?\d+)$", name)
        start, end = match.groups() if match else (0, 0)
        return export_text(context, "steps.pixelTop", start=start, end=end)
    if "-" in str(step.get("id", "")):
        module_id, stage = str(step["id"]).rsplit("-", 1)
        stage_key = f"terrainStages.{stage}"
        try:
            stage_name = export_text(context, stage_key)
        except KeyError:
            return name
        return export_text(context, "steps.terrainModule", moduleId=module_id, stage=stage_name)
    return name


def _trailing_number(value: Any, fallback: int) -> int:
    match = re.search(r"(\d+)$", str(value or ""))
    return int(match.group(1)) if match else fallback


@lru_cache(maxsize=None)
def _catalog(locale: str) -> dict[str, Any]:
    path = _RESOURCE_ROOT / f"{locale}.json"
    with path.open(encoding="utf-8") as resource:
        catalog = json.load(resource)
    if catalog.get("catalogVersion") != EXPORT_CATALOG_VERSION:
        raise ValueError("export.catalog_version_invalid")
    return catalog
