"""Unit tests for LEGO design metadata."""

import copy
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.i18n.export_catalog import create_export_context
from src.model.models import (
    Base,
    Color,
    LDrawFile,
    LDrawPart,
    LDrawPartGeometry,
    XrefPartNumber,
)
from src.services.lego_design_service import (
    create_lego_design_result,
    create_lego_design_result_from_heightmap,
    decompose_heightmap_modules,
    expand_support_cell_keys,
    export_lego_design_ldraw,
    export_lego_design_plan,
    lego_design_candidates,
    lego_design_metadata,
    terrain_placement_sort_key,
)
from src.services.lego_pixmap_strategy import create_lego_pixmap_steps


EXPORT_CONTEXT = create_export_context("en-US", "UTC")


def lego_test_placement(
    part_id: str,
    color_id: int,
    color_name: str,
    color_rgb: str,
    ldraw_color_code: str,
    x: int,
    y: int,
    width: int,
    height: int,
    rotation: int,
) -> dict:
    return {
        "partId": part_id,
        "rebrickablePartNum": part_id,
        "legoDesignId": part_id,
        "colorId": color_id,
        "colorName": color_name,
        "colorRgb": color_rgb,
        "ldrawColorCode": ldraw_color_code,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "logicalHeightPlate": LEGO_DESIGN_CONFIG["parts"]["logical_height_plate"],
        "rotation": rotation,
    }


LEGO_DESIGN_CONFIG = {
    "parts": {
        "category": "Plate",
        "logical_height_plate": 1,
        "geometry_height_plate": 1,
        "geometry_height_tolerance_plate": 0.001,
        "minimum_dimension_stud": 1,
        "maximum_area_stud": 64,
        "geometry_status": "parsed",
    },
    "candidate_features": {
        "default_footprint": "rectangular",
        "query_param": "footprint",
        "name_space_separator": " ",
        "ldraw_part_suffix": ".dat",
        "moved_to_pattern": "^~Moved to (?P<target>[A-Za-z0-9]+)$",
        "moved_target_group": "target",
        "ranking": {
            "exact_relation_type": "exact",
            "direct_exact_rank": 0,
            "moved_exact_rank": 1,
            "mapped_rank": 2,
            "unmapped_rank": 3,
        },
        "footprints": {
            "rectangular": {
                "name_pattern": "^Plate [0-9]+ x [0-9]+$",
            },
        },
    },
    "colors": {
        "include_transparent": False,
        "excluded_ids": [-1, 9999],
        "excluded_names": [
            "[Unknown]",
            "[No Color/Any Color]",
            "No color",
            "No Color",
            "Any color",
            "Any Color",
        ],
    },
    "algorithm": {
        "beam_size": 20,
        "max_candidates_per_cell": 30,
        "max_region_cells_for_beam": 10,
        "fragment_penalty": 0.4,
        "isolated_penalty": 0.8,
        "rotation_degrees": 90,
        "no_rotation_degrees": 0,
        "minimum_empty_dimension": 0,
        "minimum_area": 1,
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
    "heightmap_design": {
        "source_type": "heightmap",
        "module_id_prefix": "terrain-module",
        "module_id_separator": "-",
        "module_id_start": 1,
        "module_types": {
            "cavity": "cavity",
            "solid": "solid",
            "surface": "surface",
        },
        "module_stages": {
            "wall": "wall",
            "support": "support",
            "cover": "cover",
            "solid": "solid",
            "surface": "surface",
            "slope": "slope",
        },
        "module_step_names": {
            "wall": "Walls",
            "support": "Supports",
            "cover": "Top cover",
            "solid": "Solid fill",
            "surface": "Colored surface",
            "slope": "Terrain slopes",
        },
        "module_step_name_template": "{module_id} {stage_name}",
        "surface_module_id": "terrain-surface",
        "part_roles": {
            "plate": "plate",
            "brick": "brick",
            "slope": "slope",
        },
        "cavity": {
            "min_width": 3,
            "min_depth": 3,
            "min_height_plate": 3,
            "wall_thickness": 1,
        },
        "part_rotation": 0,
        "plate_height_ldu": 8,
        "height_direction": -1,
        "part_specs": {
            "plate": {
                "role": "plate",
                "category": "Plate",
                "logical_height_plate": 1,
                "geometry_height_plate": 1,
                "geometry_height_tolerance_plate": 0.001,
                "name_pattern": "^Plate [0-9]+ x [0-9]+$",
            },
            "brick": {
                "role": "brick",
                "category": "Brick",
                "logical_height_plate": 3,
                "geometry_height_plate": 3,
                "geometry_height_tolerance_plate": 0.001,
                "name_pattern": "^Brick [0-9]+ x [0-9]+$",
            },
            "slope_1x1": {
                "role": "slope",
                "category": "Slope",
                "logical_height_plate": 2,
                "geometry_height_plate": 0.667,
                "geometry_height_tolerance_plate": 0.001,
                "name_pattern": "^Slope Brick 31 +1 x +1 x +0[.]667$",
            },
            "slope_2x1": {
                "role": "slope",
                "category": "Slope",
                "logical_height_plate": 3,
                "geometry_height_plate": 3,
                "geometry_height_tolerance_plate": 0.001,
                "name_pattern": "^Slope Brick 45 +2 x +1$",
            },
            "slope_2x2_corner": {
                "role": "slope",
                "category": "Slope",
                "logical_height_plate": 3,
                "geometry_height_plate": 3,
                "geometry_height_tolerance_plate": 0.001,
                "name_pattern": "^Slope Brick 45 +2 x +2 Double Convex$",
            },
        },
        "color_assignment": {
            "candidate_color_count": 4,
            "minimum_preserved_cell_count": 1,
        },
        "slope": {
            "minimum_height_difference_plate": 1,
            "corner_height_difference_plate": 3,
            "dimension_swap_rotations": [90, 270],
            "part_dimensions": {
                "single": {"width": 1, "depth": 1},
                "straight": {"width": 2, "depth": 1},
                "corner": {"width": 2, "depth": 2},
            },
            "corner_rotations": [
                {"rotation": 0, "high_x": 0, "high_z": 1},
                {"rotation": 90, "high_x": 0, "high_z": 0},
                {"rotation": 180, "high_x": 1, "high_z": 0},
                {"rotation": 270, "high_x": 1, "high_z": 1},
            ],
            "directions": [
                {"rotation": 0, "pair_x": 1, "pair_z": 0, "neighbor_x": 0, "neighbor_z": -1},
                {"rotation": 90, "pair_x": 0, "pair_z": 1, "neighbor_x": 1, "neighbor_z": 0},
                {"rotation": 180, "pair_x": 1, "pair_z": 0, "neighbor_x": 0, "neighbor_z": 1},
                {"rotation": 270, "pair_x": 0, "pair_z": 1, "neighbor_x": -1, "neighbor_z": 0},
            ],
        },
        "terrain_color": {
            "id": 15,
            "name": "White",
            "rgb": "#FFFFFF",
            "ldraw_code": "15",
        },
    },
    "progress": {
        "metadata_loaded": 10,
        "components_ready": 20,
        "complete": 100,
    },
    "ldraw": {
        "line_separator": "\n",
        "metadata_line_type": 0,
        "part_line_type": 1,
        "file_command": "FILE",
        "name_command": "Name:",
        "author_command": "Author:",
        "author": "ctbzbricks",
        "model_file_name": "pixel-design.ldr",
        "comment_prefix": "//",
        "step_command": "STEP",
        "ldu_per_stud": 20,
        "top_design_y_ldu": 0,
        "white_base_y_ldu": 8,
        "black_support_y_ldu": 16,
        "seam_connector_before_stud": 1,
        "seam_connector_after_stud": 1,
        "border_width_stud": 2,
        "minimum_support_width_stud": 2,
        "support_maximum_extra_cells_per_part": 1,
        "support_minimum_covered_cells_per_part": 2,
        "part_origin_offset_divisor": 2,
        "x_origin_grid_width_multiplier": 0,
        "x_direction": 1,
        "z_origin_grid_height_multiplier": 1,
        "z_direction": -1,
        "direct_color_prefix": "0x2",
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
        "submodels": {
            "main_assembly_name": "Terrain assembly",
            "file_name_template": "{module_id}.ldr",
            "reference_color_code": "16",
            "reference_x_ldu": 0,
            "reference_y_ldu": 0,
            "reference_z_ldu": 0,
            "reference_matrix": [1, 0, 0, 0, 1, 0, 0, 0, 1],
        },
        "grid_rotation_matrices": {
            "0": [0, 0, 1, 0, 1, 0, -1, 0, 0],
            "90": [1, 0, 0, 0, 1, 0, 0, 0, 1],
            "180": [0, 0, -1, 0, 1, 0, 1, 0, 0],
            "270": [-1, 0, 0, 0, 1, 0, 0, 0, -1],
        },
    },
    "model_dimensions": {
        "stud_width_mm": 8,
        "plate_height_mm": 3.2,
        "millimeters_per_centimeter": 10,
        "round_digits": 2,
    },
    "lego_pixmap_strategy": {
        "base_step_white_plate_limit": 4,
        "top_design_step_row_count": 4,
        "step_index_start": 1,
        "step_end_inclusive_offset": 1,
        "step_id_separator": "-",
        "layers": {
            "base": "base",
            "top": "top",
        },
        "step_id_prefixes": {
            "base": "base",
            "top": "top",
        },
        "step_names": {
            "base": "Base {index}",
            "top": "Top rows {start}-{end}",
        },
    },
    "plan_export": {
        "format": "lego-design-plan",
        "content_type": "application/json; charset=utf-8",
        "filename_template": "lego-design-{job_id}-plan.json",
        "content_disposition_header": "Content-Disposition",
        "content_disposition_template": "attachment; filename=\"{filename}\"",
        "json_indent": 2,
        "layer_order": {
            "black_support": 0,
            "white_base": 1,
            "top_design": 2,
        },
        "layer_ids": {
            "black_support": "blackSupport",
            "white_base": "whiteBase",
            "top_design": "topDesign",
        },
        "layer_names": {
            "black_support": "Black support connectors and border",
            "white_base": "White support base",
            "top_design": "Top pixel design",
        },
    },
    "errors": {
        "support_base_failed": "LEGO support base could not be generated",
        "candidate_feature_not_found": "LEGO design candidate feature not found",
        "design_coverage_failed": "LEGO design candidates cannot cover every pixel",
        "design_part_not_available": "LEGO design contains parts outside the current candidate set",
        "heightmap_column_part_not_found": "LEGO heightmap design requires a 1 x 1 terrain column part",
        "heightmap_cover_part_not_found": "LEGO heightmap design requires terrain cover plate candidates",
        "heightmap_slope_part_not_found": "LEGO heightmap design requires a configured terrain slope part",
    },
}


def heightmap_cavity_test_metadata() -> dict:
    return {
        "colors": [],
        "parts": [],
        "terrainParts": [
            {
                "ldrawPartNum": "3005.dat",
                "rebrickablePartNum": "3005",
                "legoDesignId": "3005",
                "name": "Brick 1 x 1",
                "partRole": "brick",
                "width": 1,
                "height": 1,
                "logicalHeightPlate": 3,
                "area": 1,
            },
            {
                "ldrawPartNum": "11212.dat",
                "rebrickablePartNum": "11212",
                "legoDesignId": "11212",
                "name": "Plate 3 x 3",
                "partRole": "plate",
                "width": 3,
                "height": 3,
                "logicalHeightPlate": 1,
                "area": 9,
            },
            {
                "ldrawPartNum": "3024.dat",
                "rebrickablePartNum": "3024",
                "legoDesignId": "3024",
                "name": "Plate 1 x 1",
                "partRole": "plate",
                "width": 1,
                "height": 1,
                "logicalHeightPlate": 1,
                "area": 1,
            },
        ],
    }


def terrain_surface_test_metadata() -> dict:
    return {
        "colors": [
            {"id": 2, "name": "Green", "rgb": "2F6B35", "isTrans": False},
            {"id": 321, "name": "Blue", "rgb": "3F78B5", "isTrans": False},
            {"id": 15, "name": "White", "rgb": "FFFFFF", "isTrans": False},
        ],
        "parts": [],
        "terrainParts": [
            {
                "ldrawPartNum": "3003.dat",
                "rebrickablePartNum": "3003",
                "legoDesignId": "3003",
                "name": "Brick 2 x 2",
                "partRole": "brick",
                "width": 2,
                "height": 2,
                "logicalHeightPlate": 3,
                "area": 4,
            },
            {
                "ldrawPartNum": "3005.dat",
                "rebrickablePartNum": "3005",
                "legoDesignId": "3005",
                "name": "Brick 1 x 1",
                "partRole": "brick",
                "width": 1,
                "height": 1,
                "logicalHeightPlate": 3,
                "area": 1,
            },
            {
                "ldrawPartNum": "3022.dat",
                "rebrickablePartNum": "3022",
                "legoDesignId": "3022",
                "name": "Plate 2 x 2",
                "partRole": "plate",
                "width": 2,
                "height": 2,
                "logicalHeightPlate": 1,
                "area": 4,
            },
            {
                "ldrawPartNum": "3024.dat",
                "rebrickablePartNum": "3024",
                "legoDesignId": "3024",
                "name": "Plate 1 x 1",
                "partRole": "plate",
                "width": 1,
                "height": 1,
                "logicalHeightPlate": 1,
                "area": 1,
            },
            {
                "ldrawPartNum": "6270.dat",
                "rebrickablePartNum": "6270",
                "legoDesignId": "6270",
                "name": "Slope Brick 45 2 x 1",
                "partRole": "slope",
                "width": 2,
                "height": 1,
                "logicalHeightPlate": 3,
                "area": 2,
            },
            {
                "ldrawPartNum": "54200.dat",
                "rebrickablePartNum": "54200",
                "legoDesignId": "54200",
                "name": "Slope Brick 31 1 x 1 x 0.667",
                "partRole": "slope",
                "width": 1,
                "height": 1,
                "logicalHeightPlate": 2,
                "area": 1,
            },
            {
                "ldrawPartNum": "3045.dat",
                "rebrickablePartNum": "3045",
                "legoDesignId": "3045",
                "name": "Slope Brick 45 2 x 2 Double Convex",
                "partRole": "slope",
                "width": 2,
                "height": 2,
                "logicalHeightPlate": 3,
                "area": 4,
            },
        ],
    }


def heightmap_cavity_test_design() -> dict:
    heightmap = {
        "metrics": {
            "widthStud": 3,
            "depthStud": 3,
        },
        "cells": [
            {
                "x": x,
                "z": z,
                "heightPlate": 5,
                "elevationMeters": 100,
            }
            for z in range(3)
            for x in range(3)
        ],
    }
    return create_lego_design_result_from_heightmap(
        heightmap,
        heightmap_cavity_test_metadata(),
        LEGO_DESIGN_CONFIG,
        lambda _progress: None,
    )


class LegoDesignServiceTest(unittest.TestCase):
    def test_terrain_placements_are_ordered_from_bottom_to_top(self) -> None:
        placements = [
            {"yLdu": -8, "x": 0, "y": 0, "partId": "top.dat"},
            {"yLdu": 0, "x": 0, "y": 0, "partId": "bottom.dat"},
        ]

        ordered = sorted(placements, key=terrain_placement_sort_key)

        self.assertEqual([placement["partId"] for placement in ordered], ["bottom.dat", "top.dat"])

    def test_support_expansion_fills_single_cell_gap_for_larger_plate(self) -> None:
        config = copy.deepcopy(LEGO_DESIGN_CONFIG)
        config["ldraw"]["support_maximum_extra_cells_per_part"] = 1
        config["ldraw"]["support_minimum_covered_cells_per_part"] = 2
        keys = {
            f"{x}:{y}"
            for y in range(2)
            for x in range(4)
            if (x, y) != (3, 1)
        }
        parts = [
            {
                "ldrawPartNum": "3020.dat",
                "rebrickablePartNum": "3020",
                "legoDesignId": "3020",
                "width": 2,
                "height": 4,
                "logicalHeightPlate": 1,
                "area": 8,
            }
        ]

        expanded = expand_support_cell_keys(keys, 4, 2, parts, config)

        self.assertEqual(len(expanded), 8)

    def test_metadata_returns_database_colors_and_parts(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        with Session() as session:
            session.add(Color(id=4, name="Red", rgb="C91A09", is_trans=False))
            session.add(Color(id=9999, name="[No Color/Any Color]", rgb="05131D", is_trans=False))
            session.add(
                LDrawFile(
                    id=1,
                    relative_path="parts/3023b.dat",
                    file_name="3023b.dat",
                    library_section="parts",
                    file_role="part",
                )
            )
            session.add(
                LDrawPart(
                    id=1,
                    ldraw_part_num="3023b.dat",
                    file_id=1,
                    name="Plate 1 x 2",
                    category="Plate",
                    relative_path="parts/3023b.dat",
                )
            )
            session.add(
                LDrawPartGeometry(
                    id=1,
                    ldraw_part_id=1,
                    logical_width_stud=1,
                    logical_depth_stud=2,
                    logical_height_plate=1,
                    geometry_status="parsed",
                )
            )
            session.add(
                LDrawFile(
                    id=2,
                    relative_path="parts/11458.dat",
                    file_name="11458.dat",
                    library_section="parts",
                    file_role="part",
                )
            )
            session.add(
                LDrawPart(
                    id=2,
                    ldraw_part_num="11458.dat",
                    file_id=2,
                    name="Plate 1 x 2 with Offset Peghole",
                    category="Plate",
                    relative_path="parts/11458.dat",
                )
            )
            session.add(
                LDrawPartGeometry(
                    id=2,
                    ldraw_part_id=2,
                    logical_width_stud=1,
                    logical_depth_stud=2,
                    logical_height_plate=1,
                    geometry_status="parsed",
                )
            )
            session.add(
                LDrawFile(
                    id=3,
                    relative_path="parts/3023.dat",
                    file_name="3023.dat",
                    library_section="parts",
                    file_role="part",
                )
            )
            session.add(
                LDrawPart(
                    id=3,
                    ldraw_part_num="3023.dat",
                    file_id=3,
                    name="~Moved to 3023b",
                    category="Plate",
                    relative_path="parts/3023.dat",
                )
            )
            session.add(
                LDrawPartGeometry(
                    id=3,
                    ldraw_part_id=3,
                    logical_width_stud=2,
                    logical_depth_stud=1,
                    logical_height_plate=1,
                    geometry_status="parsed",
                )
            )
            session.add(
                XrefPartNumber(
                    id=1,
                    rebrickable_part_num="3023",
                    ldraw_part_num="3023.dat",
                    lego_design_id="3023",
                    relation_type="exact",
                    source="test",
                    confidence=1,
                )
            )
            session.add(
                LDrawFile(
                    id=4,
                    relative_path="parts/28653.dat",
                    file_name="28653.dat",
                    library_section="parts",
                    file_role="part",
                )
            )
            session.add(
                LDrawPart(
                    id=4,
                    ldraw_part_num="28653.dat",
                    file_id=4,
                    name="Plate 1 x 2",
                    category="Plate",
                    relative_path="parts/28653.dat",
                )
            )
            session.add(
                LDrawPartGeometry(
                    id=4,
                    ldraw_part_id=4,
                    logical_width_stud=1,
                    logical_depth_stud=2,
                    logical_height_plate=1,
                    geometry_status="parsed",
                )
            )
            session.commit()

        metadata = lego_design_metadata(engine, LEGO_DESIGN_CONFIG)
        candidates = lego_design_candidates(
            engine,
            LEGO_DESIGN_CONFIG,
            LEGO_DESIGN_CONFIG["candidate_features"]["default_footprint"],
        )

        self.assertEqual(metadata["colors"][0]["id"], 4)
        self.assertEqual(len(metadata["colors"]), 1)
        self.assertEqual(candidates["parts"], metadata["parts"])
        self.assertEqual(metadata["parts"][0]["ldrawPartNum"], "3023b.dat")
        self.assertEqual(metadata["parts"][0]["rebrickablePartNum"], "3023")

    def test_candidate_api_rejects_unknown_feature(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)

        with self.assertRaisesRegex(ValueError, LEGO_DESIGN_CONFIG["errors"]["candidate_feature_not_found"]):
            lego_design_candidates(engine, LEGO_DESIGN_CONFIG, "round")

    def test_pixmap_strategy_groups_base_support_and_top_rows_into_steps(self) -> None:
        config = copy.deepcopy(LEGO_DESIGN_CONFIG)
        config["lego_pixmap_strategy"]["base_step_white_plate_limit"] = 2
        config["lego_pixmap_strategy"]["top_design_step_row_count"] = 2
        design = {
            "width": 6,
            "height": 4,
            "placements": [
                lego_test_placement("3024.dat", 4, "Red", "#C91A09", "0x2C91A09", 0, 0, 1, 1, 0),
                lego_test_placement("3024.dat", 4, "Red", "#C91A09", "0x2C91A09", 0, 2, 1, 1, 0),
            ],
        }
        support = {
            "whiteBase": [
                lego_test_placement("3022.dat", 15, "White", "#FFFFFF", "15", 0, 0, 2, 2, 0),
                lego_test_placement("3022.dat", 15, "White", "#FFFFFF", "15", 2, 0, 2, 2, 0),
                lego_test_placement("3022.dat", 15, "White", "#FFFFFF", "15", 4, 0, 2, 2, 0),
            ],
            "blackSupport": [
                lego_test_placement("3020.dat", 0, "Black", "#000000", "0", 0, 0, 4, 2, 90),
                lego_test_placement("3022.dat", 0, "Black", "#000000", "0", 4, 0, 2, 2, 0),
            ],
        }

        steps = create_lego_pixmap_steps(design, support, True, config)

        self.assertEqual([step["id"] for step in steps], ["base-1", "base-2", "top-1", "top-2"])
        self.assertEqual([item["layer"] for item in steps[0]["placements"]], ["whiteBase", "whiteBase", "blackSupport"])
        self.assertEqual([item["layer"] for item in steps[1]["placements"]], ["whiteBase", "blackSupport"])
        self.assertEqual(steps[2]["name"], "Top rows 0-1")
        self.assertEqual(steps[3]["name"], "Top rows 2-3")

    def test_backend_generation_creates_placements_and_bom(self) -> None:
        project = {
            "modelId": "pixel-design",
            "name": "test",
            "gridWidth": 2,
            "gridHeight": 2,
            "palette": [{"colorIndex": 0, "rgb": "#C91A09", "count": 4}],
            "pixels": [
                {"x": 0, "y": 0, "colorIndex": 0, "rgb": "#C91A09"},
                {"x": 1, "y": 0, "colorIndex": 0, "rgb": "#C91A09"},
                {"x": 0, "y": 1, "colorIndex": 0, "rgb": "#C91A09"},
                {"x": 1, "y": 1, "colorIndex": 0, "rgb": "#C91A09"},
            ],
        }
        metadata = {
            "colors": [{"id": 4, "name": "Red", "rgb": "C91A09", "isTrans": False}],
            "parts": [
                {
                    "ldrawPartNum": "3023.dat",
                    "rebrickablePartNum": "3023",
                    "legoDesignId": "3023",
                    "name": "Plate 1 x 2",
                    "width": 1,
                    "height": 2,
                    "logicalHeightPlate": 1,
                    "area": 2,
                },
                {
                    "ldrawPartNum": "3024.dat",
                    "rebrickablePartNum": "3024",
                    "legoDesignId": "3024",
                    "name": "Plate 1 x 1",
                    "partRole": "plate",
                    "width": 1,
                    "height": 1,
                    "logicalHeightPlate": 1,
                    "area": 1,
                },
            ],
        }
        progress_updates = []

        result = create_lego_design_result(
            project,
            metadata,
            LEGO_DESIGN_CONFIG,
            progress_updates.append,
        )

        self.assertEqual(len(result["placements"]), 2)
        self.assertEqual(result["placements"][0]["colorId"], 4)
        self.assertEqual(result["placements"][0]["ldrawColorCode"], "0x2C91A09")
        self.assertEqual(result["bom"][0]["quantity"], 2)
        self.assertEqual(result["colorMappings"][0]["colorRgb"], "#C91A09")
        self.assertEqual(result["colorMappings"][0]["ldrawColorCode"], "0x2C91A09")
        self.assertEqual(result["modelDimensions"]["lengthStud"], 2)
        self.assertEqual(result["modelDimensions"]["widthStud"], 2)
        self.assertEqual(result["modelDimensions"]["heightPlate"], 1)
        self.assertEqual(result["modelDimensions"]["lengthCm"], 1.6)
        self.assertEqual(result["modelDimensions"]["widthCm"], 1.6)
        self.assertEqual(result["modelDimensions"]["heightCm"], 0.32)
        self.assertIn(LEGO_DESIGN_CONFIG["progress"]["components_ready"], progress_updates)

    def test_backend_generation_merges_same_color_rectangle(self) -> None:
        project = {
            "modelId": "pixel-design",
            "name": "test",
            "gridWidth": 4,
            "gridHeight": 4,
            "palette": [{"colorIndex": 0, "rgb": "#C91A09", "count": 16}],
            "pixels": [
                {"x": x, "y": y, "colorIndex": 0, "rgb": "#C91A09"}
                for y in range(4)
                for x in range(4)
            ],
        }
        metadata = {
            "colors": [{"id": 4, "name": "Red", "rgb": "C91A09", "isTrans": False}],
            "parts": [
                {
                    "ldrawPartNum": "3031.dat",
                    "rebrickablePartNum": "3031",
                    "legoDesignId": "3031",
                    "name": "Plate 4 x 4",
                    "width": 4,
                    "height": 4,
                    "logicalHeightPlate": 1,
                    "area": 16,
                },
                {
                    "ldrawPartNum": "3023.dat",
                    "rebrickablePartNum": "3023",
                    "legoDesignId": "3023",
                    "name": "Plate 1 x 2",
                    "width": 1,
                    "height": 2,
                    "logicalHeightPlate": 1,
                    "area": 2,
                },
                {
                    "ldrawPartNum": "3024.dat",
                    "rebrickablePartNum": "3024",
                    "legoDesignId": "3024",
                    "name": "Plate 1 x 1",
                    "partRole": "plate",
                    "width": 1,
                    "height": 1,
                    "logicalHeightPlate": 1,
                    "area": 1,
                },
            ],
        }

        result = create_lego_design_result(
            project,
            metadata,
            LEGO_DESIGN_CONFIG,
            lambda progress: None,
        )

        self.assertEqual(len(result["placements"]), 1)
        self.assertEqual(result["placements"][0]["partId"], "3031.dat")
        self.assertEqual(result["bom"][0]["quantity"], 1)

    def test_backend_generation_rescans_remaining_cells_after_rectangle_fill(self) -> None:
        project = {
            "modelId": "pixel-design",
            "name": "test",
            "gridWidth": 2,
            "gridHeight": 3,
            "palette": [{"colorIndex": 0, "rgb": "#C91A09", "count": 5}],
            "pixels": [
                {"x": 0, "y": 0, "colorIndex": 0, "rgb": "#C91A09"},
                {"x": 1, "y": 0, "colorIndex": 0, "rgb": "#C91A09"},
                {"x": 0, "y": 1, "colorIndex": 0, "rgb": "#C91A09"},
                {"x": 1, "y": 1, "colorIndex": 0, "rgb": "#C91A09"},
                {"x": 0, "y": 2, "colorIndex": 0, "rgb": "#C91A09"},
            ],
        }
        metadata = {
            "colors": [{"id": 4, "name": "Red", "rgb": "C91A09", "isTrans": False}],
            "parts": [
                {
                    "ldrawPartNum": "3031.dat",
                    "rebrickablePartNum": "3031",
                    "legoDesignId": "3031",
                    "name": "Plate 4 x 4",
                    "width": 4,
                    "height": 4,
                    "logicalHeightPlate": 1,
                    "area": 16,
                },
                {
                    "ldrawPartNum": "3022.dat",
                    "rebrickablePartNum": "3022",
                    "legoDesignId": "3022",
                    "name": "Plate 2 x 2",
                    "width": 2,
                    "height": 2,
                    "logicalHeightPlate": 1,
                    "area": 4,
                },
                {
                    "ldrawPartNum": "3024.dat",
                    "rebrickablePartNum": "3024",
                    "legoDesignId": "3024",
                    "name": "Plate 1 x 1",
                    "width": 1,
                    "height": 1,
                    "logicalHeightPlate": 1,
                    "area": 1,
                },
            ],
            "terrainParts": [],
        }

        result = create_lego_design_result(
            project,
            metadata,
            LEGO_DESIGN_CONFIG,
            lambda progress: None,
        )

        self.assertEqual(len(result["placements"]), 2)
        self.assertEqual(result["placements"][0]["partId"], "3022.dat")
        self.assertEqual(result["placements"][1]["partId"], "3024.dat")

    def test_backend_generation_fails_when_candidates_do_not_cover_pixels(self) -> None:
        project = {
            "modelId": "pixel-design",
            "name": "test",
            "gridWidth": 1,
            "gridHeight": 1,
            "palette": [{"colorIndex": 0, "rgb": "#C91A09", "count": 1}],
            "pixels": [
                {"x": 0, "y": 0, "colorIndex": 0, "rgb": "#C91A09"},
            ],
        }
        metadata = {
            "colors": [{"id": 4, "name": "Red", "rgb": "C91A09", "isTrans": False}],
            "parts": [
                {
                    "ldrawPartNum": "3023b.dat",
                    "rebrickablePartNum": "3023",
                    "legoDesignId": "3023",
                    "name": "Plate 1 x 2",
                    "width": 1,
                    "height": 2,
                    "logicalHeightPlate": 1,
                    "area": 2,
                },
            ],
            "terrainParts": [],
        }

        with self.assertRaisesRegex(ValueError, LEGO_DESIGN_CONFIG["errors"]["design_coverage_failed"]):
            create_lego_design_result(
                project,
                metadata,
                LEGO_DESIGN_CONFIG,
                lambda progress: None,
            )

    def test_create_heightmap_design_result_stacks_one_by_one_plates(self) -> None:
        heightmap = {
            "metrics": {
                "widthStud": 2,
                "depthStud": 1,
            },
            "cells": [
                {
                    "x": 0,
                    "z": 0,
                    "heightPlate": 2,
                    "elevationMeters": 100,
                },
                {
                    "x": 1,
                    "z": 0,
                    "heightPlate": 0,
                    "elevationMeters": None,
                },
            ],
        }
        metadata = {
            "colors": [],
            "parts": [],
            "terrainParts": [
                {
                    "ldrawPartNum": "3024.dat",
                    "rebrickablePartNum": "3024",
                    "legoDesignId": "3024",
                    "name": "Plate 1 x 1",
                    "partRole": "plate",
                    "width": 1,
                    "height": 1,
                    "logicalHeightPlate": 1,
                    "area": 1,
                },
            ],
        }

        result = create_lego_design_result_from_heightmap(
            heightmap,
            metadata,
            LEGO_DESIGN_CONFIG,
            lambda _progress: None,
        )

        self.assertEqual(result["width"], 2)
        self.assertEqual(result["height"], 1)
        self.assertEqual(len(result["placements"]), 2)
        self.assertEqual([placement["yLdu"] for placement in result["placements"]], [0, -8])
        self.assertEqual(result["bom"][0]["quantity"], 2)
        self.assertEqual(result["modules"][0]["moduleType"], "solid")
        self.assertEqual(result["modelDimensions"]["lengthStud"], 1)
        self.assertEqual(result["modelDimensions"]["widthStud"], 1)
        self.assertEqual(result["modelDimensions"]["heightPlate"], 2)
        self.assertEqual(result["modelDimensions"]["heightCm"], 0.64)

    def test_heightmap_decomposition_classifies_three_by_three_as_cavity(self) -> None:
        heightmap = {
            "metrics": {
                "widthStud": 3,
                "depthStud": 3,
            },
            "cells": [
                {
                    "x": x,
                    "z": z,
                    "heightPlate": 3,
                    "elevationMeters": 100,
                }
                for z in range(3)
                for x in range(3)
            ],
        }

        modules = decompose_heightmap_modules(heightmap, LEGO_DESIGN_CONFIG)

        self.assertEqual(
            modules,
            [
                {
                    "id": "terrain-module-1",
                    "moduleType": "cavity",
                    "originX": 0,
                    "originZ": 0,
                    "originYPlate": 0,
                    "width": 3,
                    "depth": 3,
                    "heightPlate": 3,
                    "wallThickness": 1,
                },
            ],
        )

    def test_heightmap_decomposition_classifies_two_by_two_as_solid(self) -> None:
        heightmap = {
            "metrics": {
                "widthStud": 2,
                "depthStud": 2,
            },
            "cells": [
                {
                    "x": x,
                    "z": z,
                    "heightPlate": 3,
                    "elevationMeters": 100,
                }
                for z in range(2)
                for x in range(2)
            ],
        }

        modules = decompose_heightmap_modules(heightmap, LEGO_DESIGN_CONFIG)

        self.assertEqual(modules[0]["moduleType"], "solid")
        self.assertEqual(modules[0]["wallThickness"], 0)

    def test_create_heightmap_design_result_builds_cavity_walls_support_and_cover(self) -> None:
        heightmap = {
            "metrics": {
                "widthStud": 3,
                "depthStud": 3,
            },
            "cells": [
                {
                    "x": x,
                    "z": z,
                    "heightPlate": 5,
                    "elevationMeters": 100,
                }
                for z in range(3)
                for x in range(3)
            ],
        }
        metadata = {
            "colors": [],
            "parts": [],
            "terrainParts": [
                {
                    "ldrawPartNum": "3005.dat",
                    "rebrickablePartNum": "3005",
                    "legoDesignId": "3005",
                    "name": "Brick 1 x 1",
                    "partRole": "brick",
                    "width": 1,
                    "height": 1,
                    "logicalHeightPlate": 3,
                    "area": 1,
                },
                {
                    "ldrawPartNum": "11212.dat",
                    "rebrickablePartNum": "11212",
                    "legoDesignId": "11212",
                    "name": "Plate 3 x 3",
                    "partRole": "plate",
                    "width": 3,
                    "height": 3,
                    "logicalHeightPlate": 1,
                    "area": 9,
                },
                {
                    "ldrawPartNum": "3024.dat",
                    "rebrickablePartNum": "3024",
                    "legoDesignId": "3024",
                    "name": "Plate 1 x 1",
                    "partRole": "plate",
                    "width": 1,
                    "height": 1,
                    "logicalHeightPlate": 1,
                    "area": 1,
                },
            ],
        }

        result = create_lego_design_result_from_heightmap(
            heightmap,
            metadata,
            LEGO_DESIGN_CONFIG,
            lambda _progress: None,
        )

        brick_placements = [
            placement
            for placement in result["placements"]
            if placement["partId"] == "3005.dat"
        ]
        cover_placements = [
            placement
            for placement in result["placements"]
            if placement["partId"] == "11212.dat"
        ]
        self.assertEqual(result["modules"][0]["moduleType"], "cavity")
        self.assertEqual(len(brick_placements), 9)
        self.assertEqual(len(cover_placements), 2)
        self.assertEqual({placement["yLdu"] for placement in cover_placements}, {-24, -32})
        self.assertEqual(result["bom"][0]["partId"], "3005.dat")
        self.assertEqual(result["bom"][0]["quantity"], 9)

    def test_create_heightmap_design_result_uses_land_cover_color(self) -> None:
        heightmap = {
            "metrics": {
                "widthStud": 1,
                "depthStud": 1,
            },
            "cells": [
                {
                    "x": 0,
                    "z": 0,
                    "heightPlate": 1,
                    "elevationMeters": 100,
                    "landCoverColor": "#2f6b35",
                },
            ],
        }
        metadata = {
            "colors": [
                {
                    "id": 2,
                    "name": "Green",
                    "rgb": "2F6B35",
                    "isTrans": False,
                },
            ],
            "parts": [],
            "terrainParts": [
                {
                    "ldrawPartNum": "3024.dat",
                    "rebrickablePartNum": "3024",
                    "legoDesignId": "3024",
                    "name": "Plate 1 x 1",
                    "partRole": "plate",
                    "width": 1,
                    "height": 1,
                    "logicalHeightPlate": 1,
                    "area": 1,
                },
            ],
        }

        result = create_lego_design_result_from_heightmap(
            heightmap,
            metadata,
            LEGO_DESIGN_CONFIG,
            lambda _progress: None,
        )

        self.assertEqual(result["placements"][0]["colorName"], "Green")
        self.assertEqual(result["colorMappings"][0]["sourceRgb"], "#2F6B35")

    def test_heightmap_structure_uses_bricks_and_has_continuous_vertical_coverage(self) -> None:
        heightmap = {
            "metrics": {"widthStud": 2, "depthStud": 2},
            "cells": [
                {
                    "x": x,
                    "z": z,
                    "heightPlate": 4,
                    "elevationMeters": 100,
                }
                for z in range(2)
                for x in range(2)
            ],
        }
        metadata = terrain_surface_test_metadata()

        result = create_lego_design_result_from_heightmap(
            heightmap,
            metadata,
            LEGO_DESIGN_CONFIG,
            lambda _progress: None,
        )

        self.assertIn("3003.dat", {placement["partId"] for placement in result["placements"]})
        for z in range(2):
            for x in range(2):
                occupied_levels = {
                    level
                    for placement in result["placements"]
                    if placement["x"] <= x < placement["x"] + placement["width"]
                    and placement["y"] <= z < placement["y"] + placement["height"]
                    for level in range(
                        placement["yLdu"] // (
                            LEGO_DESIGN_CONFIG["heightmap_design"]["plate_height_ldu"]
                            * LEGO_DESIGN_CONFIG["heightmap_design"]["height_direction"]
                        ),
                        placement["yLdu"] // (
                            LEGO_DESIGN_CONFIG["heightmap_design"]["plate_height_ldu"]
                            * LEGO_DESIGN_CONFIG["heightmap_design"]["height_direction"]
                        ) + placement["logicalHeightPlate"],
                    )
                }
                self.assertEqual(occupied_levels, {0, 1, 2, 3})

    def test_heightmap_surface_preserves_each_mapped_color_in_bom(self) -> None:
        heightmap = {
            "metrics": {"widthStud": 2, "depthStud": 1},
            "cells": [
                {
                    "x": 0,
                    "z": 0,
                    "heightPlate": 1,
                    "elevationMeters": 100,
                    "landCoverColor": "#2f6b35",
                },
                {
                    "x": 1,
                    "z": 0,
                    "heightPlate": 1,
                    "elevationMeters": 100,
                    "landCoverColor": "#3f78b5",
                },
            ],
        }
        metadata = terrain_surface_test_metadata()

        result = create_lego_design_result_from_heightmap(
            heightmap,
            metadata,
            LEGO_DESIGN_CONFIG,
            lambda _progress: None,
        )

        mapped_color_ids = {mapping["colorId"] for mapping in result["colorMappings"]}
        bom_color_ids = {item["colorId"] for item in result["bom"]}
        self.assertEqual(mapped_color_ids, {2, 321})
        self.assertTrue(mapped_color_ids.issubset(bom_color_ids))

    def test_heightmap_surface_uses_slope_for_configured_three_plate_drop(self) -> None:
        heightmap = {
            "metrics": {"widthStud": 2, "depthStud": 2},
            "cells": [
                {
                    "x": x,
                    "z": z,
                    "heightPlate": 0 if z == 0 else 3,
                    "elevationMeters": 100,
                    "landCoverColor": "#2f6b35",
                }
                for z in range(2)
                for x in range(2)
            ],
        }
        metadata = terrain_surface_test_metadata()

        result = create_lego_design_result_from_heightmap(
            heightmap,
            metadata,
            LEGO_DESIGN_CONFIG,
            lambda _progress: None,
        )

        slope_placements = [
            placement for placement in result["placements"]
            if placement["partId"] == "6270.dat"
        ]
        self.assertEqual(len(slope_placements), 1)
        self.assertEqual(slope_placements[0]["rotation"], 0)

    def test_heightmap_surface_uses_corner_slope_for_single_high_corner(self) -> None:
        heightmap = {
            "metrics": {"widthStud": 2, "depthStud": 2},
            "cells": [
                {
                    "x": x,
                    "z": z,
                    "heightPlate": 6 if (x, z) == (0, 1) else 3,
                    "elevationMeters": 100,
                    "landCoverColor": "#2f6b35",
                }
                for z in range(2)
                for x in range(2)
            ],
        }

        result = create_lego_design_result_from_heightmap(
            heightmap,
            terrain_surface_test_metadata(),
            LEGO_DESIGN_CONFIG,
            lambda _progress: None,
        )

        slope_placements = [
            placement for placement in result["placements"]
            if placement["partId"] == "3045.dat"
        ]
        self.assertEqual(len(slope_placements), 1)
        low_cells = {(0, 0), (1, 0), (1, 1)}
        for x, z in low_cells:
            self.assertTrue(
                any(
                    placement["partId"] != "3045.dat"
                    and placement["yLdu"] // -8 <= 2
                    < placement["yLdu"] // -8 + placement["logicalHeightPlate"]
                    for placement in result["placements"]
                    if placement["x"] <= x < placement["x"] + placement["width"]
                    and placement["y"] <= z < placement["y"] + placement["height"]
                )
            )

    def test_heightmap_surface_uses_single_slope_for_any_positive_drop(self) -> None:
        heightmap = {
            "metrics": {"widthStud": 2, "depthStud": 1},
            "cells": [
                {
                    "x": 0,
                    "z": 0,
                    "heightPlate": 4,
                    "elevationMeters": 100,
                    "landCoverColor": "#2f6b35",
                },
                {
                    "x": 1,
                    "z": 0,
                    "heightPlate": 3,
                    "elevationMeters": 100,
                    "landCoverColor": "#2f6b35",
                },
            ],
        }

        result = create_lego_design_result_from_heightmap(
            heightmap,
            terrain_surface_test_metadata(),
            LEGO_DESIGN_CONFIG,
            lambda _progress: None,
        )

        slope_placements = [
            placement for placement in result["placements"]
            if placement["partId"] == "54200.dat"
        ]
        self.assertEqual(len(slope_placements), 1)

    def test_ldraw_export_uses_heightmap_placement_y_ldu(self) -> None:
        design = {
            "width": 1,
            "height": 1,
            "placements": [
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
                    "yLdu": 8,
                },
            ],
            "bom": [],
            "colorMappings": [],
            "modelDimensions": {
                "lengthStud": 4,
                "widthStud": 4,
                "heightPlate": 1,
                "lengthCm": 3.2,
                "widthCm": 3.2,
                "heightCm": 0.32,
            },
        }
        metadata = {
            "colors": [],
            "parts": [],
            "terrainParts": [
                {
                    "ldrawPartNum": "3024.dat",
                    "rebrickablePartNum": "3024",
                    "legoDesignId": "3024",
                    "name": "Plate 1 x 1",
                    "width": 1,
                    "height": 1,
                    "logicalHeightPlate": 1,
                    "area": 1,
                },
            ],
        }

        ldraw = export_lego_design_ldraw(
            design,
            metadata,
            False,
            LEGO_DESIGN_CONFIG,
            EXPORT_CONTEXT,
        )

        self.assertIn("1 15 10 8 10 0 0 1 0 1 0 -1 0 0 3024.dat", ldraw)

    def test_ldraw_export_writes_heightmap_modules_as_submodels(self) -> None:
        design = heightmap_cavity_test_design()
        metadata = heightmap_cavity_test_metadata()

        ldraw = export_lego_design_ldraw(
            design,
            metadata,
            False,
            LEGO_DESIGN_CONFIG,
            EXPORT_CONTEXT,
        )

        self.assertIn("0 // Terrain assembly", ldraw)
        self.assertIn("1 16 0 0 0 1 0 0 0 1 0 0 0 1 terrain-module-1.ldr", ldraw)
        self.assertIn("0 FILE terrain-module-1.ldr", ldraw)
        self.assertIn("0 // Module terrain-module-1: walls", ldraw)
        self.assertIn("0 // Module terrain-module-1: supports", ldraw)
        self.assertIn("0 // Module terrain-module-1: cover", ldraw)
        self.assertIn("0 // Module terrain-surface: colored surface", ldraw)

    def test_plan_export_writes_heightmap_module_steps(self) -> None:
        design = heightmap_cavity_test_design()
        metadata = heightmap_cavity_test_metadata()

        plan = export_lego_design_plan(
            design,
            metadata,
            False,
            LEGO_DESIGN_CONFIG,
            EXPORT_CONTEXT,
        )

        self.assertEqual(plan["submodels"][0]["id"], "terrain-module-1")
        self.assertEqual(plan["submodels"][0]["fileName"], "terrain-module-1.ldr")
        self.assertEqual(
            [step["id"] for step in plan["submodels"][0]["steps"]],
            ["terrain-module-1-wall", "terrain-module-1-support", "terrain-module-1-cover"],
        )
        self.assertEqual(plan["submodels"][1]["id"], "terrain-surface")
        self.assertEqual(
            [step["layer"] for step in plan["steps"]],
            ["terrain-module-1", "terrain-module-1", "terrain-module-1", "terrain-surface"],
        )

    def test_heightmap_exports_include_white_base_when_requested(self) -> None:
        design = heightmap_cavity_test_design()
        metadata = heightmap_cavity_test_metadata()
        metadata["parts"] = [
            {
                "ldrawPartNum": "3024.dat",
                "rebrickablePartNum": "3024",
                "legoDesignId": "3024",
                "name": "Plate 1 x 1",
                "width": 1,
                "height": 1,
                "logicalHeightPlate": 1,
                "area": 1,
            },
        ]
        config = copy.deepcopy(LEGO_DESIGN_CONFIG)
        config["lego_pixmap_strategy"]["base_step_white_plate_limit"] = 2

        ldraw = export_lego_design_ldraw(
            design,
            metadata,
            True,
            config,
            EXPORT_CONTEXT,
        )
        plan = export_lego_design_plan(
            design,
            metadata,
            True,
            config,
            EXPORT_CONTEXT,
        )

        self.assertIn("0 // Base 1", ldraw)
        self.assertTrue(plan["includeSupportBase"])
        self.assertEqual([layer["id"] for layer in plan["layers"][:2]], ["blackSupport", "whiteBase"])
        self.assertIn(
            "blackSupport",
            {
                placement["layer"]
                for step in plan["steps"]
                for placement in step["placements"]
            },
        )
        self.assertEqual(
            [step["id"] for step in plan["steps"][:5]],
            ["base-1", "base-2", "base-3", "base-4", "base-5"],
        )
        self.assertTrue(
            all(
                placement["ldraw"]["y"]
                == config["ldraw"][
                    "white_base_y_ldu"
                    if placement["layer"] == config["plan_export"]["layer_ids"]["white_base"]
                    else "black_support_y_ldu"
                ]
                for step in plan["steps"][:5]
                for placement in step["placements"]
            )
        )

    def test_ldraw_export_adds_white_base_and_black_support(self) -> None:
        design = {
            "width": 4,
            "height": 4,
            "placements": [
                {
                    "partId": "3031.dat",
                    "rebrickablePartNum": "3031",
                    "legoDesignId": "3031",
                    "colorId": 4,
                    "colorName": "Red",
                    "colorRgb": "#C91A09",
                    "ldrawColorCode": "0x2C91A09",
                    "x": 0,
                    "y": 0,
                    "width": 4,
                    "height": 4,
                    "logicalHeightPlate": 1,
                    "rotation": 0,
                }
            ],
            "bom": [],
            "colorMappings": [],
            "modelDimensions": {
                "lengthStud": 2,
                "widthStud": 2,
                "heightPlate": 1,
                "lengthCm": 1.6,
                "widthCm": 1.6,
                "heightCm": 0.32,
            },
        }
        metadata = {
            "colors": [{"id": 4, "name": "Red", "rgb": "C91A09", "isTrans": False}],
            "parts": [
                {
                    "ldrawPartNum": "3031.dat",
                    "rebrickablePartNum": "3031",
                    "legoDesignId": "3031",
                    "name": "Plate 4 x 4",
                    "width": 4,
                    "height": 4,
                    "logicalHeightPlate": 1,
                    "area": 16,
                },
                {
                    "ldrawPartNum": "3022.dat",
                    "rebrickablePartNum": "3022",
                    "legoDesignId": "3022",
                    "name": "Plate 2 x 2",
                    "width": 2,
                    "height": 2,
                    "logicalHeightPlate": 1,
                    "area": 4,
                },
                {
                    "ldrawPartNum": "3023.dat",
                    "rebrickablePartNum": "3023",
                    "legoDesignId": "3023",
                    "name": "Plate 1 x 2",
                    "width": 1,
                    "height": 2,
                    "logicalHeightPlate": 1,
                    "area": 2,
                },
                {
                    "ldrawPartNum": "3024.dat",
                    "rebrickablePartNum": "3024",
                    "legoDesignId": "3024",
                    "name": "Plate 1 x 1",
                    "width": 1,
                    "height": 1,
                    "logicalHeightPlate": 1,
                    "area": 1,
                },
            ],
            "terrainParts": [],
        }

        ldraw = export_lego_design_ldraw(
            design,
            metadata,
            True,
            LEGO_DESIGN_CONFIG,
            EXPORT_CONTEXT,
        )

        self.assertIn("0 // Base 1", ldraw)
        self.assertIn("0 STEP", ldraw)
        self.assertIn("0 // Top rows 0-3", ldraw)
        self.assertIn("1 0x2C91A09 40 0 40 0 0 1 0 1 0 -1 0 0 3031.dat", ldraw)
        self.assertIn("1 15 ", ldraw)
        self.assertIn("1 0 ", ldraw)

    def test_plan_export_writes_grid_layers_and_ldraw_projection(self) -> None:
        design = {
            "width": 4,
            "height": 4,
            "placements": [
                {
                    "partId": "3031.dat",
                    "rebrickablePartNum": "3031",
                    "legoDesignId": "3031",
                    "colorId": 4,
                    "colorName": "Red",
                    "colorRgb": "#C91A09",
                    "ldrawColorCode": "0x2C91A09",
                    "x": 0,
                    "y": 0,
                    "width": 4,
                    "height": 4,
                    "logicalHeightPlate": 1,
                    "rotation": 0,
                }
            ],
            "bom": [],
            "colorMappings": [],
            "modelDimensions": {
                "lengthStud": 1,
                "widthStud": 4,
                "heightPlate": 1,
                "lengthCm": 0.8,
                "widthCm": 3.2,
                "heightCm": 0.32,
            },
        }
        metadata = {
            "colors": [{"id": 4, "name": "Red", "rgb": "C91A09", "isTrans": False}],
            "parts": [
                {
                    "ldrawPartNum": "3031.dat",
                    "rebrickablePartNum": "3031",
                    "legoDesignId": "3031",
                    "name": "Plate 4 x 4",
                    "width": 4,
                    "height": 4,
                    "logicalHeightPlate": 1,
                    "area": 16,
                },
                {
                    "ldrawPartNum": "3022.dat",
                    "rebrickablePartNum": "3022",
                    "legoDesignId": "3022",
                    "name": "Plate 2 x 2",
                    "width": 2,
                    "height": 2,
                    "logicalHeightPlate": 1,
                    "area": 4,
                },
                {
                    "ldrawPartNum": "3024.dat",
                    "rebrickablePartNum": "3024",
                    "legoDesignId": "3024",
                    "name": "Plate 1 x 1",
                    "width": 1,
                    "height": 1,
                    "logicalHeightPlate": 1,
                    "area": 1,
                },
            ],
            "terrainParts": [],
        }

        plan = export_lego_design_plan(
            design,
            metadata,
            True,
            LEGO_DESIGN_CONFIG,
            EXPORT_CONTEXT,
        )

        self.assertEqual(plan["format"], LEGO_DESIGN_CONFIG["plan_export"]["format"])
        self.assertEqual(plan["grid"], {"width": 4, "height": 4})
        self.assertEqual([layer["id"] for layer in plan["layers"]], ["blackSupport", "whiteBase", "topDesign"])
        self.assertEqual([step["id"] for step in plan["steps"]], ["base-1", "top-1"])
        self.assertEqual(plan["steps"][0]["layer"], "base")
        self.assertEqual(plan["steps"][1]["name"], "Top rows 0-3")
        black_support = plan["layers"][0]["placements"]
        self.assertGreaterEqual(min(placement["grid"]["x"] for placement in black_support), 0)
        self.assertGreaterEqual(min(placement["grid"]["y"] for placement in black_support), 0)
        self.assertLessEqual(
            max(placement["grid"]["x"] + placement["grid"]["width"] for placement in black_support),
            design["width"],
        )
        self.assertLessEqual(
            max(placement["grid"]["y"] + placement["grid"]["height"] for placement in black_support),
            design["height"],
        )
        self.assertEqual(plan["layers"][2]["placements"][0]["grid"]["width"], 4)
        self.assertEqual(plan["layers"][2]["placements"][0]["ldraw"]["x"], 40)
        self.assertEqual(plan["layers"][2]["placements"][0]["ldraw"]["y"], 0)
        self.assertEqual(plan["layers"][2]["placements"][0]["ldraw"]["z"], 40)

    def test_plan_export_projects_non_square_parts_from_grid_to_ldraw(self) -> None:
        design = {
            "width": 4,
            "height": 6,
            "placements": [
                {
                    "partId": "3023.dat",
                    "rebrickablePartNum": "3023",
                    "legoDesignId": "3023",
                    "colorId": 4,
                    "colorName": "Red",
                    "colorRgb": "#C91A09",
                    "ldrawColorCode": "0x2C91A09",
                    "x": 2,
                    "y": 3,
                    "width": 1,
                    "height": 2,
                    "logicalHeightPlate": 1,
                    "rotation": 0,
                },
                {
                    "partId": "3023.dat",
                    "rebrickablePartNum": "3023",
                    "legoDesignId": "3023",
                    "colorId": 4,
                    "colorName": "Red",
                    "colorRgb": "#C91A09",
                    "ldrawColorCode": "0x2C91A09",
                    "x": 2,
                    "y": 3,
                    "width": 2,
                    "height": 1,
                    "logicalHeightPlate": 1,
                    "rotation": 90,
                },
            ],
            "bom": [],
            "colorMappings": [],
            "modelDimensions": {
                "lengthStud": 2,
                "widthStud": 2,
                "heightPlate": 1,
                "lengthCm": 1.6,
                "widthCm": 1.6,
                "heightCm": 0.32,
            },
        }
        metadata = {
            "colors": [{"id": 4, "name": "Red", "rgb": "C91A09", "isTrans": False}],
            "parts": [
                {
                    "ldrawPartNum": "3023.dat",
                    "rebrickablePartNum": "3023",
                    "legoDesignId": "3023",
                    "name": "Plate 1 x 2",
                    "width": 1,
                    "height": 2,
                    "logicalHeightPlate": 1,
                    "area": 2,
                },
            ],
            "terrainParts": [],
        }

        plan = export_lego_design_plan(
            design,
            metadata,
            False,
            LEGO_DESIGN_CONFIG,
            EXPORT_CONTEXT,
        )

        placements = plan["layers"][0]["placements"]
        self.assertEqual(placements[0]["ldraw"]["x"], 50)
        self.assertEqual(placements[0]["ldraw"]["z"], 40)
        self.assertEqual(
            placements[0]["ldraw"]["matrix"],
            LEGO_DESIGN_CONFIG["ldraw"]["grid_rotation_matrices"]["0"],
        )
        self.assertEqual(placements[1]["ldraw"]["x"], 60)
        self.assertEqual(placements[1]["ldraw"]["z"], 50)
        self.assertEqual(
            placements[1]["ldraw"]["matrix"],
            LEGO_DESIGN_CONFIG["ldraw"]["grid_rotation_matrices"]["90"],
        )

    def test_plan_export_projects_grid_y_in_reverse_ldraw_z_direction(self) -> None:
        design = {
            "width": 2,
            "height": 4,
            "placements": [
                {
                    "partId": "3024.dat",
                    "rebrickablePartNum": "3024",
                    "legoDesignId": "3024",
                    "colorId": 4,
                    "colorName": "Red",
                    "colorRgb": "#C91A09",
                    "ldrawColorCode": "0x2C91A09",
                    "x": 0,
                    "y": 0,
                    "width": 1,
                    "height": 1,
                    "logicalHeightPlate": 1,
                    "rotation": 0,
                },
                {
                    "partId": "3024.dat",
                    "rebrickablePartNum": "3024",
                    "legoDesignId": "3024",
                    "colorId": 4,
                    "colorName": "Red",
                    "colorRgb": "#C91A09",
                    "ldrawColorCode": "0x2C91A09",
                    "x": 0,
                    "y": 3,
                    "width": 1,
                    "height": 1,
                    "logicalHeightPlate": 1,
                    "rotation": 0,
                },
            ],
            "bom": [],
            "colorMappings": [],
            "modelDimensions": {
                "lengthStud": 1,
                "widthStud": 4,
                "heightPlate": 1,
                "lengthCm": 0.8,
                "widthCm": 3.2,
                "heightCm": 0.32,
            },
        }
        metadata = {
            "colors": [{"id": 4, "name": "Red", "rgb": "C91A09", "isTrans": False}],
            "parts": [
                {
                    "ldrawPartNum": "3024.dat",
                    "rebrickablePartNum": "3024",
                    "legoDesignId": "3024",
                    "name": "Plate 1 x 1",
                    "width": 1,
                    "height": 1,
                    "logicalHeightPlate": 1,
                    "area": 1,
                },
            ],
            "terrainParts": [],
        }

        plan = export_lego_design_plan(
            design,
            metadata,
            False,
            LEGO_DESIGN_CONFIG,
            EXPORT_CONTEXT,
        )

        placements = plan["layers"][0]["placements"]
        self.assertEqual(placements[0]["ldraw"]["z"], 70)
        self.assertEqual(placements[1]["ldraw"]["z"], 10)

    def test_ldraw_export_without_base_only_writes_top_design(self) -> None:
        design = {
            "width": 1,
            "height": 1,
            "placements": [
                {
                    "partId": "3024.dat",
                    "rebrickablePartNum": "3024",
                    "legoDesignId": "3024",
                    "colorId": 4,
                    "colorName": "Red",
                    "colorRgb": "#C91A09",
                    "ldrawColorCode": "0x2C91A09",
                    "x": 0,
                    "y": 0,
                    "width": 1,
                    "height": 1,
                    "logicalHeightPlate": 1,
                    "rotation": 0,
                }
            ],
            "bom": [],
            "colorMappings": [],
        }

        ldraw = export_lego_design_ldraw(
            design,
            {
                "colors": [],
                "parts": [
                    {
                        "ldrawPartNum": "3024.dat",
                        "rebrickablePartNum": "3024",
                        "legoDesignId": "3024",
                        "name": "Plate 1 x 1",
                        "width": 1,
                        "height": 1,
                        "logicalHeightPlate": 1,
                        "area": 1,
                    },
                ],
                "terrainParts": [],
            },
            False,
            LEGO_DESIGN_CONFIG,
            EXPORT_CONTEXT,
        )

        self.assertNotIn("0 // Base 1", ldraw)
        self.assertIn("0 // Top rows 0-0", ldraw)

    def test_ldraw_export_fails_when_design_uses_unavailable_part(self) -> None:
        design = {
            "width": 1,
            "height": 1,
            "placements": [
                {
                    "partId": "99999.dat",
                    "rebrickablePartNum": None,
                    "legoDesignId": None,
                    "colorId": 4,
                    "colorName": "Red",
                    "colorRgb": "#C91A09",
                    "ldrawColorCode": "0x2C91A09",
                    "x": 0,
                    "y": 0,
                    "width": 1,
                    "height": 1,
                    "logicalHeightPlate": 1,
                    "rotation": 0,
                }
            ],
            "bom": [],
            "colorMappings": [],
        }
        metadata = {
            "colors": [{"id": 4, "name": "Red", "rgb": "C91A09", "isTrans": False}],
            "parts": [
                {
                    "ldrawPartNum": "3024.dat",
                    "rebrickablePartNum": "3024",
                    "legoDesignId": "3024",
                    "name": "Plate 1 x 1",
                    "width": 1,
                    "height": 1,
                    "logicalHeightPlate": 1,
                    "area": 1,
                },
            ],
            "terrainParts": [],
        }

        with self.assertRaisesRegex(ValueError, LEGO_DESIGN_CONFIG["errors"]["design_part_not_available"]):
            export_lego_design_ldraw(
                design,
                metadata,
                False,
                LEGO_DESIGN_CONFIG,
                EXPORT_CONTEXT,
            )


if __name__ == "__main__":
    unittest.main()
