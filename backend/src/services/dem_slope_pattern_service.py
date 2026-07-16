"""Calculate approximate four-direction Heightmap patterns for DEM slope parts."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any


def source_rotation_state(
    capability: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    source_rotation = int(config["source_rotation_degrees"])
    state = next(
        (
            item
            for item in capability["states"]
            if int(item["rotationDegrees"]) == source_rotation
        ),
        None,
    )
    if state is None:
        raise ValueError(config["errors"]["missing_source_rotation"])
    return state


def capability_surface_heights(
    capability: dict[str, Any],
    config: dict[str, Any],
) -> tuple[tuple[float | None, ...], ...]:
    state = source_rotation_state(capability, config)
    return tuple(
        tuple(
            None
            if not state["occupiedMask"][z][x]
            else float(state["cellHeightRangesPlate"][z][x]["maximum"])
            for x in range(int(state["widthStud"]))
        )
        for z in range(int(state["depthStud"]))
    )


def capability_base_height_offsets(
    capability: dict[str, Any],
    config: dict[str, Any],
) -> tuple[tuple[int | None, ...], ...]:
    state = source_rotation_state(capability, config)
    contact_ranges = state["cellContactBottomHeightRangesPlate"]
    collision_ranges = state["cellBottomHeightRangesPlate"]
    use_contact_ranges = any(
        cell_range is not None
        for row in contact_ranges
        for cell_range in row
    )
    return tuple(
        tuple(
            None
            if not state["occupiedMask"][z][x]
            else base_height_offset(
                contact_ranges[z][x],
                collision_ranges[z][x],
                use_contact_ranges,
            )
            for x in range(int(state["widthStud"]))
        )
        for z in range(int(state["depthStud"]))
    )


def base_height_offset(
    contact_range: dict[str, float] | None,
    collision_range: dict[str, float] | None,
    use_contact_ranges: bool,
) -> int | None:
    if use_contact_ranges:
        if contact_range is None:
            return None
        return math.floor(float(contact_range["minimum"]))
    return math.floor(float(collision_range["minimum"]))


def highest_cells(
    heights: tuple[tuple[float | None, ...], ...],
    tolerance_plate: float,
) -> tuple[tuple[int, int], ...]:
    values = tuple(value for row in heights for value in row if value is not None)
    if not values:
        return ()
    maximum_height = max(values)
    return tuple(
        (x, z)
        for z, row in enumerate(heights)
        for x, value in enumerate(row)
        if value is not None and maximum_height - value <= tolerance_plate
    )


def approximate_relative_heights(
    heights: tuple[tuple[float | None, ...], ...],
    peak_cells: tuple[tuple[int, int], ...],
) -> tuple[tuple[int | None, ...], ...]:
    distances = tuple(
        tuple(
            None
            if height is None
            else min(abs(x - peak_x) + abs(z - peak_z) for peak_x, peak_z in peak_cells)
            for x, height in enumerate(row)
        )
        for z, row in enumerate(heights)
    )
    maximum_distance = max(
        distance
        for row in distances
        for distance in row
        if distance is not None
    )
    return tuple(
        tuple(
            None if distance is None else maximum_distance - distance
            for distance in row
        )
        for row in distances
    )


def slope_edges(
    relative_heights: tuple[tuple[int | None, ...], ...],
    config: dict[str, Any],
) -> tuple[tuple[int, int, int, int, str, int], ...]:
    depth = len(relative_heights)
    width = len(relative_heights[0])
    edges = []
    for z, row in enumerate(relative_heights):
        for x, height in enumerate(row):
            if height is None:
                continue
            for direction in config["directions"]:
                neighbor_x = x + int(direction["x"])
                neighbor_z = z + int(direction["z"])
                if (
                    neighbor_x < 0
                    or neighbor_z < 0
                    or neighbor_x >= width
                    or neighbor_z >= depth
                ):
                    continue
                neighbor_height = relative_heights[neighbor_z][neighbor_x]
                if neighbor_height is None or neighbor_height >= height:
                    continue
                edges.append(
                    (
                        x,
                        z,
                        neighbor_x,
                        neighbor_z,
                        direction["name"],
                        height - neighbor_height,
                    )
                )
    return tuple(edges)


def longest_continuous_run(
    edges: tuple[tuple[int, int, int, int, str, int], ...],
) -> int:
    if not edges:
        return 0
    edge_lookup = {
        (start_x, start_z, direction): (end_x, end_z)
        for start_x, start_z, end_x, end_z, direction, _delta in edges
    }
    maximum = 1
    for start_x, start_z, _end_x, _end_z, direction, _delta in edges:
        length = 1
        current_x = start_x
        current_z = start_z
        while (current_x, current_z, direction) in edge_lookup:
            current_x, current_z = edge_lookup[(current_x, current_z, direction)]
            length += 1
        maximum = max(maximum, length)
    return maximum


def approximation_metrics(
    source_heights: tuple[tuple[float | None, ...], ...],
    relative_heights: tuple[tuple[int | None, ...], ...],
) -> dict[str, float]:
    source_values = tuple(value for row in source_heights for value in row if value is not None)
    minimum_source = min(source_values)
    normalized_source = tuple(value - minimum_source for value in source_values)
    pattern_values = tuple(
        value for row in relative_heights for value in row if value is not None
    )
    errors = tuple(
        abs(source - pattern)
        for source, pattern in zip(normalized_source, pattern_values)
    )
    return {
        "maximumErrorPlate": max(errors),
        "totalErrorPlate": sum(errors),
        "rootMeanSquareErrorPlate": math.sqrt(
            sum(error * error for error in errors) / len(errors)
        ),
    }


def build_candidate_heightmap_patterns(
    capability: dict[str, Any],
    rotations: tuple[int, ...],
    maximum_patterns: int,
    config: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    heights = capability_surface_heights(capability, config)
    base_height_offsets = capability_base_height_offsets(capability, config)
    peak_cells = highest_cells(
        heights,
        float(config["highest_point_tolerance_plate"]),
    )
    if not peak_cells:
        raise ValueError(config["errors"]["empty_pattern_surface"])
    relative_heights = approximate_relative_heights(heights, peak_cells)
    edges = slope_edges(relative_heights, config)
    if not edges:
        return ()
    directions = tuple(
        direction["name"]
        for direction in config["directions"]
        if any(edge[4] == direction["name"] for edge in edges)
    )
    pattern_payload = {
        "widthStud": len(heights[0]),
        "depthStud": len(heights),
        "highestCells": [list(cell) for cell in peak_cells],
        "relativeHeights": [list(row) for row in relative_heights],
        "occupiedMask": [
            [height is not None for height in row]
            for row in relative_heights
        ],
        "baseHeightOffsets": [list(row) for row in base_height_offsets],
        "slopeEdges": [
            {
                "startX": edge[0],
                "startZ": edge[1],
                "endX": edge[2],
                "endZ": edge[3],
                "direction": edge[4],
                "deltaPlate": edge[5],
            }
            for edge in edges
        ],
        "slopeDirections": list(directions),
        "slopeDirectionCount": len(directions),
        "longestContinuousRun": longest_continuous_run(edges),
        "validRotations": list(rotations),
    }
    serialized_pattern = json.dumps(
        pattern_payload,
        sort_keys=True,
        separators=(",", ":"),
    )
    record = {
        "patternKey": hashlib.new(
            config["pattern_hash_algorithm"],
            serialized_pattern.encode(),
        ).hexdigest()[: int(config["pattern_hash_length"])],
        "heightmapPattern": pattern_payload,
        "matchMetrics": approximation_metrics(heights, relative_heights),
    }
    return (record,)[:maximum_patterns]
