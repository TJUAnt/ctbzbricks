"""Report colored Heightmap regions that match persisted slope patterns."""

from __future__ import annotations

from collections import deque
import re
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from src.model.models import (
    Color,
    DemSlopeCandidate,
    DemSlopeCandidatePattern,
    InventoryPart,
    LDrawPart,
    XrefPartNumber,
)


def rotate_clockwise(matrix: tuple[tuple[Any, ...], ...]) -> tuple[tuple[Any, ...], ...]:
    return tuple(
        tuple(row[column] for row in reversed(matrix))
        for column in range(len(matrix[0]))
    )


def rotate_matrix(
    matrix: tuple[tuple[Any, ...], ...],
    quarter_turns: int,
) -> tuple[tuple[Any, ...], ...]:
    rotated = matrix
    for _turn in range(quarter_turns):
        rotated = rotate_clockwise(rotated)
    return rotated


def rotate_directions(
    directions: tuple[str, ...],
    quarter_turns: int,
    config: dict[str, Any],
) -> tuple[str, ...]:
    rotated = directions
    for _turn in range(quarter_turns):
        rotated = tuple(
            config["direction_rotation_clockwise"][direction]
            for direction in rotated
        )
    direction_order = tuple(config["direction_rotation_clockwise"])
    return tuple(direction for direction in direction_order if direction in rotated)


def heightmap_grids(
    heightmap: dict[str, Any],
    config: dict[str, Any],
) -> tuple[list[list[int | None]], list[list[str | None]]]:
    cells = heightmap.get("cells")
    if not cells:
        raise ValueError(config["errors"]["heightmap_cells_missing"])
    width = int(heightmap["metrics"]["widthStud"])
    depth = int(heightmap["metrics"]["depthStud"])
    if len(cells) != width * depth:
        raise ValueError(config["errors"]["heightmap_dimensions_invalid"])
    heights: list[list[int | None]] = [[None for _x in range(width)] for _z in range(depth)]
    colors: list[list[str | None]] = [[None for _x in range(width)] for _z in range(depth)]
    for cell in cells:
        x = int(cell["x"])
        z = int(cell["z"])
        if cell["elevationMeters"] is None or cell["landCoverColor"] is None:
            continue
        heights[z][x] = int(cell["heightPlate"])
        colors[z][x] = str(cell["landCoverColor"]).upper()
    return heights, colors


def color_connected_regions(
    colors: list[list[str | None]],
    config: dict[str, Any],
) -> tuple[list[list[int | None]], list[dict[str, Any]]]:
    depth = len(colors)
    width = len(colors[0])
    region_grid: list[list[int | None]] = [[None for _x in range(width)] for _z in range(depth)]
    regions = []
    for start_z in range(depth):
        for start_x in range(width):
            color = colors[start_z][start_x]
            if color is None or region_grid[start_z][start_x] is not None:
                continue
            region_id = len(regions)
            queue = deque(((start_x, start_z),))
            region_grid[start_z][start_x] = region_id
            cells = []
            while queue:
                x, z = queue.popleft()
                cells.append((x, z))
                for offset in config["connectivity"]:
                    neighbor_x = x + int(offset["x"])
                    neighbor_z = z + int(offset["z"])
                    if (
                        neighbor_x < 0
                        or neighbor_z < 0
                        or neighbor_x >= width
                        or neighbor_z >= depth
                        or region_grid[neighbor_z][neighbor_x] is not None
                        or colors[neighbor_z][neighbor_x] != color
                    ):
                        continue
                    region_grid[neighbor_z][neighbor_x] = region_id
                    queue.append((neighbor_x, neighbor_z))
            regions.append(
                {
                    "regionId": region_id,
                    "targetColor": color,
                    "cellCount": len(cells),
                }
            )
    return region_grid, regions


def normalized_target_heights(
    heights: list[list[int | None]],
    occupied_mask: tuple[tuple[bool, ...], ...],
    x: int,
    z: int,
) -> tuple[tuple[int | None, ...], ...]:
    values = tuple(
        heights[z + local_z][x + local_x]
        for local_z, row in enumerate(occupied_mask)
        for local_x, occupied in enumerate(row)
        if occupied
    )
    if any(value is None for value in values):
        return ()
    minimum_height = min(value for value in values if value is not None)
    return tuple(
        tuple(
            None
            if not occupied
            else int(heights[z + local_z][x + local_x]) - minimum_height
            for local_x, occupied in enumerate(row)
        )
        for local_z, row in enumerate(occupied_mask)
    )


def pattern_matches(
    target: tuple[tuple[int | None, ...], ...],
    pattern: tuple[tuple[int | None, ...], ...],
    maximum_error: int,
) -> bool:
    if not target:
        return False
    return all(
        pattern_value is None
        or abs(int(target_value) - int(pattern_value)) <= maximum_error
        for target_row, pattern_row in zip(target, pattern)
        for target_value, pattern_value in zip(target_row, pattern_row)
    )


def normalize_rgb(rgb: str, config: dict[str, Any]) -> str:
    return rgb.removeprefix(config["color"]["rgb_prefix"]).upper()


def rgb_channels(rgb: str, config: dict[str, Any]) -> tuple[int, int, int]:
    color_config = config["color"]
    channels = color_config["rgb_channels"]
    value = normalize_rgb(rgb, config)
    radix = int(color_config["hex_radix"])
    return (
        int(value[channels["red_start"] : channels["red_end"]], radix),
        int(value[channels["green_start"] : channels["green_end"]], radix),
        int(value[channels["blue_start"] : channels["blue_end"]], radix),
    )


def color_distance(first: str, second: str, config: dict[str, Any]) -> int:
    exponent = int(config["color"]["distance_exponent"])
    return sum(
        abs(first_channel - second_channel) ** exponent
        for first_channel, second_channel in zip(
            rgb_channels(first, config),
            rgb_channels(second, config),
        )
    )


def select_part_color(
    target_color: str,
    available_colors: dict[int, dict[str, Any]],
    config: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not available_colors:
        return None, {
            "reason": config["missing_color_reasons"]["no_inventory_color"],
        }
    normalized_target = normalize_rgb(target_color, config)
    exact_color_ids = tuple(
        color_id
        for color_id, color in available_colors.items()
        if normalize_rgb(color["rgb"], config) == normalized_target
    )
    if exact_color_ids:
        color_id = min(exact_color_ids)
        return {
            "colorId": color_id,
            "colorName": available_colors[color_id]["name"],
            "colorRgb": config["color"]["rgb_prefix"] + normalize_rgb(
                available_colors[color_id]["rgb"],
                config,
            ),
            "colorMatchType": config["color"]["exact_match"],
            "colorDistance": 0,
        }, None
    color_id = min(
        available_colors,
        key=lambda candidate_color_id: (
            color_distance(
                target_color,
                available_colors[candidate_color_id]["rgb"],
                config,
            ),
            candidate_color_id,
        ),
    )
    distance = color_distance(
        target_color,
        available_colors[color_id]["rgb"],
        config,
    )
    if distance > int(config["color"]["maximum_squared_distance"]):
        return None, {
            "reason": config["missing_color_reasons"]["nearest_color_exceeds_threshold"],
            "nearestColorId": color_id,
            "nearestColorName": available_colors[color_id]["name"],
            "nearestColorRgb": config["color"]["rgb_prefix"] + normalize_rgb(
                available_colors[color_id]["rgb"],
                config,
            ),
            "nearestColorDistance": distance,
            "maximumSquaredDistance": int(config["color"]["maximum_squared_distance"]),
        }
    return {
        "colorId": color_id,
        "colorName": available_colors[color_id]["name"],
        "colorRgb": config["color"]["rgb_prefix"] + normalize_rgb(
            available_colors[color_id]["rgb"],
            config,
        ),
        "colorMatchType": config["color"]["nearest_match"],
        "colorDistance": distance,
    }, None


def oriented_pattern_variants(
    pattern_record: dict[str, Any],
    config: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    pattern = pattern_record["heightmapPattern"]
    heights = tuple(tuple(row) for row in pattern["relativeHeights"])
    mask = tuple(tuple(row) for row in pattern["occupiedMask"])
    base_height_offsets = tuple(tuple(row) for row in pattern["baseHeightOffsets"])
    directions = tuple(pattern["slopeDirections"])
    valid_rotations = set(pattern["validRotations"])
    variants = []
    signatures = set()
    for rotation in config["rotations"]:
        degrees = int(rotation["degrees"])
        if degrees not in valid_rotations:
            continue
        quarter_turns = int(rotation["quarter_turns"])
        rotated_heights = rotate_matrix(heights, quarter_turns)
        rotated_mask = rotate_matrix(mask, quarter_turns)
        rotated_base_height_offsets = rotate_matrix(base_height_offsets, quarter_turns)
        rotated_directions = rotate_directions(directions, quarter_turns, config)
        signature = rotated_heights, rotated_mask, rotated_base_height_offsets, rotated_directions
        if signature in signatures:
            continue
        signatures.add(signature)
        variants.append(
            {
                "rotationDegrees": degrees,
                "relativeHeights": rotated_heights,
                "occupiedMask": rotated_mask,
                "baseHeightOffsets": rotated_base_height_offsets,
                "slopeDirections": rotated_directions,
            }
        )
    return tuple(variants)


def geometric_match_response(
    pattern_record: dict[str, Any],
    variant: dict[str, Any],
    heights: list[list[int | None]],
    x: int,
    z: int,
    region_id: int,
    target_color: str,
) -> dict[str, Any]:
    pattern = pattern_record["heightmapPattern"]
    covered_cells = tuple(
        (x + local_x, z + local_z)
        for local_z, row in enumerate(variant["occupiedMask"])
        for local_x, occupied in enumerate(row)
        if occupied
    )
    base_plate = min(
        int(heights[z + local_z][x + local_x]) - int(pattern_height)
        for local_z, row in enumerate(variant["relativeHeights"])
        for local_x, pattern_height in enumerate(row)
        if pattern_height is not None
    )
    base_height_cells = tuple(
        (x + local_x, z + local_z, base_plate + int(base_height_offset))
        for local_z, row in enumerate(variant["baseHeightOffsets"])
        for local_x, base_height_offset in enumerate(row)
        if base_height_offset is not None
    )
    solved_edges = oriented_slope_edges(
        variant["relativeHeights"],
        x,
        z,
        variant["slopeNeighborConfig"],
    )
    return {
        "candidateId": pattern_record["candidateId"],
        "partId": pattern_record["partId"],
        "patternRank": pattern_record["patternRank"],
        "patternKey": pattern_record["patternKey"],
        "xStud": x,
        "zStud": z,
        "widthStud": len(variant["relativeHeights"][0]),
        "depthStud": len(variant["relativeHeights"]),
        "rotationDegrees": variant["rotationDegrees"],
        "regionId": region_id,
        "targetColor": target_color,
        "basePlate": base_plate,
        "coveredCells": covered_cells,
        "baseHeightCells": base_height_cells,
        "solvedSlopeEdges": solved_edges,
        "slopeDirections": list(variant["slopeDirections"]),
        "slopeDirectionCount": len(variant["slopeDirections"]),
        "slopeEdgeCount": len(pattern["slopeEdges"]),
        "longestContinuousRun": pattern["longestContinuousRun"],
        "maximumPatternErrorPlate": pattern_record["matchMetrics"][
            "maximumErrorPlate"
        ],
    }


def oriented_slope_edges(
    relative_heights: tuple[tuple[int | None, ...], ...],
    offset_x: int,
    offset_z: int,
    neighbors: list[dict[str, Any]],
) -> tuple[tuple[int, int, int, int, str, int], ...]:
    depth = len(relative_heights)
    width = len(relative_heights[0])
    edges = []
    for z, row in enumerate(relative_heights):
        for x, height in enumerate(row):
            if height is None:
                continue
            for neighbor in neighbors:
                neighbor_x = x + int(neighbor["x"])
                neighbor_z = z + int(neighbor["z"])
                if neighbor_x >= width or neighbor_z >= depth:
                    continue
                neighbor_height = relative_heights[neighbor_z][neighbor_x]
                if neighbor_height is None or neighbor_height == height:
                    continue
                if height > neighbor_height:
                    edges.append(
                        (
                            offset_x + x,
                            offset_z + z,
                            offset_x + neighbor_x,
                            offset_z + neighbor_z,
                            neighbor["positive"],
                            int(height - neighbor_height),
                        )
                    )
                else:
                    edges.append(
                        (
                            offset_x + neighbor_x,
                            offset_z + neighbor_z,
                            offset_x + x,
                            offset_z + z,
                            neighbor["negative"],
                            int(neighbor_height - height),
                        )
                    )
    return tuple(edges)


def target_slope_edges_by_region(
    heights: list[list[int | None]],
    region_grid: list[list[int | None]],
    config: dict[str, Any],
) -> dict[int, set[tuple[int, int, int, int, str, int]]]:
    edges_by_region: dict[int, set[tuple[int, int, int, int, str, int]]] = {}
    depth = len(heights)
    width = len(heights[0])
    for z, row in enumerate(heights):
        for x, height in enumerate(row):
            region_id = region_grid[z][x]
            if height is None or region_id is None:
                continue
            for neighbor in config["slope_neighbors"]:
                neighbor_x = x + int(neighbor["x"])
                neighbor_z = z + int(neighbor["z"])
                if neighbor_x >= width or neighbor_z >= depth:
                    continue
                if region_grid[neighbor_z][neighbor_x] != region_id:
                    continue
                neighbor_height = heights[neighbor_z][neighbor_x]
                if neighbor_height is None or neighbor_height == height:
                    continue
                edge = oriented_slope_edges(
                    ((int(height), int(neighbor_height)),)
                    if neighbor["z"] == 0
                    else ((int(height),), (int(neighbor_height),)),
                    x,
                    z,
                    [neighbor],
                )[0]
                edges_by_region.setdefault(region_id, set()).add(edge)
    return edges_by_region


def placement_priority(match: dict[str, Any], config: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -match["slopeDirectionCount"],
        -match["longestContinuousRun"],
        -match["slopeEdgeCount"],
        match["colorMatchType"] != config["color"]["exact_match"],
        match["colorDistance"],
        -len(match["coveredCells"]),
        match["partId"],
        match["zStud"],
        match["xStud"],
        match["rotationDegrees"],
    )


def select_replacement_placements(
    matches: list[dict[str, Any]],
    target_edges_by_region: dict[int, set[tuple[int, int, int, int, str, int]]],
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], set[tuple[int, int]], set[tuple[int, int, int, int, str, int]]]:
    selected = []
    covered: set[tuple[int, int]] = set()
    solved_edges: set[tuple[int, int, int, int, str, int]] = set()
    for region_id in sorted(target_edges_by_region):
        unresolved = set(target_edges_by_region[region_id])
        region_matches = [
            match
            for match in matches
            if match["regionId"] == region_id
            and match["basePlate"] >= int(config["minimum_base_height_plate"])
        ]
        while unresolved:
            compatible = [
                match
                for match in region_matches
                if set(match["coveredCells"]).isdisjoint(covered)
                and bool(set(match["solvedSlopeEdges"]) & unresolved)
            ]
            if not compatible:
                break
            placement = min(compatible, key=lambda match: placement_priority(match, config))
            selected.append({**placement, "placementRank": len(selected) + 1})
            covered.update(placement["coveredCells"])
            matched_edges = set(placement["solvedSlopeEdges"]) & unresolved
            solved_edges.update(matched_edges)
            unresolved.difference_update(matched_edges)
            region_matches.remove(placement)
    return selected, covered, solved_edges


def build_colored_replacement_plan(
    heightmap: dict[str, Any],
    pattern_records: tuple[dict[str, Any], ...],
    available_colors_by_part: dict[str, dict[int, dict[str, Any]]],
    config: dict[str, Any],
) -> dict[str, Any]:
    heights, colors = heightmap_grids(heightmap, config)
    region_grid, regions = color_connected_regions(colors, config)
    target_edges_by_region = target_slope_edges_by_region(heights, region_grid, config)
    width = len(heights[0])
    depth = len(heights)
    matches = []
    missing_colors = []
    geometric_match_count = 0
    for pattern_record in pattern_records:
        for variant in oriented_pattern_variants(pattern_record, config):
            pattern_height = variant["relativeHeights"]
            occupied_mask = variant["occupiedMask"]
            pattern_width = len(pattern_height[0])
            pattern_depth = len(pattern_height)
            for z in range(depth - pattern_depth + 1):
                for x in range(width - pattern_width + 1):
                    occupied_regions = {
                        region_grid[z + local_z][x + local_x]
                        for local_z, row in enumerate(occupied_mask)
                        for local_x, occupied in enumerate(row)
                        if occupied
                    }
                    if len(occupied_regions) != 1 or None in occupied_regions:
                        continue
                    target = normalized_target_heights(heights, occupied_mask, x, z)
                    if not pattern_matches(
                        target,
                        pattern_height,
                        int(config["maximum_height_error_plate"]),
                    ):
                        continue
                    geometric_match_count += 1
                    region_id = next(iter(occupied_regions))
                    target_color = regions[region_id]["targetColor"]
                    geometric_match = geometric_match_response(
                        pattern_record,
                        {**variant, "slopeNeighborConfig": config["slope_neighbors"]},
                        heights,
                        x,
                        z,
                        region_id,
                        target_color,
                    )
                    selected_color, missing_color_detail = select_part_color(
                        target_color,
                        available_colors_by_part.get(pattern_record["partId"], {}),
                        config,
                    )
                    if selected_color is None:
                        missing_colors.append(
                            {
                                **geometric_match,
                                **missing_color_detail,
                            }
                        )
                        continue
                    matches.append({**geometric_match, **selected_color})
    matches.sort(
        key=lambda match: (
            -match["slopeDirectionCount"],
            -match["slopeEdgeCount"],
            -match["longestContinuousRun"],
            match["colorDistance"],
            match["partId"],
            match["zStud"],
            match["xStud"],
            match["rotationDegrees"],
        )
    )
    missing_colors.sort(
        key=lambda item: (
            -item["slopeDirectionCount"],
            item["targetColor"],
            item["partId"],
            item["zStud"],
            item["xStud"],
        )
    )
    missing_summary_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in missing_colors:
        key = (
            item["targetColor"],
            item["partId"],
            item["widthStud"],
            item["depthStud"],
            tuple(item["slopeDirections"]),
            item["reason"],
        )
        if key not in missing_summary_by_key:
            summary = {
                "targetColor": item["targetColor"],
                "partId": item["partId"],
                "widthStud": item["widthStud"],
                "depthStud": item["depthStud"],
                "slopeDirections": item["slopeDirections"],
                "slopeDirectionCount": item["slopeDirectionCount"],
                "occurrenceCount": 0,
                "reason": item["reason"],
            }
            for optional_key in (
                "nearestColorId",
                "nearestColorName",
                "nearestColorRgb",
                "nearestColorDistance",
                "maximumSquaredDistance",
            ):
                if optional_key in item:
                    summary[optional_key] = item[optional_key]
            missing_summary_by_key[key] = summary
        missing_summary_by_key[key]["occurrenceCount"] += 1
    missing_summary = sorted(
        missing_summary_by_key.values(),
        key=lambda item: (
            -item["slopeDirectionCount"],
            -item["occurrenceCount"],
            item["targetColor"],
            item["partId"],
        ),
    )
    placements, covered_cells, solved_edges = select_replacement_placements(
        matches,
        target_edges_by_region,
        config,
    )
    target_edges = set().union(*target_edges_by_region.values()) if target_edges_by_region else set()
    unresolved_edges = sorted(target_edges - solved_edges)
    base_h = [list(row) for row in heights]
    for placement in placements:
        for x, z, base_height in placement["baseHeightCells"]:
            base_h[z][x] = base_height
    selected_keys = {
        (
            placement["candidateId"],
            placement["patternRank"],
            placement["xStud"],
            placement["zStud"],
            placement["rotationDegrees"],
        )
        for placement in placements
    }
    overlap_rejected_match_count = sum(
        (
            match["candidateId"],
            match["patternRank"],
            match["xStud"],
            match["zStud"],
            match["rotationDegrees"],
        )
        not in selected_keys
        and not set(match["coveredCells"]).isdisjoint(covered_cells)
        for match in matches
    )
    placed_cells = [cell for placement in placements for cell in placement["coveredCells"]]
    unsupported_placement_count = sum(
        any(base_h[z][x] < base_height for x, z, base_height in placement["baseHeightCells"])
        for placement in placements
    )
    return {
        "strategy": config["strategy"],
        "heightmapModelId": heightmap["modelId"],
        "widthStud": width,
        "depthStud": depth,
        "connectedRegionCount": len(regions),
        "connectedRegions": regions,
        "patternCount": len(pattern_records),
        "geometricMatchCount": geometric_match_count,
        "colorMatchedCount": len(matches),
        "colorSubstitutionCount": sum(
            match["colorMatchType"] == config["color"]["nearest_match"]
            for match in matches
        ),
        "missingColorRequirementCount": len(missing_colors),
        "missingColorRequirementTypeCount": len(missing_summary),
        "placementCount": len(placements),
        "placements": placements,
        "baseH": base_h,
        "targetSlopeEdgeCount": len(target_edges),
        "solvedSlopeEdgeCount": len(solved_edges),
        "unresolvedSlopeEdgeCount": len(unresolved_edges),
        "coveredCellCount": len(covered_cells),
        "unresolvedSlopeEdgeExamples": unresolved_edges[
            : int(config["maximum_unresolved_slope_edge_examples"])
        ],
        "validation": {
            "coordinateValidatedPlacementCount": len(placements),
            "colorValidatedPlacementCount": len(placements),
            "overlapCellCount": len(placed_cells) - len(set(placed_cells)),
            "unsupportedPlacementCount": unsupported_placement_count,
            "overlapRejectedMatchCount": overlap_rejected_match_count,
            "negativeBaseRejectedMatchCount": sum(
                match["basePlate"] < int(config["minimum_base_height_plate"])
                for match in matches
            ),
        },
        "matches": matches[: int(config["maximum_match_examples"])],
        "missingColorRequirements": missing_colors[
            : int(config["maximum_missing_color_examples"])
        ],
        "missingColorSummary": missing_summary,
    }


def load_pattern_records(session: Session, config: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    rows = session.execute(
        select(DemSlopeCandidatePattern, DemSlopeCandidate, LDrawPart)
        .join(
            DemSlopeCandidate,
            DemSlopeCandidate.id == DemSlopeCandidatePattern.candidate_id,
        )
        .join(LDrawPart, LDrawPart.id == DemSlopeCandidate.ldraw_part_id)
        .where(DemSlopeCandidate.candidate_enabled.is_(True))
        .where(DemSlopeCandidate.family.not_in(tuple(config["excluded_candidate_families"])))
        .order_by(
            DemSlopeCandidatePattern.pattern_rank,
            LDrawPart.ldraw_part_num,
        )
    ).all()
    return tuple(
        {
            "candidateId": int(candidate.id),
            "partId": part.ldraw_part_num,
            "patternRank": pattern.pattern_rank,
            "patternKey": pattern.pattern_key,
            "heightmapPattern": pattern.heightmap_pattern_json,
            "matchMetrics": pattern.match_metrics_json,
        }
        for pattern, candidate, part in rows
        if candidate_name_allowed(part.name or "", config)
    )


def candidate_name_allowed(name: str, config: dict[str, Any]) -> bool:
    return not any(
        re.search(pattern, name, re.IGNORECASE)
        for pattern in config["excluded_candidate_name_patterns"]
    )


def load_available_part_colors(
    session: Session,
    part_ids: set[str],
    config: dict[str, Any],
) -> dict[str, dict[int, dict[str, Any]]]:
    rows = session.execute(
        select(XrefPartNumber.ldraw_part_num, Color.id, Color.name, Color.rgb)
        .join(
            InventoryPart,
            InventoryPart.part_num == XrefPartNumber.rebrickable_part_num,
        )
        .join(Color, Color.id == InventoryPart.color_id)
        .where(XrefPartNumber.ldraw_part_num.in_(part_ids))
        .where(XrefPartNumber.relation_type == config["color"]["xref_relation"])
        .where(Color.is_trans == config["color"]["transparent"])
        .where(Color.rgb.is_not(None))
        .distinct()
    ).all()
    available: dict[str, dict[int, dict[str, Any]]] = {}
    for part_id, color_id, color_name, rgb in rows:
        available.setdefault(part_id, {})[color_id] = {
            "name": color_name,
            "rgb": rgb,
        }
    return available


def load_colored_replacement_plan(
    heightmap: dict[str, Any],
    engine: Engine,
    config: dict[str, Any],
) -> dict[str, Any]:
    with Session(engine) as session:
        patterns = load_pattern_records(session, config)
        colors = load_available_part_colors(
            session,
            {pattern["partId"] for pattern in patterns},
            config,
        )
    return build_colored_replacement_plan(heightmap, patterns, colors, config)
