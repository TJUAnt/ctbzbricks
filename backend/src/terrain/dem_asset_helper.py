"""Build DEM terrain assets from GeoJSON and raster elevation data."""

from __future__ import annotations

import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from glob import glob
from pathlib import Path
from typing import Any, Callable, Iterable
from uuid import uuid4


Coordinate = tuple[float, float]
Ring = list[Coordinate]
Polygon = list[Ring]
MultiPolygon = list[Polygon]
ProgressReporter = Callable[[int], None]
PolygonGridTask = tuple[
    Polygon,
    tuple[float, float, float, float],
    int,
    int,
    int,
    int,
    int,
    int,
]


def load_json(path: Path, encoding: str) -> dict[str, Any]:
    with path.open(encoding=encoding) as source:
        return json.load(source)


def feature_collection_polygons(geojson: dict[str, Any]) -> MultiPolygon:
    polygons: MultiPolygon = []
    for feature in geojson["features"]:
        geometry = feature["geometry"]
        geometry_type = geometry["type"]
        coordinates = geometry["coordinates"]
        if geometry_type == "Polygon":
            polygons.append(_polygon_from_coordinates(coordinates))
        elif geometry_type == "MultiPolygon":
            polygons.extend(_polygon_from_coordinates(polygon) for polygon in coordinates)
        else:
            raise ValueError(f"Unsupported geometry type: {geometry_type}")
    return polygons


def _polygon_from_coordinates(coordinates: Iterable[Iterable[Iterable[float]]]) -> Polygon:
    return [[(float(point[0]), float(point[1])) for point in ring] for ring in coordinates]


def multipolygon_bounds(polygons: MultiPolygon) -> tuple[float, float, float, float]:
    points = [point for polygon in polygons for ring in polygon for point in ring]
    longitudes = [point[0] for point in points]
    latitudes = [point[1] for point in points]
    return min(longitudes), min(latitudes), max(longitudes), max(latitudes)


def point_in_polygon(point: Coordinate, polygon: Polygon) -> bool:
    outer_ring = polygon[0]
    hole_rings = polygon[1:]
    return point_in_ring(point, outer_ring) and not any(
        point_in_ring(point, hole_ring) for hole_ring in hole_rings
    )


def point_in_ring(point: Coordinate, ring: Ring) -> bool:
    longitude, latitude = point
    inside = False
    previous_longitude, previous_latitude = ring[-1]
    for current_longitude, current_latitude in ring:
        crosses_latitude = (current_latitude > latitude) != (previous_latitude > latitude)
        if crosses_latitude:
            intersection_longitude = (
                (previous_longitude - current_longitude)
                * (latitude - current_latitude)
                / (previous_latitude - current_latitude)
                + current_longitude
            )
            if longitude < intersection_longitude:
                inside = not inside
        previous_longitude = current_longitude
        previous_latitude = current_latitude
    return inside


def terrain_grid_dimensions(bounds: tuple[float, float, float, float], config: dict[str, Any]) -> tuple[int, int]:
    west, south, east, north = bounds
    latitude_span = north - south
    longitude_span = east - west
    middle_latitude = (north + south) / int(config["coordinate_average_divisor"])
    north_south_meters = latitude_span * float(config["latitude_meters_per_degree"])
    east_west_meters = (
        longitude_span
        * float(config["latitude_meters_per_degree"])
        * math.cos(middle_latitude * float(config["radians_per_degree"]))
    )
    spacing = float(config["target_sample_spacing_meters"])
    return math.ceil(east_west_meters / spacing) + 1, math.ceil(north_south_meters / spacing) + 1


def rounded_rings(polygons: MultiPolygon, coordinate_decimals: int) -> list[list[list[list[float]]]]:
    return [
        [
            [
                [round(longitude, coordinate_decimals), round(latitude, coordinate_decimals)]
                for longitude, latitude in ring
            ]
            for ring in polygon
        ]
        for polygon in polygons
    ]


def build_asset(config: dict[str, Any], project_root: Path) -> dict[str, Any]:
    geojson = load_json(project_root / config["geojson_path"], config["text_encoding"])
    config_with_resolved_path = {
        **config,
        "dem_datasets": {
            **config["dem_datasets"],
            "options": [
                {
                    **dataset,
                    "dataset_path": str(project_root / dataset["dataset_path"]),
                }
                for dataset in config["dem_datasets"]["options"]
            ],
        },
        "worldcover": {
            **config["worldcover"],
            "dataset_glob": str(project_root / config["worldcover"]["dataset_glob"]),
        },
    }
    return build_asset_from_geojson(
        config_with_resolved_path,
        geojson,
        config["dem_datasets"]["default_key"],
        config["default_source_name"],
    )


def build_asset_from_geojson(
    config: dict[str, Any],
    geojson: dict[str, Any],
    dem_dataset_key: str,
    source_name: str,
    progress_reporter: ProgressReporter | None = None,
) -> dict[str, Any]:
    import rasterio

    dem_dataset = dem_dataset_config(config, dem_dataset_key)
    generation_config = {
        **config,
        "target_sample_spacing_meters": dem_dataset["target_sample_spacing_meters"],
    }
    report_progress(config, progress_reporter, "polygons")
    polygons = feature_collection_polygons(geojson)
    bounds = multipolygon_bounds(polygons)
    columns, rows = terrain_grid_dimensions(bounds, generation_config)
    report_progress(config, progress_reporter, "coordinates")
    indexed_coordinates = polygon_grid_coordinates(polygons, bounds, columns, rows, generation_config)

    with rasterio.open(dem_dataset["dataset_path"]) as dataset:
        elevations = build_indexed_elevations(
            dataset,
            indexed_coordinates,
            columns,
            rows,
            generation_config,
            progress_reporter,
        )
    valid_elevations = [elevation for elevation in elevations if elevation is not None]
    if not valid_elevations:
        raise ValueError("GeoJSON does not overlap DEM data")

    west, south, east, north = bounds
    return {
        "schema": config["asset_schema"],
        "source": terrain_source_label(source_name, dem_dataset, config),
        "columns": columns,
        "rows": rows,
        "bounds": {
            "west": round(west, int(config["coordinate_decimals"])),
            "south": round(south, int(config["coordinate_decimals"])),
            "east": round(east, int(config["coordinate_decimals"])),
            "north": round(north, int(config["coordinate_decimals"])),
        },
        "minElevation": min(valid_elevations),
        "maxElevation": max(valid_elevations),
        "renderOptions": {
            "verticalExaggeration": config["render_options"]["default_vertical_exaggeration"],
        },
        "elevations": elevations,
        **build_worldcover_land_cover(config, bounds, indexed_coordinates, elevations),
        "boundary": rounded_rings(polygons, int(config["coordinate_decimals"])),
    }


def dem_dataset_config(config: dict[str, Any], dem_dataset_key: str) -> dict[str, Any]:
    for dem_dataset in config["dem_datasets"]["options"]:
        if dem_dataset["key"] == dem_dataset_key:
            return dem_dataset
    raise ValueError(config["errors"]["invalid_dem_dataset"])


def terrain_source_label(source_name: str, dem_dataset: dict[str, Any], config: dict[str, Any]) -> str:
    return source_name + config["source_name_dataset_separator"] + dem_dataset["label"]


def build_polygon_masked_elevations(
    dataset: Any,
    polygons: MultiPolygon,
    bounds: tuple[float, float, float, float],
    columns: int,
    rows: int,
    config: dict[str, Any],
    progress_reporter: ProgressReporter | None,
) -> list[float | None]:
    indexed_coordinates = polygon_grid_coordinates(polygons, bounds, columns, rows, config)
    return build_indexed_elevations(
        dataset,
        indexed_coordinates,
        columns,
        rows,
        config,
        progress_reporter,
    )


def build_indexed_elevations(
    dataset: Any,
    indexed_coordinates: list[tuple[int, Coordinate]],
    columns: int,
    rows: int,
    config: dict[str, Any],
    progress_reporter: ProgressReporter | None,
) -> list[float | None]:
    elevations: list[float | None] = [None] * (columns * rows)
    if not indexed_coordinates:
        report_progress(config, progress_reporter, "sampling_end")
        report_progress(config, progress_reporter, "masking")
        return elevations

    sampled_values = sample_dem_values(
        dataset,
        [coordinate for _, coordinate in indexed_coordinates],
        config,
        progress_reporter,
    )
    nodata_value = float(config["nodata_value"])
    elevation_decimals = int(config["elevation_decimals"])
    for (elevation_index, _), sampled_value in zip(indexed_coordinates, sampled_values):
        if sampled_value != nodata_value:
            elevations[elevation_index] = round(float(sampled_value), elevation_decimals)
    report_progress(config, progress_reporter, "masking")
    return elevations


def build_worldcover_land_cover(
    config: dict[str, Any],
    bounds: tuple[float, float, float, float],
    indexed_coordinates: list[tuple[int, Coordinate]],
    elevations: list[float | None],
) -> dict[str, Any]:
    import rasterio

    worldcover_config = config["worldcover"]
    land_cover: list[int | None] = [None] * len(elevations)
    legend: dict[str, Any] = {}
    for dataset_path in worldcover_dataset_paths(worldcover_config):
        with rasterio.open(dataset_path) as dataset:
            if not bounds_overlap(bounds, dataset_bounds_tuple(dataset.bounds)):
                continue
            sampled_land_cover, sampled_legend = sample_worldcover_land_cover(
                dataset,
                worldcover_config,
                indexed_coordinates,
                elevations,
            )
        for index, class_code in enumerate(sampled_land_cover):
            if class_code is not None:
                land_cover[index] = class_code
        legend.update(sampled_legend)
    if not legend:
        return land_cover_asset_fields(land_cover, {}, None)
    return land_cover_asset_fields(land_cover, legend, worldcover_config["dataset_glob"])


def worldcover_dataset_paths(worldcover_config: dict[str, Any]) -> list[str]:
    return sorted(glob(worldcover_config["dataset_glob"]))


def sample_worldcover_land_cover(
    dataset: Any,
    worldcover_config: dict[str, Any],
    indexed_coordinates: list[tuple[int, Coordinate]],
    elevations: list[float | None],
) -> tuple[list[int | None], dict[str, Any]]:
    land_cover: list[int | None] = [None] * len(elevations)
    sample_targets = [
        (elevation_index, coordinate)
        for elevation_index, coordinate in indexed_coordinates
        if elevations[elevation_index] is not None
    ]
    if not sample_targets:
        return land_cover, {}
    sampled_values = [sample[0] for sample in dataset.sample([coordinate for _, coordinate in sample_targets])]
    nodata_value = int(worldcover_config["nodata_value"])
    class_colors = worldcover_config["class_colors"]
    used_classes: set[str] = set()
    for (elevation_index, _), sampled_value in zip(sample_targets, sampled_values):
        class_code = int(sampled_value)
        class_key = str(class_code)
        if class_code != nodata_value and class_key in class_colors:
            land_cover[elevation_index] = class_code
            used_classes.add(class_key)
    legend = {class_key: class_colors[class_key] for class_key in sorted(used_classes)}
    return land_cover, legend


def land_cover_asset_fields(
    land_cover: list[int | None],
    legend: dict[str, Any],
    source: str | None,
) -> dict[str, Any]:
    return {
        "landCover": land_cover,
        "landCoverLegend": legend,
        "landCoverSource": source,
    }


def dataset_bounds_tuple(bounds: Any) -> tuple[float, float, float, float]:
    return bounds.left, bounds.bottom, bounds.right, bounds.top


def bounds_overlap(
    first_bounds: tuple[float, float, float, float],
    second_bounds: tuple[float, float, float, float],
) -> bool:
    first_west, first_south, first_east, first_north = first_bounds
    second_west, second_south, second_east, second_north = second_bounds
    return (
        first_west < second_east
        and first_east > second_west
        and first_south < second_north
        and first_north > second_south
    )


def polygon_grid_coordinates(
    polygons: MultiPolygon,
    bounds: tuple[float, float, float, float],
    columns: int,
    rows: int,
    config: dict[str, Any],
) -> list[tuple[int, Coordinate]]:
    tasks = polygon_grid_tasks(
        polygons,
        bounds,
        columns,
        rows,
        int(config["mask_rows_per_task"]),
    )
    worker_count = int(config["mask_worker_count"])
    if worker_count == 1:
        task_results = [polygon_grid_coordinates_for_task(task) for task in tasks]
    else:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            task_results = list(executor.map(polygon_grid_coordinates_for_task, tasks))
    return deduplicated_indexed_coordinates(task_results)


def polygon_grid_tasks(
    polygons: MultiPolygon,
    bounds: tuple[float, float, float, float],
    columns: int,
    rows: int,
    rows_per_task: int,
) -> list[PolygonGridTask]:
    tasks: list[PolygonGridTask] = []
    for polygon in polygons:
        west_column, east_column, north_row, south_row = polygon_grid_window(
            multipolygon_bounds([polygon]),
            bounds,
            columns,
            rows,
        )
        for task_start_row in range(north_row, south_row + 1, rows_per_task):
            task_end_row = min(task_start_row + rows_per_task - 1, south_row)
            tasks.append(
                (
                    polygon,
                    bounds,
                    columns,
                    rows,
                    west_column,
                    east_column,
                    task_start_row,
                    task_end_row,
                )
            )
    return tasks


def polygon_grid_coordinates_for_task(task: PolygonGridTask) -> list[tuple[int, Coordinate]]:
    (
        polygon,
        bounds,
        columns,
        rows,
        west_column,
        east_column,
        start_row,
        end_row,
    ) = task
    indexed_coordinates: list[tuple[int, Coordinate]] = []
    for row_index in range(start_row, end_row + 1):
        for column_index in range(west_column, east_column + 1):
            elevation_index = row_index * columns + column_index
            coordinate = grid_coordinate(bounds, columns, rows, column_index, row_index)
            if point_in_polygon(coordinate, polygon):
                indexed_coordinates.append((elevation_index, coordinate))
    return indexed_coordinates


def deduplicated_indexed_coordinates(
    task_results: list[list[tuple[int, Coordinate]]],
) -> list[tuple[int, Coordinate]]:
    indexed_coordinates: list[tuple[int, Coordinate]] = []
    sampled_indexes: set[int] = set()
    for task_coordinates in task_results:
        for elevation_index, coordinate in task_coordinates:
            if elevation_index not in sampled_indexes:
                sampled_indexes.add(elevation_index)
                indexed_coordinates.append((elevation_index, coordinate))
    return indexed_coordinates


def polygon_grid_window(
    polygon_bounds: tuple[float, float, float, float],
    terrain_bounds: tuple[float, float, float, float],
    columns: int,
    rows: int,
) -> tuple[int, int, int, int]:
    terrain_west, terrain_south, terrain_east, terrain_north = terrain_bounds
    polygon_west, polygon_south, polygon_east, polygon_north = polygon_bounds
    longitude_step_count = columns - 1
    latitude_step_count = rows - 1
    west_column = max(
        0,
        math.ceil((polygon_west - terrain_west) / (terrain_east - terrain_west) * longitude_step_count),
    )
    east_column = min(
        columns - 1,
        math.floor((polygon_east - terrain_west) / (terrain_east - terrain_west) * longitude_step_count),
    )
    north_row = max(
        0,
        math.ceil((terrain_north - polygon_north) / (terrain_north - terrain_south) * latitude_step_count),
    )
    south_row = min(
        rows - 1,
        math.floor((terrain_north - polygon_south) / (terrain_north - terrain_south) * latitude_step_count),
    )
    return west_column, east_column, north_row, south_row


def grid_coordinate(
    bounds: tuple[float, float, float, float],
    columns: int,
    rows: int,
    column_index: int,
    row_index: int,
) -> Coordinate:
    west, south, east, north = bounds
    longitude_ratio = column_index / (columns - 1)
    latitude_ratio = row_index / (rows - 1)
    return (
        west + (east - west) * longitude_ratio,
        north + (south - north) * latitude_ratio,
    )


def sample_dem_values(
    dataset: Any,
    coordinates: list[Coordinate],
    config: dict[str, Any],
    progress_reporter: ProgressReporter | None,
) -> list[float]:
    sampled_values: list[float] = []
    chunk_size = int(config["sample_chunk_size"])
    sampling_start = int(config["progress"]["sampling_start"])
    sampling_end = int(config["progress"]["sampling_end"])
    total_coordinates = len(coordinates)
    for chunk_start in range(0, total_coordinates, chunk_size):
        chunk = coordinates[chunk_start : chunk_start + chunk_size]
        sampled_values.extend(sample[0] for sample in dataset.sample(chunk))
        sampled_count = min(chunk_start + chunk_size, total_coordinates)
        progress = sampling_start + int(
            (sampling_end - sampling_start) * sampled_count / total_coordinates
        )
        if progress_reporter:
            progress_reporter(progress)
    return sampled_values


def save_model_asset(config: dict[str, Any], asset: dict[str, Any], model_name: str) -> dict[str, Any]:
    model_id = uuid4().hex[: int(config["model_id_hex_length"])]
    created_at = datetime.now(timezone.utc).isoformat()
    asset["modelId"] = model_id
    asset["createdAt"] = created_at
    asset["name"] = model_name
    metadata = model_metadata(model_id, created_at, asset)
    model_path(config, model_id).write_text(
        json.dumps(asset, ensure_ascii=False, separators=(",", ":")),
        encoding=config["text_encoding"],
    )
    return metadata


def list_model_metadata(config: dict[str, Any]) -> list[dict[str, Any]]:
    store_path = Path(config["model_store_path"])
    store_path.mkdir(parents=True, exist_ok=True)
    models = []
    for asset_path in store_path.glob(f"*{config['model_file_extension']}"):
        asset = json.loads(asset_path.read_text(encoding=config["text_encoding"]))
        if asset["schema"] == config["asset_schema"]:
            models.append(model_metadata(asset["modelId"], asset["createdAt"], asset))
    return sorted(models, key=lambda model: model["createdAt"], reverse=True)


def load_model_asset(config: dict[str, Any], model_id: str) -> dict[str, Any]:
    path = model_path(config, model_id)
    if not path.exists():
        raise ValueError(config["errors"]["invalid_dem_model"])
    asset = json.loads(path.read_text(encoding=config["text_encoding"]))
    if asset["schema"] != config["asset_schema"]:
        raise ValueError(config["errors"]["invalid_dem_model"])
    return asset


def model_path(config: dict[str, Any], model_id: str) -> Path:
    store_path = Path(config["model_store_path"])
    store_path.mkdir(parents=True, exist_ok=True)
    return store_path / f"{model_id}{config['model_file_extension']}"


def model_metadata(model_id: str, created_at: str, asset: dict[str, Any]) -> dict[str, Any]:
    return {
        "modelId": model_id,
        "name": asset.get("name", asset["source"]),
        "source": asset["source"],
        "createdAt": created_at,
        "columns": asset["columns"],
        "rows": asset["rows"],
        "minElevation": asset["minElevation"],
        "maxElevation": asset["maxElevation"],
        "validSampleCount": sum(elevation is not None for elevation in asset["elevations"]),
        "renderOptions": asset.get("renderOptions"),
    }


def report_progress(
    config: dict[str, Any], progress_reporter: ProgressReporter | None, progress_key: str
) -> None:
    if progress_reporter:
        progress_reporter(int(config["progress"][progress_key]))


def write_asset(asset: dict[str, Any], output_path: Path, encoding: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding=encoding) as destination:
        json.dump(asset, destination, ensure_ascii=False, separators=(",", ":"))


def main(argv: list[str]) -> int:
    config_path = Path(argv[1])
    project_root = Path(argv[2])
    config = load_json(project_root / config_path, "utf-8")
    asset = build_asset(config, project_root)
    write_asset(asset, project_root / config["output_path"], config["text_encoding"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
