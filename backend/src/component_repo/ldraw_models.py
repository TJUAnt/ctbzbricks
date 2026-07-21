"""In-memory LDraw document structures for Component Repo."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LDrawTransform:
    """LDraw position and 3x3 orientation matrix in source coordinates."""

    position: tuple[float, float, float]
    matrix: tuple[float, float, float, float, float, float, float, float, float]

    def values(self) -> tuple[float, ...]:
        return self.position + self.matrix

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": {
                "x": self.position[0],
                "y": self.position[1],
                "z": self.position[2],
            },
            "matrix": list(self.matrix),
        }


@dataclass(frozen=True)
class LDrawReference:
    """A type 1 LDraw reference to either a leaf part or a submodel."""

    instance_id: str
    source_model_id: str
    source_line_no: int
    source_order: int
    color_code: str
    transform: LDrawTransform
    reference_name: str
    reference_kind: str
    target_model_id: str | None = None
    raw_line: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "instanceId": self.instance_id,
            "sourceModelId": self.source_model_id,
            "sourceLineNo": self.source_line_no,
            "sourceOrder": self.source_order,
            "colorCode": self.color_code,
            "transform": self.transform.to_dict(),
            "referenceName": self.reference_name,
            "referenceKind": self.reference_kind,
            "targetModelId": self.target_model_id,
            "rawLine": self.raw_line,
        }


@dataclass(frozen=True)
class LDrawModel:
    """One `0 FILE` section in an LDraw MPD document."""

    model_id: str
    source_name: str
    source_order: int
    start_line_no: int
    display_name: str | None = None
    meta_lines: tuple[str, ...] = field(default_factory=tuple)
    references: tuple[LDrawReference, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "modelId": self.model_id,
            "sourceName": self.source_name,
            "sourceOrder": self.source_order,
            "startLineNo": self.start_line_no,
            "displayName": self.display_name,
            "metaLines": list(self.meta_lines),
            "references": [reference.to_dict() for reference in self.references],
        }


@dataclass(frozen=True)
class LDrawParseIssue:
    """Non-fatal parser issue."""

    code: str
    severity: str
    params: dict[str, Any]
    path: tuple[str | int, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "params": self.params,
            "path": list(self.path),
        }


@dataclass(frozen=True)
class LDrawDocument:
    """Parsed LDraw/MPD document."""

    parser_version: str
    root_model_id: str | None
    models: tuple[LDrawModel, ...]
    parse_issues: tuple[LDrawParseIssue, ...] = field(default_factory=tuple)

    def leaf_part_references(self) -> list[LDrawReference]:
        return [
            reference
            for model in self.models
            for reference in model.references
            if reference.reference_kind == "part"
        ]

    def submodel_references(self) -> list[LDrawReference]:
        return [
            reference
            for model in self.models
            for reference in model.references
            if reference.reference_kind == "submodel"
        ]

    def bom(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for reference in self.leaf_part_references():
            key = reference.reference_name.lower()
            counts[key] = counts.get(key, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "parserVersion": self.parser_version,
            "rootModelId": self.root_model_id,
            "models": [model.to_dict() for model in self.models],
            "partInstances": [
                reference.to_dict() for reference in self.leaf_part_references()
            ],
            "submodelInstances": [
                reference.to_dict() for reference in self.submodel_references()
            ],
            "bom": self.bom(),
            "parseIssues": [issue.to_dict() for issue in self.parse_issues],
        }
