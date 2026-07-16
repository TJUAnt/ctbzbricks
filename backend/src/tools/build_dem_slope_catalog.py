"""Build a complete DEM capability catalog for database LDraw slope parts."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.config.app_settings import BACKEND_ROOT, load_json_config
from src.config.db_config import get_db_url
from src.ldraw.mesh import collect_ldraw_mesh
from src.ldraw.surface_profile import build_part_surface_profile
from src.model.models import (
    DemSlopeCandidate,
    LDrawFile,
    LDrawPart,
    LDrawPartGeometry,
    PartRelationship,
    XrefPartNumber,
)
from src.services.dem_slope_catalog_service import (
    classify_surface_family,
    profile_capability,
    profile_geometry_signature,
    surface_traits,
)


REQUIRED_CONFIG_KEYS = (
    "source",
    "classification",
    "recommendation",
    "database",
    "output",
)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    return parser.parse_args()


def nested_value(payload: dict[str, Any], key_path: list[str]) -> Any:
    value: Any = payload
    for key in key_path:
        value = value[key]
    return value


def load_current_candidate_ids(config: dict[str, Any]) -> set[str]:
    config_path = BACKEND_ROOT.parent / config["source"]["current_candidate_config_path"]
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    return set(nested_value(payload, config["source"]["current_candidate_key_path"]))


def part_flags(
    part_id: str,
    name: str,
    has_printed_relationship: bool,
    config: dict[str, Any],
) -> dict[str, bool]:
    patterns = config["classification"]["part_flags"]
    return {
        "obsolete": re.search(patterns["obsolete_pattern"], name, re.IGNORECASE) is not None,
        "moved": re.search(patterns["moved_pattern"], name, re.IGNORECASE) is not None,
        "printedVariant": has_printed_relationship
        or re.search(patterns["printed_name_pattern"], name, re.IGNORECASE) is not None
        or re.search(patterns["printed_part_id_pattern"], part_id, re.IGNORECASE) is not None,
        "stickerVariant": re.search(patterns["sticker_name_pattern"], name, re.IGNORECASE) is not None
        or re.search(patterns["sticker_part_id_pattern"], part_id, re.IGNORECASE) is not None,
        "shortcutAssembly": re.search(
            patterns["shortcut_assembly_name_pattern"],
            name,
            re.IGNORECASE,
        )
        is not None
        or re.search(
            patterns["shortcut_assembly_part_id_pattern"],
            part_id,
            re.IGNORECASE,
        )
        is not None,
    }


def canonical_rank(part: dict[str, Any], current_candidate_ids: set[str]) -> tuple:
    flags = part["flags"]
    return (
        flags["obsolete"],
        flags["moved"],
        flags["printedVariant"],
        flags["stickerVariant"],
        flags["shortcutAssembly"],
        part["partId"] not in current_candidate_ids,
        len(part["partId"]),
        part["partId"],
    )


def capability_eligible(part: dict[str, Any]) -> bool:
    flags = part["flags"]
    return (
        part["status"] == "profiled"
        and not flags["obsolete"]
        and not flags["moved"]
        and not flags["printedVariant"]
        and not flags["stickerVariant"]
        and not flags["shortcutAssembly"]
    )


def group_id(signature: str, config: dict[str, Any]) -> str:
    classification = config["classification"]
    digest = hashlib.new(
        classification["group_hash_algorithm"],
        signature.encode("utf-8"),
    ).hexdigest()
    return classification["group_id_prefix"] + digest[: classification["group_id_length"]]


def catalog_source_hash(
    part: dict[str, Any],
    capability: dict[str, Any] | None,
    config: dict[str, Any],
) -> str:
    payload = json.dumps(
        {"part": part, "capability": capability},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.new(
        config["classification"]["group_hash_algorithm"],
        payload.encode("utf-8"),
    ).hexdigest()


def catalog_candidate_enabled(
    part: dict[str, Any],
    capability: dict[str, Any] | None,
    config: dict[str, Any],
) -> bool:
    excluded_families = config["recommendation"]["excluded_families"]
    return (
        part["capabilityEligible"]
        and capability is not None
        and capability["family"] not in excluded_families
        and not any(
            trait in excluded_families
            for trait in surface_traits(part["name"], config["classification"])
        )
    )


def catalog_candidate_rows(
    catalog: dict[str, Any],
    ldraw_part_ids: dict[str, int],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    groups = {group["groupId"]: group for group in catalog["groups"]}
    missing_part_ids = sorted(
        part["partId"]
        for part in catalog["parts"]
        if part["partId"] not in ldraw_part_ids
    )
    if missing_part_ids:
        raise ValueError(
            config["database"]["errors"]["missing_ldraw_parts"].format(
                part_ids=", ".join(missing_part_ids)
            )
        )

    rows = []
    for part in catalog["parts"]:
        capability = groups.get(part.get("groupId"))
        rows.append(
            {
                "ldraw_part_id": ldraw_part_ids[part["partId"]],
                "candidate_enabled": catalog_candidate_enabled(part, capability, config),
                "catalog_status": part["status"],
                "current_candidate": part["currentCandidate"],
                "capability_eligible": part["capabilityEligible"],
                "family": None if capability is None else capability["family"],
                "group_id": part.get("groupId"),
                "flags_json": part["flags"],
                "database_geometry_json": part["databaseGeometry"],
                "capability_json": capability,
                "catalog_payload_json": part,
                "source_hash": catalog_source_hash(part, capability, config),
            }
        )
    return rows


def synchronize_candidates(
    session: Session,
    catalog: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, int]:
    ldraw_part_ids = dict(
        session.execute(select(LDrawPart.ldraw_part_num, LDrawPart.id)).all()
    )
    rows = catalog_candidate_rows(catalog, ldraw_part_ids, config)
    existing = {
        candidate.ldraw_part_id: candidate
        for candidate in session.scalars(select(DemSlopeCandidate)).all()
    }
    catalog_part_ids = {row["ldraw_part_id"] for row in rows}
    inserted_count = 0
    updated_count = 0
    for row in rows:
        candidate = existing.get(row["ldraw_part_id"])
        if candidate is None:
            session.add(DemSlopeCandidate(**row))
            inserted_count += 1
            continue
        for key, value in row.items():
            setattr(candidate, key, value)
        updated_count += 1

    removed_count = 0
    for ldraw_part_id, candidate in existing.items():
        if ldraw_part_id not in catalog_part_ids:
            session.delete(candidate)
            removed_count += 1
    session.commit()
    return {
        "inserted": inserted_count,
        "updated": updated_count,
        "removed": removed_count,
    }


def profile_parts(config: dict[str, Any], dem_config: dict[str, Any]) -> list[dict[str, Any]]:
    source = config["source"]
    profile_config = dem_config["surface_profile"]
    ldraw_root = Path(profile_config["ldraw_root"])
    engine = create_engine(get_db_url(), echo=False)
    with Session(engine) as session:
        rows = session.execute(
            select(LDrawPart, LDrawPartGeometry)
            .join(LDrawPartGeometry, LDrawPartGeometry.ldraw_part_id == LDrawPart.id)
            .where(LDrawPart.category == source["category"])
            .where(LDrawPartGeometry.geometry_status == source["geometry_status"])
            .order_by(LDrawPart.ldraw_part_num)
        ).all()
        relative_paths = session.scalars(select(LDrawFile.relative_path)).all()
        printed_part_ids = set(
            session.scalars(
                select(XrefPartNumber.ldraw_part_num)
                .join(
                    PartRelationship,
                    PartRelationship.part_num == XrefPartNumber.rebrickable_part_num,
                )
                .where(
                    PartRelationship.rel_type == source["printed_relationship_type"],
                    XrefPartNumber.relation_type == source["printed_xref_relation"],
                    XrefPartNumber.ldraw_part_num.is_not(None),
                )
                .distinct()
            ).all()
        )
    files = {relative_path: ldraw_root / Path(relative_path) for relative_path in relative_paths}
    records = []
    progress_interval = config["output"]["progress_interval"]
    for index, (part, geometry) in enumerate(rows, start=1):
        name = part.name or ""
        record = {
            "partId": part.ldraw_part_num,
            "name": name,
            "category": part.category,
            "relativePath": part.relative_path,
            "databaseGeometry": {
                "widthStud": geometry.logical_width_stud,
                "depthStud": geometry.logical_depth_stud,
                "heightPlate": geometry.logical_height_plate,
            },
            "flags": part_flags(
                part.ldraw_part_num,
                name,
                part.ldraw_part_num in printed_part_ids,
                config,
            ),
        }
        mesh = collect_ldraw_mesh(part.relative_path, files, profile_config["mesh"])
        if mesh.errors:
            record.update({"status": "mesh_error", "errors": list(mesh.errors)})
        else:
            try:
                profile = build_part_surface_profile(
                    part.ldraw_part_num,
                    mesh.surface_triangles,
                    mesh.triangles,
                    mesh.top_connection_origins,
                    profile_config["sampling"],
                )
            except ValueError as error:
                record.update({"status": "profile_error", "errors": [str(error)]})
            else:
                record.update(
                    {
                        "status": "profiled",
                        "profile": profile,
                        "geometrySignature": profile_geometry_signature(
                            profile,
                            config["classification"],
                        ),
                    }
                )
        records.append(record)
        if index % progress_interval == 0 or index == len(rows):
            print(f"profiled {index}/{len(rows)}", flush=True)
    return records


def build_groups(
    parts: list[dict[str, Any]],
    current_candidate_ids: set[str],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for part in parts:
        if capability_eligible(part):
            grouped.setdefault(part["geometrySignature"], []).append(part)
    groups = []
    classification = config["classification"]
    for signature, members in grouped.items():
        ordered_members = sorted(members, key=lambda part: canonical_rank(part, current_candidate_ids))
        canonical = ordered_members[0]
        capability = profile_capability(canonical["profile"], classification)
        family = classify_surface_family(
            canonical["name"],
            capability["heightRangePlate"],
            classification,
        )
        identifier = group_id(signature, config)
        for member in members:
            member["groupId"] = identifier
        groups.append(
            {
                "groupId": identifier,
                "family": family,
                "traits": surface_traits(canonical["name"], classification),
                "canonicalPartId": canonical["partId"],
                "canonicalName": canonical["name"],
                "currentCandidate": any(member["partId"] in current_candidate_ids for member in members),
                "memberPartIds": [member["partId"] for member in ordered_members],
                **capability,
            }
        )
    return sorted(
        groups,
        key=lambda group: (
            group["family"],
            group["footprint"]["widthStud"] * group["footprint"]["depthStud"],
            group["canonicalPartId"],
        ),
    )


def public_part(part: dict[str, Any], current_candidate_ids: set[str]) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "partId": part["partId"],
            "name": part["name"],
            "category": part["category"],
            "relativePath": part["relativePath"],
            "status": part["status"],
            "groupId": part.get("groupId"),
            "currentCandidate": part["partId"] in current_candidate_ids,
            "capabilityEligible": capability_eligible(part),
            "flags": part["flags"],
            "databaseGeometry": part["databaseGeometry"],
            "errors": part.get("errors"),
        }.items()
        if value is not None
    }


def recommended_groups(groups: list[dict[str, Any]], config: dict[str, Any]) -> list[str]:
    recommendation = config["recommendation"]
    return [
        group["groupId"]
        for group in groups
        if not group["currentCandidate"]
        and group["family"] not in recommendation["excluded_families"]
        and group["footprint"]["widthStud"] * group["footprint"]["depthStud"]
        <= recommendation["maximum_area_stud"]
    ]


def build_catalog(
    parts: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    current_candidate_ids: set[str],
    config: dict[str, Any],
) -> dict[str, Any]:
    status_counts = Counter(part["status"] for part in parts)
    family_counts = Counter(group["family"] for group in groups)
    slope_part_ids = {part["partId"] for part in parts}
    covered_group_ids = {group["groupId"] for group in groups if group["currentCandidate"]}
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": {
            "databaseCategory": config["source"]["category"],
            "partCount": len(parts),
            "profiledPartCount": status_counts["profiled"],
            "capabilityEligiblePartCount": sum(capability_eligible(part) for part in parts),
            "profileErrorCount": status_counts["profile_error"],
            "meshErrorCount": status_counts["mesh_error"],
        },
        "matchingContract": {
            "targetSurfaceRule": "targetSurfacePlate = basePlate + sampleSurfacePlate",
            "baseHRule": "BaseH equals the selected candidate basePlate over its occupied footprint",
            "colorRule": "Every occupied stud of one candidate must use one colorId",
            "rotationRule": "Every unique 0/90/180/270-degree sampled state is listed",
        },
        "summary": {
            "geometryGroupCount": len(groups),
            "familyGroupCounts": dict(sorted(family_counts.items())),
            "currentConfiguredPartCount": len(current_candidate_ids),
            "currentSlopePartCount": len(current_candidate_ids & slope_part_ids),
            "currentCoveredGeometryGroupCount": len(covered_group_ids),
            "currentCandidateIdsOutsideSlope": sorted(current_candidate_ids - slope_part_ids),
            "recommendedGeometryGroupIds": recommended_groups(groups, config),
        },
        "groups": groups,
        "parts": [public_part(part, current_candidate_ids) for part in parts],
    }


def range_text(cell_range: dict[str, float] | None) -> str:
    if cell_range is None:
        return "-"
    minimum = cell_range["minimum"]
    maximum = cell_range["maximum"]
    return str(minimum) if minimum == maximum else f"{minimum}..{maximum}"


def state_text(state: dict[str, Any]) -> str:
    rows = [
        ",".join(range_text(cell_range) for cell_range in row)
        for row in state["cellHeightRangesPlate"]
    ]
    return f"{state['rotationDegrees']}deg:" + "/".join(rows)


def markdown_catalog(catalog: dict[str, Any], config: dict[str, Any]) -> str:
    source = catalog["source"]
    summary = catalog["summary"]
    lines = [
        f"# {config['output']['markdown_title']}",
        "",
        "## Scope",
        "",
        f"- Database category: `{source['databaseCategory']}`",
        f"- Database parts: {source['partCount']}",
        f"- Successfully sampled parts: {source['profiledPartCount']}",
        f"- Capability-eligible base parts: {source['capabilityEligiblePartCount']}",
        f"- Geometry capability groups: {summary['geometryGroupCount']}",
        f"- Current configured slope parts: {summary['currentSlopePartCount']}",
        f"- Current covered capability groups: {summary['currentCoveredGeometryGroupCount']}",
        "",
        "A state is matchable when `targetSurfacePlate = basePlate + sampleSurfacePlate`. "
        "The compact states below show normalized per-stud sampled height ranges; the database contains the complete sample matrices, collision intervals, occupied masks, support masks, and top connection masks.",
        "",
        "## Family Summary",
        "",
        "| Family | Geometry groups |",
        "| --- | ---: |",
    ]
    lines.extend(
        f"| {family} | {count} |"
        for family, count in summary["familyGroupCounts"].items()
    )
    lines.extend(
        [
            "",
            "## Capability Groups",
            "",
            "| Group | Family | Canonical part | Members | Footprint | Height range | Current | Solvable states |",
            "| --- | --- | --- | ---: | --- | ---: | --- | --- |",
        ]
    )
    for group in catalog["groups"]:
        footprint = group["footprint"]
        states = "<br>".join(state_text(state) for state in group["states"])
        lines.append(
            "| {group_id} | {family} | `{part_id}` {name} | {members} | {width}x{depth} | {height} | {current} | {states} |".format(
                group_id=group["groupId"],
                family=group["family"],
                part_id=group["canonicalPartId"],
                name=group["canonicalName"].replace("|", "/"),
                members=len(group["memberPartIds"]),
                width=footprint["widthStud"],
                depth=footprint["depthStud"],
                height=group["heightRangePlate"],
                current="yes" if group["currentCandidate"] else "no",
                states=states,
            )
        )
    lines.extend(
        [
            "",
            "## Current Coverage",
            "",
            f"Configured IDs outside the `Slope` category: `{', '.join(summary['currentCandidateIdsOutsideSlope'])}`.",
            f"Recommended uncovered groups under the configured area limit: {len(summary['recommendedGeometryGroupIds'])}.",
            "",
        ]
    )
    return "\n".join(lines)


def write_catalog_markdown(catalog: dict[str, Any], config: dict[str, Any]) -> None:
    project_root = BACKEND_ROOT.parent
    markdown_path = project_root / config["output"]["markdown_path"]
    markdown_path.write_text(markdown_catalog(catalog, config), encoding="utf-8")
    print(markdown_path)


def main() -> None:
    arguments = parse_arguments()
    config = load_json_config(arguments.config, REQUIRED_CONFIG_KEYS)
    current_candidate_ids = load_current_candidate_ids(config)
    dem_config = load_json_config(
        config["source"]["dem_design_config_file"],
        ("surface_profile",),
    )
    parts = profile_parts(config, dem_config)
    groups = build_groups(parts, current_candidate_ids, config)
    catalog = build_catalog(parts, groups, current_candidate_ids, config)
    engine = create_engine(get_db_url())
    with Session(engine) as session:
        result = synchronize_candidates(session, catalog, config)
    write_catalog_markdown(catalog, config)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
