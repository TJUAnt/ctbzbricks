"""Unit tests for colored LEGO heightmap generation."""

import unittest

from src.services.lego_heightmap_generation_service import create_colored_heightmap_asset


CONFIG = {
    "heightmap_asset_schema": "lego-heightmap-v1",
    "heightmap_generation": {
        "latitude_meters_per_degree": 1000,
        "radians_per_degree": 0.01,
        "kilometers_per_meter": 0.001,
        "coordinate_average_divisor": 2,
        "minimum_stud_count": 1,
        "minimum_plate_height": 0,
        "empty_elevation_height_plate": 0,
        "coverage_precision": 100,
        "rounding_offset": 0.5,
        "aggregation": {
            "percentile": "percentile",
            "mean": "mean",
            "max": "max",
        },
        "percentile_ratio": 0.75,
    },
    "errors": {
        "invalid_heightmap_aggregation": "Unsupported height aggregation",
        "missing_heightmap_land_cover": "Valid DEM samples require land cover",
        "missing_heightmap_land_cover_color": "DEM land cover class requires a color",
    },
}

DEM_ASSET = {
    "source": "colored.dem",
    "columns": 3,
    "rows": 3,
    "bounds": {"west": 0, "south": 0, "east": 2, "north": 2},
    "minElevation": 10,
    "elevations": [10, 20, 30, 40, 50, 60, 70, 80, None],
    "landCover": [10, 20, 20, 10, 20, 10, 10, 20, None],
    "landCoverLegend": {
        "10": {"label": "trees", "color": "#112233"},
        "20": {"label": "grass", "color": "#445566"},
    },
}

SCALE = {
    "horizontalKmPerStud": 1,
    "verticalMetersPerPlate": 10,
    "aggregation": "percentile",
    "minCoverageRatio": 0.25,
}


class LegoHeightmapGenerationServiceTest(unittest.TestCase):
    def test_generates_colored_cells_and_records_source_dem(self) -> None:
        heightmap = create_colored_heightmap_asset(DEM_ASSET, "dem-model", SCALE, CONFIG)

        self.assertEqual(heightmap["schema"], CONFIG["heightmap_asset_schema"])
        self.assertEqual(heightmap["sourceDemModelId"], "dem-model")
        self.assertEqual(heightmap["metrics"]["widthStud"], 2)
        self.assertEqual(heightmap["metrics"]["depthStud"], 2)
        self.assertEqual(heightmap["metrics"]["validCellCount"], 4)
        self.assertEqual(
            [(cell["landCoverCode"], cell["landCoverColor"]) for cell in heightmap["cells"]],
            [(10, "#112233"), (20, "#445566"), (10, "#112233"), (20, "#445566")],
        )

    def test_rejects_valid_elevation_without_land_cover(self) -> None:
        dem_asset = {**DEM_ASSET, "landCover": [None] * len(DEM_ASSET["elevations"])}

        with self.assertRaisesRegex(ValueError, CONFIG["errors"]["missing_heightmap_land_cover"]):
            create_colored_heightmap_asset(dem_asset, "dem-model", SCALE, CONFIG)

    def test_rejects_dem_without_land_cover_array(self) -> None:
        dem_asset = {key: value for key, value in DEM_ASSET.items() if key != "landCover"}

        with self.assertRaisesRegex(ValueError, CONFIG["errors"]["missing_heightmap_land_cover"]):
            create_colored_heightmap_asset(dem_asset, "dem-model", SCALE, CONFIG)

    def test_rejects_land_cover_without_configured_color(self) -> None:
        dem_asset = {**DEM_ASSET, "landCoverLegend": {}}

        with self.assertRaisesRegex(
            ValueError,
            CONFIG["errors"]["missing_heightmap_land_cover_color"],
        ):
            create_colored_heightmap_asset(dem_asset, "dem-model", SCALE, CONFIG)


if __name__ == "__main__":
    unittest.main()
