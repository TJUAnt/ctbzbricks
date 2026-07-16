"""Tests for assembling the final DEM LEGO design."""

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from src.services.dem_final_design_service import (
    _dem_ldraw_part_projection,
    _map_dem_placement,
    assemble_final_dem_design,
    heightmap_with_target_heights,
    load_final_dem_design,
    prepare_surface_candidates_for_inventory,
    replacement_phase_diagnostics,
    solve_layered_surface_plan,
    supplement_candidates_after_replacement,
)
from src.services.dem_surface_patch_service import SurfacePatchCandidate
from src.services.dem_surface_plan_service import (
    SurfacePlan,
    SurfacePlanValidation,
    SurfaceReplacementPhase,
)
from src.services.dem_vertical_continuity_service import VerticalContinuityValidation


FINAL_CONFIG = {
    "algorithm": {
        "no_rotation_degrees": 0,
        "rotation_degrees": 90,
        "minimum_area": 1,
        "beam_size": 20,
        "max_candidates_per_cell": 30,
        "fragment_penalty": 0.4,
        "isolated_penalty": 0.8,
        "hex_radix": 16,
        "hex_color_length": 6,
        "hex_color_prefix": "#",
        "hex_pad_value": "0",
        "cell_key_separator": ":",
        "rgb_channels": {
            "red_start": 0,
            "red_end": 2,
            "green_start": 2,
            "green_end": 4,
            "blue_start": 4,
            "blue_end": 6,
        },
    },
    "surface_patch": {"matching": {"slope_directions": {}}},
    "surface_profile": {"sampling": {"samples_per_stud_axis": 1}},
    "vertical_continuity": {"samples_per_stud_axis": 2},
    "surface_plan": {
        "surface_fill_connection_class": "surface_fill",
        "collision_tolerance_plate": 0.000001,
        "errors": {"surface_not_coverable": "surface not coverable"},
    },
    "colored_replacement": {
        "supplement_connection_class": "colored_replacement_supplement",
        "transient_heightmap_model_id_template": "transient-{source_dem_model_id}",
        "maximum_supplement_rejection_examples": 200,
        "supplement_rejection_reasons": {
            "no_slope_edges": "candidate_has_no_slope_edges",
            "approximate_geometry": "candidate_uses_approximate_geometry",
            "overlaps_replacement": "candidate_overlaps_replacement",
            "no_unresolved_edge_match": "candidate_solves_no_unresolved_edge",
            "overlaps_selected_supplement": "candidate_overlaps_selected_supplement",
            "unsupported_base_h": "candidate_breaks_surface_support",
            "base_h_collision": "candidate_collides_with_surface_base_h",
        },
        "errors": {
            "target_dimensions_mismatch": "target dimensions mismatch",
        },
    },
    "support_base": {
        "part_role": "plate",
        "placement_ref_kinds": {
            "white_base": "whiteBase",
            "black_support": "blackSupport",
        },
        "generated_keys": {
            "white_base": "whiteBase",
            "black_support": "blackSupport",
        },
        "roles": {
            "white_base": "white_base",
            "black_support": "black_support",
        },
        "ldraw": {
            "white_base_y_ldu": 0,
            "black_support_y_ldu": 8,
            "seam_connector_before_stud": 1,
            "seam_connector_after_stud": 1,
            "border_width_stud": 2,
            "minimum_support_width_stud": 2,
            "support_maximum_extra_cells_per_part": 1,
            "support_minimum_covered_cells_per_part": 1,
            "support_colors": {
                "white": {
                    "id": 15,
                    "name": "White",
                    "rgb": "#FFFFFF",
                    "ldraw_code": "15",
                },
                "black": {
                    "id": 0,
                    "name": "Black",
                    "rgb": "#000000",
                    "ldraw_code": "0",
                },
            },
        },
        "steps": {
            "base_step_white_plate_limit": 4,
            "step_index_start": 1,
            "step_id_separator": "-",
            "layers": {"base": "base"},
            "step_id_prefixes": {"base": "base"},
            "base_plate": -2,
            "step_names": {"base": "Support base {index}"},
        },
        "plan_export": {
            "layer_ids": {
                "black_support": "blackSupport",
                "white_base": "whiteBase",
            },
        },
        "errors": {"support_base_failed": "support base failed"},
    },
    "errors": {"base_h_uncovered": "base h uncovered"},
    "final_design": {
        "strategy": "surface-structure-validated",
        "surface_candidate_layers": [
            {"allow_nearest_color": False, "allow_approximate_geometry": False},
            {"allow_nearest_color": True, "allow_approximate_geometry": False},
            {"allow_nearest_color": False, "allow_approximate_geometry": True},
            {"allow_nearest_color": True, "allow_approximate_geometry": True},
        ],
        "roles": {"surface": "surface"},
        "bom_role_order": ["black_support", "white_base", "surface", "brick", "plate"],
        "inventory_colors": {
            "part_number_fallbacks": {},
            "hex_radix": 16,
            "distance_exponent": 2,
            "maximum_squared_distance": 900,
            "rgb_channels": {
                "red_start": 0,
                "red_end": 2,
                "green_start": 2,
                "green_end": 4,
                "blue_start": 4,
                "blue_end": 6,
            },
        },
        "steps": {
            "index_start": 1,
            "id_template": "dem-step-{index}",
            "structure_name_template": "Base layer {base_plate}",
            "structure_stage": "structure",
            "surface_ref_kind": "surface",
            "surface_phases": [
                {
                    "connection_class": "top_connected",
                    "name_template": "Connected slope replacement {base_plate}",
                    "stage": "surface-connected",
                },
                {
                    "connection_class": "top_finished",
                    "name_template": "Finished slope decoration {base_plate}",
                    "stage": "surface-finished",
                },
            ],
            "maximum_placements_per_step": 100,
        },
        "errors": {
            "validation_failed": "final validation failed",
        },
    }
}


def surface_plan() -> SurfacePlan:
    placement = SurfacePatchCandidate(
        part_id="3040b.dat",
        ldraw_origin_to_base_ldu=24,
        ldraw_center_x_ldu=0,
        ldraw_center_z_ldu=0,
        x_stud=0,
        z_stud=0,
        width_stud=1,
        depth_stud=1,
        rotation_degrees=0,
        base_plate=1,
        color_id=4,
        target_color_id=4,
        color_distance=0,
        uses_nearest_color=False,
        uses_approximate_geometry=False,
        is_visible=True,
        covered_cells=((0, 0),),
        required_support_cells=((0, 0),),
        base_height_cells=((0, 0, 1),),
        top_connect_cells=(),
        top_connection_class="top_finished",
        slope_edges=(),
        slope_directions=(),
        matched_slope_direction_count=0,
        surface_height_plate=((4.0,),),
        collision_intervals_plate=((((1.0, 4.5),),),),
        maximum_absolute_error_plate=0,
        total_absolute_error_plate=0,
        root_mean_square_error_plate=0,
    )
    return SurfacePlan(
        strategy="connected-first-slope-replacement",
        width_stud=1,
        depth_stud=1,
        samples_per_stud_axis=1,
        placements=(placement,),
        replacement_phases=(
            SurfaceReplacementPhase(
                connection_class="top_connected",
                placements=(),
                base_h=((4,),),
                solved_slope_edge_count=0,
                unresolved_slope_edge_count=1,
            ),
            SurfaceReplacementPhase(
                connection_class="top_finished",
                placements=(placement,),
                base_h=((1,),),
                solved_slope_edge_count=1,
                unresolved_slope_edge_count=0,
            ),
        ),
        base_h=((1,),),
        maximum_absolute_error_plate=0,
        total_absolute_error_plate=0,
        seam_error_plate=0,
        part_count=1,
        validation=SurfacePlanValidation(
            target_slope_edge_count=1,
            solved_slope_edge_count=1,
            unresolved_slope_edge_count=0,
            covered_cell_count=1,
            overlap_cell_count=0,
            unsupported_placement_count=0,
            base_h_collision_sample_count=0,
            top_connected_placement_count=0,
            top_finished_placement_count=1,
        ),
    )


STRUCTURE = {
    "strategy": "solid-bottom-up",
    "widthStud": 1,
    "depthStud": 1,
    "baseH": [[1]],
    "placements": [
        {
            "partId": "3024.dat",
            "rebrickablePartNum": "3024",
            "legoDesignId": "3024",
            "role": "plate",
            "colorId": 15,
            "colorName": "White",
            "colorRgb": "#FFFFFF",
            "ldrawColorCode": "15",
            "x": 0,
            "z": 0,
            "basePlate": 0,
            "width": 1,
            "depth": 1,
            "heightPlate": 1,
            "rotation": 0,
        }
    ],
    "bom": [],
    "validation": {
        "targetVolumeStudPlate": 1,
        "placedVolumeStudPlate": 1,
        "unsupportedPlacementCount": 0,
    },
}

SUPPORT_BASE = {
    "whiteBase": [
        {
            "partId": "3024.dat",
            "rebrickablePartNum": "3024",
            "legoDesignId": "3024",
            "colorId": 15,
            "colorName": "White",
            "colorRgb": "#FFFFFF",
            "ldrawColorCode": "15",
            "x": 0,
            "y": 0,
            "width": 1,
            "height": 1,
            "logicalHeightPlate": 1,
            "rotation": 0,
            "area": 1,
            "yLdu": 0,
        }
    ],
    "blackSupport": [
        {
            "partId": "3024.dat",
            "rebrickablePartNum": "3024",
            "legoDesignId": "3024",
            "colorId": 0,
            "colorName": "Black",
            "colorRgb": "#000000",
            "ldrawColorCode": "0",
            "x": 0,
            "y": 0,
            "width": 1,
            "height": 1,
            "logicalHeightPlate": 1,
            "rotation": 0,
            "area": 1,
            "yLdu": 8,
        }
    ],
}

SURFACE_METADATA = {
    ("3040b.dat", 4): {
        "rebrickablePartNum": "3040b",
        "legoDesignId": "3040",
        "colorName": "Red",
        "colorRgb": "#C91A09",
        "ldrawColorCode": "0x2C91A09",
    }
}

CONTINUITY = (
    VerticalContinuityValidation(
        connection_class="top_connected",
        checked_column_count=400,
        occupied_column_count=400,
        discontinuous_column_count=0,
        gap_count=0,
        maximum_gap_ldu=0,
        gap_examples=(),
    ),
    VerticalContinuityValidation(
        connection_class="top_finished",
        checked_column_count=400,
        occupied_column_count=400,
        discontinuous_column_count=0,
        gap_count=0,
        maximum_gap_ldu=0,
        gap_examples=(),
    ),
)

LDRAW_PROJECTION_CONFIG = {
    "ldu_per_stud": 20,
    "ldu_per_plate": 8,
    "y_ground_ldu": 0,
    "y_direction": -1,
    "coordinate_precision": 6,
    "support_origin_to_base_ldu": 0,
    "support_origin_center_x_ldu": 0,
    "support_origin_center_z_ldu": 0,
    "part_origin_offset_divisor": 2,
    "x_origin_grid_width_multiplier": 0,
    "x_direction": 1,
    "z_origin_grid_height_multiplier": 1,
    "z_direction": -1,
    "structure_rotation_matrices": {
        "0": [0, 0, 1, 0, 1, 0, -1, 0, 0],
    },
    "surface_rotation_matrices": {
        "0": [1, 0, 0, 0, 1, 0, 0, 0, 1],
        "90": [0, 0, 1, 0, 1, 0, -1, 0, 0],
        "270": [0, 0, -1, 0, 1, 0, 1, 0, 0],
    },
    "placement_ref_kinds": {
        "structure": "structure",
        "surface": "surface",
        "white_base": "whiteBase",
        "black_support": "blackSupport",
    },
}


class DemFinalDesignServiceTest(unittest.TestCase):
    def test_colored_replacement_heightmap_uses_final_target_heights(self) -> None:
        heightmap = {
            "sourceDemModelId": "dem-model",
            "metrics": {"widthStud": 2, "depthStud": 1},
            "cells": [
                {"x": 0, "z": 0, "heightPlate": 0},
                {"x": 1, "z": 0, "heightPlate": 0},
            ],
        }

        result = heightmap_with_target_heights(heightmap, [[3, 4]], FINAL_CONFIG)

        self.assertEqual([cell["heightPlate"] for cell in result["cells"]], [3, 4])
        self.assertEqual(result["modelId"], "transient-dem-model")

    def test_supplement_runs_after_replacement_on_unresolved_edges(self) -> None:
        replacement = replace(
            surface_plan().placements[0],
            covered_cells=((0, 0),),
            slope_edges=((0, 0, 1, 0, "east"),),
        )
        supplement = replace(
            surface_plan().placements[0],
            part_id="supplement.dat",
            x_stud=1,
            covered_cells=((1, 0),),
            slope_edges=((1, 0, 2, 0, "east"),),
        )

        result = supplement_candidates_after_replacement(
            (supplement,),
            (replacement,),
            set(replacement.covered_cells),
            set(supplement.slope_edges),
            ((1, 1),),
            FINAL_CONFIG["surface_profile"]["sampling"]["samples_per_stud_axis"],
            FINAL_CONFIG,
        )

        selected = result["placements"]
        self.assertEqual(selected[0].part_id, "supplement.dat")
        self.assertEqual(
            selected[0].top_connection_class,
            FINAL_CONFIG["colored_replacement"]["supplement_connection_class"],
        )
        self.assertEqual(result["diagnostics"]["selectedPlacementCount"], 1)
        self.assertEqual(result["diagnostics"]["unresolvedEdgeCountAfter"], 0)

    def test_supplement_reports_rejected_candidate_reasons(self) -> None:
        replacement = replace(
            surface_plan().placements[0],
            covered_cells=((0, 0),),
            slope_edges=((0, 0, 1, 0, "east"),),
        )
        selected_edge = (1, 0, 2, 0, "east")
        still_unresolved_edge = (2, 0, 3, 0, "east")
        selected = replace(
            surface_plan().placements[0],
            part_id="a-selected.dat",
            x_stud=1,
            covered_cells=((1, 0),),
            slope_edges=(selected_edge,),
        )
        no_edge = replace(
            surface_plan().placements[0],
            part_id="no-edge.dat",
            covered_cells=((4, 0),),
            slope_edges=(),
        )
        approximate = replace(
            surface_plan().placements[0],
            part_id="approximate.dat",
            covered_cells=((5, 0),),
            slope_edges=(still_unresolved_edge,),
            uses_approximate_geometry=True,
        )
        overlaps_replacement = replace(
            surface_plan().placements[0],
            part_id="overlaps-replacement.dat",
            covered_cells=((0, 0),),
            slope_edges=(still_unresolved_edge,),
        )
        no_match = replace(
            surface_plan().placements[0],
            part_id="no-match.dat",
            covered_cells=((6, 0),),
            slope_edges=((6, 0, 7, 0, "east"),),
        )
        collision = replace(
            surface_plan().placements[0],
            part_id="collision.dat",
            x_stud=6,
            covered_cells=((6, 0),),
            slope_edges=(still_unresolved_edge,),
            base_height_cells=((0, 0, 2),),
        )
        unsupported = replace(
            surface_plan().placements[0],
            part_id="unsupported.dat",
            x_stud=7,
            covered_cells=((7, 0),),
            slope_edges=(still_unresolved_edge,),
            base_height_cells=((0, 0, 0),),
        )
        overlaps_selected = replace(
            surface_plan().placements[0],
            part_id="z-overlaps-selected.dat",
            x_stud=1,
            covered_cells=((1, 0),),
            slope_edges=(still_unresolved_edge,),
        )

        result = supplement_candidates_after_replacement(
            (
                selected,
                no_edge,
                approximate,
                overlaps_replacement,
                no_match,
                collision,
                unsupported,
                overlaps_selected,
            ),
            (replacement,),
            set(replacement.covered_cells),
            {selected_edge, still_unresolved_edge},
            ((1, 1, 1, 1, 1, 1, 1, 1),),
            FINAL_CONFIG["surface_profile"]["sampling"]["samples_per_stud_axis"],
            FINAL_CONFIG,
        )

        reasons = FINAL_CONFIG["colored_replacement"]["supplement_rejection_reasons"]
        rejection_counts = {
            item["reason"]: item["count"]
            for item in result["diagnostics"]["rejectionSummary"]
        }
        self.assertEqual(result["diagnostics"]["selectedPlacementCount"], 1)
        self.assertEqual(result["diagnostics"]["unresolvedEdgeCountAfter"], 1)
        self.assertEqual(rejection_counts[reasons["no_slope_edges"]], 1)
        self.assertEqual(rejection_counts[reasons["approximate_geometry"]], 1)
        self.assertEqual(rejection_counts[reasons["overlaps_replacement"]], 1)
        self.assertEqual(rejection_counts[reasons["no_unresolved_edge_match"]], 1)
        self.assertEqual(rejection_counts[reasons["overlaps_selected_supplement"]], 1)
        self.assertEqual(rejection_counts[reasons["unsupported_base_h"]], 1)
        self.assertEqual(rejection_counts[reasons["base_h_collision"]], 1)

    def test_replacement_phase_diagnostics_reports_incremental_placements(self) -> None:
        replacement = surface_plan().placements[0]
        supplement = replace(
            replacement,
            part_id="supplement.dat",
            uses_nearest_color=True,
            uses_approximate_geometry=False,
        )
        plan = replace(
            surface_plan(),
            replacement_phases=(
                replace(
                    surface_plan().replacement_phases[0],
                    placements=(replacement,),
                ),
                replace(
                    surface_plan().replacement_phases[1],
                    placements=(replacement, supplement),
                ),
            ),
        )

        summaries = replacement_phase_diagnostics(plan)

        self.assertEqual(summaries[0]["placementCount"], 1)
        self.assertEqual(summaries[0]["incrementalPlacementCount"], 1)
        self.assertEqual(summaries[0]["targetSlopeEdgeCount"], 1)
        self.assertEqual(summaries[1]["placementCount"], 2)
        self.assertEqual(summaries[1]["incrementalPlacementCount"], 1)
        self.assertEqual(summaries[1]["targetSlopeEdgeCount"], 1)
        self.assertEqual(summaries[1]["nearestColorPlacementCount"], 1)

    def test_surface_candidate_uses_nearest_inventory_color_for_its_part(self) -> None:
        candidate = surface_plan().placements[0]

        prepared, excluded_candidate_count = prepare_surface_candidates_for_inventory(
            (candidate,),
            {candidate.color_id: "C81A08"},
            {candidate.part_id: {15: "C91B09"}},
            {
                "hex_radix": 16,
                "distance_exponent": 2,
                "maximum_squared_distance": 900,
                "rgb_channels": {
                    "red_start": 0,
                    "red_end": 2,
                    "green_start": 2,
                    "green_end": 4,
                    "blue_start": 4,
                    "blue_end": 6,
                },
            },
        )

        self.assertEqual(prepared[0].color_id, 15)
        self.assertTrue(prepared[0].uses_nearest_color)
        self.assertGreater(prepared[0].color_distance, 0)
        self.assertEqual(prepared[0].covered_cells, candidate.covered_cells)
        self.assertEqual(excluded_candidate_count, 0)

    def test_surface_candidate_without_inventory_is_excluded_before_solving(self) -> None:
        candidate = surface_plan().placements[0]

        prepared, excluded_candidate_count = prepare_surface_candidates_for_inventory(
            (candidate,),
            {candidate.color_id: "C91A09"},
            {},
            FINAL_CONFIG["final_design"]["inventory_colors"],
        )

        self.assertEqual(prepared, ())
        self.assertEqual(excluded_candidate_count, 1)

    def test_surface_candidate_with_distant_inventory_color_is_excluded(self) -> None:
        candidate = surface_plan().placements[0]

        prepared, excluded_candidate_count = prepare_surface_candidates_for_inventory(
            (candidate,),
            {candidate.color_id: "112233"},
            {candidate.part_id: {15: "FFFFFF"}},
            FINAL_CONFIG["final_design"]["inventory_colors"],
        )

        self.assertEqual(prepared, ())
        self.assertEqual(excluded_candidate_count, 1)

    def test_surface_solver_uses_configured_geometry_and_color_layers(self) -> None:
        exact_strict = surface_plan().placements[0]
        nearest_strict = replace(exact_strict, part_id="nearest-strict.dat", uses_nearest_color=True)
        exact_approximate = replace(
            exact_strict,
            part_id="exact-approximate.dat",
            uses_approximate_geometry=True,
        )
        nearest_approximate = replace(
            exact_strict,
            part_id="nearest-approximate.dat",
            uses_nearest_color=True,
            uses_approximate_geometry=True,
        )
        incomplete_plan = replace(
            surface_plan(),
            validation=replace(
                surface_plan().validation,
                unresolved_slope_edge_count=1,
            ),
        )
        complete_plan = surface_plan()

        with patch(
            "src.services.dem_final_design_service.solve_surface_plan",
            side_effect=(incomplete_plan, incomplete_plan, complete_plan),
        ) as solve_plan:
            result = solve_layered_surface_plan(
                1,
                1,
                ((1.0,),),
                ((1,),),
                1,
                (exact_strict, nearest_strict, exact_approximate, nearest_approximate),
                set(),
                FINAL_CONFIG,
            )

        self.assertIs(result, complete_plan)
        self.assertEqual(solve_plan.call_count, 3)
        self.assertEqual(solve_plan.call_args_list[0].args[5], (exact_strict,))
        self.assertEqual(
            solve_plan.call_args_list[1].args[5],
            (exact_strict, nearest_strict),
        )
        self.assertEqual(
            solve_plan.call_args_list[2].args[5],
            (exact_strict, exact_approximate),
        )

    def test_ldraw_projection_stacks_structure_parts_upward_from_ground(self) -> None:
        brick = {
            **STRUCTURE["placements"][0],
            "partId": "3005.dat",
            "basePlate": 0,
            "heightPlate": 3,
        }
        plate = {
            **STRUCTURE["placements"][0],
            "basePlate": 3,
            "heightPlate": 1,
        }

        mapped_brick = _map_dem_placement(brick, "structure", LDRAW_PROJECTION_CONFIG)
        mapped_plate = _map_dem_placement(plate, "structure", LDRAW_PROJECTION_CONFIG)
        brick_projection = _dem_ldraw_part_projection(
            mapped_brick,
            STRUCTURE["widthStud"],
            STRUCTURE["depthStud"],
            LDRAW_PROJECTION_CONFIG,
        )
        plate_projection = _dem_ldraw_part_projection(
            mapped_plate,
            STRUCTURE["widthStud"],
            STRUCTURE["depthStud"],
            LDRAW_PROJECTION_CONFIG,
        )

        self.assertEqual(brick_projection["y"], -24)
        self.assertEqual(plate_projection["y"], -32)
        self.assertEqual(
            brick_projection["y"] + mapped_brick["originToBaseLdu"],
            LDRAW_PROJECTION_CONFIG["y_ground_ldu"],
        )
        self.assertEqual(
            plate_projection["y"] + mapped_plate["originToBaseLdu"],
            brick_projection["y"],
        )

    def test_ldraw_projection_places_support_base_directly_below_structure(self) -> None:
        mapped_structure = _map_dem_placement(
            STRUCTURE["placements"][0],
            "structure",
            LDRAW_PROJECTION_CONFIG,
        )
        mapped_support = _map_dem_placement(
            SUPPORT_BASE["whiteBase"][0],
            "whiteBase",
            LDRAW_PROJECTION_CONFIG,
        )

        structure_projection = _dem_ldraw_part_projection(
            mapped_structure,
            STRUCTURE["widthStud"],
            STRUCTURE["depthStud"],
            LDRAW_PROJECTION_CONFIG,
        )
        support_projection = _dem_ldraw_part_projection(
            mapped_support,
            STRUCTURE["widthStud"],
            STRUCTURE["depthStud"],
            LDRAW_PROJECTION_CONFIG,
        )

        self.assertEqual(
            structure_projection["y"] + mapped_structure["originToBaseLdu"],
            support_projection["y"],
        )
        self.assertEqual(structure_projection["x"], support_projection["x"])
        self.assertEqual(structure_projection["z"], support_projection["z"])

    def test_ldraw_projection_uses_slope_mesh_origin_to_base_offset(self) -> None:
        slope = {
            "xStud": 0,
            "zStud": 0,
            "widthStud": 1,
            "depthStud": 1,
            "rotationDegrees": 0,
            "basePlate": 3,
            "ldrawOriginToBaseLdu": 24,
            "ldrawCenterXLdu": 0,
            "ldrawCenterZLdu": 0,
            "ldrawColorCode": "4",
            "partId": "3040b.dat",
        }

        mapped_slope = _map_dem_placement(slope, "surface", LDRAW_PROJECTION_CONFIG)
        slope_projection = _dem_ldraw_part_projection(
            mapped_slope,
            STRUCTURE["widthStud"],
            STRUCTURE["depthStud"],
            LDRAW_PROJECTION_CONFIG,
        )

        self.assertEqual(slope_projection["y"], -48)
        self.assertEqual(
            slope_projection["y"] + mapped_slope["originToBaseLdu"],
            -24,
        )
        self.assertEqual(slope_projection["x"], 10)
        self.assertEqual(slope_projection["z"], 10)

    def test_ldraw_projection_aligns_rotated_asymmetric_slope_footprint(self) -> None:
        slope = {
            "xStud": 0,
            "zStud": 0,
            "widthStud": 3,
            "depthStud": 1,
            "rotationDegrees": 90,
            "basePlate": 3,
            "ldrawOriginToBaseLdu": 24,
            "ldrawCenterXLdu": 0,
            "ldrawCenterZLdu": -20,
            "ldrawColorCode": "4",
            "partId": "4286.dat",
        }

        mapped_slope = _map_dem_placement(slope, "surface", LDRAW_PROJECTION_CONFIG)
        projection = _dem_ldraw_part_projection(
            mapped_slope,
            4,
            4,
            LDRAW_PROJECTION_CONFIG,
        )

        self.assertEqual(projection["x"], 50)
        self.assertEqual(projection["z"], 70)
        self.assertEqual(
            projection["matrix"],
            LDRAW_PROJECTION_CONFIG["surface_rotation_matrices"]["90"],
        )

    def test_surface_rotation_matrices_keep_east_west_slope_direction(self) -> None:
        surface_matrices = LDRAW_PROJECTION_CONFIG["surface_rotation_matrices"]
        x_direction = LDRAW_PROJECTION_CONFIG["x_direction"]
        opposite_x_direction = (
            LDRAW_PROJECTION_CONFIG["x_direction"]
            * LDRAW_PROJECTION_CONFIG["z_direction"]
        )

        self.assertEqual(
            (
                surface_matrices["90"][2],
                surface_matrices["90"][5],
                surface_matrices["90"][8],
            ),
            (x_direction, 0, 0),
        )
        self.assertEqual(
            (
                surface_matrices["270"][2],
                surface_matrices["270"][5],
                surface_matrices["270"][8],
            ),
            (opposite_x_direction, 0, 0),
        )

    def test_assemble_final_design_merges_bom_steps_and_validation(self) -> None:
        result = assemble_final_dem_design(
            surface_plan(),
            3,
            STRUCTURE,
            SUPPORT_BASE,
            SURFACE_METADATA,
            CONTINUITY,
            1,
            2,
            3,
            4,
            FINAL_CONFIG["final_design"]["strategy"],
            None,
            FINAL_CONFIG,
        )

        self.assertEqual(result["strategy"], FINAL_CONFIG["final_design"]["strategy"])
        self.assertEqual(result["surfacePlan"]["candidateCount"], 3)
        self.assertEqual(result["baseStructure"]["baseH"], [[1]])
        self.assertEqual(result["supportBase"], SUPPORT_BASE)
        self.assertEqual(
            {(item["partId"], item["role"], item["quantity"]) for item in result["bom"]},
            {
                ("3024.dat", "black_support", 1),
                ("3024.dat", "white_base", 1),
                ("3040b.dat", "surface", 1),
                ("3024.dat", "plate", 1),
            },
        )
        self.assertEqual(
            [step["stage"] for step in result["steps"]],
            ["base", "structure", "surface-finished"],
        )
        self.assertEqual(
            result["steps"][0]["placementRefs"],
            [{"kind": "whiteBase", "index": 0}, {"kind": "blackSupport", "index": 0}],
        )
        self.assertEqual(result["steps"][1]["placementRefs"], [{"kind": "structure", "index": 0}])
        self.assertEqual(result["steps"][2]["placementRefs"], [{"kind": "surface", "index": 0}])
        self.assertEqual(result["validation"]["rejectedBaseHCount"], 1)
        self.assertEqual(result["validation"]["inventoryColorMappingCount"], 2)
        self.assertEqual(result["validation"]["approximateGeometryPlacementCount"], 3)
        self.assertEqual(result["validation"]["excludedColorCandidateCount"], 4)
        self.assertEqual(result["validation"]["totalPlacementCount"], 4)
        self.assertEqual(
            result["validation"]["verticalContinuity"][0]["discontinuousColumnCount"],
            0,
        )

    def test_final_design_rejects_unbuildable_base_h_and_resolves_surface(self) -> None:
        first_plan = replace(surface_plan(), base_h=((0,),))
        second_plan = surface_plan()
        with (
            patch("src.services.dem_final_design_service.validate_surface_part_ids"),
            patch(
                "src.services.dem_final_design_service.load_part_surface_profile_models",
                return_value=(SimpleNamespace(part_id="3040b.dat", samples_per_stud_axis=1),),
            ),
            patch(
                "src.services.dem_final_design_service.generate_surface_patch_candidates",
                return_value=(),
            ),
            patch(
                "src.services.dem_final_design_service.load_surface_color_options",
                return_value=({4: "C91A09"}, {"3040b.dat": {4: "C91A09"}}),
            ),
            patch(
                "src.services.dem_final_design_service.load_dem_structure_parts",
                return_value=[],
            ),
            patch(
                "src.services.dem_final_design_service.solve_surface_plan",
                side_effect=(first_plan, second_plan),
            ) as solve_plan,
            patch(
                "src.services.dem_final_design_service.build_base_h_structure",
                side_effect=(ValueError("base h uncovered"), STRUCTURE),
            ) as build_structure,
            patch(
                "src.services.dem_final_design_service.load_surface_metadata",
                return_value=SURFACE_METADATA,
            ),
            patch(
                "src.services.dem_final_design_service.phase_vertical_continuity",
                side_effect=CONTINUITY,
            ),
            patch(
                "src.services.dem_final_design_service.build_dem_support_base",
                return_value=SUPPORT_BASE,
            ),
        ):
            result = load_final_dem_design(
                [[4.0]],
                [[4]],
                [[4]],
                ["3040b.dat"],
                object(),
                FINAL_CONFIG,
            )

        self.assertEqual(solve_plan.call_count, 2)
        self.assertEqual(build_structure.call_count, 2)
        self.assertEqual(result["validation"]["rejectedBaseHCount"], 1)

    def test_final_design_rejects_any_discontinuous_ldu_column(self) -> None:
        discontinuous = (
            replace(
                CONTINUITY[0],
                discontinuous_column_count=1,
                gap_count=1,
                maximum_gap_ldu=8,
            ),
            CONTINUITY[1],
        )

        with self.assertRaisesRegex(
            ValueError,
            FINAL_CONFIG["final_design"]["errors"]["validation_failed"],
        ):
            assemble_final_dem_design(
                surface_plan(),
                3,
                STRUCTURE,
                SUPPORT_BASE,
                SURFACE_METADATA,
                discontinuous,
                1,
                0,
                0,
                0,
                FINAL_CONFIG["final_design"]["strategy"],
                None,
                FINAL_CONFIG,
            )


if __name__ == "__main__":
    unittest.main()
