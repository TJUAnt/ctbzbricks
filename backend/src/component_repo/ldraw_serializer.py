"""Serialize Component Repo LDraw memory structures back to LDraw/MPD text."""

from __future__ import annotations

from typing import Any

from src.component_repo.ldraw_models import LDrawDocument, LDrawModel, LDrawReference


def serialize_ldraw_document(document: LDrawDocument, config: dict[str, Any]) -> str:
    """Serialize an LDraw document while preserving source coordinates."""
    ldraw = config["ldraw"]
    lines: list[str] = []
    for model in document.models:
        lines.extend(serialize_model(model, ldraw))
    return ldraw["line_separator"].join(lines) + ldraw["line_separator"]


def serialize_model(model: LDrawModel, ldraw: dict[str, Any]) -> list[str]:
    lines = [f"0 FILE {model.source_name}"]
    if model.display_name and not contains_name_meta(model.meta_lines, ldraw):
        lines.append(f"0 Name: {model.display_name}")
    for meta_line in model.meta_lines:
        stripped = meta_line.strip()
        if stripped.startswith(ldraw["file_meta_prefix"]) or stripped == ldraw["nofile_meta"]:
            continue
        lines.append(meta_line)
    for reference in sorted(model.references, key=lambda item: item.source_order):
        lines.append(serialize_reference(reference))
    lines.append(ldraw["nofile_meta"])
    return lines


def contains_name_meta(meta_lines: tuple[str, ...], ldraw: dict[str, Any]) -> bool:
    return any(line.strip().startswith(ldraw["name_meta_prefix"]) for line in meta_lines)


def serialize_reference(reference: LDrawReference) -> str:
    values = [format_ldraw_number(value) for value in reference.transform.values()]
    return " ".join(
        [
            "1",
            reference.color_code,
            *values,
            reference.reference_name,
        ]
    )


def format_ldraw_number(value: float) -> str:
    if value == 0:
        value = 0.0
    return f"{value:.6f}"
