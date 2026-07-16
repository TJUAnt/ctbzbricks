"""Tests for grouping real slope surface capabilities."""

import unittest

from src.ldraw.surface_profile import PartSurfaceProfile
from src.services.dem_slope_catalog_service import (
    classify_surface_family,
    profile_capability,
    profile_geometry_signature,
    surface_traits,
)


CONFIG = {
    "quantization_step_plate": 0.125,
    "value_precision": 3,
    "flat_surface_range_plate": 0.125,
    "orientation_degrees": [0, 90, 180, 270],
    "family_patterns": [
        {"family": "inverted", "pattern": "\\bInverted\\b"},
        {"family": "double_convex", "pattern": "\\bDouble Convex\\b"},
        {"family": "straight", "pattern": "^Slope Brick"},
    ],
    "families": {
        "flat_top": "flat_top",
        "unclassified": "unclassified",
    },
}


def slope_profile() -> PartSurfaceProfile:
    surface = (
        (0.25, 0.75, 1.25, 1.75),
        (0.25, 0.75, 1.25, 1.75),
    )
    return PartSurfaceProfile(
        part_id="slope.dat",
        ldraw_origin_to_base_ldu=24,
        ldraw_center_x_ldu=0,
        ldraw_center_z_ldu=0,
        width_stud=2,
        depth_stud=1,
        samples_per_stud_axis=2,
        surface_height_plate=surface,
        collision_intervals_plate=tuple(
            tuple(((0.0, height),) for height in row)
            for row in surface
        ),
        bottom_contact=((True, True, True, True), (True, True, True, True)),
        top_connection_mask=((True, False),),
    )


class DemSlopeCatalogServiceTest(unittest.TestCase):
    def test_profile_capability_exposes_rotated_surface_states(self) -> None:
        capability = profile_capability(slope_profile(), CONFIG)

        self.assertEqual(capability["footprint"], {"widthStud": 2, "depthStud": 1})
        self.assertEqual(capability["heightRangePlate"], 1.5)
        self.assertEqual(len(capability["states"]), 4)
        self.assertEqual(
            capability["states"][0]["cellHeightRangesPlate"],
            [[{"minimum": 0.0, "maximum": 0.5}, {"minimum": 1.0, "maximum": 1.5}]],
        )
        self.assertEqual(capability["states"][0]["occupiedMask"], [[True, True]])
        self.assertEqual(capability["states"][0]["supportMask"], [[True, True]])
        self.assertEqual(capability["states"][0]["topConnectMask"], ((True, False),))

    def test_rotated_equivalent_profiles_share_geometry_signature(self) -> None:
        profile = slope_profile()
        rotated = PartSurfaceProfile(
            part_id="rotated.dat",
            ldraw_origin_to_base_ldu=profile.ldraw_origin_to_base_ldu,
            ldraw_center_x_ldu=profile.ldraw_center_x_ldu,
            ldraw_center_z_ldu=profile.ldraw_center_z_ldu,
            width_stud=1,
            depth_stud=2,
            samples_per_stud_axis=2,
            surface_height_plate=tuple(zip(*reversed(profile.surface_height_plate))),
            collision_intervals_plate=tuple(zip(*reversed(profile.collision_intervals_plate))),
            bottom_contact=tuple(zip(*reversed(profile.bottom_contact))),
            top_connection_mask=tuple(zip(*reversed(profile.top_connection_mask))),
        )

        self.assertEqual(
            profile_geometry_signature(profile, CONFIG),
            profile_geometry_signature(rotated, CONFIG),
        )

    def test_flat_inverted_part_keeps_name_family(self) -> None:
        self.assertEqual(
            classify_surface_family("Slope Brick 45 2 x 2 Inverted", 0.0, CONFIG),
            "inverted",
        )

    def test_flat_unmatched_part_is_classified_as_flat_top(self) -> None:
        self.assertEqual(classify_surface_family("Unknown", 0.0, CONFIG), "flat_top")

    def test_surface_traits_preserve_compound_name_capabilities(self) -> None:
        self.assertEqual(
            surface_traits("Slope Brick 45 Double Convex Inverted", CONFIG),
            ["inverted", "double_convex", "straight"],
        )


if __name__ == "__main__":
    unittest.main()
