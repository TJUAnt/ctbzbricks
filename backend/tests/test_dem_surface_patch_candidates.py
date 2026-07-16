"""Tests for DEM surface patch candidate generation."""

import unittest

from src.ldraw.surface_profile import PartSurfaceProfile
from src.services.dem_surface_patch_service import generate_surface_patch_candidates


MATCH_CONFIG = {
    "minimum_base_height_plate": 0,
    "maximum_absolute_error_plate": 0.01,
    "approximate_maximum_absolute_error_plate": 0.5,
    "unbounded_error_part_ids": ["flat-1x1.dat"],
    "unbounded_error_maximum_base_candidates": 1,
    "rounding_decimal_places": 6,
    "base_height_offsets": [-1, 0, 1],
    "slope_directions": {
        "minimum_delta_plate": 0.001,
        "neighbors": [
            {"x": 1, "z": 0, "positive": "east", "negative": "west"},
            {"x": 0, "z": 1, "positive": "south", "negative": "north"},
        ],
        "order": ["north", "east", "south", "west"],
    },
    "top_connection_classes": {
        "connected": "top_connected",
        "finished": "top_finished",
    },
    "rotations": [
        {"degrees": 0, "quarter_turns": 0},
        {"degrees": 90, "quarter_turns": 1},
        {"degrees": 180, "quarter_turns": 2},
        {"degrees": 270, "quarter_turns": 3},
    ],
    "errors": {
        "target_surface_empty": "target surface empty",
        "target_surface_not_rectangular": "target surface not rectangular",
        "target_color_not_rectangular": "target color not rectangular",
        "target_dimensions_mismatch": "target dimensions mismatch",
        "profile_sample_rate_mismatch": "profile sample rate mismatch",
    },
}


def profile(part_id: str, surface: tuple[tuple[float, ...], ...]) -> PartSurfaceProfile:
    depth = len(surface)
    width = len(surface[0])
    return PartSurfaceProfile(
        part_id=part_id,
        ldraw_origin_to_base_ldu=max(max(row) for row in surface) * 8,
        ldraw_center_x_ldu=0,
        ldraw_center_z_ldu=0,
        width_stud=width,
        depth_stud=depth,
        samples_per_stud_axis=1,
        surface_height_plate=surface,
        collision_intervals_plate=tuple(
            tuple(((0.0, height),) for height in row)
            for row in surface
        ),
        bottom_contact=tuple(tuple(True for _height in row) for row in surface),
        top_connection_mask=tuple(tuple(False for _height in row) for row in surface),
    )


class DemSurfacePatchCandidatesTest(unittest.TestCase):
    def test_one_by_one_flat_fallback_covers_a_steep_stud(self) -> None:
        fallback = PartSurfaceProfile(
            part_id="flat-1x1.dat",
            ldraw_origin_to_base_ldu=8,
            ldraw_center_x_ldu=0,
            ldraw_center_z_ldu=0,
            width_stud=1,
            depth_stud=1,
            samples_per_stud_axis=2,
            surface_height_plate=((1.0, 1.0), (1.0, 1.0)),
            collision_intervals_plate=(
                (((0.0, 1.0),), ((0.0, 1.0),)),
                (((0.0, 1.0),), ((0.0, 1.0),)),
            ),
            bottom_contact=((True, True), (True, True)),
            top_connection_mask=((True,),),
        )

        candidates = generate_surface_patch_candidates(
            ((1.0, 5.0), (1.0, 5.0)),
            ((1,),),
            (fallback,),
            MATCH_CONFIG,
        )

        self.assertTrue(candidates)
        self.assertEqual(len(candidates), MATCH_CONFIG["unbounded_error_maximum_base_candidates"])
        self.assertGreater(candidates[0].maximum_absolute_error_plate, MATCH_CONFIG["maximum_absolute_error_plate"])
        self.assertFalse(candidates[0].uses_approximate_geometry)

    def test_slope_between_strict_and_approximate_error_limits_is_marked_approximate(self) -> None:
        candidates = generate_surface_patch_candidates(
            ((1.0, 1.0, 2.0),),
            ((4, 4, 4),),
            (profile("slope-3x1.dat", ((1.0, 1.25, 2.0),)),),
            MATCH_CONFIG,
        )

        self.assertTrue(candidates)
        self.assertTrue(candidates[0].uses_approximate_geometry)

    def test_slope_above_approximate_error_limit_is_rejected(self) -> None:
        candidates = generate_surface_patch_candidates(
            ((1.0, 1.0, 2.0),),
            ((4, 4, 4),),
            (profile("slope-3x1.dat", ((1.0, 1.75, 2.0),)),),
            MATCH_CONFIG,
        )

        self.assertEqual(candidates, ())

    def test_continuous_slope_matches_123_with_integer_base_height(self) -> None:
        candidates = generate_surface_patch_candidates(
            ((5.0, 6.0, 7.0),),
            ((1, 1, 1),),
            (profile("slope-3x1.dat", ((1.0, 2.0, 3.0),)),),
            MATCH_CONFIG,
        )

        exact = [candidate for candidate in candidates if candidate.maximum_absolute_error_plate == 0]
        self.assertEqual(len(exact), 1)
        self.assertEqual(exact[0].base_plate, 4)
        self.assertEqual(exact[0].rotation_degrees, 0)
        self.assertEqual(exact[0].covered_cells, ((0, 0), (1, 0), (2, 0)))

    def test_ridge_profile_matches_121_as_one_patch(self) -> None:
        candidates = generate_surface_patch_candidates(
            ((1.0, 2.0, 1.0),),
            ((7, 7, 7),),
            (profile("ridge.dat", ((1.0, 2.0, 1.0),)),),
            MATCH_CONFIG,
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].part_id, "ridge.dat")
        self.assertEqual(candidates[0].maximum_absolute_error_plate, 0)

    def test_122_exposes_slope_and_flat_candidates_for_global_composition(self) -> None:
        candidates = generate_surface_patch_candidates(
            ((1.0, 2.0, 2.0),),
            ((3, 3, 3),),
            (
                profile("slope-2x1.dat", ((1.0, 2.0),)),
                profile("flat-1x1.dat", ((1.0,),)),
            ),
            MATCH_CONFIG,
        )

        exact_keys = {
            (candidate.part_id, candidate.x_stud, candidate.base_plate)
            for candidate in candidates
            if candidate.maximum_absolute_error_plate == 0
        }
        self.assertIn(("slope-2x1.dat", 0, 0), exact_keys)
        self.assertIn(("flat-1x1.dat", 2, 1), exact_keys)

    def test_multi_cell_part_cannot_cross_color_boundary(self) -> None:
        candidates = generate_surface_patch_candidates(
            ((1.0, 2.0),),
            ((1, 2),),
            (profile("slope-2x1.dat", ((1.0, 2.0),)),),
            MATCH_CONFIG,
        )

        self.assertEqual(candidates, ())

    def test_rotation_matches_vertical_slope(self) -> None:
        candidates = generate_surface_patch_candidates(
            ((1.0,), (2.0,)),
            ((4,), (4,)),
            (profile("slope-2x1.dat", ((1.0, 2.0),)),),
            MATCH_CONFIG,
        )

        exact_rotations = {
            candidate.rotation_degrees
            for candidate in candidates
            if candidate.maximum_absolute_error_plate == 0
        }
        self.assertEqual(exact_rotations, {90})

    def test_ldraw_z_rows_are_reversed_before_matching_dem_rows(self) -> None:
        candidates = generate_surface_patch_candidates(
            ((2.0,), (1.0,)),
            ((4,), (4,)),
            (profile("slope-1x2.dat", ((1.0,), (2.0,))),),
            MATCH_CONFIG,
        )

        exact = [candidate for candidate in candidates if candidate.maximum_absolute_error_plate == 0]
        self.assertEqual(len(exact), 1)
        self.assertEqual(exact[0].rotation_degrees, 0)

    def test_matching_direction_accepts_flat_samples_within_geometric_error(self) -> None:
        candidates = generate_surface_patch_candidates(
            ((1.0, 1.0, 2.0),),
            ((4, 4, 4),),
            (profile("slope-3x1.dat", ((1.0, 1.5, 2.0),)),),
            {**MATCH_CONFIG, "maximum_absolute_error_plate": 0.5},
        )

        self.assertTrue(candidates)
        self.assertEqual(candidates[0].slope_directions, ("east",))

    def test_corner_candidate_exposes_all_matched_slope_directions_and_top_connections(self) -> None:
        corner = PartSurfaceProfile(
            part_id="corner.dat",
            ldraw_origin_to_base_ldu=24,
            ldraw_center_x_ldu=0,
            ldraw_center_z_ldu=0,
            width_stud=2,
            depth_stud=2,
            samples_per_stud_axis=1,
            surface_height_plate=((1.0, 2.0), (2.0, 3.0)),
            collision_intervals_plate=(
                (((0.0, 1.0),), ((0.0, 2.0),)),
                (((0.0, 2.0),), ((0.0, 3.0),)),
            ),
            bottom_contact=((True, True), (True, True)),
            top_connection_mask=((False, False), (False, True)),
        )

        candidates = generate_surface_patch_candidates(
            ((1.0, 2.0), (2.0, 3.0)),
            ((5, 5), (5, 5)),
            (corner,),
            MATCH_CONFIG,
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].slope_directions, ("east", "south"))
        self.assertEqual(candidates[0].matched_slope_direction_count, 2)
        self.assertEqual(candidates[0].top_connect_cells, ((1, 1),))
        self.assertEqual(candidates[0].top_connection_class, "top_connected")
        self.assertEqual(len(candidates[0].slope_edges), 4)

    def test_candidate_with_unmatched_direction_is_rejected(self) -> None:
        candidates = generate_surface_patch_candidates(
            ((1.0, 2.0), (1.0, 2.0)),
            ((5, 5), (5, 5)),
            (
                profile("corner.dat", ((1.0, 2.0), (2.0, 3.0))),
            ),
            {**MATCH_CONFIG, "maximum_absolute_error_plate": 2.0},
        )

        self.assertEqual(candidates, ())


if __name__ == "__main__":
    unittest.main()
