"""Validate unified part candidate search."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.ldraw.search import search_part_candidates


REQUIRED_CONFIG_KEYS = (
    "validation_cases",
)


def _load_config(config_path: Path) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    missing_keys = [key for key in REQUIRED_CONFIG_KEYS if key not in config]
    if missing_keys:
        raise KeyError(
            f"Missing part candidate search validation config keys: {', '.join(missing_keys)}"
        )
    return config


def _logical_size(case: dict) -> tuple[float, float, float] | None:
    value = case.get("logical_size")
    if value is None:
        return None
    return tuple(value)


def _run_case(case: dict):
    return search_part_candidates(
        logical_size=_logical_size(case),
        strict_bbox=case.get("strict_bbox", False),
        category=case.get("category"),
        rebrickable_part_num=case.get("rebrickable_part_num"),
        required_connectors=case.get("required_connectors"),
        include_substitutes=case.get("include_substitutes", False),
        limit=case.get("limit"),
    )


def validate_part_candidate_search(config_path: Path) -> int:
    config = _load_config(config_path)
    failures = []

    for case in config["validation_cases"]:
        candidates = _run_case(case)
        print(case["name"])
        for candidate in candidates[:5]:
            relation_type = (
                candidate.mapping.relation_type
                if candidate.mapping is not None
                else None
            )
            print(
                "  "
                f"{candidate.geometry.ldraw_part_num} | "
                f"{candidate.geometry.name} | "
                f"relation={relation_type} | "
                f"score={candidate.score:.3f} | "
                f"connectors={candidate.connector_counts}"
            )

        expected_minimum_results = case.get("expected_minimum_results")
        if expected_minimum_results is not None and len(candidates) < expected_minimum_results:
            failures.append(f"{case['name']} returned fewer candidates than expected")

        expected_first = case.get("expected_first_ldraw_part_num")
        if expected_first is not None:
            if not candidates or candidates[0].geometry.ldraw_part_num != expected_first:
                failures.append(f"{case['name']} first candidate mismatch")

        expected_part = case.get("expected_ldraw_part_num")
        if expected_part is not None:
            matched = [
                candidate for candidate in candidates
                if candidate.geometry.ldraw_part_num == expected_part
            ]
            if not matched:
                failures.append(f"{case['name']} expected part missing")
            else:
                expected_relation = case.get("expected_relation_type")
                if expected_relation is not None:
                    relation_type = (
                        matched[0].mapping.relation_type
                        if matched[0].mapping is not None
                        else None
                    )
                    if relation_type != expected_relation:
                        failures.append(f"{case['name']} relation type mismatch")

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
        default=Path("config/part_candidate_search.json"),
    )
    args = parser.parse_args()
    return validate_part_candidate_search(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
