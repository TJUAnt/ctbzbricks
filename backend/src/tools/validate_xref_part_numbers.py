"""Validate Phase 2 Rebrickable-to-LDraw xref mappings."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from src.config.db_config import get_db_url
from src.ldraw.search import (
    get_part_geometries_by_rebrickable_part_num,
    get_resolved_part_geometry_candidates,
    get_resolved_part_geometry_candidates_with_substitutes,
    resolve_ldraw_part_numbers,
)
from src.model.models import LDrawPart, Part, XrefPartNumber


REQUIRED_CONFIG_KEYS = (
    "ldraw_part_suffix",
    "direct_exact_relation_type",
    "direct_exact_source",
    "relationship_mappings",
    "validation_required_mappings",
    "validation_default_excluded_relation_type",
    "validation_substitute_sample",
    "validation_obsolete_substitute_sample",
)


def _load_config(config_path: Path) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    missing_keys = [key for key in REQUIRED_CONFIG_KEYS if key not in config]
    if missing_keys:
        raise KeyError(f"Missing xref validation config keys: {', '.join(missing_keys)}")
    return config


def _count_direct_exact_matches(session, config: dict) -> int:
    return session.execute(
        select(func.count())
        .select_from(Part)
        .join(
            LDrawPart,
            func.lower(func.concat(Part.part_num, config["ldraw_part_suffix"]))
            == LDrawPart.ldraw_part_num,
        )
    ).scalar_one()


def _count_imported_exact_mappings(session, config: dict) -> int:
    return session.execute(
        select(func.count())
        .select_from(XrefPartNumber)
        .where(XrefPartNumber.relation_type == config["direct_exact_relation_type"])
        .where(XrefPartNumber.source == config["direct_exact_source"])
    ).scalar_one()


def _count_relationship_mappings(session, mapping: dict) -> int:
    return session.execute(
        select(func.count())
        .select_from(XrefPartNumber)
        .where(XrefPartNumber.relation_type == mapping["xref_relation_type"])
        .where(XrefPartNumber.source == mapping["xref_source"])
    ).scalar_one()


def _find_duplicate_exact_mappings(session, config: dict) -> list[tuple[str, str, int]]:
    return session.execute(
        select(
            XrefPartNumber.rebrickable_part_num,
            XrefPartNumber.ldraw_part_num,
            func.count(),
        )
        .where(XrefPartNumber.relation_type == config["direct_exact_relation_type"])
        .where(XrefPartNumber.source == config["direct_exact_source"])
        .group_by(
            XrefPartNumber.rebrickable_part_num,
            XrefPartNumber.ldraw_part_num,
        )
        .having(func.count() > 1)
    ).all()


def _find_duplicate_mappings(session) -> list[tuple[str, str, str, str, int]]:
    return session.execute(
        select(
            XrefPartNumber.rebrickable_part_num,
            XrefPartNumber.ldraw_part_num,
            XrefPartNumber.relation_type,
            XrefPartNumber.source,
            func.count(),
        )
        .group_by(
            XrefPartNumber.rebrickable_part_num,
            XrefPartNumber.ldraw_part_num,
            XrefPartNumber.relation_type,
            XrefPartNumber.source,
        )
        .having(func.count() > 1)
    ).all()


def validate_xref_part_numbers(config_path: Path) -> int:
    config = _load_config(config_path)
    engine = create_engine(get_db_url(), echo=False)
    Session = sessionmaker(bind=engine)

    failures = []
    with Session() as session:
        direct_exact_matches = _count_direct_exact_matches(session, config)
        imported_exact_mappings = _count_imported_exact_mappings(session, config)
        duplicate_exact_mappings = _find_duplicate_exact_mappings(session, config)
        duplicate_mappings = _find_duplicate_mappings(session)
        relationship_counts = [
            (
                mapping["rebrickable_rel_type"],
                mapping["xref_relation_type"],
                _count_relationship_mappings(session, mapping),
            )
            for mapping in config["relationship_mappings"]
        ]

    if imported_exact_mappings != direct_exact_matches:
        failures.append(
            "imported exact mapping count does not match direct exact match count"
        )
    if duplicate_exact_mappings:
        failures.append("duplicate exact mappings exist")
    if duplicate_mappings:
        failures.append("duplicate xref mappings exist")

    for mapping in config["validation_required_mappings"]:
        resolved_parts = resolve_ldraw_part_numbers(
            mapping["rebrickable_part_num"],
            relation_types=(mapping["relation_type"],),
        )
        if mapping["ldraw_part_num"] not in resolved_parts:
            failures.append(
                "required mapping missing: "
                f"{mapping['rebrickable_part_num']} -> {mapping['ldraw_part_num']}"
            )

        geometries = get_part_geometries_by_rebrickable_part_num(
            mapping["rebrickable_part_num"],
            relation_types=(mapping["relation_type"],),
        )
        if not any(
            candidate.ldraw_part_num == mapping["ldraw_part_num"]
            for candidate in geometries
        ):
            failures.append(
                "required geometry resolution missing: "
                f"{mapping['rebrickable_part_num']} -> {mapping['ldraw_part_num']}"
            )

        resolved_candidates = get_resolved_part_geometry_candidates(
            mapping["rebrickable_part_num"],
            relation_types=(mapping["relation_type"],),
        )
        if not any(
            candidate.mapping.relation_type == mapping["relation_type"]
            and candidate.geometry.ldraw_part_num == mapping["ldraw_part_num"]
            for candidate in resolved_candidates
        ):
            failures.append(
                "required xref-aware candidate missing: "
                f"{mapping['rebrickable_part_num']} -> {mapping['ldraw_part_num']} "
                f"as {mapping['relation_type']}"
            )

    substitute_sample = config["validation_substitute_sample"]
    default_substitute_sample_candidates = get_resolved_part_geometry_candidates(
        substitute_sample["rebrickable_part_num"]
    )
    default_substitute_sample_relation_types = {
        candidate.mapping.relation_type
        for candidate in default_substitute_sample_candidates
    }
    if (
        config["validation_default_excluded_relation_type"]
        in default_substitute_sample_relation_types
    ):
        failures.append(
            "default candidate resolution included excluded relation type"
        )

    candidates_with_substitutes = (
        get_resolved_part_geometry_candidates_with_substitutes(
            substitute_sample["rebrickable_part_num"]
        )
    )
    if not any(
        candidate.mapping.relation_type == substitute_sample["relation_type"]
        and candidate.geometry.ldraw_part_num == substitute_sample["ldraw_part_num"]
        for candidate in candidates_with_substitutes
    ):
        failures.append("substitute candidate resolution did not include sample")

    obsolete_substitute_sample = config["validation_obsolete_substitute_sample"]
    filtered_obsolete_candidates = (
        get_resolved_part_geometry_candidates_with_substitutes(
            obsolete_substitute_sample["rebrickable_part_num"]
        )
    )
    if any(
        candidate.mapping.relation_type == obsolete_substitute_sample["relation_type"]
        and candidate.geometry.ldraw_part_num
        == obsolete_substitute_sample["ldraw_part_num"]
        for candidate in filtered_obsolete_candidates
    ):
        failures.append("obsolete substitute sample was not filtered by default")

    unfiltered_obsolete_candidates = (
        get_resolved_part_geometry_candidates_with_substitutes(
            obsolete_substitute_sample["rebrickable_part_num"],
            exclude_obsolete=False,
        )
    )
    if not any(
        candidate.mapping.relation_type == obsolete_substitute_sample["relation_type"]
        and candidate.geometry.ldraw_part_num
        == obsolete_substitute_sample["ldraw_part_num"]
        for candidate in unfiltered_obsolete_candidates
    ):
        failures.append("obsolete substitute sample missing when filter disabled")

    print(f"direct_exact_matches: {direct_exact_matches}")
    print(f"imported_exact_mappings: {imported_exact_mappings}")
    print(f"duplicate_exact_mappings: {len(duplicate_exact_mappings)}")
    print(f"duplicate_mappings: {len(duplicate_mappings)}")
    print("relationship_mappings")
    for rel_type, xref_relation_type, count in relationship_counts:
        print(f"  {rel_type} -> {xref_relation_type}: {count}")
    print("default_substitute_sample_relation_types:")
    for relation_type in sorted(default_substitute_sample_relation_types):
        print(f"  {relation_type}")
    print(
        "filtered_obsolete_substitute_sample_count: "
        f"{len(filtered_obsolete_candidates)}"
    )
    print(
        "unfiltered_obsolete_substitute_sample_count: "
        f"{len(unfiltered_obsolete_candidates)}"
    )

    if failures:
        print("FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/ldraw_xref_import.json"),
    )
    args = parser.parse_args()
    return validate_xref_part_numbers(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
