"""Run batch evaluations for search_part_candidates."""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.ldraw.search import search_part_candidates


REQUIRED_CONFIG_KEYS = (
    "default_cases_path",
    "default_log_dir",
    "log_file_prefix",
    "default_top_n",
    "pass_status",
    "fail_status",
    "expected_query_keys",
    "expect_keys",
)


def _load_config(config_path: Path) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    missing_keys = [key for key in REQUIRED_CONFIG_KEYS if key not in config]
    if missing_keys:
        raise KeyError(
            f"Missing search evaluation config keys: {', '.join(missing_keys)}"
        )
    return config


def _load_cases(cases_path: Path) -> list[dict]:
    return json.loads(cases_path.read_text(encoding="utf-8"))


def _query_kwargs(case: dict, config: dict) -> dict:
    query = case["query"]
    unknown_keys = [
        key for key in query
        if key not in config["expected_query_keys"]
    ]
    if unknown_keys:
        raise KeyError(
            f"Unknown query keys in case {case['name']}: {', '.join(unknown_keys)}"
        )
    return {
        key: tuple(value) if key in ("logical_size", "bbox") and value is not None else value
        for key, value in query.items()
    }


def _candidate_summary(candidate) -> dict:
    return {
        "ldraw_part_num": candidate.geometry.ldraw_part_num,
        "name": candidate.geometry.name,
        "category": candidate.geometry.category,
        "relation_type": (
            candidate.mapping.relation_type
            if candidate.mapping is not None
            else None
        ),
        "source": (
            candidate.mapping.source
            if candidate.mapping is not None
            else None
        ),
        "score": candidate.score,
        "score_reason": candidate.score_reason,
        "connector_counts": candidate.connector_counts,
        "logical_size": [
            candidate.geometry.logical_width_stud,
            candidate.geometry.logical_depth_stud,
            candidate.geometry.logical_height_plate,
        ],
        "bbox": [
            candidate.geometry.width_ldu,
            candidate.geometry.height_ldu,
            candidate.geometry.depth_ldu,
        ],
    }


def _hit_rank(candidates: list[dict], expected_parts: list[str]) -> int | None:
    for index, candidate in enumerate(candidates, 1):
        if candidate["ldraw_part_num"] in expected_parts:
            return index
    return None


def _evaluate_expectations(case: dict, candidates: list[dict], config: dict) -> list[str]:
    expect = case.get("expect", {})
    keys = config["expect_keys"]
    failures = []

    top1 = expect.get(keys["top1"])
    if top1 is not None:
        actual_top1 = candidates[0]["ldraw_part_num"] if candidates else None
        if actual_top1 != top1:
            failures.append(f"top1 expected {top1}, got {actual_top1}")

    hit_any = expect.get(keys["hit_any"])
    if hit_any is not None and _hit_rank(candidates, hit_any) is None:
        failures.append(f"hit_any missing: {', '.join(hit_any)}")

    relation_type = expect.get(keys["relation_type"])
    if relation_type is not None:
        matched_candidates = candidates
        if hit_any is not None:
            matched_candidates = [
                candidate for candidate in candidates
                if candidate["ldraw_part_num"] in hit_any
            ]
        if not matched_candidates:
            failures.append(f"relation_type {relation_type} has no matched candidate")
        elif matched_candidates[0]["relation_type"] != relation_type:
            failures.append(
                "relation_type expected "
                f"{relation_type}, got {matched_candidates[0]['relation_type']}"
            )

    min_results = expect.get(keys["min_results"])
    if min_results is not None and len(candidates) < min_results:
        failures.append(f"min_results expected {min_results}, got {len(candidates)}")

    return failures


def _evaluate_case(case: dict, config: dict, top_n: int) -> dict:
    candidates = search_part_candidates(**_query_kwargs(case, config))
    summaries = [_candidate_summary(candidate) for candidate in candidates[:top_n]]
    failures = _evaluate_expectations(case, summaries, config)
    status = config["pass_status"] if not failures else config["fail_status"]
    expected_parts = case.get("expect", {}).get(config["expect_keys"]["hit_any"], [])
    return {
        "case_name": case["name"],
        "status": status,
        "failures": failures,
        "result_count": len(candidates),
        "top1": summaries[0]["ldraw_part_num"] if summaries else None,
        "hit_rank": _hit_rank(summaries, expected_parts) if expected_parts else None,
        "top_candidates": summaries,
    }


def _write_jsonl(log_path: Path, records: list[dict]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")


def evaluate_part_search(
    config_path: Path,
    cases_path: Path | None,
    log_dir: Path | None,
    top_n: int | None,
) -> int:
    config = _load_config(config_path)
    active_cases_path = cases_path or Path(config["default_cases_path"])
    active_log_dir = log_dir or Path(config["default_log_dir"])
    active_top_n = top_n or config["default_top_n"]
    cases = _load_cases(active_cases_path)
    records = [
        _evaluate_case(case, config, active_top_n)
        for case in cases
    ]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = active_log_dir / f"{config['log_file_prefix']}_{timestamp}.jsonl"
    _write_jsonl(log_path, records)

    passed = sum(1 for record in records if record["status"] == config["pass_status"])
    failed = len(records) - passed
    print(f"cases: {len(records)}")
    print(f"passed: {passed}")
    print(f"failed: {failed}")
    print(f"log: {log_path}")
    for record in records:
        print(
            f"{record['status']} | {record['case_name']} | "
            f"top1={record['top1']} | hit_rank={record['hit_rank']} | "
            f"count={record['result_count']}"
        )
        for failure in record["failures"]:
            print(f"  - {failure}")

    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/search_evaluation.json"),
    )
    parser.add_argument("--cases", type=Path, default=None)
    parser.add_argument("--log-dir", type=Path, default=None)
    parser.add_argument("--top-n", type=int, default=None)
    args = parser.parse_args()
    return evaluate_part_search(
        args.config,
        args.cases,
        args.log_dir,
        args.top_n,
    )


if __name__ == "__main__":
    raise SystemExit(main())
