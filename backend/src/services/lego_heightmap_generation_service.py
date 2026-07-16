"""Generate a persisted-ready colored LEGO heightmap from a DEM asset."""

from __future__ import annotations

import math
from typing import Any


def create_colored_heightmap_asset(
    dem_asset: dict[str, Any],
    source_dem_model_id: str,
    scale: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    generation_config = config["heightmap_generation"]
    validate_dem_land_cover(dem_asset, config)
    width_km, depth_km = terrain_bounds_size(dem_asset["bounds"], generation_config)
    width_stud = max(
        int(generation_config["minimum_stud_count"]),
        math.ceil(width_km / float(scale["horizontalKmPerStud"])),
    )
    depth_stud = max(
        int(generation_config["minimum_stud_count"]),
        math.ceil(depth_km / float(scale["horizontalKmPerStud"])),
    )
    buckets = [
        {"sample_count": 0, "elevations": [], "land_cover_codes": []}
        for _ in range(width_stud * depth_stud)
    ]
    populate_buckets(dem_asset, buckets, width_stud, depth_stud)
    cells = [
        height_cell_from_bucket(
            bucket,
            index,
            width_stud,
            dem_asset,
            scale,
            config,
        )
        for index, bucket in enumerate(buckets)
    ]
    valid_cells = [cell for cell in cells if cell["elevationMeters"] is not None]
    minimum_plate_height = int(generation_config["minimum_plate_height"])
    minimum_stud_count = int(generation_config["minimum_stud_count"])
    max_height_plate = max(
        minimum_plate_height,
        *(cell["heightPlate"] for cell in valid_cells),
    )
    average_coverage_ratio = rounded_coverage_ratio(
        sum(cell["coverageRatio"] for cell in valid_cells)
        / max(minimum_stud_count, len(valid_cells)),
        generation_config,
    )
    return {
        "schema": config["heightmap_asset_schema"],
        "source": dem_asset["source"],
        "sourceDemModelId": source_dem_model_id,
        "bounds": dem_asset["bounds"],
        "scale": scale,
        "cells": cells,
        "metrics": {
            "widthKm": width_km,
            "depthKm": depth_km,
            "widthStud": width_stud,
            "depthStud": depth_stud,
            "maxHeightPlate": max_height_plate,
            "validCellCount": len(valid_cells),
            "totalCellCount": len(cells),
            "averageCoverageRatio": average_coverage_ratio,
        },
    }


def validate_dem_land_cover(dem_asset: dict[str, Any], config: dict[str, Any]) -> None:
    land_cover = dem_asset.get("landCover")
    if land_cover is None or len(land_cover) != len(dem_asset["elevations"]):
        raise ValueError(config["errors"]["missing_heightmap_land_cover"])
    if not dem_asset.get("landCoverLegend"):
        raise ValueError(config["errors"]["missing_heightmap_land_cover_color"])


def terrain_bounds_size(bounds: dict[str, float], config: dict[str, Any]) -> tuple[float, float]:
    latitude_span = bounds["north"] - bounds["south"]
    longitude_span = bounds["east"] - bounds["west"]
    middle_latitude = (
        bounds["north"] + bounds["south"]
    ) / float(config["coordinate_average_divisor"])
    depth_meters = latitude_span * float(config["latitude_meters_per_degree"])
    width_meters = (
        longitude_span
        * float(config["latitude_meters_per_degree"])
        * math.cos(middle_latitude * float(config["radians_per_degree"]))
    )
    kilometers_per_meter = float(config["kilometers_per_meter"])
    return width_meters * kilometers_per_meter, depth_meters * kilometers_per_meter


def populate_buckets(
    dem_asset: dict[str, Any],
    buckets: list[dict[str, Any]],
    width_stud: int,
    depth_stud: int,
) -> None:
    columns = int(dem_asset["columns"])
    rows = int(dem_asset["rows"])
    elevations = dem_asset["elevations"]
    land_cover = dem_asset["landCover"]
    for row_index in range(rows):
        for column_index in range(columns):
            sample_index = row_index * columns + column_index
            stud_x = min(
                width_stud - 1,
                math.floor(column_index / (columns - 1) * width_stud),
            )
            stud_z = min(
                depth_stud - 1,
                math.floor(row_index / (rows - 1) * depth_stud),
            )
            bucket = buckets[stud_z * width_stud + stud_x]
            bucket["sample_count"] += 1
            elevation = elevations[sample_index]
            if elevation is None:
                continue
            bucket["elevations"].append(float(elevation))
            land_cover_code = land_cover[sample_index]
            if land_cover_code is not None:
                bucket["land_cover_codes"].append(int(land_cover_code))


def height_cell_from_bucket(
    bucket: dict[str, Any],
    index: int,
    width_stud: int,
    dem_asset: dict[str, Any],
    scale: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    generation_config = config["heightmap_generation"]
    coverage_ratio = rounded_coverage_ratio(
        len(bucket["elevations"])
        / max(int(generation_config["minimum_stud_count"]), bucket["sample_count"]),
        generation_config,
    )
    cell = {
        "x": index % width_stud,
        "z": index // width_stud,
        "heightPlate": int(generation_config["empty_elevation_height_plate"]),
        "elevationMeters": None,
        "landCoverCode": None,
        "landCoverColor": None,
        "coverageRatio": coverage_ratio,
    }
    if not bucket["elevations"] or coverage_ratio < float(scale["minCoverageRatio"]):
        return cell
    land_cover_code = dominant_land_cover_code(bucket["land_cover_codes"], config)
    legend_entry = dem_asset["landCoverLegend"].get(str(land_cover_code))
    if legend_entry is None or not legend_entry.get("color"):
        raise ValueError(config["errors"]["missing_heightmap_land_cover_color"])
    elevation_meters = aggregate_elevations(
        bucket["elevations"],
        scale["aggregation"],
        generation_config,
        config["errors"]["invalid_heightmap_aggregation"],
    )
    normalized_height = (
        elevation_meters - float(dem_asset["minElevation"])
    ) / float(scale["verticalMetersPerPlate"])
    return {
        **cell,
        "heightPlate": max(
            int(generation_config["minimum_plate_height"]),
            math.floor(normalized_height + float(generation_config["rounding_offset"])),
        ),
        "elevationMeters": elevation_meters,
        "landCoverCode": land_cover_code,
        "landCoverColor": legend_entry["color"],
    }


def aggregate_elevations(
    elevations: list[float],
    aggregation: str,
    generation_config: dict[str, Any],
    invalid_aggregation_message: str,
) -> float:
    aggregation_config = generation_config["aggregation"]
    if aggregation == aggregation_config["mean"]:
        return sum(elevations) / len(elevations)
    if aggregation == aggregation_config["max"]:
        return max(elevations)
    if aggregation == aggregation_config["percentile"]:
        sorted_elevations = sorted(elevations)
        percentile_index = math.ceil(
            (len(sorted_elevations) - 1) * float(generation_config["percentile_ratio"])
        )
        return sorted_elevations[percentile_index]
    raise ValueError(invalid_aggregation_message)


def dominant_land_cover_code(land_cover_codes: list[int], config: dict[str, Any]) -> int:
    if not land_cover_codes:
        raise ValueError(config["errors"]["missing_heightmap_land_cover"])
    counts: dict[int, int] = {}
    for land_cover_code in land_cover_codes:
        counts[land_cover_code] = counts.get(land_cover_code, 0) + 1
    return min(counts, key=lambda land_cover_code: (-counts[land_cover_code], land_cover_code))


def rounded_coverage_ratio(ratio: float, config: dict[str, Any]) -> float:
    precision = int(config["coverage_precision"])
    return math.floor(ratio * precision + float(config["rounding_offset"])) / precision
