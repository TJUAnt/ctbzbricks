"""Unit tests for DEM terrain asset helpers."""

import tempfile
import unittest
from pathlib import Path

from src.terrain.dem_asset_helper import (
    bounds_overlap,
    build_polygon_masked_elevations,
    dem_dataset_config,
    list_model_metadata,
    load_model_asset,
    multipolygon_bounds,
    point_in_polygon,
    point_in_ring,
    sample_dem_values,
    sample_worldcover_land_cover,
    save_model_asset,
    terrain_grid_dimensions,
    terrain_source_label,
    worldcover_dataset_paths,
)


TERRAIN_TEST_CONFIG = {
    "bounds": (120.0, 22.0, 122.0, 24.0),
    "columns": 3,
    "rows": 3,
    "nodata_value": -32768.0,
    "elevation_decimals": 1,
    "target_sample_spacing_meters": 100,
    "latitude_meters_per_degree": 100,
    "radians_per_degree": 0.017453292519943295,
    "coordinate_average_divisor": 2,
    "sample_chunk_size": 2,
    "mask_worker_count": 2,
    "mask_rows_per_task": 2,
    "progress": {
        "sampling_start": 30,
        "sampling_end": 70,
    },
    "model_file_extension": ".json",
    "model_id_hex_length": 32,
    "text_encoding": "utf-8",
    "asset_schema": "terrain-dem-v1",
    "source_name_dataset_separator": " + ",
    "dem_datasets": {
        "options": [
            {
                "key": "dem_1km",
                "label": "DEM 1km",
                "dataset_path": "dem_1km",
                "target_sample_spacing_meters": 1000,
            },
            {
                "key": "dem_250m",
                "label": "DEM 250m",
                "dataset_path": "dem_250m",
                "target_sample_spacing_meters": 250,
            },
        ],
    },
    "errors": {
        "invalid_dem_dataset": "invalid DEM dataset",
        "invalid_dem_model": "invalid DEM model",
    },
    "open_ring": [(120.0, 22.0), (122.0, 22.0), (122.0, 24.0), (120.0, 24.0)],
    "polygon": [[(120.0, 22.0), (122.0, 22.0), (122.0, 24.0), (120.0, 24.0)]],
    "polygon_with_hole": [
        [(120.0, 22.0), (122.0, 22.0), (122.0, 24.0), (120.0, 24.0)],
        [(120.5, 22.5), (121.5, 22.5), (121.5, 23.5), (120.5, 23.5)],
    ],
}


class FakeDemDataset:
    def __init__(self) -> None:
        self.sampled_coordinates = []

    def sample(self, coordinates):
        for longitude, latitude in coordinates:
            self.sampled_coordinates.append((longitude, latitude))
            yield [longitude * 100 + latitude]


class FakeWorldCoverDataset:
    def __init__(self, sampled_values) -> None:
        self.sampled_values = sampled_values
        self.sampled_coordinates = []

    def sample(self, coordinates):
        for sampled_value, coordinate in zip(self.sampled_values, coordinates):
            self.sampled_coordinates.append(coordinate)
            yield [sampled_value]


class TaiwanDemTerrainTest(unittest.TestCase):
    def test_bounds_cover_all_polygon_points(self) -> None:
        self.assertEqual(
            multipolygon_bounds([TERRAIN_TEST_CONFIG["polygon"]]),
            TERRAIN_TEST_CONFIG["bounds"],
        )

    def test_point_in_polygon_excludes_holes(self) -> None:
        self.assertTrue(point_in_polygon((120.25, 22.25), TERRAIN_TEST_CONFIG["polygon_with_hole"]))
        self.assertFalse(point_in_polygon((121.0, 23.0), TERRAIN_TEST_CONFIG["polygon_with_hole"]))

    def test_point_in_ring_accepts_open_geojson_ring(self) -> None:
        self.assertTrue(point_in_ring((121.0, 23.0), TERRAIN_TEST_CONFIG["open_ring"]))

    def test_terrain_grid_dimensions_follow_configured_sample_spacing(self) -> None:
        self.assertEqual(
            terrain_grid_dimensions(TERRAIN_TEST_CONFIG["bounds"], TERRAIN_TEST_CONFIG),
            (3, 3),
        )

    def test_dem_dataset_config_selects_requested_dataset(self) -> None:
        self.assertEqual(
            dem_dataset_config(TERRAIN_TEST_CONFIG, "dem_250m"),
            TERRAIN_TEST_CONFIG["dem_datasets"]["options"][1],
        )

    def test_dem_dataset_config_rejects_unconfigured_dataset(self) -> None:
        with self.assertRaisesRegex(ValueError, TERRAIN_TEST_CONFIG["errors"]["invalid_dem_dataset"]):
            dem_dataset_config(TERRAIN_TEST_CONFIG, "dem_500m")

    def test_terrain_source_label_includes_dataset_label(self) -> None:
        self.assertEqual(
            terrain_source_label(
                "custom.geojson",
                TERRAIN_TEST_CONFIG["dem_datasets"]["options"][1],
                TERRAIN_TEST_CONFIG,
            ),
            "custom.geojson + DEM 250m",
        )

    def test_polygon_masked_elevations_sample_only_polygon_candidate_cells(self) -> None:
        dataset = FakeDemDataset()
        elevations = build_polygon_masked_elevations(
            dataset,
            [
                [[(1.5, 7.5), (2.5, 7.5), (2.5, 8.5), (1.5, 8.5)]],
                [[(7.5, 1.5), (8.5, 1.5), (8.5, 2.5), (7.5, 2.5)]],
            ],
            (0.0, 0.0, 10.0, 10.0),
            11,
            11,
            TERRAIN_TEST_CONFIG,
            None,
        )
        self.assertEqual(dataset.sampled_coordinates, [(2.0, 8.0), (8.0, 2.0)])
        self.assertEqual(len(elevations), 121)
        self.assertEqual(elevations[24], 208.0)
        self.assertEqual(elevations[96], 802.0)
        self.assertEqual(sum(elevation is not None for elevation in elevations), 2)

    def test_sample_dem_values_reports_chunk_progress(self) -> None:
        progress_values = []
        values = sample_dem_values(
            FakeDemDataset(),
            [(120.0, 22.0), (121.0, 23.0), (122.0, 24.0)],
            TERRAIN_TEST_CONFIG,
            progress_values.append,
        )
        self.assertEqual(values, [12022.0, 12123.0, 12224.0])
        self.assertEqual(progress_values, [56, 70])

    def test_worldcover_land_cover_uses_valid_elevation_samples(self) -> None:
        dataset = FakeWorldCoverDataset([60, 0, 70])
        land_cover, legend = sample_worldcover_land_cover(
            dataset,
            {
                "nodata_value": 0,
                "class_colors": {
                    "60": {"label": "Bare", "color": "#bfa77a"},
                    "70": {"label": "Snow", "color": "#f2f7fb"},
                },
            },
            [
                (0, (75.0, 36.0)),
                (1, (75.1, 36.1)),
                (2, (75.2, 36.2)),
                (3, (75.3, 36.3)),
            ],
            [10.0, None, 20.0, 30.0],
        )
        self.assertEqual(dataset.sampled_coordinates, [(75.0, 36.0), (75.2, 36.2), (75.3, 36.3)])
        self.assertEqual(land_cover, [60, None, None, 70])
        self.assertEqual(
            legend,
            {
                "60": {"label": "Bare", "color": "#bfa77a"},
                "70": {"label": "Snow", "color": "#f2f7fb"},
            },
        )

    def test_worldcover_dataset_paths_uses_configured_glob(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_tile = root / "ESA_WorldCover_10m_2021_v200_N24E096_Map"
            second_tile = root / "ESA_WorldCover_10m_2021_v200_N24E099_Map"
            first_tile.mkdir()
            second_tile.mkdir()
            (second_tile / "ESA_WorldCover_10m_2021_v200_N24E099_Map.tif").touch()
            (first_tile / "ESA_WorldCover_10m_2021_v200_N24E096_Map.tif").touch()
            (first_tile / "ESA_WorldCover_10m_2021_v200_N24E096_InputQuality.tif").touch()

            paths = worldcover_dataset_paths({"dataset_glob": str(root / "*" / "*_Map.tif")})

        self.assertEqual(
            [Path(path).name for path in paths],
            [
                "ESA_WorldCover_10m_2021_v200_N24E096_Map.tif",
                "ESA_WorldCover_10m_2021_v200_N24E099_Map.tif",
            ],
        )

    def test_bounds_overlap_requires_intersecting_area(self) -> None:
        self.assertTrue(bounds_overlap((75.0, 36.0, 76.0, 37.0), (75.5, 36.5, 76.5, 37.5)))
        self.assertFalse(bounds_overlap((75.0, 36.0, 76.0, 37.0), (76.0, 36.5, 77.0, 37.5)))

    def test_saved_model_metadata_is_listed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = {
                **TERRAIN_TEST_CONFIG,
                "model_store_path": str(Path(directory)),
            }
            metadata = save_model_asset(
                config,
                {
                    "schema": TERRAIN_TEST_CONFIG["asset_schema"],
                    "source": "test.geojson",
                    "columns": 3,
                    "rows": 2,
                    "minElevation": 10,
                    "maxElevation": 30,
                    "elevations": [10, None, 30],
                },
                "test model",
            )
            self.assertEqual(list_model_metadata(config), [metadata])

    def test_model_metadata_list_ignores_non_dem_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = {
                **TERRAIN_TEST_CONFIG,
                "model_store_path": str(Path(directory)),
            }
            metadata = save_model_asset(
                config,
                {
                    "schema": TERRAIN_TEST_CONFIG["asset_schema"],
                    "source": "test.geojson",
                    "columns": 3,
                    "rows": 2,
                    "minElevation": 10,
                    "maxElevation": 30,
                    "elevations": [10, None, 30],
                },
                "test model",
            )
            Path(directory, "heightmap.json").write_text(
                '{"schema":"lego-heightmap-v1","modelId":"heightmap","createdAt":"2026-06-15T00:00:00Z"}',
                encoding=config["text_encoding"],
            )

            self.assertEqual(list_model_metadata(config), [metadata])

    def test_load_model_asset_rejects_non_dem_asset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = {
                **TERRAIN_TEST_CONFIG,
                "model_store_path": str(Path(directory)),
            }
            Path(directory, f"heightmap{config['model_file_extension']}").write_text(
                '{"schema":"lego-heightmap-v1","modelId":"heightmap","createdAt":"2026-06-15T00:00:00Z"}',
                encoding=config["text_encoding"],
            )

            with self.assertRaisesRegex(ValueError, config["errors"]["invalid_dem_model"]):
                load_model_asset(config, "heightmap")


if __name__ == "__main__":
    unittest.main()
