"""Tests for colored Heightmap replacement pattern reports."""

import unittest

from src.services.dem_colored_replacement_service import (
    build_colored_replacement_plan,
    candidate_name_allowed,
    placement_priority,
)


CONFIG = {
    "strategy": "colored-region-replacement",
    "minimum_base_height_plate": 0,
    "maximum_height_error_plate": 0,
    "maximum_match_examples": 500,
    "maximum_missing_color_examples": 200,
    "maximum_unresolved_slope_edge_examples": 200,
    "connectivity": [
        {"x": 0, "z": -1},
        {"x": 1, "z": 0},
        {"x": 0, "z": 1},
        {"x": -1, "z": 0},
    ],
    "rotations": [
        {"degrees": 0, "quarter_turns": 0},
        {"degrees": 90, "quarter_turns": 1},
        {"degrees": 180, "quarter_turns": 2},
        {"degrees": 270, "quarter_turns": 3},
    ],
    "direction_rotation_clockwise": {
        "north": "east",
        "east": "south",
        "south": "west",
        "west": "north",
    },
    "slope_neighbors": [
        {"x": 1, "z": 0, "positive": "east", "negative": "west"},
        {"x": 0, "z": 1, "positive": "south", "negative": "north"},
    ],
    "color": {
        "exact_match": "exact",
        "nearest_match": "nearest",
        "rgb_prefix": "#",
        "hex_radix": 16,
        "distance_exponent": 2,
        "maximum_squared_distance": 900,
        "transparent": False,
        "xref_relation": "exact",
        "rgb_channels": {
            "red_start": 0,
            "red_end": 2,
            "green_start": 2,
            "green_end": 4,
            "blue_start": 4,
            "blue_end": 6,
        },
    },
    "excluded_candidate_name_patterns": ["\\bInverted\\b"],
    "missing_color_reasons": {
        "no_inventory_color": "candidate_part_has_no_inventory_color",
        "nearest_color_exceeds_threshold": "candidate_part_nearest_color_exceeds_threshold",
    },
    "errors": {
        "heightmap_cells_missing": "heightmap cells missing",
        "heightmap_dimensions_invalid": "heightmap dimensions invalid",
    },
}

PATTERN = {
    "candidateId": 1,
    "partId": "slope.dat",
    "patternRank": 1,
    "patternKey": "east-3",
    "heightmapPattern": {
        "widthStud": 3,
        "depthStud": 1,
        "relativeHeights": [[2, 1, 0]],
        "occupiedMask": [[True, True, True]],
        "baseHeightOffsets": [[0, 0, 0]],
        "slopeDirections": ["east"],
        "slopeDirectionCount": 1,
        "slopeEdges": [{}, {}],
        "longestContinuousRun": 3,
        "validRotations": [0, 90, 180, 270],
    },
    "matchMetrics": {"maximumErrorPlate": 0},
}


def heightmap(width: int, depth: int, heights: list[int], colors: list[str]) -> dict:
    return {
        "modelId": "heightmap-model",
        "metrics": {"widthStud": width, "depthStud": depth},
        "cells": [
            {
                "x": index % width,
                "z": index // width,
                "heightPlate": height,
                "elevationMeters": height,
                "landCoverColor": colors[index],
            }
            for index, height in enumerate(heights)
        ],
    }


class DemColoredReplacementServiceTest(unittest.TestCase):
    def test_inverted_candidate_name_is_excluded_before_matching(self) -> None:
        self.assertFalse(
            candidate_name_allowed(
                "Slope Brick Curved 4 x 1 Inverted",
                CONFIG,
            )
        )

    def test_priority_uses_continuous_run_before_edge_count_and_color(self) -> None:
        common = {
            "slopeDirectionCount": 1,
            "coveredCells": ((0, 0),),
            "partId": "part.dat",
            "zStud": 0,
            "xStud": 0,
            "rotationDegrees": 0,
        }
        continuous = {
            **common,
            "longestContinuousRun": 3,
            "slopeEdgeCount": 1,
            "colorMatchType": "nearest",
            "colorDistance": 3,
        }
        fragmented = {
            **common,
            "longestContinuousRun": 2,
            "slopeEdgeCount": 4,
            "colorMatchType": "exact",
            "colorDistance": 0,
        }

        self.assertLess(
            placement_priority(continuous, CONFIG),
            placement_priority(fragmented, CONFIG),
        )

    def test_exact_color_match_stays_inside_connected_region(self) -> None:
        report = build_colored_replacement_plan(
            heightmap(4, 1, [3, 2, 1, 0], ["#112233", "#112233", "#112233", "#445566"]),
            (PATTERN,),
            {"slope.dat": {1: {"name": "target", "rgb": "112233"}}},
            CONFIG,
        )

        self.assertEqual(report["connectedRegionCount"], 2)
        self.assertEqual(report["geometricMatchCount"], 1)
        self.assertEqual(report["colorMatchedCount"], 1)
        self.assertEqual(report["placementCount"], 1)
        self.assertEqual(report["placements"][0]["basePlate"], 1)
        self.assertEqual(report["placements"][0]["baseHeightCells"], ((0, 0, 1), (1, 0, 1), (2, 0, 1)))
        self.assertEqual(report["validation"]["overlapCellCount"], 0)
        self.assertEqual(report["validation"]["unsupportedPlacementCount"], 0)
        self.assertEqual(report["matches"][0]["colorMatchType"], "exact")
        self.assertEqual(report["missingColorRequirements"], [])

    def test_vertical_target_is_matched_by_rotating_pattern(self) -> None:
        report = build_colored_replacement_plan(
            heightmap(1, 3, [3, 2, 1], ["#112233"] * 3),
            (PATTERN,),
            {"slope.dat": {1: {"name": "target", "rgb": "112233"}}},
            CONFIG,
        )

        self.assertEqual(report["placements"][0]["rotationDegrees"], 90)
        self.assertEqual(report["placements"][0]["slopeDirections"], ["south"])

    def test_local_base_height_offsets_update_replacement_base_h(self) -> None:
        curved_pattern = {
            **PATTERN,
            "heightmapPattern": {
                **PATTERN["heightmapPattern"],
                "baseHeightOffsets": [[0, 1, 2]],
            },
        }

        report = build_colored_replacement_plan(
            heightmap(3, 1, [3, 2, 1], ["#112233"] * 3),
            (curved_pattern,),
            {"slope.dat": {1: {"name": "target", "rgb": "112233"}}},
            CONFIG,
        )

        self.assertEqual(report["placements"][0]["baseHeightCells"], ((0, 0, 1), (1, 0, 2), (2, 0, 3)))
        self.assertEqual(report["baseH"], [[1, 2, 3]])

    def test_nearest_color_is_selected_and_reported(self) -> None:
        report = build_colored_replacement_plan(
            heightmap(3, 1, [3, 2, 1], ["#112233"] * 3),
            (PATTERN,),
            {"slope.dat": {2: {"name": "near", "rgb": "122334"}}},
            CONFIG,
        )

        self.assertEqual(report["placements"][0]["colorMatchType"], "nearest")
        self.assertGreater(report["placements"][0]["colorDistance"], 0)
        self.assertEqual(report["colorSubstitutionCount"], 1)

    def test_missing_part_color_produces_requirement_report(self) -> None:
        report = build_colored_replacement_plan(
            heightmap(3, 1, [3, 2, 1], ["#112233"] * 3),
            (PATTERN,),
            {},
            CONFIG,
        )

        self.assertEqual(report["colorMatchedCount"], 0)
        missing = report["missingColorRequirements"][0]
        self.assertEqual(missing["targetColor"], "#112233")
        self.assertEqual(missing["partId"], "slope.dat")
        self.assertEqual(missing["slopeDirections"], ["east"])
        self.assertEqual(
            missing["reason"],
            CONFIG["missing_color_reasons"]["no_inventory_color"],
        )
        summary = report["missingColorSummary"][0]
        self.assertEqual(summary["targetColor"], "#112233")
        self.assertEqual(summary["partId"], "slope.dat")
        self.assertEqual(summary["occurrenceCount"], 1)
        self.assertEqual(report["missingColorRequirementTypeCount"], 1)

    def test_distant_color_produces_requirement_report(self) -> None:
        report = build_colored_replacement_plan(
            heightmap(3, 1, [3, 2, 1], ["#112233"] * 3),
            (PATTERN,),
            {"slope.dat": {2: {"name": "distant", "rgb": "FFFFFF"}}},
            CONFIG,
        )

        self.assertEqual(report["colorMatchedCount"], 0)
        self.assertEqual(report["missingColorRequirementCount"], 1)
        missing = report["missingColorRequirements"][0]
        self.assertEqual(
            missing["reason"],
            CONFIG["missing_color_reasons"]["nearest_color_exceeds_threshold"],
        )
        self.assertEqual(missing["nearestColorName"], "distant")
        self.assertGreater(missing["nearestColorDistance"], CONFIG["color"]["maximum_squared_distance"])
        summary = report["missingColorSummary"][0]
        self.assertEqual(summary["nearestColorName"], "distant")

    def test_more_slope_directions_are_placed_before_overlapping_straight_slope(self) -> None:
        corner_pattern = {
            **PATTERN,
            "partId": "corner.dat",
            "patternKey": "corner",
            "heightmapPattern": {
                **PATTERN["heightmapPattern"],
                "widthStud": 2,
                "depthStud": 2,
                "relativeHeights": [[2, 1], [1, 0]],
                "occupiedMask": [[True, True], [True, True]],
                "baseHeightOffsets": [[0, 0], [0, 0]],
                "slopeDirections": ["east", "south"],
                "slopeDirectionCount": 2,
                "slopeEdges": [{}, {}, {}, {}],
                "longestContinuousRun": 2,
            },
        }
        straight_pattern = {
            **PATTERN,
            "partId": "straight.dat",
            "patternKey": "straight",
            "heightmapPattern": {
                **PATTERN["heightmapPattern"],
                "widthStud": 2,
                "relativeHeights": [[1, 0]],
                "baseHeightOffsets": [[0, 0]],
                "occupiedMask": [[True, True]],
                "slopeEdges": [{}],
                "longestContinuousRun": 2,
            },
        }
        colors = {
            "corner.dat": {1: {"name": "target", "rgb": "112233"}},
            "straight.dat": {1: {"name": "target", "rgb": "112233"}},
        }

        report = build_colored_replacement_plan(
            heightmap(2, 2, [3, 2, 2, 1], ["#112233"] * 4),
            (straight_pattern, corner_pattern),
            colors,
            CONFIG,
        )

        self.assertEqual(report["placementCount"], 1)
        self.assertGreater(report["validation"]["overlapRejectedMatchCount"], 0)
        self.assertEqual(report["placements"][0]["partId"], "corner.dat")
        self.assertEqual(report["solvedSlopeEdgeCount"], 4)

    def test_overlapping_matches_are_not_both_placed(self) -> None:
        report = build_colored_replacement_plan(
            heightmap(5, 1, [5, 4, 3, 2, 1], ["#112233"] * 5),
            (PATTERN,),
            {"slope.dat": {1: {"name": "target", "rgb": "112233"}}},
            CONFIG,
        )

        covered = [cell for placement in report["placements"] for cell in placement["coveredCells"]]
        self.assertEqual(len(covered), len({tuple(cell) for cell in covered}))
        self.assertEqual(report["placementCount"], 1)


if __name__ == "__main__":
    unittest.main()
