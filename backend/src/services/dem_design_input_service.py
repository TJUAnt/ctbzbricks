"""Build backend-owned DEM design matrices from a stored terrain model."""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from src.model.models import Color, InventoryPart


def build_dem_design_targets(
    asset: dict[str, Any],
    scale: dict[str, Any],
    color_rgb_by_id: dict[int, str],
    config: dict[str, Any],
) -> dict[str, Any]:
    width_stud, depth_stud = design_grid_size(asset["bounds"], scale, config)
    buckets = [
        {"sample_count": 0, "elevations": [], "land_cover_codes": []}
        for _cell in range(width_stud * depth_stud)
    ]
    for row_index in range(asset["rows"]):
        for column_index in range(asset["columns"]):
            bucket = buckets[
                design_cell_index(
                    row_index,
                    column_index,
                    asset["rows"],
                    asset["columns"],
                    width_stud,
                    depth_stud,
                )
            ]
            bucket["sample_count"] += 1
            sample_index = row_index * asset["columns"] + column_index
            elevation = asset["elevations"][sample_index]
            if elevation is None:
                continue
            bucket["elevations"].append(elevation)
            land_cover = asset.get("landCover")
            if land_cover is not None and land_cover[sample_index] is not None:
                bucket["land_cover_codes"].append(land_cover[sample_index])

    heights = []
    colors = []
    for z_stud in range(depth_stud):
        height_row = []
        color_row = []
        for x_stud in range(width_stud):
            bucket = buckets[z_stud * width_stud + x_stud]
            coverage = rounded_ratio(
                len(bucket["elevations"]) / max(config["minimum_stud_count"], bucket["sample_count"]),
                config,
            )
            if not bucket["elevations"] or coverage < scale["minimum_coverage_ratio"]:
                height_row.append(config["empty_elevation_height_plate"])
                color_row.append(config["default_color_id"])
                continue
            elevation = aggregate_elevations(bucket["elevations"], scale["aggregation"], config)
            height_row.append(
                max(
                    config["minimum_plate_height"],
                    round(
                        (elevation - asset["minElevation"])
                        / scale["vertical_meters_per_plate"]
                    ),
                )
            )
            source_color = dominant_land_cover_color(
                bucket["land_cover_codes"],
                asset.get("landCoverLegend", {}),
            )
            color_row.append(
                config["default_color_id"]
                if source_color is None
                else nearest_color_id(source_color, color_rgb_by_id, config)
            )
        heights.append(height_row)
        colors.append(color_row)

    raised_heights = [
        [height + config["minimum_surface_height_plate"] for height in row]
        for row in heights
    ]
    return {
        "targetHeightPlate": raised_heights,
        "targetSurfacePlate": interpolated_surface(raised_heights, config),
        "targetColorId": colors,
        "partIds": list(config["part_ids"]),
    }


def load_dem_design_targets(
    asset: dict[str, Any],
    scale: dict[str, Any],
    engine: Engine,
    config: dict[str, Any],
) -> dict[str, Any]:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        colors = session.execute(
            select(Color.id, Color.rgb).where(
                Color.rgb.is_not(None),
                Color.is_trans.is_(False),
            )
            .join(InventoryPart, InventoryPart.color_id == Color.id)
            .where(InventoryPart.part_num == config["surface_color_reference_part_num"])
            .distinct()
        ).all()
    return build_dem_design_targets(
        asset,
        scale,
        {color_id: rgb.upper() for color_id, rgb in colors},
        config,
    )


def design_grid_size(
    bounds: dict[str, float],
    scale: dict[str, Any],
    config: dict[str, Any],
) -> tuple[int, int]:
    middle_latitude = (
        bounds["north"] + bounds["south"]
    ) / config["coordinate_average_divisor"]
    depth_km = (
        (bounds["north"] - bounds["south"])
        * config["latitude_meters_per_degree"]
        * config["kilometers_per_meter"]
    )
    width_km = (
        (bounds["east"] - bounds["west"])
        * config["latitude_meters_per_degree"]
        * math.cos(middle_latitude * config["radians_per_degree"])
        * config["kilometers_per_meter"]
    )
    return (
        max(config["minimum_stud_count"], math.ceil(width_km / scale["horizontal_km_per_stud"])),
        max(config["minimum_stud_count"], math.ceil(depth_km / scale["horizontal_km_per_stud"])),
    )


def design_cell_index(
    row_index: int,
    column_index: int,
    row_count: int,
    column_count: int,
    width_stud: int,
    depth_stud: int,
) -> int:
    x_stud = min(
        width_stud - 1,
        math.floor((column_index / (column_count - 1)) * width_stud),
    )
    z_stud = min(
        depth_stud - 1,
        math.floor((row_index / (row_count - 1)) * depth_stud),
    )
    return z_stud * width_stud + x_stud


def aggregate_elevations(
    elevations: list[float],
    aggregation: str,
    config: dict[str, Any],
) -> float:
    if aggregation == config["aggregations"]["mean"]:
        return sum(elevations) / len(elevations)
    if aggregation == config["aggregations"]["maximum"]:
        return max(elevations)
    if aggregation == config["aggregations"]["percentile"]:
        ordered = sorted(elevations)
        index = math.ceil((len(ordered) - 1) * config["percentile_ratio"])
        return ordered[index]
    raise ValueError(config["errors"]["aggregation_invalid"])


def dominant_land_cover_color(
    codes: list[int],
    legend: dict[str, dict[str, Any]],
) -> str | None:
    if not codes:
        return None
    counts = {code: codes.count(code) for code in set(codes)}
    selected = min(counts, key=lambda code: (-counts[code], code))
    item = legend.get(str(selected))
    return None if item is None else item["color"]


def nearest_color_id(
    source_color: str,
    color_rgb_by_id: dict[int, str],
    config: dict[str, Any],
) -> int:
    source = color_channels(source_color, config)
    return min(
        color_rgb_by_id,
        key=lambda color_id: (
            sum(
                (left - right) ** config["color_distance_exponent"]
                for left, right in zip(source, color_channels(color_rgb_by_id[color_id], config))
            ),
            color_id,
        ),
    )


def color_channels(color: str, config: dict[str, Any]) -> tuple[int, int, int]:
    value = color.removeprefix(config["color_hex_prefix"])
    channels = config["color_channels"]
    return (
        int(value[channels["red_start"] : channels["red_end"]], config["color_hex_radix"]),
        int(value[channels["green_start"] : channels["green_end"]], config["color_hex_radix"]),
        int(value[channels["blue_start"] : channels["blue_end"]], config["color_hex_radix"]),
    )


def interpolated_surface(
    heights: list[list[int]],
    config: dict[str, Any],
) -> list[list[float]]:
    sample_rate = config["samples_per_stud_axis"]
    return [
        [
            rounded_surface_height(
                interpolated_height(heights, sample_x, sample_z, config),
                config,
            )
            for sample_x in range(len(heights[0]) * sample_rate)
        ]
        for sample_z in range(len(heights) * sample_rate)
    ]


def interpolated_height(
    heights: list[list[int]],
    sample_x: int,
    sample_z: int,
    config: dict[str, Any],
) -> float:
    sample_rate = config["samples_per_stud_axis"]
    grid_x = (sample_x + config["sample_center_fraction"]) / sample_rate - config["stud_center_offset"]
    grid_z = (sample_z + config["sample_center_fraction"]) / sample_rate - config["stud_center_offset"]
    minimum_x = max(0, math.floor(grid_x))
    maximum_x = min(len(heights[0]) - 1, math.ceil(grid_x))
    minimum_z = max(0, math.floor(grid_z))
    maximum_z = min(len(heights) - 1, math.ceil(grid_z))
    x_ratio = max(0, min(1, grid_x - minimum_x))
    z_ratio = max(0, min(1, grid_z - minimum_z))
    upper = heights[minimum_z][minimum_x] * (1 - x_ratio) + heights[minimum_z][maximum_x] * x_ratio
    lower = heights[maximum_z][minimum_x] * (1 - x_ratio) + heights[maximum_z][maximum_x] * x_ratio
    return upper * (1 - z_ratio) + lower * z_ratio


def rounded_surface_height(height: float, config: dict[str, Any]) -> float:
    factor = config["decimal_radix"] ** config["surface_precision"]
    return round(height * factor) / factor


def rounded_ratio(ratio: float, config: dict[str, Any]) -> float:
    return round(ratio * config["coverage_precision"]) / config["coverage_precision"]
