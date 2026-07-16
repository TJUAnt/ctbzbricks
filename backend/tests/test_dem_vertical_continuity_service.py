"""Tests for strict vertical continuity in LDU columns."""

import unittest

from src.ldraw.surface_profile import PartSurfaceProfile
from src.services.dem_surface_patch_service import SurfacePatchCandidate
from src.services.dem_surface_plan_service import SurfaceReplacementPhase
from src.services.dem_vertical_continuity_service import phase_vertical_continuity


CONFIG = {
    "samples_per_stud_axis": 2,
    "ldu_per_stud": 2,
    "ldu_per_plate": 2,
    "ground_ldu": 0,
    "sample_center_offset_ldu": 0.5,
    "rounding_decimal_places": 6,
    "maximum_gap_examples": 4,
    "rotations": [{"degrees": 0, "quarter_turns": 0}],
    "errors": {
        "rotation_missing": "rotation missing",
        "sample_resolution": "sample resolution invalid",
        "profile_sample_resolution": "profile sample resolution invalid",
        "profile_missing": "profile missing {part_id}",
    },
}


def placement() -> SurfacePatchCandidate:
    return SurfacePatchCandidate(
        part_id="slope.dat",
        ldraw_origin_to_base_ldu=6,
        ldraw_center_x_ldu=0,
        ldraw_center_z_ldu=0,
        x_stud=0,
        z_stud=0,
        width_stud=1,
        depth_stud=1,
        rotation_degrees=0,
        base_plate=1,
        color_id=1,
        target_color_id=1,
        color_distance=0,
        uses_nearest_color=False,
        uses_approximate_geometry=False,
        is_visible=True,
        covered_cells=((0, 0),),
        required_support_cells=((0, 0),),
        base_height_cells=((0, 0, 1),),
        top_connect_cells=((0, 0),),
        top_connection_class="top_connected",
        slope_edges=((0, 0, 1, 0, "east"),),
        slope_directions=("east",),
        matched_slope_direction_count=1,
        surface_height_plate=((2.0, 3.0), (2.0, 3.0)),
        collision_intervals_plate=(
            (((1.0, 2.0),), ((1.0, 3.0),)),
            (((1.0, 2.0),), ((1.0, 3.0),)),
        ),
        maximum_absolute_error_plate=0,
        total_absolute_error_plate=0,
        root_mean_square_error_plate=0,
    )


def profile(lower_plate: float) -> PartSurfaceProfile:
    return PartSurfaceProfile(
        part_id="slope.dat",
        ldraw_origin_to_base_ldu=6,
        ldraw_center_x_ldu=0,
        ldraw_center_z_ldu=0,
        width_stud=1,
        depth_stud=1,
        samples_per_stud_axis=2,
        surface_height_plate=((2.0, 3.0), (2.0, 3.0)),
        collision_intervals_plate=(
            (((lower_plate, 2.0),), ((lower_plate, 3.0),)),
            (((lower_plate, 2.0),), ((lower_plate, 3.0),)),
        ),
        bottom_contact=((True, True), (True, True)),
        top_connection_mask=((True,),),
    )


class DemVerticalContinuityServiceTest(unittest.TestCase):
    def test_slope_touching_base_is_continuous_in_every_ldu_column(self) -> None:
        phase = SurfaceReplacementPhase(
            connection_class="top_connected",
            placements=(placement(),),
            base_h=((1,),),
            solved_slope_edge_count=1,
            unresolved_slope_edge_count=0,
        )

        result = phase_vertical_continuity(
            phase,
            1,
            1,
            {"slope.dat": profile(0)},
            CONFIG,
        )

        self.assertEqual(result.checked_column_count, 4)
        self.assertEqual(result.discontinuous_column_count, 0)
        self.assertEqual(result.gap_count, 0)

    def test_gap_between_base_and_slope_placement_is_reported_in_ldu(self) -> None:
        phase = SurfaceReplacementPhase(
            connection_class="top_connected",
            placements=(placement(),),
            base_h=((0,),),
            solved_slope_edge_count=1,
            unresolved_slope_edge_count=0,
        )

        result = phase_vertical_continuity(
            phase,
            1,
            1,
            {"slope.dat": profile(0)},
            CONFIG,
        )

        self.assertEqual(result.discontinuous_column_count, 4)
        self.assertEqual(result.gap_count, 4)
        self.assertEqual(result.maximum_gap_ldu, 2)
        self.assertEqual(result.gap_examples[0]["lowerLdu"], 0)
        self.assertEqual(result.gap_examples[0]["upperLdu"], 2)


if __name__ == "__main__":
    unittest.main()
