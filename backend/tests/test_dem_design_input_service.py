"""Tests for building DEM design matrices from a stored terrain model."""

import unittest

from src.services.dem_design_input_service import build_dem_design_targets


CONFIG = {
    "minimum_stud_count": 1,
    "minimum_plate_height": 0,
    "empty_elevation_height_plate": 0,
    "minimum_surface_height_plate": 1,
    "latitude_meters_per_degree": 100,
    "radians_per_degree": 0.017453292519943295,
    "meters_per_kilometer": 1000,
    "kilometers_per_meter": 0.001,
    "coordinate_average_divisor": 2,
    "coverage_precision": 100,
    "percentile_ratio": 0.75,
    "samples_per_stud_axis": 2,
    "sample_center_fraction": 0.5,
    "stud_center_offset": 0.5,
    "surface_precision": 6,
    "decimal_radix": 10,
    "default_color_id": 15,
    "surface_color_reference_part_num": "3024",
    "color_distance_exponent": 2,
    "color_hex_radix": 16,
    "color_hex_prefix": "#",
    "color_channels": {
        "red_start": 0,
        "red_end": 2,
        "green_start": 2,
        "green_end": 4,
        "blue_start": 4,
        "blue_end": 6,
    },
    "aggregations": {
        "mean": "mean",
        "maximum": "max",
        "percentile": "percentile",
    },
    "part_ids": ["3024.dat", "3040b.dat"],
    "errors": {"aggregation_invalid": "invalid aggregation"},
}

ASSET = {
    "columns": 2,
    "rows": 2,
    "bounds": {"west": 0, "south": 0, "east": 20, "north": 20},
    "minElevation": 100,
    "elevations": [100, 200, 300, 400],
    "landCover": [10, 10, 20, 20],
    "landCoverLegend": {
        "10": {"color": "#C91A09"},
        "20": {"color": "#FFFFFF"},
    },
}

SCALE = {
    "horizontal_km_per_stud": 1,
    "vertical_meters_per_plate": 100,
    "aggregation": "mean",
    "minimum_coverage_ratio": 0,
}


class DemDesignInputServiceTest(unittest.TestCase):
    def test_builds_height_surface_color_and_part_inputs(self) -> None:
        targets = build_dem_design_targets(
            ASSET,
            SCALE,
            {4: "C91A09", 15: "FFFFFF"},
            CONFIG,
        )

        self.assertEqual(targets["targetHeightPlate"], [[1, 2], [3, 4]])
        self.assertEqual(
            targets["targetSurfacePlate"],
            [[1, 1.25, 1.75, 2], [1.5, 1.75, 2.25, 2.5], [2.5, 2.75, 3.25, 3.5], [3, 3.25, 3.75, 4]],
        )
        self.assertEqual(targets["targetColorId"], [[4, 4], [15, 15]])
        self.assertEqual(targets["partIds"], CONFIG["part_ids"])


if __name__ == "__main__":
    unittest.main()
