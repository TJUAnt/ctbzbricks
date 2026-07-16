"""Validate the Phase 1 LDraw geometry query layer."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.ldraw.search import (
    get_part_geometry,
    search_geometry_candidates,
    search_parts_by_bbox,
    search_parts_by_logical_size,
)


def _contains(candidates, part_num: str) -> bool:
    return any(candidate.ldraw_part_num == part_num for candidate in candidates)


def _print_candidates(label: str, candidates) -> None:
    print(label)
    for candidate in candidates[:10]:
        print(
            "  "
            f"{candidate.ldraw_part_num} | {candidate.name} | "
            f"logical={candidate.logical_width_stud}x"
            f"{candidate.logical_depth_stud}x{candidate.logical_height_plate} | "
            f"bbox={candidate.width_ldu}x{candidate.height_ldu}x{candidate.depth_ldu}"
            f" | score={candidate.score:.3f}"
        )


def validate_ldraw_geometry() -> int:
    failures = []

    brick_2x4 = search_parts_by_logical_size(2, 4, 3, category=["Brick"], limit=50)
    plate_2x4 = search_parts_by_logical_size(2, 4, 1, category=["Plate"], limit=50)
    brick_bbox = search_parts_by_bbox(80, 28, 40, category=["Brick"], limit=50)
    plate_bbox = search_parts_by_bbox(80, 12, 40, category=["Plate"], limit=50)
    ranked_brick_2x4 = search_geometry_candidates(
        (2, 4, 3),
        strict_bbox=True,
        category=["Brick"],
        limit=20,
    )
    ranked_plate_2x4 = search_geometry_candidates(
        (2, 4, 1),
        strict_bbox=True,
        category=["Plate"],
        limit=20,
    )

    if not _contains(brick_2x4, "3001.dat"):
        failures.append("logical 2x4x3 did not include 3001.dat")
    if not _contains(plate_2x4, "3020.dat"):
        failures.append("logical 2x4x1 did not include 3020.dat")
    if not _contains(brick_bbox, "3001.dat"):
        failures.append("bbox 80x28x40 did not include 3001.dat")
    if not _contains(plate_bbox, "3020.dat"):
        failures.append("bbox 80x12x40 did not include 3020.dat")
    if not ranked_brick_2x4 or ranked_brick_2x4[0].ldraw_part_num != "3001.dat":
        failures.append("ranked strict logical 2x4x3 did not rank 3001.dat first")
    if not ranked_plate_2x4 or ranked_plate_2x4[0].ldraw_part_num != "3020.dat":
        failures.append("ranked strict logical 2x4x1 did not rank 3020.dat first")
    if _contains(ranked_plate_2x4, "302021.dat"):
        failures.append("ranked strict logical 2x4x1 included obsolete 302021.dat")

    for part_num in ("3001.dat", "3020.dat"):
        if get_part_geometry(part_num) is None:
            failures.append(f"get_part_geometry returned None for {part_num}")

    _print_candidates("logical 2 x 4 x 3 candidates", brick_2x4)
    _print_candidates("logical 2 x 4 x 1 candidates", plate_2x4)
    _print_candidates("bbox 80 x 28 x 40 candidates", brick_bbox)
    _print_candidates("bbox 80 x 12 x 40 candidates", plate_bbox)
    _print_candidates("ranked strict logical 2 x 4 x 3 candidates", ranked_brick_2x4)
    _print_candidates("ranked strict logical 2 x 4 x 1 candidates", ranked_plate_2x4)

    if failures:
        print("FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(validate_ldraw_geometry())
