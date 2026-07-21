"""Deserialize LDraw/MPD text into Component Repo memory structures."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from src.component_repo.ldraw_models import (
    LDrawDocument,
    LDrawModel,
    LDrawParseIssue,
    LDrawReference,
    LDrawTransform,
)


def deserialize_ldraw_document(content: str, config: dict[str, Any]) -> LDrawDocument:
    """Parse LDraw/MPD content without changing source coordinates."""
    ldraw = config["ldraw"]
    parser_version = ldraw["parser_version"]
    lines = normalized_lines(content)
    models: list[dict[str, Any]] = []
    issues: list[LDrawParseIssue] = []
    current_model: dict[str, Any] | None = None
    reference_counter = 0

    for line_no, raw_line in enumerate(lines, start=ldraw["line_number_start"]):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(ldraw["file_meta_prefix"]):
            if current_model is not None:
                models.append(current_model)
            source_name = line.removeprefix(ldraw["file_meta_prefix"]).strip()
            current_model = {
                "source_name": source_name or ldraw["default_model_name"],
                "start_line_no": line_no,
                "meta_lines": [raw_line],
                "references": [],
                "display_name": None,
            }
            continue
        if line == ldraw["nofile_meta"]:
            if current_model is not None:
                current_model["meta_lines"].append(raw_line)
                models.append(current_model)
                current_model = None
            continue
        if current_model is None:
            current_model = {
                "source_name": ldraw["default_model_name"],
                "start_line_no": line_no,
                "meta_lines": [],
                "references": [],
                "display_name": None,
            }
        if line.startswith(ldraw["name_meta_prefix"]):
            current_model["display_name"] = line.removeprefix(ldraw["name_meta_prefix"]).strip()
            current_model["meta_lines"].append(raw_line)
            continue
        tokens = line.split()
        if not tokens:
            continue
        if tokens[0] == ldraw["part_line_type"]:
            reference_counter += 1
            reference = parse_type1_reference(
                ldraw,
                current_model_id_placeholder(current_model, len(models), ldraw),
                line_no,
                reference_counter,
                raw_line,
                tokens,
                issues,
            )
            if reference is not None:
                current_model["references"].append(reference)
            continue
        if tokens[0] == ldraw["studio_v2_line_type"]:
            issues.append(
                parse_issue(ldraw["issues"]["unsupported_line_type"], line_no)
            )
            current_model["meta_lines"].append(raw_line)
            continue
        current_model["meta_lines"].append(raw_line)

    if current_model is not None:
        issues.append(
            parse_issue(ldraw["issues"]["unclosed_model"], current_model["start_line_no"])
        )
        models.append(current_model)

    materialized_models = materialize_models(models, ldraw, issues)
    model_lookup = model_name_lookup(materialized_models, ldraw, issues)
    classified_models = classify_references(materialized_models, model_lookup)
    return LDrawDocument(
        parser_version=parser_version,
        root_model_id=classified_models[0].model_id if classified_models else None,
        models=tuple(classified_models),
        parse_issues=tuple(issues),
    )


def normalized_lines(content: str) -> list[str]:
    return content.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff").split("\n")


def current_model_id_placeholder(
    current_model: dict[str, Any],
    model_index: int,
    ldraw: dict[str, Any],
) -> str:
    return f"{ldraw['model_id_prefix']}_{model_index + 1:04d}"


def parse_type1_reference(
    ldraw: dict[str, Any],
    source_model_id: str,
    line_no: int,
    reference_counter: int,
    raw_line: str,
    tokens: list[str],
    issues: list[LDrawParseIssue],
) -> LDrawReference | None:
    if len(tokens) < ldraw["type1_token_count"]:
        issues.append(
            parse_issue(ldraw["issues"]["invalid_type1_line"], line_no)
        )
        return None
    try:
        values = tuple(float(token) for token in tokens[2:14])
    except ValueError:
        issues.append(
            parse_issue(ldraw["issues"]["invalid_type1_line"], line_no)
        )
        return None
    reference_name = " ".join(tokens[14:]).strip()
    return LDrawReference(
        instance_id=f"{ldraw['part_instance_id_prefix']}_{reference_counter:06d}",
        source_model_id=source_model_id,
        source_line_no=line_no,
        source_order=reference_counter,
        color_code=tokens[1],
        transform=LDrawTransform(position=values[:3], matrix=values[3:]),
        reference_name=reference_name,
        reference_kind="unresolved",
        target_model_id=None,
        raw_line=raw_line,
    )


def materialize_models(
    raw_models: list[dict[str, Any]],
    ldraw: dict[str, Any],
    issues: list[LDrawParseIssue],
) -> list[LDrawModel]:
    materialized = []
    seen_names: set[str] = set()
    for index, raw_model in enumerate(raw_models, start=1):
        source_name = raw_model["source_name"]
        normalized_name = normalize_reference_name(source_name)
        if normalized_name in seen_names:
            issues.append(
                parse_issue(
                    ldraw["issues"]["duplicate_model_name"],
                    raw_model["start_line_no"],
                    {"modelName": source_name},
                )
            )
        seen_names.add(normalized_name)
        model_id = f"{ldraw['model_id_prefix']}_{index:04d}"
        materialized.append(
            LDrawModel(
                model_id=model_id,
                source_name=source_name,
                source_order=index,
                start_line_no=raw_model["start_line_no"],
                display_name=raw_model["display_name"],
                meta_lines=tuple(raw_model["meta_lines"]),
                references=tuple(
                    replace(reference, source_model_id=model_id)
                    for reference in raw_model["references"]
                ),
            )
        )
    return materialized


def model_name_lookup(
    models: list[LDrawModel],
    ldraw: dict[str, Any],
    issues: list[LDrawParseIssue],
) -> dict[str, list[LDrawModel]]:
    lookup: dict[str, list[LDrawModel]] = {}
    for model in models:
        key = normalize_reference_name(model.source_name)
        lookup.setdefault(key, []).append(model)
    return lookup


def classify_references(
    models: list[LDrawModel],
    lookup: dict[str, list[LDrawModel]],
) -> list[LDrawModel]:
    classified = []
    for model in models:
        references = []
        for reference in model.references:
            target_model = resolve_submodel_reference(model, reference, lookup)
            if target_model is None:
                references.append(
                    replace(
                        reference,
                        instance_id=reference.instance_id.replace("part_", "part_"),
                        reference_kind="part",
                        target_model_id=None,
                    )
                )
            else:
                references.append(
                    replace(
                        reference,
                        instance_id=reference.instance_id.replace("part_", "submodel_"),
                        reference_kind="submodel",
                        target_model_id=target_model.model_id,
                    )
                )
        classified.append(replace(model, references=tuple(references)))
    return classified


def resolve_submodel_reference(
    source_model: LDrawModel,
    reference: LDrawReference,
    lookup: dict[str, list[LDrawModel]],
) -> LDrawModel | None:
    candidates = lookup.get(normalize_reference_name(reference.reference_name), [])
    if not candidates:
        return None
    for candidate in candidates:
        if candidate.source_order > source_model.source_order:
            return candidate
    for candidate in candidates:
        if candidate.model_id != source_model.model_id:
            return candidate
    return None


def normalize_reference_name(value: str) -> str:
    return value.strip().lower()


def parse_issue(
    issue_type: str,
    line_no: int,
    params: dict[str, Any] | None = None,
) -> LDrawParseIssue:
    return LDrawParseIssue(
        code=f"component_repo.parse.{issue_type}",
        severity="warning",
        params={"line": line_no, **dict(params or {})},
        path=("lines", line_no),
    )
