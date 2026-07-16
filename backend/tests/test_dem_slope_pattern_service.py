"""Tests for approximate four-direction DEM slope patterns."""

import unittest

from src.services.dem_slope_pattern_service import build_candidate_heightmap_patterns


CONFIG = {
    "highest_point_tolerance_plate": 0.001,
    "source_rotation_degrees": 0,
    "pattern_hash_algorithm": "sha256",
    "pattern_hash_length": 64,
    "directions": [
        {"name": "north", "x": 0, "z": -1},
        {"name": "east", "x": 1, "z": 0},
        {"name": "south", "x": 0, "z": 1},
        {"name": "west", "x": -1, "z": 0},
    ],
    "errors": {
        "empty_pattern_surface": "empty pattern surface",
        "missing_source_rotation": "missing source rotation",
    },
}


def capability(surface: tuple[tuple[float | None, ...], ...]) -> dict:
    width = len(surface[0])
    depth = len(surface)
    return {
        "states": [
            {
                "rotationDegrees": 0,
                "widthStud": width,
                "depthStud": depth,
                "occupiedMask": [
                    [value is not None for value in row]
                    for row in surface
                ],
                "cellHeightRangesPlate": [
                    [
                        None if value is None else {"minimum": value, "maximum": value}
                        for value in row
                    ]
                    for row in surface
                ],
                "cellBottomHeightRangesPlate": [
                    [
                        None if value is None else {"minimum": 0, "maximum": 0}
                        for value in row
                    ]
                    for row in surface
                ],
                "cellContactBottomHeightRangesPlate": [
                    [
                        None if value is None else {"minimum": 0, "maximum": 0}
                        for value in row
                    ]
                    for row in surface
                ],
            }
        ]
    }


class DemSlopePatternServiceTest(unittest.TestCase):
    def test_highest_cell_at_left_builds_one_east_slope(self) -> None:
        patterns = build_candidate_heightmap_patterns(
            capability(((3.0, 2.0, 1.0),)),
            (0, 90, 180, 270),
            3,
            CONFIG,
        )

        pattern = patterns[0]["heightmapPattern"]
        self.assertEqual(pattern["relativeHeights"], [[2, 1, 0]])
        self.assertEqual(pattern["slopeDirections"], ["east"])
        self.assertEqual(pattern["slopeDirectionCount"], 1)
        self.assertEqual(pattern["longestContinuousRun"], 3)

    def test_corner_highest_cell_builds_two_direction_slope(self) -> None:
        patterns = build_candidate_heightmap_patterns(
            capability(((5.0, 4.0, 3.0), (4.0, 3.0, 2.0), (3.0, 2.0, 1.0))),
            (0, 90, 180, 270),
            3,
            CONFIG,
        )

        pattern = patterns[0]["heightmapPattern"]
        self.assertEqual(
            pattern["relativeHeights"],
            [[4, 3, 2], [3, 2, 1], [2, 1, 0]],
        )
        self.assertEqual(pattern["slopeDirections"], ["east", "south"])
        self.assertEqual(pattern["slopeDirectionCount"], 2)

    def test_center_highest_cell_builds_four_direction_slope(self) -> None:
        patterns = build_candidate_heightmap_patterns(
            capability(((1.0, 2.0, 1.0), (2.0, 3.0, 2.0), (1.0, 2.0, 1.0))),
            (0, 90, 180, 270),
            3,
            CONFIG,
        )

        pattern = patterns[0]["heightmapPattern"]
        self.assertEqual(
            pattern["relativeHeights"],
            [[0, 1, 0], [1, 2, 1], [0, 1, 0]],
        )
        self.assertEqual(
            pattern["slopeDirections"],
            ["north", "east", "south", "west"],
        )
        self.assertEqual(pattern["slopeDirectionCount"], 4)

    def test_rotation_is_stored_for_runtime_matching(self) -> None:
        patterns = build_candidate_heightmap_patterns(
            capability(((2.0, 1.0),)),
            (0, 90, 180, 270),
            3,
            CONFIG,
        )

        self.assertEqual(
            patterns[0]["heightmapPattern"]["validRotations"],
            [0, 90, 180, 270],
        )

    def test_contact_base_height_offsets_are_stored_for_curved_bottoms(self) -> None:
        source = capability(((2.0, 1.0),))
        source["states"][0]["cellBottomHeightRangesPlate"] = [
            [{"minimum": 0, "maximum": 0}, {"minimum": 1, "maximum": 1}]
        ]
        source["states"][0]["cellContactBottomHeightRangesPlate"] = [
            [{"minimum": 0, "maximum": 0}, None]
        ]

        patterns = build_candidate_heightmap_patterns(
            source,
            (0, 90, 180, 270),
            3,
            CONFIG,
        )

        self.assertEqual(patterns[0]["heightmapPattern"]["baseHeightOffsets"], [[0, None]])

    def test_collision_base_height_offsets_are_used_when_part_has_no_contact(self) -> None:
        source = capability(((2.0, 1.0),))
        source["states"][0]["cellBottomHeightRangesPlate"] = [
            [{"minimum": 0, "maximum": 0}, {"minimum": 1, "maximum": 1}]
        ]
        source["states"][0]["cellContactBottomHeightRangesPlate"] = [[None, None]]

        patterns = build_candidate_heightmap_patterns(
            source,
            (0, 90, 180, 270),
            3,
            CONFIG,
        )

        self.assertEqual(patterns[0]["heightmapPattern"]["baseHeightOffsets"], [[0, 1]])


if __name__ == "__main__":
    unittest.main()
