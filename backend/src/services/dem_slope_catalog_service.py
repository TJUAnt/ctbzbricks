"""Derive reusable DEM surface capabilities from sampled LDraw slope meshes."""

from __future__ import annotations

import json
import re
from typing import Any

from src.ldraw.surface_profile import PartSurfaceProfile
from src.services.dem_surface_patch_service import orient_ldraw_matrix_to_dem, rotate_matrix


def quantized_plate(value: float, config: dict[str, Any]) -> float:
    step = config["quantization_step_plate"]
    return round(
        round(value / step) * step,
        config["value_precision"],
    )


def normalized_surface(
    surface: tuple[tuple[float | None, ...], ...],
    config: dict[str, Any],
) -> tuple[tuple[float | None, ...], ...]:
    minimum = min(value for row in surface for value in row if value is not None)
    return tuple(
        tuple(
            None if value is None else quantized_plate(value - minimum, config)
            for value in row
        )
        for row in surface
    )


def normalized_collision(
    collision: tuple[tuple[tuple[tuple[float, float], ...], ...], ...],
    config: dict[str, Any],
) -> tuple:
    return tuple(
        tuple(
            tuple(
                (
                    quantized_plate(lower, config),
                    quantized_plate(upper, config),
                )
                for lower, upper in intervals
            )
            for intervals in row
        )
        for row in collision
    )


def stud_boolean_mask(
    samples: tuple[tuple[object, ...], ...],
    sample_rate: int,
    occupied,
) -> list[list[bool]]:
    return [
        [
            any(
                occupied(samples[sample_z][sample_x])
                for sample_z in range(z_stud * sample_rate, (z_stud + 1) * sample_rate)
                for sample_x in range(x_stud * sample_rate, (x_stud + 1) * sample_rate)
            )
            for x_stud in range(len(samples[0]) // sample_rate)
        ]
        for z_stud in range(len(samples) // sample_rate)
    ]


def cell_height_ranges(
    surface: tuple[tuple[float | None, ...], ...],
    sample_rate: int,
) -> list[list[dict[str, float] | None]]:
    return [
        [
            cell_height_range(surface, x_stud, z_stud, sample_rate)
            for x_stud in range(len(surface[0]) // sample_rate)
        ]
        for z_stud in range(len(surface) // sample_rate)
    ]


def cell_height_range(
    surface: tuple[tuple[float | None, ...], ...],
    x_stud: int,
    z_stud: int,
    sample_rate: int,
) -> dict[str, float] | None:
    values = [
        surface[sample_z][sample_x]
        for sample_z in range(z_stud * sample_rate, (z_stud + 1) * sample_rate)
        for sample_x in range(x_stud * sample_rate, (x_stud + 1) * sample_rate)
        if surface[sample_z][sample_x] is not None
    ]
    if not values:
        return None
    return {"minimum": min(values), "maximum": max(values)}


def cell_collision_bottom_ranges(
    collision: tuple[tuple[tuple[tuple[float, float], ...], ...], ...],
    sample_rate: int,
) -> list[list[dict[str, float] | None]]:
    return [
        [
            cell_collision_bottom_range(collision, x_stud, z_stud, sample_rate)
            for x_stud in range(len(collision[0]) // sample_rate)
        ]
        for z_stud in range(len(collision) // sample_rate)
    ]


def cell_collision_bottom_range(
    collision: tuple[tuple[tuple[tuple[float, float], ...], ...], ...],
    x_stud: int,
    z_stud: int,
    sample_rate: int,
) -> dict[str, float] | None:
    values = [
        intervals[0][0]
        for sample_z in range(z_stud * sample_rate, (z_stud + 1) * sample_rate)
        for sample_x in range(x_stud * sample_rate, (x_stud + 1) * sample_rate)
        if (intervals := collision[sample_z][sample_x])
    ]
    if not values:
        return None
    return {"minimum": min(values), "maximum": max(values)}


def cell_contact_bottom_ranges(
    collision: tuple[tuple[tuple[tuple[float, float], ...], ...], ...],
    contact: tuple[tuple[bool, ...], ...],
    sample_rate: int,
) -> list[list[dict[str, float] | None]]:
    return [
        [
            cell_contact_bottom_range(collision, contact, x_stud, z_stud, sample_rate)
            for x_stud in range(len(collision[0]) // sample_rate)
        ]
        for z_stud in range(len(collision) // sample_rate)
    ]


def cell_contact_bottom_range(
    collision: tuple[tuple[tuple[tuple[float, float], ...], ...], ...],
    contact: tuple[tuple[bool, ...], ...],
    x_stud: int,
    z_stud: int,
    sample_rate: int,
) -> dict[str, float] | None:
    values = []
    for sample_z in range(z_stud * sample_rate, (z_stud + 1) * sample_rate):
        for sample_x in range(x_stud * sample_rate, (x_stud + 1) * sample_rate):
            intervals = collision[sample_z][sample_x]
            if contact[sample_z][sample_x] and intervals:
                values.append(intervals[0][0])
    if not values:
        return None
    return {"minimum": min(values), "maximum": max(values)}


def orientation_state(
    profile: PartSurfaceProfile,
    quarter_turns: int,
    rotation_degrees: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    surface = normalized_surface(
        rotate_matrix(
            orient_ldraw_matrix_to_dem(profile.surface_height_plate),
            quarter_turns,
        ),
        config,
    )
    collision = normalized_collision(
        rotate_matrix(
            orient_ldraw_matrix_to_dem(profile.collision_intervals_plate),
            quarter_turns,
        ),
        config,
    )
    contact = rotate_matrix(
        orient_ldraw_matrix_to_dem(profile.bottom_contact),
        quarter_turns,
    )
    top_connection = rotate_matrix(
        orient_ldraw_matrix_to_dem(profile.top_connection_mask),
        quarter_turns,
    )
    sample_rate = profile.samples_per_stud_axis
    return {
        "rotationDegrees": rotation_degrees,
        "widthStud": len(surface[0]) // sample_rate,
        "depthStud": len(surface) // sample_rate,
        "sampleSurfacePlate": surface,
        "cellHeightRangesPlate": cell_height_ranges(surface, sample_rate),
        "cellBottomHeightRangesPlate": cell_collision_bottom_ranges(collision, sample_rate),
        "cellContactBottomHeightRangesPlate": cell_contact_bottom_ranges(
            collision,
            contact,
            sample_rate,
        ),
        "occupiedMask": stud_boolean_mask(collision, sample_rate, bool),
        "supportMask": stud_boolean_mask(contact, sample_rate, bool),
        "topConnectMask": top_connection,
        "collisionIntervalsPlate": collision,
    }


def state_geometry(state: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in state.items()
        if key != "rotationDegrees"
    }


def profile_states(profile: PartSurfaceProfile, config: dict[str, Any]) -> list[dict[str, Any]]:
    states = []
    signatures = set()
    for quarter_turns, rotation_degrees in enumerate(config["orientation_degrees"]):
        state = orientation_state(
            profile,
            quarter_turns,
            rotation_degrees,
            config,
        )
        signature = json.dumps(state_geometry(state), sort_keys=True)
        if signature in signatures:
            continue
        signatures.add(signature)
        states.append(state)
    return states


def profile_geometry_signature(profile: PartSurfaceProfile, config: dict[str, Any]) -> str:
    signatures = [
        json.dumps(
            {
                "ldrawOriginToBaseLdu": profile.ldraw_origin_to_base_ldu,
                "ldrawCenterXLdu": profile.ldraw_center_x_ldu,
                "ldrawCenterZLdu": profile.ldraw_center_z_ldu,
                "state": state_geometry(state),
            },
            sort_keys=True,
        )
        for state in profile_states(profile, config)
    ]
    return min(signatures)


def profile_capability(profile: PartSurfaceProfile, config: dict[str, Any]) -> dict[str, Any]:
    surface = normalized_surface(profile.surface_height_plate, config)
    heights = [value for row in surface for value in row if value is not None]
    return {
        "footprint": {
            "widthStud": profile.width_stud,
            "depthStud": profile.depth_stud,
        },
        "ldrawOriginToBaseLdu": profile.ldraw_origin_to_base_ldu,
        "ldrawCenterXLdu": profile.ldraw_center_x_ldu,
        "ldrawCenterZLdu": profile.ldraw_center_z_ldu,
        "samplesPerStudAxis": profile.samples_per_stud_axis,
        "heightRangePlate": quantized_plate(max(heights) - min(heights), config),
        "states": [
            {
                key: value
                for key, value in state.items()
                if key != "collisionIntervalsPlate"
            }
            for state in profile_states(profile, config)
        ],
    }


def classify_surface_family(name: str, height_range: float, config: dict[str, Any]) -> str:
    traits = surface_traits(name, config)
    if traits:
        return traits[0]
    if height_range <= config["flat_surface_range_plate"]:
        return config["families"]["flat_top"]
    return config["families"]["unclassified"]


def surface_traits(name: str, config: dict[str, Any]) -> list[str]:
    return [
        family_pattern["family"]
        for family_pattern in config["family_patterns"]
        if re.search(family_pattern["pattern"], name, re.IGNORECASE)
    ]
