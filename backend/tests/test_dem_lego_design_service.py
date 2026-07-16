"""Unit tests for the independent DEM BaseH LEGO strategy."""

import unittest

from src.services.dem_lego_design_service import build_base_h_structure


CONFIG = {
    "structure": {
        "strategy": "solid-bottom-up",
        "color": {
            "id": 15,
            "name": "White",
            "rgb": "#FFFFFF",
            "ldraw_code": "15",
        },
    },
    "algorithm": {
        "no_rotation_degrees": 0,
        "rotation_degrees": 90,
        "minimum_height_plate": 0,
        "minimum_part_height_plate": 1,
        "minimum_part_area": 1,
        "scan_orders": [
            {"x_direction": 1, "z_direction": 1},
            {"x_direction": -1, "z_direction": 1},
        ],
    },
    "errors": {
        "base_h_empty": "base h empty",
        "base_h_not_rectangular": "base h not rectangular",
        "base_h_negative": "base h negative",
        "part_metadata_missing": "part metadata missing",
        "base_h_uncovered": "base h uncovered",
    },
}


PARTS = [
    {
        "partId": "3003.dat",
        "rebrickablePartNum": "3003",
        "legoDesignId": "3003",
        "role": "brick",
        "width": 2,
        "depth": 2,
        "heightPlate": 3,
        "area": 4,
    },
    {
        "partId": "3004.dat",
        "rebrickablePartNum": "3004",
        "legoDesignId": "3004",
        "role": "brick",
        "width": 1,
        "depth": 2,
        "heightPlate": 3,
        "area": 2,
    },
    {
        "partId": "3005.dat",
        "rebrickablePartNum": "3005",
        "legoDesignId": "3005",
        "role": "brick",
        "width": 1,
        "depth": 1,
        "heightPlate": 3,
        "area": 1,
    },
    {
        "partId": "3022.dat",
        "rebrickablePartNum": "3022",
        "legoDesignId": "3022",
        "role": "plate",
        "width": 2,
        "depth": 2,
        "heightPlate": 1,
        "area": 4,
    },
    {
        "partId": "3023.dat",
        "rebrickablePartNum": "3023",
        "legoDesignId": "3023",
        "role": "plate",
        "width": 1,
        "depth": 2,
        "heightPlate": 1,
        "area": 2,
    },
    {
        "partId": "3024.dat",
        "rebrickablePartNum": "3024",
        "legoDesignId": "3024",
        "role": "plate",
        "width": 1,
        "depth": 1,
        "heightPlate": 1,
        "area": 1,
    },
]


class DemLegoDesignServiceTest(unittest.TestCase):
    def test_build_base_h_prefers_brick_and_uses_plate_for_remainder(self) -> None:
        result = build_base_h_structure([[4, 4], [4, 4]], PARTS, CONFIG)

        self.assertEqual(
            [(placement["partId"], placement["basePlate"]) for placement in result["placements"]],
            [("3003.dat", 0), ("3022.dat", 3)],
        )
        self.assertEqual(result["validation"]["targetVolumeStudPlate"], 16)
        self.assertEqual(result["validation"]["placedVolumeStudPlate"], 16)
        self.assertEqual(result["validation"]["unsupportedPlacementCount"], 0)

    def test_build_base_h_covers_irregular_heightmap_without_floating(self) -> None:
        base_h = [[1, 4], [2, 4]]

        result = build_base_h_structure(base_h, PARTS, CONFIG)

        occupied = set()
        for placement in result["placements"]:
            for level in range(
                placement["basePlate"],
                placement["basePlate"] + placement["heightPlate"],
            ):
                for z in range(placement["z"], placement["z"] + placement["depth"]):
                    for x in range(placement["x"], placement["x"] + placement["width"]):
                        occupied.add((x, z, level))
        expected = {
            (x, z, level)
            for z, row in enumerate(base_h)
            for x, height in enumerate(row)
            for level in range(height)
        }
        self.assertEqual(occupied, expected)
        self.assertEqual(result["validation"]["unsupportedPlacementCount"], 0)
        self.assertIn("3004.dat", {placement["partId"] for placement in result["placements"]})

    def test_build_base_h_rejects_invalid_matrices(self) -> None:
        invalid_cases = [
            ([], CONFIG["errors"]["base_h_empty"]),
            ([[]], CONFIG["errors"]["base_h_empty"]),
            ([[1], [1, 2]], CONFIG["errors"]["base_h_not_rectangular"]),
            ([[1, -1]], CONFIG["errors"]["base_h_negative"]),
        ]

        for base_h, message in invalid_cases:
            with self.subTest(base_h=base_h):
                with self.assertRaisesRegex(ValueError, message):
                    build_base_h_structure(base_h, PARTS, CONFIG)


if __name__ == "__main__":
    unittest.main()
