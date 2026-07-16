"""Tests for two-phase DEM slope replacement planning."""

import unittest

from src.services.dem_surface_patch_service import SurfacePatchCandidate
from src.services.dem_surface_plan_service import build_base_h, solve_surface_plan


PLAN_CONFIG = {
    "strategy": "connected-first-slope-replacement",
    "minimum_base_height_plate": 0,
    "collision_tolerance_plate": 0.000001,
    "rounding_decimal_places": 6,
    "top_connection_phase_order": ["top_connected", "top_finished"],
    "surface_fill_connection_class": "surface_fill",
    "seam_neighbor_offsets": [
        {"x": 1, "z": 0},
        {"x": 0, "z": 1},
    ],
    "errors": {
        "surface_not_coverable": "surface not coverable",
        "candidate_outside_target": "candidate outside target",
        "candidate_cells_empty": "candidate cells empty",
        "target_height_dimensions_mismatch": "target height dimensions mismatch",
    },
}

DIRECTION_CONFIG = {
    "minimum_delta_plate": 0.001,
    "neighbors": [
        {"x": 1, "z": 0, "positive": "east", "negative": "west"},
        {"x": 0, "z": 1, "positive": "south", "negative": "north"},
    ],
    "order": ["north", "east", "south", "west"],
}


def candidate(
    part_id: str,
    cells: tuple[tuple[int, int], ...],
    edges: tuple[tuple[int, int, int, int, str], ...],
    surface: tuple[tuple[float, ...], ...],
    connection_class: str,
    base_plate: int = 0,
    support_cells: tuple[tuple[int, int], ...] | None = None,
    base_height_cells: tuple[tuple[int, int, int], ...] | None = None,
    collision_lower_plate: tuple[tuple[float, ...], ...] | None = None,
) -> SurfacePatchCandidate:
    directions = tuple(dict.fromkeys(edge[4] for edge in edges))
    width = len(surface[0])
    depth = len(surface)
    return SurfacePatchCandidate(
        part_id=part_id,
        ldraw_origin_to_base_ldu=max(max(row) for row in surface),
        ldraw_center_x_ldu=0,
        ldraw_center_z_ldu=0,
        x_stud=min(cell[0] for cell in cells),
        z_stud=min(cell[1] for cell in cells),
        width_stud=width,
        depth_stud=depth,
        rotation_degrees=0,
        base_plate=base_plate,
        color_id=1,
        target_color_id=1,
        color_distance=0,
        uses_nearest_color=False,
        uses_approximate_geometry=False,
        is_visible=True,
        covered_cells=cells,
        required_support_cells=support_cells if support_cells is not None else cells,
        base_height_cells=base_height_cells if base_height_cells is not None else tuple(
            (x, z, base_plate)
            for x, z in (support_cells if support_cells is not None else cells)
        ),
        top_connect_cells=cells if connection_class == "top_connected" else (),
        top_connection_class=connection_class,
        slope_edges=edges,
        slope_directions=directions,
        matched_slope_direction_count=len(directions),
        surface_height_plate=surface,
        collision_intervals_plate=tuple(
            tuple(
                ((float(collision_lower_plate[z][x] if collision_lower_plate is not None else base_plate), height),)
                for x, height in enumerate(row)
            )
            for z, row in enumerate(surface)
        ),
        maximum_absolute_error_plate=0,
        total_absolute_error_plate=0,
        root_mean_square_error_plate=0,
    )


def solve(
    surface: tuple[tuple[float, ...], ...],
    heights: tuple[tuple[int, ...], ...],
    candidates: tuple[SurfacePatchCandidate, ...],
):
    return solve_surface_plan(
        len(heights[0]),
        len(heights),
        surface,
        heights,
        1,
        candidates,
        set(),
        PLAN_CONFIG,
        DIRECTION_CONFIG,
    )


class DemSurfacePlanServiceTest(unittest.TestCase):
    def test_build_base_h_uses_actual_required_support_cells(self) -> None:
        slope = candidate(
            "slope.dat",
            ((0, 0),),
            ((0, 0, 1, 0, "east"),),
            ((4.0,),),
            "top_connected",
            3,
            ((0, 0), (1, 0)),
        )

        base_h = build_base_h((slope,), ((4, 1),))

        self.assertEqual(base_h, ((3, 3),))

    def test_build_base_h_caps_non_contact_cells_to_collision_clearance(self) -> None:
        curved = candidate(
            "curved.dat",
            ((0, 0), (1, 0)),
            ((0, 0, 1, 0, "east"),),
            ((4.0, 4.0),),
            "top_connected",
            1,
            ((0, 0),),
            ((0, 0, 1),),
            ((1.0, 2.0),),
        )

        base_h = build_base_h((curved,), ((3, 9),))

        self.assertEqual(base_h, ((1, 2),))

    def test_flat_surface_uses_colored_surface_plates(self) -> None:
        left = candidate(
            "3024.dat",
            ((0, 0),),
            (),
            ((4.0,),),
            "top_connected",
            3,
        )
        right = candidate(
            "3024.dat",
            ((1, 0),),
            (),
            ((4.0,),),
            "top_connected",
            3,
        )

        plan = solve(((4.0, 4.0),), ((4, 4),), (left, right))

        self.assertEqual([item.part_id for item in plan.placements], ["3024.dat", "3024.dat"])
        self.assertEqual(plan.base_h, ((3, 3),))
        self.assertEqual(plan.validation.target_slope_edge_count, 0)

    def test_connected_phase_runs_before_finished_phase(self) -> None:
        connected = candidate(
            "connected.dat",
            ((0, 0), (1, 0)),
            ((0, 0, 1, 0, "east"),),
            ((1.0, 2.0),),
            "top_connected",
        )
        finished = candidate(
            "finished.dat",
            ((0, 0), (1, 0), (0, 1), (1, 1)),
            ((0, 0, 1, 0, "east"), (0, 0, 0, 1, "south")),
            ((1.0, 2.0), (2.0, 3.0)),
            "top_finished",
        )

        plan = solve(
            ((1.0, 2.0), (2.0, 3.0)),
            ((1, 2), (2, 3)),
            (finished, connected),
        )

        self.assertEqual([item.part_id for item in plan.placements], ["connected.dat"])
        self.assertEqual(plan.validation.top_connected_placement_count, 1)
        self.assertGreater(plan.validation.unresolved_slope_edge_count, 0)
        self.assertEqual(plan.replacement_phases[0].connection_class, "top_connected")
        self.assertEqual(
            [item.part_id for item in plan.replacement_phases[0].placements],
            ["connected.dat"],
        )
        self.assertEqual(plan.replacement_phases[0].base_h, ((0, 0), (2, 3)))

    def test_corner_with_more_directions_has_priority(self) -> None:
        corner = candidate(
            "corner.dat",
            ((0, 0), (1, 0), (0, 1), (1, 1)),
            ((0, 0, 1, 0, "east"), (0, 0, 0, 1, "south")),
            ((1.0, 2.0), (2.0, 3.0)),
            "top_connected",
        )
        straight = candidate(
            "straight.dat",
            ((0, 0), (1, 0)),
            ((0, 0, 1, 0, "east"),),
            ((1.0, 2.0),),
            "top_connected",
        )

        plan = solve(
            ((1.0, 2.0), (2.0, 3.0)),
            ((1, 2), (2, 3)),
            (straight, corner),
        )

        self.assertEqual([item.part_id for item in plan.placements], ["corner.dat"])

    def test_parent_covering_child_slope_edges_has_priority(self) -> None:
        parent = candidate(
            "parent.dat",
            ((0, 0), (1, 0), (2, 0)),
            ((0, 0, 1, 0, "east"), (1, 0, 2, 0, "east")),
            ((1.0, 2.0, 3.0),),
            "top_connected",
        )
        child = candidate(
            "child.dat",
            ((0, 0), (1, 0)),
            ((0, 0, 1, 0, "east"),),
            ((1.0, 2.0),),
            "top_connected",
        )

        plan = solve(((1.0, 2.0, 3.0),), ((1, 2, 3),), (child, parent))

        self.assertEqual([item.part_id for item in plan.placements], ["parent.dat"])

    def test_finished_slope_handles_edges_left_by_connected_phase(self) -> None:
        finished = candidate(
            "finished.dat",
            ((0, 0), (1, 0)),
            ((0, 0, 1, 0, "east"),),
            ((1.0, 2.0),),
            "top_finished",
        )

        plan = solve(((1.0, 2.0),), ((1, 2),), (finished,))

        self.assertEqual([item.part_id for item in plan.placements], ["finished.dat"])
        self.assertEqual(plan.validation.unresolved_slope_edge_count, 0)
        self.assertEqual(plan.validation.top_finished_placement_count, 1)
        self.assertEqual(plan.replacement_phases[0].placements, ())
        self.assertEqual(
            [item.part_id for item in plan.replacement_phases[1].placements],
            ["finished.dat"],
        )


if __name__ == "__main__":
    unittest.main()
