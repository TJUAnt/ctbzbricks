"""Pure parser materialization used by the Go-owned Component Repo task pipeline."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from src.component_repo.ldraw_deserializer import deserialize_ldraw_document


MAX_STUDIO_EXCHANGE_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True)
class MaterializedImport:
    document: dict[str, Any]
    bom: dict[str, int]
    parse_issues: list[dict[str, Any]]
    root_model_id: str | None
    summary: dict[str, Any]
    interface_signature: str
    structure_hash: str
    geometry_hash: str
    exchange_bytes: bytes | None = None
    exchange_filename: str | None = None


class ImportParseError(ValueError):
    """Expected invalid source content; the public task stores only its stable code."""


def materialize_import(
    content: bytes,
    artifact_type: str,
    original_filename: str,
    config: dict[str, Any],
) -> MaterializedImport:
    exchange_bytes: bytes | None = None
    exchange_filename: str | None = None
    if artifact_type == config["artifacts"]["studio_io"]:
        exchange_bytes = extract_studio_exchange(content)
        exchange_filename = f"{Path(original_filename).stem}.ldr"
        parse_bytes = exchange_bytes
    elif artifact_type in {
        config["artifacts"]["ldraw_ldr"],
        config["artifacts"]["ldraw_mpd"],
    }:
        parse_bytes = content
    else:
        raise ImportParseError("unsupported artifact type")

    try:
        source_text = parse_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ImportParseError("invalid LDraw encoding") from error
    try:
        parsed = deserialize_ldraw_document(source_text, config)
    except (KeyError, TypeError, ValueError) as error:
        raise ImportParseError("invalid LDraw document") from error

    document = parsed.to_dict()
    bom = parsed.bom()
    issues = [issue.to_dict() for issue in parsed.parse_issues]
    return MaterializedImport(
        document=document,
        bom=bom,
        parse_issues=issues,
        root_model_id=parsed.root_model_id,
        summary={
            "modelCount": len(parsed.models),
            "partInstanceCount": len(parsed.leaf_part_references()),
            "submodelInstanceCount": len(parsed.submodel_references()),
            "bom": bom,
            "parseIssueCount": len(issues),
        },
        interface_signature=stable_hash([]),
        structure_hash=stable_hash(document),
        geometry_hash=stable_hash(geometry_projection(document)),
        exchange_bytes=exchange_bytes,
        exchange_filename=exchange_filename,
    )


def extract_studio_exchange(content: bytes) -> bytes:
    try:
        with ZipFile(BytesIO(content)) as archive:
            member = archive.getinfo("model.ldr")
            if member.file_size > MAX_STUDIO_EXCHANGE_BYTES:
                raise ImportParseError("Studio exchange is too large")
            return archive.read(member)
    except (BadZipFile, KeyError) as error:
        raise ImportParseError("Studio archive does not contain model.ldr") from error


def geometry_projection(document: dict[str, Any]) -> list[dict[str, Any]]:
    projection = []
    for model in document.get("models", []):
        for reference in model.get("references", []):
            projection.append(
                {
                    "sourceModelId": reference.get("sourceModelId"),
                    "sourceOrder": reference.get("sourceOrder"),
                    "referenceName": reference.get("referenceName"),
                    "referenceKind": reference.get("referenceKind"),
                    "targetModelId": reference.get("targetModelId"),
                    "transform": reference.get("transform"),
                }
            )
    return projection


def stable_hash(payload: Any) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
