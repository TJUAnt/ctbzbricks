"""Validate DEM replacement phases as continuous vertical LDU columns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.ldraw.surface_profile import PartSurfaceProfile
from src.services.dem_surface_patch_service import orient_ldraw_matrix_to_dem, rotate_matrix
from src.services.dem_surface_plan_service import SurfaceReplacementPhase


@dataclass(frozen=True)
class VerticalContinuityValidation:
    connection_class: str
    checked_column_count: int
    occupied_column_count: int
    discontinuous_column_count: int
    gap_count: int
    maximum_gap_ldu: float
    gap_examples: tuple[dict[str, float], ...]


def rotation_quarter_turns(rotation_degrees: int, config: dict[str, Any]) -> int:
    rotations = {
        rotation["degrees"]: rotation["quarter_turns"]
        for rotation in config["rotations"]
    }
    if rotation_degrees not in rotations:
        raise ValueError(config["errors"]["rotation_missing"])
    return rotations[rotation_degrees]


def phase_vertical_continuity(
    phase: SurfaceReplacementPhase,
    width_stud: int,
    depth_stud: int,
    profiles_by_part_id: dict[str, PartSurfaceProfile],
    config: dict[str, Any],
) -> VerticalContinuityValidation:
    sample_rate = config["samples_per_stud_axis"]
    if sample_rate != config["ldu_per_stud"]:
        raise ValueError(config["errors"]["sample_resolution"])
    width_ldu = width_stud * sample_rate
    depth_ldu = depth_stud * sample_rate
    intervals_by_column: list[list[list[tuple[float, float]]]] = [
        [[] for _x in range(width_ldu)]
        for _z in range(depth_ldu)
    ]
    for z_ldu in range(depth_ldu):
        for x_ldu in range(width_ldu):
            base_plate = phase.base_h[z_ldu // sample_rate][x_ldu // sample_rate]
            base_top_ldu = base_plate * config["ldu_per_plate"]
            if base_top_ldu > config["ground_ldu"]:
                intervals_by_column[z_ldu][x_ldu].append(
                    (config["ground_ldu"], base_top_ldu)
                )

    for placement in phase.placements:
        profile = profiles_by_part_id.get(placement.part_id)
        if profile is None:
            raise ValueError(
                config["errors"]["profile_missing"].format(part_id=placement.part_id)
            )
        if profile.samples_per_stud_axis != sample_rate:
            raise ValueError(config["errors"]["profile_sample_resolution"])
        collision = rotate_matrix(
            orient_ldraw_matrix_to_dem(profile.collision_intervals_plate),
            rotation_quarter_turns(placement.rotation_degrees, config),
        )
        start_x_ldu = placement.x_stud * sample_rate
        start_z_ldu = placement.z_stud * sample_rate
        for local_z_ldu, row in enumerate(collision):
            for local_x_ldu, intervals in enumerate(row):
                if not intervals:
                    continue
                global_x_ldu = start_x_ldu + local_x_ldu
                global_z_ldu = start_z_ldu + local_z_ldu
                intervals_by_column[global_z_ldu][global_x_ldu].append(
                    (
                        placement.base_plate * config["ldu_per_plate"],
                        round(
                            (
                                max(upper_plate for _lower_plate, upper_plate in intervals)
                                + placement.base_plate
                            )
                            * config["ldu_per_plate"],
                            config["rounding_decimal_places"],
                        ),
                    )
                )

    occupied_column_count = 0
    discontinuous_column_count = 0
    gap_count = 0
    maximum_gap_ldu = 0.0
    gap_examples = []
    for z_ldu, row in enumerate(intervals_by_column):
        for x_ldu, intervals in enumerate(row):
            if not intervals:
                continue
            occupied_column_count += 1
            column_discontinuous = False
            continuous_top = config["ground_ldu"]
            for lower_ldu, upper_ldu in sorted(intervals):
                if lower_ldu > continuous_top:
                    gap_ldu = round(
                        lower_ldu - continuous_top,
                        config["rounding_decimal_places"],
                    )
                    gap_count += 1
                    maximum_gap_ldu = max(maximum_gap_ldu, gap_ldu)
                    column_discontinuous = True
                    if len(gap_examples) < config["maximum_gap_examples"]:
                        gap_examples.append(
                            {
                                "xLdu": x_ldu + config["sample_center_offset_ldu"],
                                "zLdu": z_ldu + config["sample_center_offset_ldu"],
                                "lowerLdu": continuous_top,
                                "upperLdu": lower_ldu,
                            }
                        )
                continuous_top = max(continuous_top, upper_ldu)
            if column_discontinuous:
                discontinuous_column_count += 1
    return VerticalContinuityValidation(
        connection_class=phase.connection_class,
        checked_column_count=width_ldu * depth_ldu,
        occupied_column_count=occupied_column_count,
        discontinuous_column_count=discontinuous_column_count,
        gap_count=gap_count,
        maximum_gap_ldu=maximum_gap_ldu,
        gap_examples=tuple(gap_examples),
    )


def vertical_continuity_response(
    validation: VerticalContinuityValidation,
) -> dict[str, Any]:
    return {
        "connectionClass": validation.connection_class,
        "checkedColumnCount": validation.checked_column_count,
        "occupiedColumnCount": validation.occupied_column_count,
        "discontinuousColumnCount": validation.discontinuous_column_count,
        "gapCount": validation.gap_count,
        "maximumGapLdu": validation.maximum_gap_ldu,
        "gapExamples": validation.gap_examples,
    }
