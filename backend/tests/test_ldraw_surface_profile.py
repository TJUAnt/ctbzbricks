"""Tests for extracting DEM surface profiles from LDraw triangle meshes."""

import unittest

from src.ldraw.mesh import Triangle, Vector
from src.ldraw.surface_profile import build_part_surface_profile


PROFILE_CONFIG = {
    "ldu_per_stud": 20,
    "ldu_per_plate": 8,
    "samples_per_stud_axis": 1,
    "sample_center_fraction": 0.5,
    "dimension_tolerance_stud": 0.000001,
    "ray_tolerance_ldu": 0.000001,
    "bottom_contact_tolerance_ldu": 0.000001,
    "connection_position_tolerance_ldu": 0.000001,
    "center_divisor": 2,
    "rounding_decimal_places": 6,
    "errors": {
        "empty_mesh": "empty mesh",
        "non_stud_width": "invalid width {part_id}",
        "non_stud_depth": "invalid depth {part_id}",
    },
}


def horizontal_quad(y: float, min_x: float, max_x: float, min_z: float, max_z: float):
    return (
        Triangle(Vector(min_x, y, min_z), Vector(max_x, y, min_z), Vector(max_x, y, max_z)),
        Triangle(Vector(min_x, y, min_z), Vector(max_x, y, max_z), Vector(min_x, y, max_z)),
    )


def sloped_strip(
    min_x: float,
    max_x: float,
    min_z: float,
    max_z: float,
    min_z_y: float,
    max_z_y: float,
):
    return (
        Triangle(
            Vector(min_x, min_z_y, min_z),
            Vector(max_x, min_z_y, min_z),
            Vector(max_x, max_z_y, max_z),
        ),
        Triangle(
            Vector(min_x, min_z_y, min_z),
            Vector(max_x, max_z_y, max_z),
            Vector(min_x, max_z_y, max_z),
        ),
    )


class LDrawSurfaceProfileTest(unittest.TestCase):
    def test_flat_plate_profile_contains_surface_collision_and_support(self) -> None:
        triangles = horizontal_quad(0, 0, 20, 0, 20) + horizontal_quad(8, 0, 20, 0, 20)

        profile = build_part_surface_profile(
            "flat.dat",
            triangles,
            triangles,
            (Vector(10, 0, 10),),
            PROFILE_CONFIG,
        )

        self.assertEqual(profile.width_stud, 1)
        self.assertEqual(profile.depth_stud, 1)
        self.assertEqual(profile.surface_height_plate, ((1.0,),))
        self.assertEqual(profile.collision_intervals_plate, ((((0.0, 1.0),),),))
        self.assertEqual(profile.bottom_contact, ((True,),))
        self.assertEqual(profile.top_connection_mask, ((True,),))
        self.assertEqual(profile.ldraw_origin_to_base_ldu, 8)
        self.assertEqual(profile.ldraw_center_x_ldu, 10)
        self.assertEqual(profile.ldraw_center_z_ldu, 10)

    def test_two_stud_slope_preserves_continuous_surface_height(self) -> None:
        triangles = (
            sloped_strip(0, 20, 0, 40, 24, -8)
            + horizontal_quad(24, 0, 20, 0, 40)
        )

        profile = build_part_surface_profile(
            "slope.dat",
            triangles,
            triangles,
            (Vector(10, -8, 30),),
            PROFILE_CONFIG,
        )

        self.assertEqual(profile.surface_height_plate, ((1.0,), (3.0,)))
        self.assertEqual(profile.bottom_contact, ((True,), (True,)))
        self.assertEqual(profile.top_connection_mask, ((False,), (True,)))
        self.assertEqual(profile.ldraw_origin_to_base_ldu, 24)
        self.assertEqual(profile.ldraw_center_x_ldu, 10)
        self.assertEqual(profile.ldraw_center_z_ldu, 20)

    def test_ridge_profile_is_evaluated_as_a_two_dimensional_surface(self) -> None:
        triangles = (
            sloped_strip(0, 20, 0, 20, 16, 16)
            + sloped_strip(20, 40, 0, 20, 8, 8)
            + sloped_strip(40, 60, 0, 20, 16, 16)
            + horizontal_quad(24, 0, 60, 0, 20)
        )

        profile = build_part_surface_profile(
            "ridge.dat",
            triangles,
            triangles,
            (),
            PROFILE_CONFIG,
        )

        self.assertEqual(profile.surface_height_plate, ((1.0, 2.0, 1.0),))
        self.assertEqual(profile.top_connection_mask, ((False, False, False),))


if __name__ == "__main__":
    unittest.main()
